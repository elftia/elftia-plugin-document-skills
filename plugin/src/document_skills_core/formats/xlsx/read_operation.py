"""Public XLSX/XLSM structured-read orchestration."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest
from .formula_analysis import validate_formula_analysis
from .formula_security import assert_provider_formula_safe
from .formula_state import build_formula_state_summary, should_downgrade
from .read import read_xlsx
from .recalculation_service import RecalculationOutcome, recalculate_candidate
from .results import read_validation, success_result, with_recalculation_gate
from .service_support import formula_degradations, outcome_provider
from .source_snapshot import stage_source_snapshot


def execute_read(
    request: ParsedXlsxRequest,
    *,
    libreoffice: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    source = file_record(request.input_path, "input")
    try:
        with OperationTempRoot() as private_root:
            provider_source = stage_source_snapshot(source, private_root)
            operation_result, warnings = read_xlsx(
                provider_source,
                request.arguments,
            )
            if request.arguments["include_formulas"]:
                read_policy = (
                    "skip"
                    if provider_source.suffix.casefold() == ".xlsm"
                    else "auto"
                )
                outcome = recalculate_candidate(
                    provider_source,
                    private_root,
                    libreoffice=_screened_provider(libreoffice),
                    policy=read_policy,
                    formula_cells=operation_result.get("formula_state", {}).get(
                        "cells", {}
                    ),
                )
                if (
                    read_policy == "skip"
                    and outcome.evidence["outcome"] == "not_run"
                ):
                    outcome = RecalculationOutcome(
                        outcome.candidate,
                        outcome.formula_cells,
                        outcome.manifest,
                        {
                            **outcome.evidence,
                            "reason": "macro-workbook-provider-disabled",
                        },
                        outcome.provider_chain,
                    )
            else:
                outcome = RecalculationOutcome(
                    provider_source,
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
                provider_source,
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
            result = success_result(
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
                achieved_fidelity=(
                    "enhanced" if outcome.provider_chain else "core"
                ),
                provider_chain=outcome.provider_chain,
            )
            assert_source_preserved(source.path, source.sha256)
            return result
    except BaseException as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


class _ScreenedProvider:
    """Route read-owned snapshots through the no-restage provider seam."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def recalculate_xlsx_artifact(self, input_path: Any) -> Any:
        assert_provider_formula_safe(input_path)
        method = getattr(
            self._provider,
            "recalculate_screened_xlsx_artifact",
            None,
        )
        if callable(method):
            return method(input_path)
        return self._provider.recalculate_xlsx_artifact(input_path)


def _screened_provider(provider: Any) -> Any:
    if provider is None:
        return None
    return _ScreenedProvider(provider)
