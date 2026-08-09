"""Canonical DOCX provider results within the Foundation schema."""

from typing import Any

from document_skills_core.core.contracts.models import gate_record

from .contracts import ParsedDocxRequest


def success_result(
    request: ParsedDocxRequest,
    *,
    artifacts: list[dict[str, Any]],
    operation_result: dict[str, Any],
    warnings: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "operation": request.operation,
        "provider_chain": [],
        "requested_fidelity": request.requested_fidelity,
        "achieved_fidelity": "core",
        "degraded": False,
        "degradations": [],
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
    return {
        "schema_version": "1.0",
        "status": "pass",
        "gates": [
            gate_record(
                "docx.package-security",
                "pass",
                evidence={
                    "policy": "reject" if "document" in operation_result else "inert"
                },
            ),
            gate_record(
                gate_id,
                "pass",
                evidence={"structured_result": True},
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
        ],
    }
