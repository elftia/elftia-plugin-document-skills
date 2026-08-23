"""One-shot public command supervisor and sole stdout/cancellation owner."""

import json
from pathlib import Path
import secrets
import sys
from typing import Any, Callable

from document_skills_core import __version__
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import empty_validation, make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.contracts.serialization import render_json_bytes
from document_skills_core.core.process import ProcessPolicy, ProcessRunner

from .protocol import (
    MAX_WORKER_BYTES,
    PublicCommand,
    command_envelope,
    parse_public_command,
    read_bounded_json,
    validate_worker_envelope,
)

_INVOCATION_ROOT = ".document-skills-tmp"
_HTML_OPERATION = "pptx.create.from-html"
_HTML_WORKER_TIMEOUT_SECONDS = 60.0
_HTML_WORKER_RESULT_BYTES = 1_048_576
_PROVIDER_PROBE_TIMEOUT_SECONDS = 45.0
_WORKER_TIMEOUT_SECONDS = 15.0


class PublicCommandSupervisor:
    def __init__(
        self,
        project_root: Path,
        *,
        worker_script: Path | None = None,
        timeout_seconds: float = _WORKER_TIMEOUT_SECONDS,
        output_limit: int = 65_536,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.worker_script = (
            worker_script
            or self.project_root
            / "src"
            / "document_skills_core"
            / "worker"
            / "main.py"
        ).resolve()
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit
        self.nonce_factory = nonce_factory or (lambda: secrets.token_hex(24))

    def run(
        self,
        format_id: str,
        argv: list[str] | None,
    ) -> tuple[dict[str, Any], bool]:
        command = parse_public_command(argv)
        invocation_base = Path.cwd().resolve(strict=True)
        if not invocation_base.is_dir():
            raise ValueError("public invocation base is not a directory")
        invocation_id = self.nonce_factory()
        if (
            type(invocation_id) is not str
            or not invocation_id
            or len(invocation_id.encode("ascii", errors="strict")) > 128
        ):
            raise ValueError("private invocation nonce is invalid")
        root = self.project_root / _INVOCATION_ROOT / f"invocation-{invocation_id}"
        root.mkdir(mode=0o700, parents=True)
        try:
            timeout_seconds, result_limit = self._command_limits(command, invocation_base)
            command_path = root / "command.json"
            result_path = root / "result.json"
            encoded = json.dumps(
                command_envelope(
                    invocation_id,
                    command,
                    format_id,
                    invocation_base,
                ),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            command_path.write_bytes(encoded)
            process = self._launch(
                command_path,
                result_path,
                invocation_id,
                root,
                timeout_seconds,
            )
            if process.returncode != 0:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "The isolated command worker failed safely.",
                    details={"phase": "worker", "reason_category": "worker_exit"},
                )
            envelope = validate_worker_envelope(
                read_bounded_json(result_path, result_limit),
                invocation_id,
                command.name,
            )
            if envelope["outcome"] != "ok":
                return self._safe_failure(command, format_id, envelope["failure"]), False
            payload = envelope["payload"]
            SchemaCatalog(self.project_root).validate(
                self._schema_for(command.name), payload
            )
            return payload, True
        except KeyboardInterrupt:
            return (
                self._safe_failure(
                    command,
                    format_id,
                    {
                        "category": "cancelled",
                        "phase": "supervisor",
                        "provider": None,
                        "exception_class": "KeyboardInterrupt",
                    },
                ),
                False,
            )
        except BaseException as error:
            return (
                self._safe_failure(
                    command,
                    format_id,
                    {
                        "category": self._reason_category(error),
                        "phase": "supervisor",
                        "provider": None,
                        "exception_class": type(error).__name__[:64],
                    },
                ),
                False,
            )
        finally:
            self._remove_private_root(root)

    def _launch(
        self,
        command_path: Path,
        result_path: Path,
        invocation_id: str,
        cwd: Path,
        timeout_seconds: float,
    ) -> Any:
        policy = ProcessPolicy(self.project_root)
        runner = ProcessRunner(policy)
        executable = policy.allow_executable("public-command-worker", sys.executable)
        worker = policy.allow_script("public-command-worker", self.worker_script)
        return runner.run(
            "public-command-worker",
            executable,
            [
                str(worker),
                "--command-file",
                str(command_path),
                "--result-file",
                str(result_path),
                "--invocation-id",
                invocation_id,
            ],
            script=worker,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            output_limit=self.output_limit,
        )

    def _command_limits(
        self,
        command: PublicCommand,
        invocation_base: Path,
    ) -> tuple[float, int]:
        if command.name in {"doctor", "capabilities"} and self.timeout_seconds >= 8.0:
            return max(self.timeout_seconds, _PROVIDER_PROBE_TIMEOUT_SECONDS), MAX_WORKER_BYTES
        if command.name != "run":
            return self.timeout_seconds, MAX_WORKER_BYTES
        try:
            request_index = command.argv.index("--request") + 1
            request_path = Path(command.argv[request_index]).expanduser()
            if not request_path.is_absolute():
                request_path = invocation_base / request_path
            request_path = request_path.resolve(strict=True)
            if request_path.is_symlink() or request_path.stat().st_size > 65_536:
                return self.timeout_seconds, MAX_WORKER_BYTES
            value = json.loads(request_path.read_text(encoding="utf-8"))
            if type(value) is dict and value.get("operation") == _HTML_OPERATION:
                return max(self.timeout_seconds, _HTML_WORKER_TIMEOUT_SECONDS), _HTML_WORKER_RESULT_BYTES
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        return self.timeout_seconds, MAX_WORKER_BYTES

    def _safe_failure(
        self,
        command: PublicCommand,
        format_id: str,
        failure: dict[str, Any],
    ) -> dict[str, Any]:
        category = failure.get("category")
        if command.name == "doctor":
            return {
                "schema_version": "1.0",
                "status": "unavailable",
                "project_version": __version__,
                "format": format_id,
                "runtime": [],
                "providers": [],
                "errors": [
                    {
                        "code": ErrorCode.RUNTIME_UNAVAILABLE.value,
                        "component": "isolated-worker",
                        "message": "Runtime diagnostics failed safely.",
                    }
                ],
            }
        if command.name == "capabilities":
            return {
                "schema_version": "1.0",
                "format": format_id,
                "operations": [],
                "providers": [],
                "validation": {
                    "package": "unavailable",
                    "schema": "unavailable",
                    "visual": "unavailable",
                },
            }
        if command.name == "validate":
            return empty_validation("unavailable")
        code = (
            ErrorCode.PROCESS_TIMEOUT
            if category == "timeout"
            else ErrorCode.PROVIDER_FAILED
        )
        return make_error_result(
            "",
            DocumentSkillsError(
                code,
                "The isolated provider boundary failed safely.",
                details={
                    "phase": str(failure.get("phase") or "worker")[:64],
                    "reason_category": str(category or "worker_failure")[:64],
                    "provider": (
                        str(failure["provider"])[:128]
                        if failure.get("provider") is not None
                        else None
                    ),
                    "exception_class": str(
                        failure.get("exception_class") or "UnknownFailure"
                    )[:64],
                },
            ),
        )

    @staticmethod
    def _reason_category(error: BaseException) -> str:
        if isinstance(error, DocumentSkillsError):
            if error.details.get("reason_category") == "cancelled":
                return "cancelled"
            if error.code == ErrorCode.PROCESS_TIMEOUT:
                return "timeout"
            text = str(error).casefold()
            if "byte ceiling" in text or "output exceeded" in text:
                return "overflow"
        return "invalid_worker_result"

    @staticmethod
    def _schema_for(command: str) -> str:
        return {
            "doctor": "doctor-report",
            "capabilities": "capability-report",
            "run": "operation-result",
            "validate": "validation-report",
        }[command]

    def _remove_private_root(self, root: Path) -> None:
        import shutil

        resolved = root.resolve(strict=False)
        expected_parent = (self.project_root / _INVOCATION_ROOT).resolve()
        if resolved.parent == expected_parent and resolved.name.startswith("invocation-"):
            shutil.rmtree(resolved, ignore_errors=True)


def main(format_id: str, project_root: Path, argv: list[str] | None = None) -> int:
    payload, success = PublicCommandSupervisor(project_root).run(format_id, argv)
    rendered = render_json_bytes(payload)
    sys.stdout.buffer.write(rendered)
    sys.stdout.buffer.flush()
    if success and payload.get("status") not in {
        "failed",
        "fail",
        "invalid_request",
        "unavailable",
    }:
        return 0
    category = (
        payload.get("errors", [{}])[0].get("details", {}).get("reason_category")
        if isinstance(payload.get("errors"), list)
        else None
    )
    return 130 if category == "cancelled" else 2
