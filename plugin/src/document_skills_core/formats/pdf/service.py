"""Five-operation PDF dispatch and shared transactional mutation.

Operations: pdf.read, pdf.inspect.structure, pdf.create, pdf.edit, pdf.rewrite.apply

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedPdfRequest, parse_pdf_request
from .create import create_pdf
from .edit import edit_pdf
from .inspect import inspect_pdf
from .read import read_pdf
from .results import read_validation, success_result
from .rewrite import rewrite_apply_pdf
from .transaction import promote_candidate, write_candidate_result
from .validation import (
    validate_created,
    validate_mutation,
    validate_rewrite,
)


class PdfService:
    """Five-operation PDF dispatch and transactional mutation."""

    def __init__(self, project_root: Path, libreoffice=None) -> None:
        self.project_root = project_root.resolve()
        self.schemas = SchemaCatalog(self.project_root)
        self.libreoffice = libreoffice

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
        parsed = parse_pdf_request(request)
        if parsed.operation != operation:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "PDF provider binding does not match the request operation.",
                status="invalid_request",
            )
        if operation == "pdf.read":
            return self._read(parsed)
        if operation == "pdf.inspect.structure":
            return self._inspect(parsed)
        if operation == "pdf.create":
            return self._create(parsed)
        if operation == "pdf.edit":
            return self._edit(parsed)
        return self._rewrite_apply(parsed)

    def _read(self, request: ParsedPdfRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = read_pdf(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.structured-read", operation_result),
        )

    def _inspect(self, request: ParsedPdfRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = inspect_pdf(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.inert-inspection", operation_result),
        )

    def _create(self, request: ParsedPdfRequest) -> dict[str, Any]:
        assert request.output_path is not None
        document = request.arguments["document"]
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "created.pdf"
            creation = create_pdf(staged, document)
            validation = validate_created(staged, document)
            operation_result = {"creation": creation}
            result = write_candidate_result(
                self.schemas,
                request,
                staged,
                validation,
                operation_result,
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

    def _edit(self, request: ParsedPdfRequest) -> dict[str, Any]:
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
            with OperationTempRoot() as private_root:
                staged = private_root / "edited.pdf"
                operation_result, manifest = edit_pdf(
                    request.input_path, staged, request.arguments
                )
                validation = validate_mutation(
                    staged,
                    source=request.input_path,
                    source_sha256=source_record.sha256,
                    manifest=manifest,
                )
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

    def _rewrite_apply(self, request: ParsedPdfRequest) -> dict[str, Any]:
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
            with OperationTempRoot() as private_root:
                staged = private_root / "rewritten.pdf"
                operation_result, manifest = rewrite_apply_pdf(
                    request.input_path, staged, request.arguments
                )
                layout_evidence = operation_result.get("rewrite", {}).get("page_layout_preservation", {})
                is_degraded = bool(operation_result.get("rewrite", {}).get("glyph_degradation"))
                degradations = []
                status = "success"
                if is_degraded:
                    status = "degraded"
                    gd = operation_result.get("rewrite", {}).get("glyph_degradation", [])
                    degradations.append({
                        "code": "core.cjk_glyph_coverage",
                        "semantic_difference": "Embedded font subset does not cover required CJK/RTL codepoints.",
                        "missing_capabilities": ["core.cjk_glyph_coverage"],
                        "recommended_providers": ["libreoffice"],
                    })
                validation = validate_rewrite(
                    staged,
                    source=request.input_path,
                    source_sha256=source_record.sha256,
                    manifest=manifest,
                    layout_evidence=layout_evidence,
                )
                result = write_candidate_result(
                    self.schemas,
                    request,
                    staged,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source_record,
                    status=status,
                    degraded=is_degraded,
                    degradations=degradations,
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


def build_pdf_service(project_root: Path, libreoffice=None) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Build the PDF service executor."""
    service = PdfService(project_root, libreoffice=libreoffice)
    return service.execute
