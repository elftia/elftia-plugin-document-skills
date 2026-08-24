"""Centralized, shell-free external process policy."""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts.errors import DocumentSkillsError, ErrorCode
from ..io.portable_paths import PORTABLE_PATH_POLICY
from .streams import BoundedPipeCollector
from .tree import ProcessTree

_SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key)=\S+")
_ENV_ALLOWLIST = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "DOTNET_ROOT", "DOTNET_CLI_TELEMETRY_OPTOUT")
_POST_KILL_WAIT_SECONDS = 1.0
_STREAM_CLOSE_GRACE_SECONDS = 0.25


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
            except BaseException as caught:
                error = caught
            with self._lock:
                self._error = error
            self._completed.set()


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
        runtime_check: Callable[[], None] | None = None,
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
        isolated_cwd = (cwd or self.policy.project_root).resolve()
        if not isolated_cwd.is_relative_to(self.policy.project_root.resolve()):
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE, "Process cwd must remain inside the project root."
            )
        command = [str(executable_path), *args]
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=isolated_cwd,
            env=self._minimal_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=creation_flags,
        )
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
        launch_path = Path(executable).absolute()
        canonical_identity = launch_path.resolve()
        approved_identity = self.policy.executables.get(provider_id, {}).get(launch_path)
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
        return redacted.replace(str(self.policy.project_root.resolve()), "<project-root>")
