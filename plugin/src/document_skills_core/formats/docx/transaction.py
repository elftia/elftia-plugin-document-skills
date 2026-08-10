"""Canonical result validation and race-aware DOCX promotion."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.validation.promotion import assert_promotable
from document_skills_core.core.io.paths import (
    ArtifactRecord,
    DestinationSnapshot,
    assert_source_preserved,
    atomic_promote,
)

from .contracts import ParsedDocxRequest
from .results import success_result


def write_candidate_result(
    schemas: SchemaCatalog,
    request: ParsedDocxRequest,
    staged: Path,
    validation: dict[str, Any],
    operation_result: dict[str, Any],
    *,
    warnings: list[dict[str, Any]],
    source: ArtifactRecord | None,
) -> dict[str, Any]:
    assert request.output_path is not None
    staged_record = assert_promotable("success", validation, staged)
    output_record = ArtifactRecord(
        "output",
        str(request.output_path),
        staged_record.sha256,
        staged_record.bytes,
    )
    artifacts = ([source.as_dict()] if source is not None else []) + [
        output_record.as_dict()
    ]
    result = success_result(
        request,
        artifacts=artifacts,
        operation_result=operation_result,
        warnings=warnings,
        validation=validation,
    )
    schemas.validate("operation-result", result)
    return result


def promote_candidate(
    request: ParsedDocxRequest,
    staged: Path,
    result: dict[str, Any],
    *,
    source: ArtifactRecord | None,
    destination: DestinationSnapshot,
) -> dict[str, Any]:
    assert request.output_path is not None
    identity = assert_promotable(result["status"], result["validation"], staged)
    promoted = atomic_promote(
        staged,
        request.output_path,
        expected_destination=destination,
        expected_source_sha256=identity.sha256,
        expected_source_bytes=identity.bytes,
    )
    expected = result["artifacts"][-1]
    if promoted.sha256 != expected["sha256"] or promoted.bytes != expected["bytes"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promoted DOCX differs from the validated candidate.",
        )
    if source is not None:
        assert_source_preserved(source.path, source.sha256)
    return result
