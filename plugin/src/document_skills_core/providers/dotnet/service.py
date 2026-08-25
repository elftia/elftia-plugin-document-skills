"""DotnetOpenXmlProvider — dispatcher and injectable factory.

Exposes ``build_dotnet_provider(project_root, detector=None, runner=None)``
returning a ``(ProviderDefinition, DotnetOpenXmlProvider)`` pair. The
ProviderDefinition is registered in the catalog; the DotnetOpenXmlProvider
is the consultation object passed to format services.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.capabilities.catalog import (
    Capability,
    DetectionEvidence,
    ProviderDefinition,
    ProviderId,
)
from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.contracts.models import gate_record, make_error_result
from ...core.io.paths import assert_source_preserved, file_record
from ...core.process import ProcessPolicy, ProcessRunner
from ...formats.xlsx.schema_operation import execute_schema_validation
from .comments import add_comment, read_comments
from .detector import DotnetOpenXmlDetector
from .revisions import accept_reject_revisions, read_revisions
from .runner import DotnetOpenXmlRunner
from .schema import validate_schema, validate_spreadsheet_schema
from .template import apply_template_advanced


class DotnetOpenXmlProvider:
    """Wraps detector + runner; provides consultation methods for format services."""

    def __init__(
        self,
        project_root: Path,
        detector: DotnetOpenXmlDetector | None = None,
        runner: DotnetOpenXmlRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        if detector is None and runner is None:
            policy = ProcessPolicy(self.project_root)
            process_runner = ProcessRunner(policy)
            self.detector = DotnetOpenXmlDetector(
                project_root,
                runner=process_runner,
                policy=policy,
            )
            self.runner = DotnetOpenXmlRunner(
                project_root,
                runner=process_runner,
                policy=policy,
            )
        else:
            self.detector = detector or DotnetOpenXmlDetector(project_root)
            self.runner = runner or DotnetOpenXmlRunner(project_root)

    def detect(self) -> DetectionEvidence:
        return self.detector.detect()

    def diagnostics(self) -> dict[str, Any]:
        evidence = self.detector.detect()
        if evidence.available:
            return {"path": evidence.path, "version": evidence.version}
        return {
            "path": None,
            "version": None,
            "reason": evidence.reason or "unavailable",
        }

    def _detect_for_operation(self) -> DetectionEvidence:
        if isinstance(self.detector, DotnetOpenXmlDetector):
            if isinstance(self.runner, DotnetOpenXmlRunner):
                bind = self.runner.bind_authorized_executable
            else:
                bind = self.runner.set_executable
            return self.detector.detect_and_authorize(bind)
        evidence = self.detector.detect()
        if evidence.available and evidence.path:
            self.runner.set_executable(evidence.path)
        return evidence

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._dispatch(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            requested_fidelity = (
                options.get("fidelity", "core")
                if type(options) is dict
                else "unknown"
            )
            return make_error_result(
                operation,
                error,
                requested_fidelity=requested_fidelity,
            )

    def _dispatch(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "dotnet-openxml is not callable.",
            )
        if operation == "dotnet.docx.revisions-read":
            return self._do_revisions_read(Path(request["input"]))
        if operation == "dotnet.docx.revisions-accept":
            return self._do_revisions_mutate(Path(request["input"]), Path(request["output"]), request.get("revision_ids", []), "accept")
        if operation == "dotnet.docx.revisions-reject":
            return self._do_revisions_mutate(Path(request["input"]), Path(request["output"]), request.get("revision_ids", []), "reject")
        if operation == "dotnet.docx.comments-read":
            return self._do_comments_read(Path(request["input"]), request)
        if operation == "dotnet.docx.comments-add":
            return self._do_comments_add(Path(request["input"]), Path(request["output"]), request["comment"])
        if operation == "dotnet.docx.template-apply":
            return self._do_template(Path(request["input"]), Path(request["output"]), request.get("variables", {}))
        if operation == "dotnet.docx.schema-validate":
            return self._do_schema(Path(request["input"]))
        if operation == "xlsx.validate.schema":
            return self._do_xlsx_schema(request)
        if operation == "pptx.validate.schema":
            return self._do_pptx_schema(Path(request["input"]), request)
        raise DocumentSkillsError(
            ErrorCode.OPERATION_UNKNOWN,
            f"Unknown dotnet-openxml operation: {operation}",
        )

    # -- consultation helpers (return None on absent/failure) --

    def try_read_revisions(self, input_path: Path) -> list[dict[str, Any]] | None:
        evidence = self._detect_for_operation()
        if not evidence.available:
            return None
        try:
            return read_revisions(input_path, self.runner)
        except DocumentSkillsError:
            return None

    def try_accept_reject_revisions(
        self, input_path: Path, output_path: Path, revision_ids: list[str], action: str,
    ) -> dict[str, Any] | None:
        evidence = self._detect_for_operation()
        if not evidence.available:
            return None
        try:
            return accept_reject_revisions(input_path, output_path, revision_ids, action, self.runner)
        except DocumentSkillsError:
            return None

    def try_read_comments(
        self, input_path: Path, **filters: Any,
    ) -> list[dict[str, Any]] | None:
        evidence = self._detect_for_operation()
        if not evidence.available:
            return None
        try:
            return read_comments(input_path, self.runner, **filters)
        except DocumentSkillsError:
            return None

    def try_add_comment(
        self, input_path: Path, output_path: Path, comment: dict[str, Any],
    ) -> str | None:
        evidence = self._detect_for_operation()
        if not evidence.available:
            return None
        try:
            return add_comment(input_path, output_path, comment, self.runner)
        except DocumentSkillsError:
            return None

    def try_validate_schema(self, input_path: Path) -> dict[str, Any] | None:
        evidence = self._detect_for_operation()
        if not evidence.available:
            return None
        try:
            return validate_schema(input_path, self.runner)
        except DocumentSkillsError:
            return None

    def try_apply_template(
        self, input_path: Path, output_path: Path, variables: dict[str, str],
    ) -> dict[str, Any] | None:
        evidence = self._detect_for_operation()
        if not evidence.available:
            return None
        try:
            return apply_template_advanced(input_path, output_path, variables, self.runner)
        except DocumentSkillsError:
            return None

    # -- execute dispatchers --

    def _do_revisions_read(self, input_path: Path) -> dict[str, Any]:
        revisions = read_revisions(input_path, self.runner)
        return _build_success(
            "dotnet.docx.revisions-read",
            diagnostics={"revisions": revisions},
        )

    def _do_revisions_mutate(
        self, input_path: Path, output_path: Path, revision_ids: list[str], action: str,
    ) -> dict[str, Any]:
        diag = accept_reject_revisions(input_path, output_path, revision_ids, action, self.runner)
        return _build_success(
            f"dotnet.docx.revisions-{action}",
            diagnostics=diag,
        )

    def _do_comments_read(self, input_path: Path, request: dict[str, Any]) -> dict[str, Any]:
        comments = read_comments(
            input_path, self.runner,
            filter_id=request.get("filter_id"),
            filter_author=request.get("filter_author"),
            filter_range=request.get("filter_range"),
        )
        return _build_success(
            "dotnet.docx.comments-read",
            diagnostics={"comments": comments},
        )

    def _do_comments_add(
        self, input_path: Path, output_path: Path, comment: dict[str, Any],
    ) -> dict[str, Any]:
        comment_id = add_comment(input_path, output_path, comment, self.runner)
        return _build_success(
            "dotnet.docx.comments-add",
            diagnostics={"comment_id": comment_id},
        )

    def _do_template(
        self, input_path: Path, output_path: Path, variables: dict[str, str],
    ) -> dict[str, Any]:
        diag = apply_template_advanced(input_path, output_path, variables, self.runner)
        return _build_success(
            "dotnet.docx.template-apply",
            diagnostics=diag,
        )

    def _do_schema(self, input_path: Path) -> dict[str, Any]:
        result = validate_schema(input_path, self.runner)
        return _build_success(
            "dotnet.docx.schema-validate",
            diagnostics=result,
        )

    def _do_xlsx_schema(self, request: dict[str, Any]) -> dict[str, Any]:
        return execute_schema_validation(
            request,
            project_root=self.project_root,
            validator=lambda path, max_errors: validate_spreadsheet_schema(
                path,
                self.runner,
                max_errors=max_errors,
            ),
        )

    def _do_pptx_schema(
        self,
        input_path: Path,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        source = file_record(input_path, "input")
        result = validate_schema(input_path, self.runner)
        assert_source_preserved(source.path, source.sha256)
        valid = result["valid"] is True
        errors = result["errors"]
        gate = gate_record(
            "schema.full",
            "pass" if valid else "fail",
            required=True,
            validator="dotnet-openxml",
            evidence={
                "error_count": len(errors),
                "errors": errors[:100],
                "valid": valid,
            },
        )
        requested = request.get("options", {})
        requested_fidelity = (
            requested.get("fidelity", "core")
            if type(requested) is dict
            else "unknown"
        )
        return {
            "schema_version": "1.0",
            "status": "success" if valid else "failed",
            "operation": "pptx.validate.schema",
            "provider_chain": [],
            "requested_fidelity": requested_fidelity,
            "achieved_fidelity": "enhanced",
            "degraded": False,
            "degradations": [],
            "artifacts": [source.as_dict()],
            "validation": {
                "schema_version": "1.0",
                "status": "pass" if valid else "fail",
                "gates": [gate],
            },
            "warnings": [],
            "errors": [] if valid else [{
                "code": ErrorCode.VALIDATION_FAILED.value,
                "message": "OpenXML schema validation reported errors.",
                "details": {"error_count": len(errors)},
            }],
            "diagnostics": {"dotnet-openxml": result},
        }


def _build_success(operation: str, *, diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "operation": operation,
        "provider_chain": [],
        "requested_fidelity": "enhanced",
        "achieved_fidelity": "enhanced",
        "degraded": False,
        "degradations": [],
        "artifacts": [],
        "validation": {"gates": []},
        "warnings": [],
        "errors": [],
        "diagnostics": {"dotnet-openxml": diagnostics},
    }


def build_dotnet_provider(
    project_root: Path,
    detector: DotnetOpenXmlDetector | None = None,
    runner: DotnetOpenXmlRunner | None = None,
) -> tuple[ProviderDefinition, DotnetOpenXmlProvider]:
    """Build the callable dotnet-openxml provider definition + consultation object."""
    provider = DotnetOpenXmlProvider(project_root, detector=detector, runner=runner)
    definition = ProviderDefinition(
        id=ProviderId.DOTNET_OPENXML,
        version=None,
        detect=provider.detect,
        execute=provider.execute,
        capabilities=[
            Capability("dotnet.docx.revisions-read", "enhanced", validation_strength=1),
            Capability("dotnet.docx.revisions-accept", "enhanced", validation_strength=1),
            Capability("dotnet.docx.revisions-reject", "enhanced", validation_strength=1),
            Capability("dotnet.docx.comments-read", "enhanced", validation_strength=1),
            Capability("dotnet.docx.comments-add", "enhanced", validation_strength=1),
            Capability("dotnet.docx.template-apply", "enhanced", validation_strength=1),
            Capability("dotnet.docx.schema-validate", "enhanced", validation_strength=1),
            Capability("xlsx.validate.schema", "enhanced", validation_strength=3),
            Capability("pptx.validate.schema", "enhanced", validation_strength=3),
        ],
        diagnostics=provider.diagnostics,
        validators={"schema": provider.try_validate_schema},
        required=False,
    )
    return definition, provider
