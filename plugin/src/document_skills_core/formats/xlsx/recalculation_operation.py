"""Transactional public ``xlsx.recalculate`` operation."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest
from .formula_state import build_formula_state_summary
from .mapping import map_workbook
from .package import OpcPackage
from .recalculation import compare_final_preservation
from .recalculation_service import recalculate_candidate
from .results import with_formula_gate, with_recalculation_gate
from .transaction import promote_candidate, write_candidate_result
from .validation import (
    assert_formula_state_invariant,
    validate_mutation,
)


def execute_recalculation(
    request: ParsedXlsxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    """Recalculate through an accepted provider and atomically publish the result."""

    assert request.input_path is not None and request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / "core-copy.xlsx"
            core_manifest = OpcPackage.open(request.input_path).write_copy(
                staged,
                changed_parts={},
            )
            formula_cells = map_workbook(OpcPackage.open(staged)).get(
                "formula_cells", {}
            )
            outcome = recalculate_candidate(
                staged,
                private_root,
                libreoffice=libreoffice,
                policy="required",
                formula_cells=formula_cells,
            )
            manifest = core_manifest
            if outcome.manifest is not None:
                manifest = compare_final_preservation(
                    request.input_path,
                    outcome.candidate,
                    allowed_changed=set(outcome.manifest.changed),
                    expected_added=set(),
                    expected_removed=set(),
                )
            provider = "libreoffice" if outcome.provider_chain else None
            formula_summary = build_formula_state_summary(
                outcome.formula_cells,
                recalculation_provider=provider,
            )
            operation_result = {
                "formula_state": {
                    "cells": outcome.formula_cells,
                    "summary": formula_summary,
                },
                "preservation": manifest.as_dict(),
                "recalculation": outcome.evidence,
            }
            validation = validate_mutation(
                outcome.candidate,
                source=request.input_path,
                source_sha256=source.sha256,
                manifest=manifest,
                assertion=lambda _candidate: assert_formula_state_invariant(
                    outcome.formula_cells,
                    recalculation_provider=provider,
                ),
            )
            validation = with_formula_gate(validation, operation_result)
            validation = with_recalculation_gate(
                validation,
                outcome.evidence,
                required=bool(outcome.formula_cells),
            )
            result = write_candidate_result(
                schemas,
                request,
                outcome.candidate,
                validation,
                operation_result,
                warnings=[],
                source=source,
                achieved_fidelity=(
                    "enhanced" if outcome.provider_chain else "core"
                ),
                provider_chain=outcome.provider_chain,
            )
            return promote_candidate(
                request,
                outcome.candidate,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise
