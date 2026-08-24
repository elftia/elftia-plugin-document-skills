"""Centralized, shell-free external process policy."""

import json
import os
import re
import shutil
import subprocess
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
            tree.terminate()
            self._finish_collectors(process, stdout_collector, stderr_collector)
            stdout_collector.close()
            stderr_collector.close()
            raise
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
        while True:
            if runtime_check is not None:
                runtime_check()
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
        return redacted.replace(str(self.policy.project_root.resolve()), "<project-root>")
