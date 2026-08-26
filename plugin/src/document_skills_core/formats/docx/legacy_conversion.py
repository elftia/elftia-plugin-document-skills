"""Explicit provider-backed conversion of legacy binary Word documents."""

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

from .constants import MAX_DOCX_BYTES
from .contracts import ParsedDocxRequest
from .transaction import promote_candidate, write_candidate_result
from .validation import reopen_docx


def convert_legacy_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    """Convert one bounded ``.doc`` through LibreOffice and validate privately."""

    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    if source_record.bytes > MAX_DOCX_BYTES:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Legacy DOC input exceeds the public byte ceiling.",
            status="invalid_request",
            details={"bytes": source_record.bytes, "max_bytes": MAX_DOCX_BYTES},
        )
    destination = destination_snapshot(request.output_path)
    if libreoffice is None:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Legacy DOC conversion requires the LibreOffice provider.",
            status="unavailable",
            details={"recommended_providers": ["libreoffice"]},
        )
    convert_legacy = libreoffice.convert_legacy
    target_format = request.arguments["format"]
    maximum = request.arguments["max_output_bytes"]
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / f"legacy-output.{target_format}"
            payload = convert_legacy(request.input_path, target_format, maximum)
            if type(payload) is not bytes:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice returned an invalid legacy conversion payload.",
                )
            staged.write_bytes(payload)
            validation, reopened = _validate_legacy_output(
                staged,
                target_format=target_format,
                source=request.input_path,
                source_sha256=source_record.sha256,
                max_output_bytes=maximum,
            )
            operation_result = {
                "conversion": {
                    "input_format": "doc",
                    "format": target_format,
                    "output_bytes": len(payload),
                    **(
                        {"pages": reopened["pages"]}
                        if target_format == "pdf"
                        else {"parts": reopened["parts"]}
                    ),
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


def _validate_legacy_output(
    path: Path,
    *,
    target_format: str,
    source: Path,
    source_sha256: str,
    max_output_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reopened: dict[str, Any] = {}

    def reopen(candidate: Path) -> dict[str, Any]:
        evidence = (
            reopen_pdf(candidate)
            if target_format == "pdf"
            else reopen_docx(candidate)
        )
        reopened.update(evidence)
        return evidence

    def assert_conversion(candidate: Path) -> dict[str, Any]:
        output_bytes = candidate.stat().st_size
        if output_bytes > max_output_bytes:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Legacy conversion exceeds the requested output bound.",
                details={
                    "max_output_bytes": max_output_bytes,
                    "output_bytes": output_bytes,
                },
            )
        return {
            "conversion_succeeded": True,
            "input_format": "doc",
            "format": target_format,
            "output_bytes": output_bytes,
        }

    report = validate_artifact(
        path,
        expected_format=target_format,
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen,
        assertions=[("docx-convert-legacy", assert_conversion)],
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
            "Legacy conversion failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report, reopened
