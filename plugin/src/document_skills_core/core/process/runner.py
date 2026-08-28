"""Centralized, shell-free external process policy."""

import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts.errors import DocumentSkillsError, ErrorCode
from ..io.portable_paths import PORTABLE_PATH_POLICY
from ..io.temp_roots import OperationTempRoot, cleanup_stale_roots
from .executable import (
    ExecutableIdentity,
    ExecutableLaunchLease,
    acquire_executable_lease,
    capture_executable_identity,
)
from .streams import BoundedPipeCollector
from .tree import ProcessTree

_SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key)=\S+")
_ENV_ALLOWLIST = (
    "PATH",
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "DOTNET_ROOT",
    "DOTNET_CLI_TELEMETRY_OPTOUT",
    "DOCUMENT_SKILLS_XLSX_CORE_ONLY",
)
_POST_KILL_WAIT_SECONDS = 1.0
_STREAM_CLOSE_GRACE_SECONDS = 0.25
_PRIVATE_ENVIRONMENT_PATHS = {
    "APPDATA": "app-data",
    "DOTNET_CLI_HOME": "dotnet-cli-home",
    "LOCALAPPDATA": "local-app-data",
    "NUGET_PACKAGES": "nuget-packages",
    "PROGRAMFILES(X86)": "program-files-x86",
}
_PERSISTENT_ENVIRONMENT_GUARDS = {
    # The .NET CLI can persist its global-tools directory directly to
    # HKCU\Environment on Windows. Apply the opt-out to every managed child so
    # direct probes and nested dotnet launches cannot mutate the user's PATH.
    "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
    # Managed Python workers must not write bytecode into a verified install
    # tree. This fixed guard is intentionally stricter than caller passthrough.
    "PYTHONDONTWRITEBYTECODE": "1",
}
_FIXED_ENVIRONMENT = {
    "DOCUMENT_SKILLS_PROVIDER_PROFILE": "core-only",
}


class _RuntimeCheckWatcher:
    """Run one caller-supplied safety check at a time off the deadline thread."""

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._request = threading.Event()
        self._completed = threading.Event()
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._in_flight = False
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def poll(self) -> None:
        """Consume a completed check and keep exactly one check in flight."""

        if self._in_flight:
            if not self._completed.is_set():
                return
            self._consume()
        self._start()

    def finish_after_exit(self, deadline: float) -> bool:
        """Finish the current check, then require one check started post-exit."""

        if self._in_flight:
            if not self._wait_until(deadline):
                return False
            self._consume()
        self._start()
        if not self._wait_until(deadline):
            return False
        self._consume()
        return True

    def close(self) -> None:
        self._stopped.set()
        self._request.set()
        if not self._in_flight or self._completed.is_set():
            self._thread.join(0.05)

    def _start(self) -> None:
        self._completed.clear()
        with self._lock:
            self._error = None
        self._in_flight = True
        self._request.set()

    def _consume(self) -> None:
        self._in_flight = False
        with self._lock:
            error = self._error
            self._error = None
        if error is None:
            return
        if isinstance(error, DocumentSkillsError):
            raise error
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Process runtime safety check failed.",
            details={
                "reason_category": "runtime_check_failed",
                "exception_class": type(error).__name__[:64],
            },
        ) from error

    def _wait_until(self, deadline: float) -> bool:
        remaining = deadline - time.monotonic()
        return remaining > 0 and self._completed.wait(remaining)

    def _watch(self) -> None:
        while True:
            self._request.wait()
            self._request.clear()
            if self._stopped.is_set():
                return
            error: BaseException | None = None
            try:
                self._callback()
            except BaseException as caught:  # noqa: BLE001 - watcher reports safely
                error = caught
            with self._lock:
                self._error = error
            self._completed.set()


_PUBLIC_WORKER_PROVIDER = "public-command-worker"
_PUBLIC_WORKER_RELATIVE_PATH = Path("src/document_skills_core/worker/main.py")
_WORKSPACE_FD_FLAG = "--workspace-fd"
_WORKSPACE_DEVICE_FLAG = "--workspace-device"
_WORKSPACE_INODE_FLAG = "--workspace-inode"


def _path_unsafe(message: str) -> DocumentSkillsError:
    return DocumentSkillsError(ErrorCode.PATH_UNSAFE, message)


@dataclass
class ProcessPolicy:
    project_root: Path
    executables: dict[str, dict[Path, ExecutableIdentity]] = field(default_factory=dict)
    scripts: dict[str, set[Path]] = field(default_factory=dict)
    _executable_lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )

    def allow_executable(self, provider_id: str, executable: str | Path) -> Path:
        raw = str(executable)
        resolved_raw = shutil.which(raw) if not Path(raw).is_absolute() else raw
        if not resolved_raw:
            raise DocumentSkillsError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Executable is unavailable for provider {provider_id}.",
                details={"provider": provider_id, "executable": Path(raw).name},
            )
        launch_path = Path(resolved_raw).absolute()
        captured = capture_executable_identity(launch_path)
        with self._executable_lock:
            provider_executables = self.executables.setdefault(provider_id, {})
            approved = provider_executables.get(launch_path)
            if approved is not None and approved != captured:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "Executable identity changed after authorization.",
                    details={
                        "provider": provider_id,
                        "executable": launch_path.name,
                        "reason_category": "executable_identity_changed",
                    },
                )
            provider_executables[launch_path] = captured
        return launch_path

    def require_executable(self, provider_id: str, executable: str | Path) -> Path:
        launch_path = Path(executable).absolute()
        expected = self._approved_executable(provider_id, launch_path)
        with acquire_executable_lease(expected, require_native=False):
            return launch_path

    def acquire_executable(
        self,
        provider_id: str,
        executable: str | Path,
    ) -> ExecutableLaunchLease:
        launch_path = Path(executable).absolute()
        expected = self._approved_executable(provider_id, launch_path)
        return acquire_executable_lease(expected, require_native=True)

    def _approved_executable(
        self,
        provider_id: str,
        launch_path: Path,
    ) -> ExecutableIdentity:
        with self._executable_lock:
            approved = self.executables.get(provider_id, {}).get(launch_path)
        if approved is None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Executable is not allowlisted for this provider.",
                details={"provider": provider_id, "executable": launch_path.name},
            )
        return approved

    def allow_script(self, provider_id: str, script: str | Path) -> Path:
        resolved = Path(script).resolve()
        project = self.project_root.resolve()
        if not resolved.is_relative_to(project) or not resolved.is_file():
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Provider script must be a file contained by the document-skills project.",
                details={"provider": provider_id, "script": resolved.name},
            )
        try:
            PORTABLE_PATH_POLICY.require_release_safe(
                resolved.relative_to(project).as_posix()
            )
        except ValueError as error:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Provider script uses a forbidden portable path.",
                details={"provider": provider_id, "script": resolved.name},
            ) from error
        self.scripts.setdefault(provider_id, set()).add(resolved)
        return resolved


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int

    def json(self) -> Any:
        try:
            return json.loads(self.stdout)
        except json.JSONDecodeError as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider returned invalid JSON.",
                details={"line": error.lineno, "column": error.colno},
            ) from error


class ProcessRunner:
    def __init__(self, policy: ProcessPolicy) -> None:
        self.policy = policy
        self._private_environment_lock = threading.Lock()
        self._private_environment_root: Path | None = None
        self._private_environment_context: OperationTempRoot | None = None

    def run(
        self,
        provider_id: str,
        executable: str | Path,
        args: list[str],
        *,
        script: Path | None = None,
        stdin_json: Any | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 2.0,
        output_limit: int = 1_048_576,
        runtime_check: Callable[[], None] | None = None,
        private_environment: tuple[str, ...] = (),
        fixed_environment: dict[str, str] | None = None,
    ) -> ProcessResult:
        executable_path = Path(executable).absolute()
        if script is not None:
            self._check_script(provider_id, script)
            if str(script.resolve()) not in args:
                raise DocumentSkillsError(
                    ErrorCode.PATH_UNSAFE,
                    "Allowlisted provider script is not the script named by argv.",
                    details={"provider": provider_id},
                )
        launch_cwd = self._contained_cwd(cwd)
        return self._execute(
            provider_id,
            executable_path,
            [str(executable_path), *args],
            launch_cwd,
            (),
            stdin_json,
            timeout_seconds,
            output_limit,
            runtime_check=runtime_check,
            private_environment=private_environment,
            fixed_environment=fixed_environment,
        )

    def run_public_command_worker(
        self,
        provider_id: str,
        executable: str | Path,
        args: list[str],
        *,
        script: Path,
        stdin_json: Any,
        workspace_cwd: Path,
        posix_workspace_fd: int | None,
        posix_workspace_identity: tuple[int, int] | None,
        timeout_seconds: float,
        output_limit: int,
        fixed_environment: dict[str, str] | None = None,
    ) -> ProcessResult:
        """Launch only the fixed public worker with its narrow cwd capability."""
        if provider_id != _PUBLIC_WORKER_PROVIDER:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "The private workspace capability is restricted to the public worker.",
                details={"provider": provider_id},
            )
        executable_path = Path(executable).absolute()
        self._check_script(provider_id, script)
        launch_cwd, pass_fds = self._prepare_public_worker_launch(
            args,
            script,
            workspace_cwd,
            posix_workspace_fd,
            posix_workspace_identity,
        )
        return self._execute(
            provider_id,
            executable_path,
            [str(executable_path), *args],
            launch_cwd,
            pass_fds,
            stdin_json,
            timeout_seconds,
            output_limit,
            fixed_environment=fixed_environment,
        )

    def _execute(
        self,
        provider_id: str,
        executable: Path,
        command: list[str],
        launch_cwd: Path,
        pass_fds: tuple[int, ...],
        stdin_json: Any | None,
        timeout_seconds: float,
        output_limit: int,
        *,
        runtime_check: Callable[[], None] | None = None,
        private_environment: tuple[str, ...] = (),
        fixed_environment: dict[str, str] | None = None,
    ) -> ProcessResult:
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        started = time.monotonic()
        try:
            with self.policy.acquire_executable(provider_id, executable) as launch:
                atomic_launch: dict[str, Any] = {
                    "executable": launch.popen_executable,
                    "close_fds": True,
                }
                inherited_fds = tuple(dict.fromkeys((*launch.pass_fds, *pass_fds)))
                if inherited_fds:
                    atomic_launch["pass_fds"] = inherited_fds
                process = subprocess.Popen(
                    command,
                    cwd=launch_cwd,
                    env=self._process_environment(
                        private_environment,
                        fixed_environment,
                    ),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=creation_flags,
                    **atomic_launch,
                )
        except OSError as error:
            raise DocumentSkillsError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                "Atomic executable launch failed.",
                details={
                    "provider": provider_id,
                    "reason_category": "atomic_launch_failed",
                    "exception_class": type(error).__name__[:64],
                },
            ) from error
        tree = ProcessTree(process)
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_collector = BoundedPipeCollector(process.stdout, output_limit)
        stderr_collector = BoundedPipeCollector(process.stderr, output_limit)
        stdout_collector.start()
        stderr_collector.start()
        payload = (
            None
            if stdin_json is None
            else json.dumps(stdin_json, separators=(",", ":")).encode("utf-8")
        )
        try:
            self._write_stdin(process, payload)
            outcome = self._wait_bounded(
                process,
                tree,
                stdout_collector,
                stderr_collector,
                timeout_seconds,
                runtime_check,
            )
        except DocumentSkillsError:
            self._terminate_and_close_collectors(
                process,
                tree,
                stdout_collector,
                stderr_collector,
            )
            raise
        except KeyboardInterrupt:
            self._terminate_and_close_collectors(
                process,
                tree,
                stdout_collector,
                stderr_collector,
            )
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Process execution was cancelled.",
                details={"provider": provider_id, "reason_category": "cancelled"},
            ) from None
        except BaseException as error:
            self._terminate_and_close_collectors(
                process,
                tree,
                stdout_collector,
                stderr_collector,
            )
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Process runtime monitoring failed.",
                details={
                    "provider": provider_id,
                    "reason_category": "process_monitor_failed",
                    "exception_class": type(error).__name__[:64],
                },
            ) from error
        finally:
            tree.close()
        if outcome == "timeout":
            self._finish_collectors(process, stdout_collector, stderr_collector)
            stdout_collector.close()
            stderr_collector.close()
            raise DocumentSkillsError(
                ErrorCode.PROCESS_TIMEOUT,
                f"Provider {provider_id} exceeded its time budget.",
                details={"provider": provider_id, "timeout_seconds": timeout_seconds},
            )
        if outcome == "overflow":
            self._finish_collectors(process, stdout_collector, stderr_collector)
            stdout_collector.close()
            stderr_collector.close()
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider output exceeded the configured byte ceiling.",
                details={"provider": provider_id, "output_limit": output_limit},
            )
        self._finish_collectors(process, stdout_collector, stderr_collector)
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = stdout_collector.bytes().decode("utf-8", errors="replace")
        stderr = stderr_collector.bytes().decode("utf-8", errors="replace")
        stdout_collector.close()
        stderr_collector.close()
        redacted_stderr = self._redact(stderr)
        return ProcessResult(process.returncode, stdout, redacted_stderr, duration_ms)

    def _check_executable(self, provider_id: str, executable: str | Path) -> Path:
        return self.policy.require_executable(provider_id, executable)

    def _check_script(self, provider_id: str, script: Path) -> None:
        resolved = script.resolve()
        if resolved not in self.policy.scripts.get(provider_id, set()):
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Provider script is not allowlisted for this provider.",
                details={"provider": provider_id, "script": resolved.name},
            )

    def _contained_cwd(self, cwd: Path | None) -> Path:
        project_root = self.policy.project_root.resolve()
        isolated_cwd = (cwd or project_root).resolve()
        if not isolated_cwd.is_relative_to(project_root):
            raise _path_unsafe("Process cwd must remain inside the project root.")
        return isolated_cwd

    def _prepare_public_worker_launch(
        self,
        args: list[str],
        script: Path,
        workspace_cwd: Path,
        posix_workspace_fd: int | None,
        posix_workspace_identity: tuple[int, int] | None,
    ) -> tuple[Path, tuple[int, ...]]:
        project_root = self.policy.project_root.resolve()
        expected_worker = (project_root / _PUBLIC_WORKER_RELATIVE_PATH).resolve()
        resolved_script = script.resolve()
        if (
            resolved_script != expected_worker
            or not args
            or args[0] != str(expected_worker)
        ):
            raise _path_unsafe(
                "The private workspace capability requires the fixed public worker first in argv."
            )
        isolated_cwd = self._contained_cwd(workspace_cwd)
        if os.name == "nt":
            if (
                posix_workspace_fd is not None
                or posix_workspace_identity is not None
                or args != [str(expected_worker)]
            ):
                raise _path_unsafe(
                    "Windows public workers cannot inherit POSIX workspace descriptors.",
                )
            return isolated_cwd, ()
        if posix_workspace_fd is None or posix_workspace_identity is None:
            raise _path_unsafe(
                "A POSIX public worker requires one held workspace descriptor and identity.",
            )
        expected_args = [
            str(expected_worker),
            _WORKSPACE_FD_FLAG,
            str(posix_workspace_fd),
            _WORKSPACE_DEVICE_FLAG,
            str(posix_workspace_identity[0]),
            _WORKSPACE_INODE_FLAG,
            str(posix_workspace_identity[1]),
        ]
        if args != expected_args:
            raise _path_unsafe(
                "The POSIX public worker bootstrap arguments are invalid.",
            )
        try:
            held = os.fstat(posix_workspace_fd)
            lexical = os.stat(isolated_cwd, follow_symlinks=False)
        except OSError as error:
            raise _path_unsafe("The bound POSIX cwd is unavailable.") from error
        held_identity = (held.st_dev, held.st_ino)
        lexical_identity = (lexical.st_dev, lexical.st_ino)
        if (
            not stat.S_ISDIR(held.st_mode)
            or not stat.S_ISDIR(lexical.st_mode)
            or held_identity != posix_workspace_identity
            or lexical_identity != posix_workspace_identity
        ):
            raise _path_unsafe("The bound POSIX cwd identity changed before spawn.")
        return project_root, (posix_workspace_fd,)

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        environment = {
            key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ
        }
        environment.update(_PERSISTENT_ENVIRONMENT_GUARDS)
        return environment

    def _process_environment(
        self,
        private_environment: tuple[str, ...],
        fixed_environment: dict[str, str] | None = None,
    ) -> dict[str, str]:
        environment = self._minimal_environment()
        for name, value in (fixed_environment or {}).items():
            if _FIXED_ENVIRONMENT.get(name) != value:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "Process fixed environment contains an unsupported value.",
                    details={"setting": name},
                )
            environment[name] = value
        if not private_environment:
            return environment
        requested = set(private_environment)
        if len(requested) != len(private_environment):
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Private process environment contains duplicate entries.",
            )
        unsupported = requested.difference(_PRIVATE_ENVIRONMENT_PATHS)
        if unsupported:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Private process environment contains an unsupported entry.",
                details={"entries": sorted(unsupported)},
            )
        for name in private_environment:
            path = self.private_environment_directory(name)
            environment[name] = str(path)
        return environment

    def private_environment_directory(self, name: str) -> Path:
        """Return one managed private environment directory for this runner."""

        relative = _PRIVATE_ENVIRONMENT_PATHS.get(name)
        if relative is None:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Private process environment contains an unsupported entry.",
                details={"entries": [name]},
            )
        root = self._ensure_private_environment_root()
        path = (root / relative).resolve(strict=False)
        if path.parent != root:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Private process environment escaped its managed root.",
            )
        try:
            path.mkdir(mode=0o700, parents=False, exist_ok=True)
        except OSError as error:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Private process environment could not be created safely.",
                details={"entry": name},
            ) from error
        if not path.is_dir() or path.is_symlink():
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Private process environment must be a real directory.",
                details={"entry": name},
            )
        return path

    def _ensure_private_environment_root(self) -> Path:
        with self._private_environment_lock:
            if self._private_environment_root is not None:
                return self._private_environment_root
            base = (
                self.policy.project_root
                / ".document-skills-tmp"
                / "document-skills-operations"
            ).resolve(strict=False)
            project_root = self.policy.project_root.resolve()
            if not base.is_relative_to(project_root) or base.is_symlink():
                raise DocumentSkillsError(
                    ErrorCode.PATH_UNSAFE,
                    "Private process environment base is not project-contained.",
                )
            cleanup_stale_roots(base=base)
            context = OperationTempRoot(base=base)
            try:
                root = context.__enter__().resolve(strict=True)
            except OSError as error:
                raise DocumentSkillsError(
                    ErrorCode.PATH_UNSAFE,
                    "Private process environment root could not be created safely.",
                ) from error
            if root.parent != base or root.is_symlink():
                context.__exit__(None, None, None)
                raise DocumentSkillsError(
                    ErrorCode.PATH_UNSAFE,
                    "Private process environment root is not managed.",
                )
            self._private_environment_context = context
            self._private_environment_root = root
            return root

    def close(self) -> None:
        """Clean the project-private process environment, if one was created."""

        context = self._private_environment_context
        self._private_environment_root = None
        self._private_environment_context = None
        if context is not None:
            self._cleanup_private_environment(context)

    def __del__(self) -> None:
        """Best-effort cleanup for callers that do not use explicit close()."""

        self.close()

    @staticmethod
    def _cleanup_private_environment(context: OperationTempRoot) -> None:
        try:
            context.__exit__(None, None, None)
        except (DocumentSkillsError, OSError):
            # A killed worker may leave this managed operation root for a later
            # conservative stale-root cleanup; never broaden deletion here.
            pass

    @staticmethod
    def _write_stdin(process: subprocess.Popen[bytes], payload: bytes | None) -> None:
        if process.stdin is None:
            return
        try:
            if payload is not None:
                process.stdin.write(payload)
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    @staticmethod
    def _wait_bounded(
        process: subprocess.Popen[bytes],
        tree: ProcessTree,
        stdout: BoundedPipeCollector,
        stderr: BoundedPipeCollector,
        timeout_seconds: float,
        runtime_check: Callable[[], None] | None,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        exited_at: float | None = None
        watcher = (
            _RuntimeCheckWatcher(runtime_check)
            if runtime_check is not None
            else None
        )
        post_exit_checked = False
        try:
            while True:
                if watcher is not None:
                    watcher.poll()
                if stdout.overflow.is_set() or stderr.overflow.is_set():
                    tree.terminate()
                    return "overflow"
                now = time.monotonic()
                if now >= deadline:
                    tree.terminate()
                    return "timeout"
                if process.poll() is not None:
                    exited_at = exited_at or now
                    if watcher is not None and not post_exit_checked:
                        if not watcher.finish_after_exit(deadline):
                            tree.terminate()
                            return "timeout"
                        post_exit_checked = True
                        if stdout.overflow.is_set() or stderr.overflow.is_set():
                            tree.terminate()
                            return "overflow"
                    if stdout.done.is_set() and stderr.done.is_set():
                        return "complete"
                    if now - exited_at >= _STREAM_CLOSE_GRACE_SECONDS:
                        tree.terminate()
                        return "complete"
                time.sleep(0.01)
        finally:
            if watcher is not None:
                watcher.close()

    @staticmethod
    def _finish_collectors(
        process: subprocess.Popen[bytes],
        stdout: BoundedPipeCollector,
        stderr: BoundedPipeCollector,
    ) -> None:
        try:
            process.wait(timeout=_POST_KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=_POST_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        stdout.wait(_POST_KILL_WAIT_SECONDS)
        stderr.wait(_POST_KILL_WAIT_SECONDS)
        if not stdout.done.is_set():
            stdout.abort()
            stdout.wait(_POST_KILL_WAIT_SECONDS)
        if not stderr.done.is_set():
            stderr.abort()
            stderr.wait(_POST_KILL_WAIT_SECONDS)

    @classmethod
    def _terminate_and_close_collectors(
        cls,
        process: subprocess.Popen[bytes],
        tree: ProcessTree,
        stdout: BoundedPipeCollector,
        stderr: BoundedPipeCollector,
    ) -> None:
        tree.terminate()
        try:
            cls._finish_collectors(process, stdout, stderr)
        finally:
            try:
                stdout.close()
            finally:
                stderr.close()

    def _redact(self, stderr: str) -> str:
        redacted = _SECRET_PATTERN.sub(r"\1=<redacted>", stderr)
        return redacted.replace(
            str(self.policy.project_root.resolve()), "<project-root>"
        )
