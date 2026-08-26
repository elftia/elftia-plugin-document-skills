"""Centralized, shell-free external process policy."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from typing import Any

from ..contracts.errors import DocumentSkillsError, ErrorCode
from ..io.portable_paths import PORTABLE_PATH_POLICY
from .streams import BoundedPipeCollector
from .tree import ProcessTree

_SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key)=\S+")
_ENV_ALLOWLIST = "PATH SystemRoot WINDIR TEMP TMP LANG LC_ALL DOTNET_ROOT DOTNET_CLI_TELEMETRY_OPTOUT".split()
_POST_KILL_WAIT_SECONDS = 1.0
_STREAM_CLOSE_GRACE_SECONDS = 0.25
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
    executables: dict[str, dict[Path, Path]] = field(default_factory=dict)
    scripts: dict[str, set[Path]] = field(default_factory=dict)

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
        canonical_identity = launch_path.resolve()
        self.executables.setdefault(provider_id, {})[launch_path] = canonical_identity
        return launch_path

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
    ) -> ProcessResult:
        executable_path = self._check_executable(provider_id, executable)
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
            [str(executable_path), *args],
            launch_cwd,
            (),
            stdin_json,
            timeout_seconds,
            output_limit,
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
    ) -> ProcessResult:
        """Launch only the fixed public worker with its narrow cwd capability."""
        if provider_id != _PUBLIC_WORKER_PROVIDER:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "The private workspace capability is restricted to the public worker.",
                details={"provider": provider_id},
            )
        executable_path = self._check_executable(provider_id, executable)
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
            [str(executable_path), *args],
            launch_cwd,
            pass_fds,
            stdin_json,
            timeout_seconds,
            output_limit,
        )

    def _execute(
        self,
        provider_id: str,
        command: list[str],
        launch_cwd: Path,
        pass_fds: tuple[int, ...],
        stdin_json: Any | None,
        timeout_seconds: float,
        output_limit: int,
    ) -> ProcessResult:
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        started = time.monotonic()
        popen_options: dict[str, Any] = {
            "cwd": launch_cwd,
            "env": self._minimal_environment(),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": False,
            "shell": False,
            "start_new_session": os.name != "nt",
            "creationflags": creation_flags,
            "close_fds": True,
        }
        if pass_fds:
            popen_options["pass_fds"] = pass_fds
        process = subprocess.Popen(command, **popen_options)
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
            )
        except KeyboardInterrupt:
            tree.terminate()
            self._finish_collectors(process, stdout_collector, stderr_collector)
            stdout_collector.close()
            stderr_collector.close()
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Process execution was cancelled.",
                details={"provider": provider_id, "reason_category": "cancelled"},
            ) from None
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
        launch_path = Path(executable).absolute()
        canonical_identity = launch_path.resolve()
        approved_identity = self.policy.executables.get(provider_id, {}).get(
            launch_path
        )
        if approved_identity != canonical_identity:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Executable is not allowlisted for this provider.",
                details={"provider": provider_id, "executable": launch_path.name},
            )
        return launch_path

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
        return {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}

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
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        exited_at: float | None = None
        while True:
            if stdout.overflow.is_set() or stderr.overflow.is_set():
                tree.terminate()
                return "overflow"
            now = time.monotonic()
            if now >= deadline:
                tree.terminate()
                return "timeout"
            if process.poll() is not None:
                exited_at = exited_at or now
                if stdout.done.is_set() and stderr.done.is_set():
                    return "complete"
                if now - exited_at >= _STREAM_CLOSE_GRACE_SECONDS:
                    tree.terminate()
                    return "complete"
            time.sleep(0.01)

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

    def _redact(self, stderr: str) -> str:
        redacted = _SECRET_PATTERN.sub(r"\1=<redacted>", stderr)
        return redacted.replace(
            str(self.policy.project_root.resolve()), "<project-root>"
        )
