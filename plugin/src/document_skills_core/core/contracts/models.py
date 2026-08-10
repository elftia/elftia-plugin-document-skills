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
    validation = error.validation or _error_validation(error)
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
        "validation": validation,
        "warnings": [],
        "errors": [error.record()],
        "diagnostics": {},
    }


def apply_committed_promotion(
    result: dict[str, Any],
    promotion: Any,
    *,
    source_error: DocumentSkillsError | None = None,
) -> dict[str, Any]:
    """Expose one truthful result shape for every verified committed output."""

    details = promotion.promotion_details()
    filesystem_state = str(details["state"])
    details["filesystem_state"] = filesystem_state
    warnings = list(result.get("warnings", []))
    if filesystem_state == "committed_with_residue":
        warnings.append(
            {
                "code": "DS_PROMOTION_RESIDUE_PRESERVED",
                "message": "The validated output committed and the displaced destination remains preserved.",
                "details": {
                    "transaction_residues": details["transaction_residues"],
                    "transaction_residue_paths": details[
                        "transaction_residue_paths"
                    ],
                    "destination_capture_preserved": details[
                        "destination_capture_preserved"
                    ],
                    "residue_observation_stable": details[
                        "residue_observation_stable"
                    ],
                },
            }
        )
    if source_error is not None:
        details["state"] = "committed_with_warnings"
        details["source_preservation"] = {
            "status": "fail",
            "error": source_error.record(),
        }
        warnings.append(
            {
                "code": "DS_SOURCE_CHANGED_AFTER_COMMIT",
                "message": "The validated output committed, but the mutation source changed concurrently afterward.",
                "details": source_error.record()["details"],
            }
        )
    else:
        details["source_preservation"] = {"status": "pass"}
    diagnostics = dict(result.get("diagnostics", {}))
    diagnostics["promotion"] = details
    return {
        **result,
        "warnings": warnings,
        "diagnostics": diagnostics,
    }


def _error_validation(error: DocumentSkillsError) -> dict[str, Any]:
    """Give every typed rejection an explicit required non-pass gate."""

    outcome = "unavailable" if error.status == "unavailable" else "fail"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": outcome,
        "gates": [
            gate_record(
                "request.preflight",
                outcome,
                required=True,
                evidence={
                    "error_code": error.code.value,
                    "result_status": error.status,
                },
                warnings=[str(error)[:512]],
            )
        ],
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
