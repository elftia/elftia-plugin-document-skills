"""Validation-authoritative candidate promotion policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts.errors import DocumentSkillsError, ErrorCode
from ..io.paths import ArtifactRecord, file_record


def assert_promotable(
    result_status: str,
    validation: dict[str, Any],
    candidate: str | Path,
) -> ArtifactRecord:
    """Return the exact validated identity or reject before exposure/promotion."""

    if result_status not in {"success", "degraded"}:
        raise _rejection(
            validation,
            "Only success or optional-only degraded results can be promoted.",
            {"result_status": result_status},
        )
    required_nonpass = [
        gate.get("id", "unknown")
        for gate in validation.get("gates", [])
        if gate.get("required") is True and gate.get("outcome") != "pass"
    ]
    if validation.get("status") != "pass" or required_nonpass:
        raise _rejection(
            validation,
            "Required validation did not accept the candidate.",
            {"required_nonpass": required_nonpass},
        )
    expected = _validated_identity(validation)
    actual = file_record(candidate, "output")
    if expected is None or actual.sha256 != expected[0] or actual.bytes != expected[1]:
        raise _rejection(
            validation,
            "Candidate identity differs from the validation evidence.",
            {
                "candidate_identity_mismatch": True,
                "expected_sha256": expected[0] if expected else None,
                "expected_bytes": expected[1] if expected else None,
                "actual_sha256": actual.sha256,
                "actual_bytes": actual.bytes,
            },
        )
    return actual


def _validated_identity(validation: dict[str, Any]) -> tuple[str, int] | None:
    for gate in validation.get("gates", []):
        if gate.get("required") is not True or gate.get("outcome") != "pass":
            continue
        evidence = gate.get("evidence", {})
        sha256 = evidence.get("sha256")
        byte_count = evidence.get("bytes")
        if (
            isinstance(sha256, str)
            and len(sha256) == 64
            and isinstance(byte_count, int)
            and byte_count > 0
        ):
            return sha256, byte_count
    return None


def _rejection(
    validation: dict[str, Any],
    message: str,
    details: dict[str, Any],
) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        status="failed",
        details=details,
        validation=validation,
    )
