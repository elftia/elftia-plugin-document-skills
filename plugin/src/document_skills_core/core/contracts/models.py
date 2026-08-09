"""Canonical dictionary builders shared by dispatch and providers."""

from typing import Any

from .errors import DocumentSkillsError

SCHEMA_VERSION = "1.0"
RESULT_STATUSES = frozenset(
    {"success", "degraded", "enhancement_required", "invalid_request", "unavailable", "failed"}
)
GATE_OUTCOMES = frozenset({"pass", "fail", "unavailable", "not_run", "not_applicable"})


def empty_validation(status: str = "not_run") -> dict[str, Any]:
    if status not in GATE_OUTCOMES:
        raise ValueError(f"Unknown validation status: {status}")
    return {"schema_version": SCHEMA_VERSION, "status": status, "gates": []}


def make_error_result(
    operation: str,
    error: DocumentSkillsError,
    *,
    requested_fidelity: str = "unknown",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": error.status,
        "operation": operation,
        "provider_chain": [],
        "requested_fidelity": requested_fidelity,
        "achieved_fidelity": "none",
        "degraded": False,
        "degradations": [],
        "artifacts": [],
        "validation": empty_validation(),
        "warnings": [],
        "errors": [error.record()],
        "diagnostics": {},
    }


def gate_record(
    gate_id: str,
    outcome: str,
    *,
    required: bool = True,
    validator: str = "document-skills-core",
    version: str | None = None,
    duration_ms: int = 0,
    evidence: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    if outcome not in GATE_OUTCOMES:
        raise ValueError(f"Unknown gate outcome: {outcome}")
    return {
        "id": gate_id,
        "required": required,
        "outcome": outcome,
        "validator": validator,
        "version": version,
        "duration_ms": max(duration_ms, 0),
        "evidence": evidence or {},
        "warnings": warnings or [],
    }
