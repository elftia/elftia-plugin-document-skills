"""Canonical result validation and race-aware PDF promotion.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import apply_committed_promotion
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.validation.promotion import assert_promotable
from document_skills_core.core.io.paths import (
    ArtifactRecord,
    DestinationSnapshot,
    assert_source_preserved,
    atomic_promote,
)

from .contracts import ParsedPdfRequest
from .results import success_result


def write_candidate_result(
    schemas: SchemaCatalog,
    request: ParsedPdfRequest,
    staged: Path,
    validation: dict[str, Any],
    operation_result: dict[str, Any],
    *,
    warnings: list[dict[str, Any]],
    source: ArtifactRecord | None,
    status: str = "success",
    degraded: bool = False,
    degradations: list[dict[str, Any]] | None = None,
    achieved_fidelity: str = "core",
) -> dict[str, Any]:
    assert request.output_path is not None
    staged_record = assert_promotable(status, validation, staged)
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
        status=status,
        degraded=degraded,
        degradations=degradations,
        achieved_fidelity=achieved_fidelity,
    )
    schemas.validate("operation-result", result)
    return result


def promote_candidate(
    request: ParsedPdfRequest,
    staged: Path,
    result: dict[str, Any],
    *,
    source: ArtifactRecord | None,
    destination: DestinationSnapshot,
    preserved_inputs: list[ArtifactRecord] | None = None,
) -> dict[str, Any]:
    assert request.output_path is not None
    identity = assert_promotable(result["status"], result["validation"], staged)
    expected = result["artifacts"][-1]
    if identity.sha256 != expected["sha256"] or identity.bytes != expected["bytes"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF result artifact is not bound to the validated candidate.",
            details={"candidate_identity_mismatch": True},
        )
    inputs = ([source] if source is not None else []) + (preserved_inputs or [])
    for item in inputs:
        assert_source_preserved(item.path, item.sha256)
    promoted = atomic_promote(
        staged,
        request.output_path,
        expected_destination=destination,
        expected_source_sha256=identity.sha256,
        expected_source_bytes=identity.bytes,
    )
    source_error = None
    for item in inputs:
        try:
            assert_source_preserved(item.path, item.sha256)
        except DocumentSkillsError as error:
            error.details.setdefault("role", item.role)
            source_error = error
            break
    return apply_committed_promotion(
        result,
        promoted,
        source_error=source_error,
    )
