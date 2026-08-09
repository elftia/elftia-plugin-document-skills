"""Five-operation DOCX dispatch and shared transactional mutation."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedDocxRequest, parse_docx_request
from .create import create_docx
from .inspect import inspect_docx
from .mapping import document_stories, protected_comment_text
from .package import OpcPackage
from .read import read_docx
from .replace import (
    apply_replacement_plan,
    changed_story_parts,
    plan_diagnostics,
    plan_replacements,
)
from .results import read_validation, success_result
from .template import (
    apply_template_with_node,
    plan_template,
    stage_template_source,
)
from .transaction import promote_candidate, write_candidate_result
from .validation import (
    assert_replacement_text,
    assert_template_semantics,
    validate_created,
    validate_mutation,
)


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
        if operation == "docx.inspect.structure":
            return self._inspect(parsed)
        if operation == "docx.create":
            return self._create(parsed)
        if operation == "docx.edit.replace-text":
            return self._replace(parsed)
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

    def _create(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.output_path is not None
        report = request.arguments["report"]
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "created.docx"
            creation = create_docx(staged, report)
            validation = validate_created(staged, report, creation["images"])
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
        finally:
            assert_source_preserved(source_record.path, source_record.sha256)

    def _template(self, request: ParsedDocxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        assert request.output_path is not None
        assert_distinct_paths(request.input_path, request.output_path, in_place=False)
        source_record = file_record(request.input_path, "input")
        destination = destination_snapshot(request.output_path)
        try:
            package = OpcPackage.open(request.input_path)
            variables = request.arguments["variables"]
            plan = plan_template(package, variables)
            warnings = (
                [
                    {
                        "code": "DS_TEMPLATE_UNUSED_VARIABLES",
                        "message": "Some supplied template variables were unused.",
                        "details": {"unused_variables": list(plan.unused)},
                    }
                ]
                if plan.unused
                else []
            )
            with OperationTempRoot() as private_root:
                staged_source = stage_template_source(request.input_path, private_root)
                staged = private_root / "template-output.docx"
                manifest, backend = apply_template_with_node(
                    self.project_root,
                    staged_source,
                    staged,
                    variables=variables,
                    plan=plan,
                )
                validation = validate_mutation(
                    staged,
                    source=request.input_path,
                    source_sha256=source_record.sha256,
                    manifest=manifest,
                    assertion=lambda candidate: assert_template_semantics(
                        candidate,
                        plan,
                    ),
                )
                operation_result = {
                    "template": plan.as_dict(),
                    "backend": backend,
                    "preservation": manifest.as_dict(),
                }
                result = write_candidate_result(
                    self.schemas,
                    request,
                    staged,
                    validation,
                    operation_result,
                    warnings=warnings,
                    source=source_record,
                )
                return promote_candidate(
                    request,
                    staged,
                    result,
                    source=source_record,
                    destination=destination,
                )
        finally:
            assert_source_preserved(source_record.path, source_record.sha256)

def build_docx_service(project_root: Path, libreoffice=None, dotnet=None) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    service = DocxService(project_root, libreoffice=libreoffice, dotnet=dotnet)
    return service.execute
