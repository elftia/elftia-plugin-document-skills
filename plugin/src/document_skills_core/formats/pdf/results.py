"""Canonical PDF provider results within the Foundation schema.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.models import gate_record

from .contracts import ParsedPdfRequest


def success_result(
    request: ParsedPdfRequest,
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
    """Build validation gates for read/inspect operations."""
    gates: list[dict[str, Any]] = [
        gate_record(
            "pdf.byte-format-security",
            "pass",
            evidence={"policy": "reject" if "page_count" in operation_result else "inert"},
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
            evidence={"reason": "Poppler/LibreOffice visual validation is not implemented."},
            warnings=["Optional visual validation is unavailable."],
        ),
        gate_record(
            "ocr.text",
            "unavailable",
            required=False,
            evidence={"reason": "Tesseract OCR is not implemented."},
            warnings=["Optional OCR validation is unavailable."],
        ),
        gate_record(
            "schema.full",
            "unavailable",
            required=False,
            evidence={"reason": "Full structure-enhanced PDF schema validation is not implemented."},
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
    """Build validation gates for mutation operations (create/edit/rewrite)."""
    gates: list[dict[str, Any]] = [
        gate_record(
            "pdf.byte-format-security",
            "pass",
            evidence={"policy": "reject"},
        ),
        gate_record(
            gate_id,
            "pass",
            evidence={"structured_result": True},
        ),
    ]
    preservation = operation_result.get("preservation", {})
    if preservation:
        gates.append(
            gate_record(
                "object-preservation",
                "pass",
                evidence=preservation,
            )
        )
    rewrite = operation_result.get("rewrite", {})
    if rewrite:
        gates.append(
            gate_record(
                "operation.rewrite-fidelity",
                "pass",
                required=True,
                evidence=rewrite,
            )
        )
    gates.extend([
        gate_record(
            "visual.render",
            "unavailable",
            required=False,
            evidence={"reason": "Poppler/LibreOffice visual validation is not implemented."},
            warnings=["Optional visual validation is unavailable."],
        ),
        gate_record(
            "ocr.text",
            "unavailable",
            required=False,
            evidence={"reason": "Tesseract OCR is not implemented."},
            warnings=["Optional OCR validation is unavailable."],
        ),
        gate_record(
            "schema.full",
            "unavailable",
            required=False,
            evidence={"reason": "Full structure-enhanced PDF schema validation is not implemented."},
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
