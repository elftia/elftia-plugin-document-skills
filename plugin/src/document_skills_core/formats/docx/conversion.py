"""DOCX-to-PDF reopen and operation-specific validation."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.validation import validate_artifact
from document_skills_core.formats.pdf.validation import reopen_pdf

from .contracts import ParsedDocxRequest
from .package import OpcPackage
from .transaction import promote_candidate, write_candidate_result


def convert_pdf_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    """Convert through LibreOffice, validate privately, then promote."""

    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    OpcPackage.open(request.input_path)
    if libreoffice is None:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "DOCX-to-PDF conversion requires the LibreOffice provider.",
            status="unavailable",
            details={"recommended_providers": ["libreoffice"]},
        )
    convert_pdf = libreoffice.convert_pdf
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / "converted.pdf"
            pdf_bytes = convert_pdf(
                request.input_path,
                request.arguments["max_output_bytes"],
            )
            if type(pdf_bytes) is not bytes:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice returned an invalid PDF payload.",
                )
            staged.write_bytes(pdf_bytes)
            validation, reopened = validate_pdf_conversion(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                max_output_bytes=request.arguments["max_output_bytes"],
            )
            operation_result = {
                "conversion": {
                    "format": "pdf",
                    "output_bytes": len(pdf_bytes),
                    "pages": reopened["pages"],
                    "visual_comparison": "unavailable",
                }
            }
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=source_record,
                achieved_fidelity="enhanced",
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
            error,
            source_record.path,
            source_record.sha256,
        )
        raise


def validate_pdf_conversion(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    max_output_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require a bounded, reopenable PDF with at least one page."""

    reopened: dict[str, Any] = {}

    def reopen(candidate: Path) -> dict[str, Any]:
        evidence = reopen_pdf(candidate)
        reopened.update(evidence)
        return evidence

    def assert_conversion(candidate: Path) -> dict[str, Any]:
        output_bytes = candidate.stat().st_size
        pages = int(reopened.get("pages", 0))
        if output_bytes > max_output_bytes or pages < 1:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Converted PDF violates the requested output bounds.",
                details={
                    "max_output_bytes": max_output_bytes,
                    "output_bytes": output_bytes,
                    "pages": pages,
                },
            )
        return {
            "conversion_succeeded": True,
            "format": "pdf",
            "output_bytes": output_bytes,
            "pages": pages,
        }

    report = validate_artifact(
        path,
        expected_format="pdf",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen,
        assertions=[("docx-convert-pdf", assert_conversion)],
        visual_available=False,
        schema_available=False,
    )
    if report["status"] != "pass":
        failed = [
            gate["id"]
            for gate in report["gates"]
            if gate["required"] and gate["outcome"] != "pass"
        ]
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Converted PDF failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report, reopened


def validate_pdf_render(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    expected_pages: int,
    max_total_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require bounded, reopenable PDF evidence with the selected page count."""

    reopened: dict[str, Any] = {}

    def reopen(candidate: Path) -> dict[str, Any]:
        evidence = reopen_pdf(candidate)
        reopened.update(evidence)
        return evidence

    def assert_render(candidate: Path) -> dict[str, Any]:
        total_bytes = candidate.stat().st_size
        page_count = int(reopened.get("pages", 0))
        if total_bytes > max_total_bytes or page_count != expected_pages:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Rendered PDF violates the requested page or byte bounds.",
                details={
                    "expected_pages": expected_pages,
                    "max_total_bytes": max_total_bytes,
                    "page_count": page_count,
                    "total_bytes": total_bytes,
                },
            )
        return {
            "conversion_succeeded": True,
            "pages_generated": True,
            "page_count": page_count,
            "total_bytes": total_bytes,
        }

    report = validate_artifact(
        path,
        expected_format="pdf",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen,
        assertions=[("docx-render-pages", assert_render)],
        visual_available=False,
        schema_available=False,
    )
    if report["status"] != "pass":
        failed = [
            gate["id"]
            for gate in report["gates"]
            if gate["required"] and gate["outcome"] != "pass"
        ]
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Rendered PDF failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report, reopened
