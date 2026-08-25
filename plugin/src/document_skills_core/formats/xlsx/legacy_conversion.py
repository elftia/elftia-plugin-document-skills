"""Provider-required, fail-closed legacy ``.xls`` to ``.xlsx`` conversion."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest
from .format_policy import assert_package_matches_path
from .formula_analysis import validate_formula_analysis
from .package import OpcPackage
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_converted


def execute_legacy_conversion(
    request: ParsedXlsxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    assert request.input_path is not None and request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    limits = request.arguments["limits"]
    if source.bytes > limits["max_input_bytes"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Legacy conversion input exceeds the configured byte limit.",
            details={"bytes": source.bytes, "limit": limits["max_input_bytes"]},
        )
    if libreoffice is None:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Legacy .xls conversion requires LibreOffice.",
            status="unavailable",
            details={"provider": "libreoffice"},
        )
    try:
        with OperationTempRoot() as private_root:
            payload = libreoffice.convert_legacy_required(
                request.input_path,
                target_format="xlsx",
            )
            candidate = private_root / "legacy-converted.xlsx"
            candidate.write_bytes(payload)
            package = OpcPackage.open(candidate)
            assert_package_matches_path(candidate, package.workbook_format)
            output = file_record(candidate, "output")
            if output.bytes > limits["max_output_bytes"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Legacy conversion output exceeds the configured byte limit.",
                    details={
                        "bytes": output.bytes,
                        "limit": limits["max_output_bytes"],
                    },
                )
            validation = validate_converted(candidate)
            formula_analysis, validation = validate_formula_analysis(
                candidate,
                validation,
                required=True,
            )
            assert_source_preserved(source.path, source.sha256)
            loss = {
                "code": "legacy-provider-conversion",
                "description": (
                    "LibreOffice converted the binary .xls workbook; unsupported legacy "
                    "features may have compatibility differences."
                ),
            }
            validation = _with_legacy_gates(
                validation,
                source_sha256=source.sha256,
                output_sha256=output.sha256,
            )
            operation_result = {
                "conversion": {
                    "source_format": "xls",
                    "target_format": "xlsx",
                    "provider": "libreoffice",
                    "legacy": True,
                    "source_bytes": source.bytes,
                    "output_bytes": output.bytes,
                    "limits": limits,
                    "provider_diagnostics": libreoffice.diagnostics(),
                },
                "formula_analysis": formula_analysis,
                "semantic_losses": [loss],
            }
            result = write_candidate_result(
                schemas,
                request,
                candidate,
                validation,
                operation_result,
                warnings=[
                    {
                        "code": "DS_CONVERSION_SEMANTIC_LOSS",
                        "message": loss["description"],
                        "details": {"code": loss["code"]},
                    }
                ],
                source=source,
                status="degraded",
                degraded=True,
                degradations=[
                    {
                        "code": loss["code"],
                        "semantic_difference": loss["description"],
                        "missing_capabilities": [],
                        "recommended_providers": [],
                    }
                ],
                achieved_fidelity="enhanced",
                provider_chain=["libreoffice"],
            )
            return promote_candidate(
                request,
                candidate,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _with_legacy_gates(
    validation: dict[str, Any],
    *,
    source_sha256: str,
    output_sha256: str,
) -> dict[str, Any]:
    gates = list(validation.get("gates", []))
    gates.extend(
        [
            gate_record(
                "conversion.legacy-provider",
                "pass",
                evidence={"provider": "libreoffice", "output_sha256": output_sha256},
            ),
            gate_record(
                "conversion.source-preservation",
                "pass",
                evidence={"source_sha256": source_sha256},
            ),
            gate_record(
                "conversion.semantic-loss-disclosure",
                "pass",
                evidence={"loss_codes": ["legacy-provider-conversion"]},
            ),
        ]
    )
    return {**validation, "gates": gates}
