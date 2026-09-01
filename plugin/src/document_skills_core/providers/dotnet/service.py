"""DotnetOpenXmlProvider — dispatcher and injectable factory.

Exposes ``build_dotnet_provider(project_root, detector=None, runner=None)``
returning a ``(ProviderDefinition, DotnetOpenXmlProvider)`` pair. The
ProviderDefinition is registered in the catalog; the DotnetOpenXmlProvider
is the consultation object passed to format services.

Module provenance: original Elftia-authored clean-room implementation.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

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
from .comments import add_comment, read_comments, resolve_comment
from .detector import DotnetOpenXmlDetector
from .revisions import accept_reject_revisions, read_revisions
from .runner import DotnetOpenXmlRunner
from .schema import validate_schema, validate_spreadsheet_schema
from .template import apply_template_advanced


class _OperationAuthorization:
    def __init__(self, evidence: DetectionEvidence, runner: Any) -> None:
        self.evidence = evidence
        self.runner = runner


class _OperationLease:
    def __init__(self) -> None:
        self.authorization: _OperationAuthorization | None = None


class DotnetOpenXmlProvider:
    """Wraps detector + runner; provides consultation methods for format services."""

    def __init__(
        self,
        project_root: Path,
        detector: DotnetOpenXmlDetector | None = None,
        runner: DotnetOpenXmlRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self._operation_lease: ContextVar[_OperationLease | None] = ContextVar(
            f"dotnet-openxml-operation-lease-{id(self)}",
            default=None,
        )
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
        if self._operation_lease.get() is not None:
            return self._authorization_for_operation().evidence
        return self.detector.detect()

    @contextmanager
    def operation_lease(self) -> Iterator[None]:
        """Reuse one authorized detection only within the current command."""

        if self._operation_lease.get() is not None:
            yield
            return
        token = self._operation_lease.set(_OperationLease())
        try:
            yield
        finally:
            self._operation_lease.reset(token)

    def diagnostics(self) -> dict[str, Any]:
        evidence = self.detector.detect()
        if evidence.available:
            return {"path": evidence.path, "version": evidence.version}
        return {
            "path": None,
            "version": None,
            "reason": evidence.reason or "unavailable",
        }

    def _authorization_for_operation(self) -> _OperationAuthorization:
        lease = self._operation_lease.get()
        if lease is not None and lease.authorization is not None:
            return lease.authorization
        launch_runner: Any = self.runner
        if isinstance(self.detector, DotnetOpenXmlDetector):
            if isinstance(self.runner, DotnetOpenXmlRunner):
                bindings: list[Any] = []

                def bind(executable: str | Path) -> None:
                    bindings.append(
                        self.runner.bind_authorized_executable(executable)
                    )

            else:
                bind = self.runner.set_executable
            evidence = self.detector.detect_and_authorize(bind)
            if (
                evidence.available
                and isinstance(self.runner, DotnetOpenXmlRunner)
            ):
                if len(bindings) != 1:
                    evidence = DetectionEvidence(
                        available=False,
                        reason="dotnet operation launch binding is unavailable",
                        path=evidence.path,
                    )
                elif bindings[0] is None:
                    # Legacy injected runners record the authorized path but do
                    # not expose a launch binding.  They are test doubles, not
                    # the production runner that owns executable authority.
                    if type(self.runner) is DotnetOpenXmlRunner:
                        evidence = DetectionEvidence(
                            available=False,
                            reason="dotnet operation launch binding is unavailable",
                            path=evidence.path,
                        )
                else:
                    launch_runner = self.runner.bind(bindings[0])
        else:
            evidence = self.detector.detect()
            if evidence.available and evidence.path:
                self.runner.set_executable(evidence.path)
        authorization = _OperationAuthorization(evidence, launch_runner)
        if lease is not None:
            lease.authorization = authorization
        return authorization

    def _callable_authorization(self) -> _OperationAuthorization:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "dotnet-openxml is not callable.",
            )
        return authorization

    def read_revisions(
        self,
        input_path: Path,
        limit: int,
        *,
        filters: dict[str, Any] | None = None,
        scope: dict[str, Any] | None = None,
        revision_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run the strict private helper for the public revisions projection."""

        authorization = self._callable_authorization()
        return read_revisions(
            input_path,
            authorization.runner,
            limit=limit,
            filters=filters,
            scope=scope,
            revision_ids=revision_ids,
        )

    def apply_revisions(
        self,
        input_path: Path,
        output_path: Path,
        revision_ids: list[str],
        action: str,
    ) -> dict[str, Any]:
        """Apply a bounded revision transaction into a private candidate."""

        authorization = self._callable_authorization()
        return accept_reject_revisions(
            input_path,
            output_path,
            revision_ids,
            action,
            authorization.runner,
        )

    def read_comments(
        self,
        input_path: Path,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Run the strict private helper for the public comments projection."""

        authorization = self._callable_authorization()
        return read_comments(
            input_path,
            authorization.runner,
            max_comments=limit,
        )

    def add_comment(
        self,
        input_path: Path,
        output_path: Path,
        comment: dict[str, Any],
    ) -> str:
        """Add one bounded anchored comment into a private candidate."""

        authorization = self._callable_authorization()
        return add_comment(
            input_path,
            output_path,
            comment,
            authorization.runner,
        )

    def resolve_comment(
        self,
        input_path: Path,
        output_path: Path,
        comment_id: str,
        resolved: bool,
    ) -> dict[str, Any]:
        """Set the resolved state of one bounded root comment thread."""

        authorization = self._callable_authorization()
        return resolve_comment(
            input_path,
            output_path,
            comment_id,
            resolved,
            authorization.runner,
        )

    def validate_schema(
        self,
        input_path: Path,
        limit: int,
    ) -> dict[str, Any]:
        """Run OpenXmlValidator and return its bounded private report."""

        authorization = self._callable_authorization()
        return validate_schema(
            input_path,
            authorization.runner,
            max_errors=limit,
        )

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        if self._operation_lease.get() is None:
            with self.operation_lease():
                return self.execute(operation, request)
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
        authorization = self._callable_authorization()
        runner = authorization.runner
        if operation == "dotnet.docx.revisions-read":
            return self._do_revisions_read(Path(request["input"]), runner)
        if operation == "dotnet.docx.revisions-accept":
            return self._do_revisions_mutate(Path(request["input"]), Path(request["output"]), request.get("revision_ids", []), "accept", runner)
        if operation == "dotnet.docx.revisions-reject":
            return self._do_revisions_mutate(Path(request["input"]), Path(request["output"]), request.get("revision_ids", []), "reject", runner)
        if operation == "dotnet.docx.comments-read":
            return self._do_comments_read(Path(request["input"]), request, runner)
        if operation == "dotnet.docx.comments-add":
            return self._do_comments_add(Path(request["input"]), Path(request["output"]), request["comment"], runner)
        if operation == "dotnet.docx.comments-resolve":
            return self._do_comments_resolve(
                Path(request["input"]),
                Path(request["output"]),
                request["comment_id"],
                request["resolved"],
                runner,
            )
        if operation == "dotnet.docx.template-apply":
            return self._do_template(Path(request["input"]), Path(request["output"]), request.get("variables", {}), runner)
        if operation == "dotnet.docx.schema-validate":
            return self._do_schema(Path(request["input"]), runner)
        if operation == "xlsx.validate.schema":
            return self._do_xlsx_schema(request, runner)
        if operation == "pptx.validate.schema":
            return self._do_pptx_schema(Path(request["input"]), request, runner)
        raise DocumentSkillsError(
            ErrorCode.OPERATION_UNKNOWN,
            f"Unknown dotnet-openxml operation: {operation}",
        )

    # -- consultation helpers (return None on absent/failure) --

    def try_read_revisions(self, input_path: Path) -> list[dict[str, Any]] | None:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            return None
        try:
            return read_revisions(input_path, authorization.runner)
        except DocumentSkillsError:
            return None

    def try_accept_reject_revisions(
        self, input_path: Path, output_path: Path, revision_ids: list[str], action: str,
    ) -> dict[str, Any] | None:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            return None
        try:
            return accept_reject_revisions(
                input_path,
                output_path,
                revision_ids,
                action,
                authorization.runner,
            )
        except DocumentSkillsError:
            return None

    def try_read_comments(
        self, input_path: Path, **filters: Any,
    ) -> list[dict[str, Any]] | None:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            return None
        try:
            return read_comments(input_path, authorization.runner, **filters)
        except DocumentSkillsError:
            return None

    def try_add_comment(
        self, input_path: Path, output_path: Path, comment: dict[str, Any],
    ) -> str | None:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            return None
        try:
            return add_comment(
                input_path,
                output_path,
                comment,
                authorization.runner,
            )
        except DocumentSkillsError:
            return None

    def try_resolve_comment(
        self,
        input_path: Path,
        output_path: Path,
        comment_id: str,
        resolved: bool,
    ) -> dict[str, Any] | None:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            return None
        try:
            return resolve_comment(
                input_path,
                output_path,
                comment_id,
                resolved,
                authorization.runner,
            )
        except DocumentSkillsError:
            return None

    def try_validate_schema(self, input_path: Path) -> dict[str, Any] | None:
        _evidence, result = self.try_validate_schema_with_evidence(input_path)
        return result

    def try_validate_schema_with_evidence(
        self,
        input_path: Path,
    ) -> tuple[DetectionEvidence | None, dict[str, Any] | None]:
        """Detect, authorize, and validate without repeating the provider probe."""

        try:
            authorization = self._authorization_for_operation()
        except Exception:
            return None, None
        evidence = authorization.evidence
        if not evidence.available:
            return evidence, None
        try:
            return evidence, validate_schema(input_path, authorization.runner)
        except DocumentSkillsError:
            return evidence, None

    def try_apply_template(
        self, input_path: Path, output_path: Path, variables: dict[str, str],
    ) -> dict[str, Any] | None:
        authorization = self._authorization_for_operation()
        if not authorization.evidence.available:
            return None
        try:
            return apply_template_advanced(
                input_path,
                output_path,
                variables,
                authorization.runner,
            )
        except DocumentSkillsError:
            return None

    # -- execute dispatchers --

    def _do_revisions_read(self, input_path: Path, runner: Any) -> dict[str, Any]:
        revisions = read_revisions(input_path, runner)
        return _build_success(
            "dotnet.docx.revisions-read",
            diagnostics={"revisions": revisions},
        )

    def _do_revisions_mutate(
        self, input_path: Path, output_path: Path, revision_ids: list[str], action: str,
        runner: Any,
    ) -> dict[str, Any]:
        diag = accept_reject_revisions(
            input_path,
            output_path,
            revision_ids,
            action,
            runner,
        )
        return _build_success(
            f"dotnet.docx.revisions-{action}",
            diagnostics=diag,
        )

    def _do_comments_read(
        self,
        input_path: Path,
        request: dict[str, Any],
        runner: Any,
    ) -> dict[str, Any]:
        comments = read_comments(
            input_path, runner,
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
        runner: Any,
    ) -> dict[str, Any]:
        comment_id = add_comment(input_path, output_path, comment, runner)
        return _build_success(
            "dotnet.docx.comments-add",
            diagnostics={"comment_id": comment_id},
        )

    def _do_comments_resolve(
        self,
        input_path: Path,
        output_path: Path,
        comment_id: str,
        resolved: bool,
        runner: Any,
    ) -> dict[str, Any]:
        result = resolve_comment(
            input_path,
            output_path,
            comment_id,
            resolved,
            runner,
        )
        return _build_success(
            "dotnet.docx.comments-resolve",
            diagnostics=result,
        )

    def _do_template(
        self, input_path: Path, output_path: Path, variables: dict[str, str],
        runner: Any,
    ) -> dict[str, Any]:
        diag = apply_template_advanced(input_path, output_path, variables, runner)
        return _build_success(
            "dotnet.docx.template-apply",
            diagnostics=diag,
        )

    def _do_schema(self, input_path: Path, runner: Any) -> dict[str, Any]:
        result = validate_schema(input_path, runner)
        return _build_success(
            "dotnet.docx.schema-validate",
            diagnostics=result,
        )

    def _do_xlsx_schema(self, request: dict[str, Any], runner: Any) -> dict[str, Any]:
        return execute_schema_validation(
            request,
            project_root=self.project_root,
            validator=lambda path, max_errors: validate_spreadsheet_schema(
                path,
                runner,
                max_errors=max_errors,
            ),
        )

    def _do_pptx_schema(
        self,
        input_path: Path,
        request: dict[str, Any],
        runner: Any,
    ) -> dict[str, Any]:
        source = file_record(input_path, "input")
        result = validate_schema(input_path, runner)
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
            Capability("dotnet.docx.comments-resolve", "enhanced", validation_strength=1),
            Capability("dotnet.docx.template-apply", "enhanced", validation_strength=1),
            Capability("dotnet.docx.schema-validate", "enhanced", validation_strength=1),
            Capability("xlsx.validate.schema", "enhanced", validation_strength=3),
            Capability("pptx.validate.schema", "enhanced", validation_strength=3),
        ],
        diagnostics=provider.diagnostics,
        validators={"schema": provider.try_validate_schema},
        required=False,
        operation_lease=provider.operation_lease,
    )
    return definition, provider
