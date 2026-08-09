"""Canonical XLSX provider results within the Foundation schema."""

from typing import Any

from document_skills_core.core.contracts.models import gate_record

from .contracts import ParsedXlsxRequest


def success_result(
    request: ParsedXlsxRequest,
    *,
    artifacts: list[dict[str, Any]],
    operation_result: dict[str, Any],
    warnings: list[dict[str, Any]],
    validation: dict[str, Any],
    status: str = "success",
    degraded: bool = False,
    degradations: list[dict[str, Any]] | None = None,
    achieved_fidelity: str = "core",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": status,
        "operation": request.operation,
        "provider_chain": [],
        "requested_fidelity": request.requested_fidelity,
        "achieved_fidelity": achieved_fidelity,
        "degraded": degraded,
        "degradations": degradations or [],
        "artifacts": artifacts,
        "validation": validation,
        "warnings": warnings,
        "errors": [],
        "diagnostics": {"operation_result": operation_result},
    }


def read_validation(
    gate_id: str,
    operation_result: dict[str, Any],
) -> dict[str, Any]:
    formula_state = operation_result.get("formula_state", {})
    summary = formula_state.get("summary", {})
    outstanding = summary.get("outstanding_recalculation_required", 0)
    has_formulas = bool(formula_state.get("cells"))
    formula_invariant = summary.get("no_unverified_claimed_recalculated", True)
    gates: list[dict[str, Any]] = [
        gate_record(
            "xlsx.package-security",
            "pass",
            evidence={
                "policy": "reject" if "sheets" in operation_result else "inert"
            },
        ),
        gate_record(
            gate_id,
            "pass",
            evidence={"structured_result": True},
        ),
    ]
    if has_formulas:
        gates.append(
            gate_record(
                "operation.formula-state",
                "pass" if formula_invariant else "fail",
                required=True,
                evidence={
                    "no_unverified_claimed_recalculated": formula_invariant,
                    "outstanding_recalculation_required": outstanding,
                },
                warnings=[] if formula_invariant else [
                    "Formula-state invariant violated."
                ],
            )
        )
    gates.extend([
        gate_record(
            "recalculation.full",
            "unavailable",
            required=False,
            evidence={"reason": "LibreOffice recalculation provider is not implemented."},
            warnings=["Optional whole-workbook recalculation is unavailable."],
        ),
        gate_record(
            "visual.render",
            "unavailable",
            required=False,
            evidence={"reason": "LibreOffice visual validation is not implemented."},
            warnings=["Optional visual validation is unavailable."],
        ),
        gate_record(
            "schema.full",
            "unavailable",
            required=False,
            evidence={
                "reason": ".NET/OpenXML full schema validation is not implemented."
            },
            warnings=["Optional full-schema validation is unavailable."],
        ),
    ])
    return {
        "schema_version": "1.0",
        "status": "pass" if all(
            g["outcome"] == "pass" or not g["required"] for g in gates
        ) else "fail",
        "gates": gates,
    }


def mutation_validation(
    gate_id: str,
    operation_result: dict[str, Any],
) -> dict[str, Any]:
    """Build validation gates for mutation operations (create/edit)."""
    formula_state = operation_result.get("formula_state", {})
    summary = formula_state.get("summary", {})
    outstanding = summary.get("outstanding_recalculation_required", 0)
    has_formulas = bool(formula_state.get("cells"))
    formula_invariant = summary.get("no_unverified_claimed_recalculated", True)
    gates: list[dict[str, Any]] = [
        gate_record(
            "xlsx.package-security",
            "pass",
            evidence={"policy": "reject"},
        ),
        gate_record(
            gate_id,
            "pass",
            evidence={"structured_result": True},
        ),
        gate_record(
            "part-preservation",
            "pass",
            evidence=operation_result.get("preservation", {}),
        ),
    ]
    if has_formulas:
        formula_outcome = "pass" if formula_invariant else "fail"
        gates.append(
            gate_record(
                "operation.formula-state",
                formula_outcome,
                required=True,
                evidence={
                    "no_unverified_claimed_recalculated": formula_invariant,
                    "outstanding_recalculation_required": outstanding,
                },
            )
        )
    gates.extend([
        gate_record(
            "recalculation.full",
            "unavailable",
            required=False,
            evidence={"reason": "LibreOffice recalculation provider is not implemented."},
            warnings=["Optional whole-workbook recalculation is unavailable."],
        ),
        gate_record(
            "visual.render",
            "unavailable",
            required=False,
            evidence={"reason": "LibreOffice visual validation is not implemented."},
            warnings=["Optional visual validation is unavailable."],
        ),
        gate_record(
            "schema.full",
            "unavailable",
            required=False,
            evidence={
                "reason": ".NET/OpenXML full schema validation is not implemented."
            },
            warnings=["Optional full-schema validation is unavailable."],
        ),
    ])
    return {
        "schema_version": "1.0",
        "status": "pass" if all(
            g["outcome"] == "pass" or not g["required"] for g in gates
        ) else "fail",
        "gates": gates,
    }
