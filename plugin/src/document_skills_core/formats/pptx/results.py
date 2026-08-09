"""Canonical PPTX provider results within the Foundation schema."""

from typing import Any

from document_skills_core.core.contracts.models import gate_record

from .contracts import ParsedPptxRequest


def success_result(
    request: ParsedPptxRequest,
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
    gates: list[dict[str, Any]] = [
        gate_record(
            "pptx.package-security",
            "pass",
            evidence={
                "policy": "reject" if "slides" in operation_result else "inert"
            },
        ),
        gate_record(
            gate_id,
            "pass",
            evidence={"structured_result": True},
        ),
    ]
    gates.extend([
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
    gates: list[dict[str, Any]] = [
        gate_record(
            "pptx.package-security",
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
    if "reorder" in operation_result:
        gates.append(
            gate_record(
                "operation.reorder-fidelity",
                "pass",
                required=True,
                evidence={"slides_checked": len(operation_result["reorder"])},
            )
        )
    gates.extend([
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
