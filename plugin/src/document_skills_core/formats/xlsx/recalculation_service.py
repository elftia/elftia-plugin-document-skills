"""Policy-aware orchestration for provider-backed XLSX formula recalculation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .formula_analysis import analyze_formulas
from .formula_state import assert_invariant
from .package import PreservationManifest
from .recalculation import apply_provider_recalculation, formula_count


@dataclass(frozen=True)
class RecalculationOutcome:
    candidate: Path
    formula_cells: dict[str, dict[str, Any]]
    manifest: PreservationManifest | None
    evidence: dict[str, Any]
    provider_chain: list[str]


def recalculate_candidate(
    candidate: Path,
    private_root: Path,
    *,
    libreoffice: Any,
    policy: str,
    formula_cells: dict[str, dict[str, Any]],
) -> RecalculationOutcome:
    count = formula_count(candidate)
    if count != len(formula_cells):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Core formula-state projection does not match the staged XLSX.",
            details={
                "staged_formula_cells": count,
                "projected_formula_cells": len(formula_cells),
            },
        )
    if count == 0:
        return RecalculationOutcome(
            candidate,
            formula_cells,
            None,
            {
                "outcome": "not_applicable",
                "policy": policy,
                "reason": "workbook-has-no-formulas",
                "formula_cells": 0,
            },
            [],
        )
    if policy == "skip":
        return RecalculationOutcome(
            candidate,
            formula_cells,
            None,
            {
                "outcome": "not_run",
                "policy": policy,
                "reason": "request-policy-skip",
                "formula_cells": count,
            },
            [],
        )
    analysis = analyze_formulas(candidate)
    if analysis["categories"].get("external_reference", 0):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "External-workbook formulas are never sent to a recalculation provider.",
            details={"formula_analysis": analysis},
        )
    unsupported_types = [
        formula_type
        for formula_type in ("shared", "array", "data_table")
        if analysis["categories"].get(formula_type, 0)
    ]
    if unsupported_types:
        if policy == "required":
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Provider recalculation does not yet harvest special formula types.",
                status="enhancement_required",
                details={"formula_types": unsupported_types},
            )
        return RecalculationOutcome(
            candidate,
            formula_cells,
            None,
            {
                "outcome": "not_run",
                "policy": policy,
                "reason": "unsupported-formula-types",
                "formula_types": unsupported_types,
                "formula_cells": count,
            },
            [],
        )
    if libreoffice is None:
        return _provider_unavailable(
            candidate,
            formula_cells,
            count=count,
            policy=policy,
            reason="provider-not-configured",
        )
    try:
        provider_result = libreoffice.recalculate_xlsx_artifact(
            candidate,
            policy=policy,
        )
    except DocumentSkillsError as error:
        if policy == "required":
            raise
        if error.code not in {
            ErrorCode.PROVIDER_UNAVAILABLE,
            ErrorCode.PROVIDER_FAILED,
            ErrorCode.PROCESS_TIMEOUT,
        }:
            raise
        return _provider_unavailable(
            candidate,
            formula_cells,
            count=count,
            policy=policy,
            reason=error.code.value,
        )
    provider_candidate = private_root / "libreoffice-recalculated.xlsx"
    provider_candidate.write_bytes(provider_result.payload)
    accepted = private_root / "accepted-recalculated.xlsx"
    states, manifest, evidence = apply_provider_recalculation(
        candidate,
        provider_candidate,
        accepted,
    )
    assert_invariant(states, recalculation_provider="libreoffice")
    return RecalculationOutcome(
        accepted,
        states,
        manifest,
        {**evidence, "outcome": "pass", "policy": policy},
        ["libreoffice"],
    )


def _provider_unavailable(
    candidate: Path,
    formula_cells: dict[str, dict[str, Any]],
    *,
    count: int,
    policy: str,
    reason: str,
) -> RecalculationOutcome:
    if policy == "required":
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Required XLSX recalculation provider is unavailable.",
            status="unavailable",
            details={"provider": "libreoffice", "reason": reason},
        )
    return RecalculationOutcome(
        candidate,
        formula_cells,
        None,
        {
            "outcome": "unavailable",
            "policy": policy,
            "provider": "libreoffice",
            "reason": reason,
            "formula_cells": count,
        },
        [],
    )
