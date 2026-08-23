"""Public XLSX/XLSM structured-read orchestration."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import assert_source_preserved, file_record
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest
from .formula_analysis import validate_formula_analysis
from .formula_state import build_formula_state_summary, should_downgrade
from .read import read_xlsx
from .recalculation_service import RecalculationOutcome, recalculate_candidate
from .results import read_validation, success_result, with_recalculation_gate
from .service_support import formula_degradations, outcome_provider


def execute_read(
    request: ParsedXlsxRequest,
    *,
    libreoffice: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    source = file_record(request.input_path, "input")
    operation_result, warnings = read_xlsx(request.input_path, request.arguments)
    assert_source_preserved(source.path, source.sha256)
    if request.arguments["include_formulas"]:
        with OperationTempRoot() as private_root:
            read_policy = (
                "skip" if request.input_path.suffix.casefold() == ".xlsm" else "auto"
            )
            outcome = recalculate_candidate(
                request.input_path,
                private_root,
                libreoffice=libreoffice,
                policy=read_policy,
                formula_cells=operation_result.get("formula_state", {}).get("cells", {}),
            )
            if read_policy == "skip" and outcome.evidence["outcome"] == "not_run":
                outcome = RecalculationOutcome(
                    outcome.candidate,
                    outcome.formula_cells,
                    outcome.manifest,
                    {**outcome.evidence, "reason": "macro-workbook-provider-disabled"},
                    outcome.provider_chain,
                )
    else:
        outcome = RecalculationOutcome(
            request.input_path,
            {},
            None,
            {
                "outcome": "not_run",
                "policy": "auto",
                "reason": "request-excluded-formulas",
                "formula_cells": 0,
            },
            [],
        )
    formula_cells = outcome.formula_cells
    operation_result["formula_state"]["cells"] = formula_cells
    formula_summary = build_formula_state_summary(
        formula_cells,
        recalculation_provider=outcome_provider(outcome),
    )
    operation_result["formula_state"]["summary"] = formula_summary
    operation_result["recalculation"] = outcome.evidence
    degraded = should_downgrade(formula_summary)
    formula_analysis, validation = validate_formula_analysis(
        request.input_path,
        read_validation("operation.structured-read", operation_result),
        required=False,
    )
    operation_result["formula_analysis"] = formula_analysis
    validation = with_recalculation_gate(validation, outcome.evidence)
    if formula_analysis["categories"]["external_reference"]:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "External-workbook formulas require inert structural inspection.",
            details={"formula_analysis": formula_analysis},
            validation=validation,
        )
    return success_result(
        request,
        artifacts=[source.as_dict()],
        operation_result=operation_result,
        warnings=warnings,
        validation=validation,
        status="degraded" if degraded else "success",
        degraded=degraded,
        degradations=formula_degradations(
            degraded,
            "Formulas require recalculation by an accepted provider.",
        ),
        achieved_fidelity="enhanced" if outcome.provider_chain else "core",
        provider_chain=outcome.provider_chain,
    )
