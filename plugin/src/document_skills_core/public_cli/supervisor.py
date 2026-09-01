"""One-shot public command supervisor and sole stdout/cancellation owner."""

import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any, Callable

from document_skills_core import __version__
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import (
    empty_validation,
    make_error_result,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.contracts.serialization import render_json_bytes
from document_skills_core.core.process import ProcessPolicy, ProcessRunner
from document_skills_core.providers.dotnet.constants import (
    TIMEOUT_COLD_DETECTION,
    TIMEOUT_SCHEMA_VALIDATE,
)
from document_skills_core.worker.private_workspace import (
    PrivateOperationRoot,
    PrivateWorkspace,
)

from .protocol import (
    MAX_COMMAND_BYTES,
    MAX_WORKER_BYTES,
    PublicCommand,
    command_envelope,
    parse_public_command,
    parse_worker_terminal_frame,
    worker_failure_category,
    worker_schema,
)

_HTML_OPERATION = "pptx.create.from-html"
# Browser detection and capture have independent 30-second and 45-second hard
# bounds. Emission, package validation, worker startup, and teardown happen
# outside those subprocess windows, so the aggregate public boundary must
# contain their serial path while remaining finite.
_HTML_WORKER_TIMEOUT_SECONDS = 120.0
_HTML_WORKER_RESULT_BYTES = 1_048_576
_PDF_WORKER_TIMEOUT_SECONDS = 30.0
_PPTX_RECONSTRUCTION_OPERATION = "pptx.reconstruct.from-image"
_PPTX_RECONSTRUCTION_TIMEOUT_SECONDS = 60.0
_PPTX_RECONSTRUCTION_RESULT_BYTES = 1_048_576
_DOCX_LIBREOFFICE_OPERATIONS = frozenset(
    {
        "docx.compare.visual",
        "docx.convert.legacy",
        "docx.convert.pdf",
        "docx.layout.repair",
        "docx.render",
    }
)
_DOCX_LIBREOFFICE_WORKER_TIMEOUT_SECONDS = 90.0
_DOCX_DOTNET_OPERATIONS = frozenset(
    {
        "docx.comments.add",
        "docx.comments.read",
        "docx.comments.resolve",
        "docx.revisions.apply",
        "docx.revisions.read",
        "docx.validate.schema",
    }
)
# Keep every cold OpenXML public route derived from the provider's bounded
# detection chain. The remaining terms are one schema/operation call and finite
# worker startup/teardown headroom.
_DOTNET_WORKER_STARTUP_TEARDOWN_HEADROOM_SECONDS = 18.0
_DOTNET_COLD_OPERATION_TIMEOUT_SECONDS = (
    TIMEOUT_COLD_DETECTION
    + TIMEOUT_SCHEMA_VALIDATE
    + _DOTNET_WORKER_STARTUP_TEARDOWN_HEADROOM_SECONDS
)
_DOCX_DOTNET_WORKER_TIMEOUT_SECONDS = _DOTNET_COLD_OPERATION_TIMEOUT_SECONDS
_DOCX_TEMPLATE_PACK_OPERATIONS = frozenset(
    {
        "docx.template.pack.list",
        "docx.template.pack.read",
        "docx.template.pack.instantiate",
        "docx.template.import.inspect",
        "docx.template.import.create",
    }
)
_DOCX_TEMPLATE_PACK_WORKER_TIMEOUT_SECONDS = 90.0
_PPTX_MUTATION_OPERATIONS = {
    "pptx.create",
    "pptx.create.from-markdown",
    "pptx.create.from-svg",
    "pptx.create.from-template",
    "pptx.edit",
    "pptx.template.sanitize",
}
# A PPTX mutation can finish with one authorized OpenXML schema gate, so it uses
# the same single-detection aggregate as direct DOCX/XLSX/PPTX schema routes.
_PPTX_MUTATION_WORKER_TIMEOUT_SECONDS = _DOTNET_COLD_OPERATION_TIMEOUT_SECONDS
_PPTX_TEMPLATE_INSPECT_TIMEOUT_SECONDS = 150.0
_PROVIDER_OPERATION_TIMEOUTS = {
    "pptx.scene.export": 90.0,
    "pptx.template.inspect": _PPTX_TEMPLATE_INSPECT_TIMEOUT_SECONDS,
    "xlsx.convert": 45.0,
    "xlsx.recalculate": 90.0,
    "xlsx.render": 45.0,
}
_RECALCULATION_POLICY_OPERATIONS = {"xlsx.create", "xlsx.edit"}
_REQUIRED_RECALCULATION_TIMEOUT_SECONDS = 90.0
_LIBREOFFICE_CONVERT_OPERATION = "pptx.convert.pdf"
_LIBREOFFICE_CONVERT_TIMEOUT_SECONDS = 60.0
_LIBREOFFICE_LEGACY_OPERATION = "pptx.convert.legacy"
_LIBREOFFICE_RENDER_OPERATION = "pptx.render"
_LIBREOFFICE_RENDER_TIMEOUT_SECONDS = 150.0
# Provider reports probe independent runtimes serially. Preserve the existing
# finite 78-second allowance for the non-.NET probes around the shared cold
# detection bound.
_PROVIDER_PROBE_OTHER_HEADROOM_SECONDS = 78.0
_PROVIDER_PROBE_TIMEOUT_SECONDS = (
    TIMEOUT_COLD_DETECTION + _PROVIDER_PROBE_OTHER_HEADROOM_SECONDS
)
_DOTNET_SCHEMA_OPERATIONS = frozenset(
    {"pptx.validate.schema", "xlsx.validate.schema"}
)
_SCHEMA_WORKER_TIMEOUT_SECONDS = _DOTNET_COLD_OPERATION_TIMEOUT_SECONDS
# Ordinary public requests measured 8-10 seconds in isolation on the loaded
# Windows gate host and crossed the former 15-second ceiling under sustained
# development load.  Thirty seconds remains a hard fail-closed bound while
# avoiding false timeouts for otherwise valid cold worker starts.
_WORKER_TIMEOUT_SECONDS = 30.0
_PROVIDER_PROFILE_ENV = "DOCUMENT_SKILLS_PROVIDER_PROFILE"
_CORE_ONLY_PROFILE = "core-only"


class PublicCommandSupervisor:
    def __init__(
        self,
        project_root: Path,
        *,
        timeout_seconds: float = _WORKER_TIMEOUT_SECONDS,
        output_limit: int = 65_536,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.worker_script = (
            self.project_root
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
        workspace: PrivateWorkspace | None = None
        operation_root: PrivateOperationRoot | None = None
        outcome: tuple[dict[str, Any], bool] | None = None
        cleanup_failed = False
        try:
            invocation_base = Path.cwd().resolve(strict=True)
            if not invocation_base.is_dir():
                raise ValueError("public invocation base is not a directory")
            invocation_id = self.nonce_factory()
            if (
                type(invocation_id) is not str
                or not invocation_id
                or len(invocation_id.encode("ascii", errors="strict")) > 128
                or not all(
                    character.isalnum() or character in "-_"
                    for character in invocation_id
                )
            ):
                raise ValueError("private invocation nonce is invalid")
            workspace = PrivateWorkspace.create(self.project_root, invocation_id)
            operation_root = PrivateOperationRoot.create(
                self.project_root,
                invocation_id,
            )
            timeout_seconds, result_limit = self._command_limits(
                command, invocation_base
            )
            envelope = command_envelope(
                invocation_id,
                command,
                format_id,
                invocation_base,
                operation_root.path,
                operation_root.identity,
            )
            encoded = json.dumps(
                envelope,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            if len(encoded) > MAX_COMMAND_BYTES:
                raise ValueError("private command exceeds its byte ceiling")
            process = self._launch(
                envelope,
                workspace,
                timeout_seconds,
                result_limit,
            )
            if process.returncode != 0:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "The isolated command worker failed safely.",
                    details={
                        "phase": "worker",
                        "reason_category": "worker_exit",
                    },
                )
            envelope = parse_worker_terminal_frame(
                process.stdout,
                result_limit,
                invocation_id,
                command.name,
            )
            if envelope["outcome"] != "ok":
                outcome = (
                    self._safe_failure(command, format_id, envelope["failure"]),
                    False,
                )
            else:
                payload = envelope["payload"]
                SchemaCatalog(self.project_root).validate(
                    worker_schema(command.name), payload
                )
                outcome = (payload, True)
        except KeyboardInterrupt:
            outcome = (
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
            details = {}
            if (
                isinstance(error, DocumentSkillsError)
                and error.details.get("reason_category") == "worker_exit"
            ):
                details = error.details
            outcome = (
                self._safe_failure(
                    command,
                    format_id,
                    {
                        "category": worker_failure_category(error),
                        "phase": details.get("phase") or "supervisor",
                        "provider": details.get("provider"),
                        "exception_class": type(error).__name__[:64],
                    },
                ),
                False,
            )
        finally:
            if operation_root is not None:
                try:
                    cleanup_failed = not operation_root.close()
                except BaseException:
                    cleanup_failed = True
            if workspace is not None:
                workspace.close()
        if cleanup_failed:
            return (
                self._safe_failure(
                    command,
                    format_id,
                    {
                        "category": "cleanup_failed",
                        "phase": "supervisor_cleanup",
                        "provider": None,
                        "exception_class": "OSError",
                    },
                ),
                False,
            )
        if outcome is None:
            raise RuntimeError("public command completed without an outcome")
        return outcome

    def _launch(
        self,
        envelope: dict[str, Any],
        workspace: PrivateWorkspace,
        timeout_seconds: float,
        result_limit: int,
    ) -> Any:
        policy = ProcessPolicy(self.project_root)
        runner = ProcessRunner(policy)
        executable = policy.allow_executable("public-command-worker", sys.executable)
        worker = policy.allow_script("public-command-worker", self.worker_script)
        fixed_environment = (
            {_PROVIDER_PROFILE_ENV: _CORE_ONLY_PROFILE}
            if os.environ.get(_PROVIDER_PROFILE_ENV) == _CORE_ONLY_PROFILE
            else None
        )
        cwd, descriptor, identity, bootstrap_args = workspace.launch_parameters()
        return runner.run_public_command_worker(
            "public-command-worker",
            executable,
            [str(worker), *bootstrap_args],
            script=worker,
            stdin_json=envelope,
            workspace_cwd=cwd,
            posix_workspace_fd=descriptor,
            posix_workspace_identity=identity,
            timeout_seconds=timeout_seconds,
            output_limit=result_limit + self.output_limit,
            fixed_environment=fixed_environment,
        )

    def _command_limits(
        self,
        command: PublicCommand,
        invocation_base: Path,
    ) -> tuple[float, int]:
        if command.name in {"doctor", "capabilities"} and self.timeout_seconds >= 8.0:
            return max(
                self.timeout_seconds, _PROVIDER_PROBE_TIMEOUT_SECONDS
            ), MAX_WORKER_BYTES
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
                return max(
                    self.timeout_seconds, _HTML_WORKER_TIMEOUT_SECONDS
                ), _HTML_WORKER_RESULT_BYTES
            if type(value) is dict and str(value.get("operation", "")).startswith(
                "pdf."
            ):
                return max(
                    self.timeout_seconds, _PDF_WORKER_TIMEOUT_SECONDS
                ), MAX_WORKER_BYTES
            if (
                type(value) is dict
                and value.get("operation") == _PPTX_RECONSTRUCTION_OPERATION
            ):
                return (
                    max(self.timeout_seconds, _PPTX_RECONSTRUCTION_TIMEOUT_SECONDS),
                    _PPTX_RECONSTRUCTION_RESULT_BYTES,
                )
            if (
                type(value) is dict
                and value.get("operation") in _DOCX_LIBREOFFICE_OPERATIONS
            ):
                return (
                    max(
                        self.timeout_seconds,
                        _DOCX_LIBREOFFICE_WORKER_TIMEOUT_SECONDS,
                    ),
                    MAX_WORKER_BYTES,
                )
            if (
                type(value) is dict
                and value.get("operation") in _DOCX_DOTNET_OPERATIONS
            ):
                return (
                    max(self.timeout_seconds, _DOCX_DOTNET_WORKER_TIMEOUT_SECONDS),
                    MAX_WORKER_BYTES,
                )
            if (
                type(value) is dict
                and value.get("operation") in _DOCX_TEMPLATE_PACK_OPERATIONS
            ):
                return (
                    max(self.timeout_seconds, _DOCX_TEMPLATE_PACK_WORKER_TIMEOUT_SECONDS),
                    MAX_WORKER_BYTES,
                )
            if type(value) is dict and value.get("operation") in _PPTX_MUTATION_OPERATIONS:
                return (
                    max(self.timeout_seconds, _PPTX_MUTATION_WORKER_TIMEOUT_SECONDS),
                    MAX_WORKER_BYTES,
                )
            if type(value) is dict and value.get("operation") in _PROVIDER_OPERATION_TIMEOUTS:
                operation = value["operation"]
                return max(
                    self.timeout_seconds,
                    _PROVIDER_OPERATION_TIMEOUTS[operation],
                ), MAX_WORKER_BYTES
            if (
                type(value) is dict
                and value.get("operation") in _RECALCULATION_POLICY_OPERATIONS
                and type(value.get("arguments")) is dict
                and value["arguments"].get("recalculation") == "required"
            ):
                return max(
                    self.timeout_seconds,
                    _REQUIRED_RECALCULATION_TIMEOUT_SECONDS,
                ), MAX_WORKER_BYTES
            if (
                type(value) is dict
                and value.get("operation") in _DOTNET_SCHEMA_OPERATIONS
            ):
                return max(self.timeout_seconds, _SCHEMA_WORKER_TIMEOUT_SECONDS), MAX_WORKER_BYTES
            if (
                type(value) is dict
                and value.get("operation") in {
                    _LIBREOFFICE_CONVERT_OPERATION,
                    _LIBREOFFICE_LEGACY_OPERATION,
                }
            ):
                return (
                    max(self.timeout_seconds, _LIBREOFFICE_CONVERT_TIMEOUT_SECONDS),
                    MAX_WORKER_BYTES,
                )
            if (
                type(value) is dict
                and value.get("operation") == _LIBREOFFICE_RENDER_OPERATION
            ):
                return (
                    max(self.timeout_seconds, _LIBREOFFICE_RENDER_TIMEOUT_SECONDS),
                    MAX_WORKER_BYTES,
                )
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
