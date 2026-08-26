"""Twenty-operation DOCX dispatch and shared transactional mutation."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .accessibility import inspect_accessibility_operation
from .comment_operation import (
    comments_add_operation,
    comments_read_operation,
    comments_resolve_operation,
)
from .contracts import ParsedDocxRequest, parse_docx_request
from .conversion import convert_pdf_operation
from .create import create_docx
from .editing import edit_operation
from .inspect import inspect_docx
from .legacy_conversion import convert_legacy_operation
from .layout_repair import layout_repair_operation
from .mapping import document_stories, protected_comment_text
from .merge_operation import merge_operation
from .package import OpcPackage
from .read import read_docx
from .rendering import render_pdf_operation
from .replace import (
    apply_replacement_plan,
    changed_story_parts,
    plan_diagnostics,
    plan_replacements,
)
from .revisions import (
    assert_revision_scope,
    project_revision_records,
)
from .revision_operation import revision_apply_operation
from .results import read_validation, success_result
from .schema_validation import project_schema_result, schema_validation_report
from .semantic_compare import semantic_compare_operation
from .structural_diff import summarize_structural_diff
from .template import (
    apply_template_with_node,
)
from .template_operation import template_operation
from .transaction import promote_candidate, write_candidate_result
from .validation import (
    assert_replacement_text,
    validate_created,
    validate_mutation,
)
from .visual_compare import visual_compare_operation


class DocxService:
    def __init__(self, project_root: Path, libreoffice=None, dotnet=None) -> None:
        self.project_root = project_root.resolve()
        self.schemas = SchemaCatalog(self.project_root)
        self.libreoffice = libreoffice
        self.dotnet = dotnet

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._execute(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            requested_fidelity = (
                options.get("fidelity", "core") if type(options) is dict else "unknown"
            )
            return make_error_result(
                operation,
                error,
                requested_fidelity=requested_fidelity,
            )

    def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_docx_request(request)
        if parsed.operation != operation:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "DOCX provider binding does not match the request operation.",
                status="invalid_request",
            )
        if operation == "docx.read":
            return self._read(parsed)
        if operation == "docx.inspect.accessibility":
            return inspect_accessibility_operation(parsed)
        if operation == "docx.inspect.structure":
            return self._inspect(parsed)
        if operation == "docx.compare.semantic":
            return semantic_compare_operation(parsed)
        if operation == "docx.compare.visual":
            return visual_compare_operation(parsed, libreoffice=self.libreoffice)
        if operation == "docx.create":
            return self._create(parsed)
        if operation == "docx.edit":
            return edit_operation(parsed, schemas=self.schemas)
        if operation == "docx.edit.replace-text":
            return self._replace(parsed)
        if operation == "docx.merge":
            return merge_operation(parsed, schemas=self.schemas)
        if operation == "docx.revisions.read":
            return self._revisions_read(parsed)
        if operation == "docx.revisions.apply":
            return self._revisions_apply(parsed)
        if operation == "docx.comments.read":
            return comments_read_operation(parsed, dotnet=self.dotnet)
        if operation == "docx.comments.add":
            return comments_add_operation(
                parsed,
                dotnet=self.dotnet,
                schemas=self.schemas,
            )
        if operation == "docx.comments.resolve":
            return comments_resolve_operation(
                parsed,
                dotnet=self.dotnet,
                schemas=self.schemas,
            )
        if operation == "docx.validate.schema":
            return self._validate_schema(parsed)
        if operation == "docx.convert.legacy":
            return convert_legacy_operation(
                parsed,
                schemas=self.schemas,
                libreoffice=self.libreoffice,
            )
        if operation == "docx.convert.pdf":
            return convert_pdf_operation(
                parsed,
                schemas=self.schemas,
                libreoffice=self.libreoffice,
            )
        if operation == "docx.render":
            return render_pdf_operation(
                parsed,
                schemas=self.schemas,
                libreoffice=self.libreoffice,
            )
        if operation == "docx.layout.repair":
            return layout_repair_operation(
                parsed,
                schemas=self.schemas,
                libreoffice=self.libreoffice,
            )
        return self._template(parsed)

    def _read(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = read_docx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.structured-read", operation_result),
        )

    def _inspect(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = inspect_docx(
            request.input_path, request.arguments
        )
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.inert-inspection", operation_result),
        )

    def _revisions_read(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        source_package = OpcPackage.open(request.input_path)
        if self.dotnet is None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "DOCX revision reading requires the dotnet-openxml provider.",
                status="enhancement_required",
                details={"recommended_providers": ["dotnet-openxml"]},
            )
        maximum = request.arguments["max_revisions"]
        filters = request.arguments.get("filters")
        scope = request.arguments.get("scope")
        provider_scope = assert_revision_scope(source_package, scope)
        if filters is None and provider_scope is None:
            raw_records = self.dotnet.read_revisions(request.input_path, maximum + 1)
        else:
            raw_records = self.dotnet.read_revisions(
                request.input_path,
                maximum + 1,
                filters=filters,
                scope=provider_scope,
                revision_ids=None,
            )
        revisions = project_revision_records(
            raw_records,
            max_revisions=maximum,
            package=source_package,
            filters=filters,
            scope=scope,
        )
        assert_source_preserved(source.path, source.sha256)
        operation_result = {"revisions": revisions}
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=[],
            validation=read_validation("operation.revisions-read", operation_result),
            achieved_fidelity="enhanced",
        )

    def _validate_schema(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        OpcPackage.open(request.input_path)
        if self.dotnet is None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "DOCX schema validation requires the dotnet-openxml provider.",
                status="enhancement_required",
                details={"recommended_providers": ["dotnet-openxml"]},
            )
        maximum = request.arguments["max_errors"]
        raw_result = self.dotnet.validate_schema(request.input_path, maximum + 1)
        schema = project_schema_result(raw_result, max_errors=maximum)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result={"schema": schema},
            warnings=[],
            validation=schema_validation_report(schema),
            achieved_fidelity="enhanced",
        )

    def _revisions_apply(self, request: ParsedDocxRequest) -> dict[str, Any]:
        return revision_apply_operation(
            request,
            dotnet=self.dotnet,
            schemas=self.schemas,
        )

    def _create(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.output_path is not None
        report = request.arguments["report"]
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "created.docx"
            creation = create_docx(staged, report)
            validation = validate_created(
                staged,
                report,
                creation["images"],
                creation["styles"],
            )
            result = write_candidate_result(
                self.schemas,
                request,
                staged,
                validation,
                {"creation": creation},
                warnings=[],
                source=None,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=None,
                destination=destination,
            )

    def _replace(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        assert request.output_path is not None
        assert_distinct_paths(
            request.input_path,
            request.output_path,
            in_place=False,
        )
        source_record = file_record(request.input_path, "input")
        destination = destination_snapshot(request.output_path)
        try:
            package = OpcPackage.open(request.input_path)
            stories = document_stories(package)
            rules = request.arguments["replacements"]
            plan = plan_replacements(
                stories,
                rules,
                case_sensitive=request.arguments["case_sensitive"],
                protected_comment_text=protected_comment_text(package),
            )
            apply_replacement_plan(plan)
            with OperationTempRoot() as private_root:
                staged = private_root / "replacement-output.docx"
                manifest = package.write_copy(
                    staged,
                    changed_parts=changed_story_parts(stories, plan),
                )
                validation = validate_mutation(
                    staged,
                    source=request.input_path,
                    source_sha256=source_record.sha256,
                    manifest=manifest,
                    assertion=lambda candidate: assert_replacement_text(
                        candidate,
                        rules,
                        case_sensitive=request.arguments["case_sensitive"],
                    ),
                )
                operation_result = {
                    "replacement": plan_diagnostics(plan, rules),
                    "preservation": manifest.as_dict(),
                    "structure_diff": summarize_structural_diff(
                        package,
                        OpcPackage.open(staged),
                    ),
                }
                result = write_candidate_result(
                    self.schemas,
                    request,
                    staged,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source_record,
                )
                return promote_candidate(
                    request,
                    staged,
                    result,
                    source=source_record,
                    destination=destination,
                )
        except Exception as error:
            merge_source_preservation_failure(
                error, source_record.path, source_record.sha256
            )
            raise

    def _template(self, request: ParsedDocxRequest) -> dict[str, Any]:
        return template_operation(
            request,
            project_root=self.project_root,
            schemas=self.schemas,
            apply_backend=apply_template_with_node,
        )

def build_docx_service(project_root: Path, libreoffice=None, dotnet=None) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    service = DocxService(project_root, libreoffice=libreoffice, dotnet=dotnet)
    return service.execute
