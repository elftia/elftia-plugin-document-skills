"""Transactional public ``xlsx.summary.aggregate`` orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from .edit import edit_xlsx
from .format_policy import allowed_inert_categories, assert_package_matches_path, format_id
from .formula_analysis import validate_formula_analysis
from .formula_state import build_formula_state_summary, should_downgrade
from .macro_policy import (
    signature_degradation,
    signature_invalidated,
    signature_warnings,
    validate_macro_preservation,
    with_macro_preservation_gate,
)
from .mapping import col_to_num, num_to_col, parse_ref
from .package import OpcPackage
from .results import with_formula_gate, with_recalculation_gate
from .service_support import formula_degradations
from .summary_model import SummaryBuild, build_summary
from .summary_support import OutputCell
from .summary_validation import assert_summary_written
from .transaction import promote_candidate, write_candidate_result
from .validation import assert_edits_applied, validate_mutation


def execute_summary_aggregate(
    request: ParsedXlsxRequest,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None and request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    source_format = format_id(request.input_path)
    try:
        with OperationTempRoot() as private_root:
            source_package = OpcPackage.open(
                request.input_path,
                allowed_inert_categories=allowed_inert_categories(source_format),
            )
            assert_package_matches_path(request.input_path, source_package.workbook_format)
            summary = build_summary(source_package, request.arguments)
            edits = _summary_edits(summary)
            candidate = private_root / f"summary{request.output_path.suffix.casefold()}"
            edit_result, manifest = edit_xlsx(
                request.input_path,
                candidate,
                {"edits": edits, "expected_edits": len(edits)},
            )
            validation = validate_mutation(
                candidate,
                source=request.input_path,
                source_sha256=source.sha256,
                manifest=manifest,
                assertion=lambda path: _assert_summary_mutation(
                    path,
                    request.input_path,
                    edits,
                    summary,
                ),
            )
            output_package = OpcPackage.open(
                candidate,
                allowed_inert_categories=allowed_inert_categories(source_format),
            )
            assert_package_matches_path(candidate, output_package.workbook_format)
            macro_evidence = None
            if source_format == "xlsm":
                macro_evidence = validate_macro_preservation(
                    source_package,
                    output_package,
                    package_mutated=True,
                )
                validation = with_macro_preservation_gate(validation, macro_evidence)
            formula_analysis, validation = validate_formula_analysis(
                candidate,
                validation,
                required=True,
            )
            formula_cells = edit_result.get("formula_state", {}).get("cells", {})
            formula_summary = build_formula_state_summary(formula_cells)
            recalculation = {
                "outcome": "not_run",
                "policy": "skip",
                "reason": "ordinary-summary-static-values",
                "formula_cells": len(formula_cells),
            }
            operation_result = {
                "summary": {
                    "kind": "ordinary_table",
                    "native_pivot": False,
                    "source": {
                        "sheet": summary.source_sheet,
                        "range": summary.source_range,
                        "rows_scanned": summary.rows_scanned,
                        "rows_included": summary.rows_included,
                        "formula_policy": request.arguments["formula_policy"],
                        "formula_cells_used": list(summary.formula_cells_used),
                        "numeric_policy": request.arguments["numeric_policy"],
                    },
                    "group_by": request.arguments["group_by"],
                    "aggregates": request.arguments["aggregates"],
                    "sort": request.arguments["sort"],
                    "top_n": request.arguments["top_n"],
                    "groups_before_top_n": summary.groups_before_top_n,
                    "groups_written": summary.groups_written,
                    "output": {
                        "sheet": summary.target_sheet,
                        "range": summary.target_range,
                        "table_name": summary.table_name,
                        "table_style": summary.table_style,
                        "columns": list(summary.headers),
                    },
                },
                "preservation": manifest.as_dict(),
                "formula_state": {
                    "cells": formula_cells,
                    "summary": formula_summary,
                },
                "formula_analysis": formula_analysis,
                "recalculation": recalculation,
            }
            if macro_evidence is not None:
                operation_result["macro"] = macro_evidence
            validation = _with_summary_truthfulness_gate(validation, summary)
            validation = with_formula_gate(validation, operation_result)
            validation = with_recalculation_gate(validation, recalculation)
            formula_degraded = should_downgrade(formula_summary)
            cached_degraded = bool(summary.formula_cells_used)
            signature_degraded = signature_invalidated(macro_evidence)
            degraded = formula_degraded or cached_degraded or signature_degraded
            warnings = _cached_formula_warnings(summary) + signature_warnings(macro_evidence)
            degradations = formula_degradations(
                formula_degraded,
                "Summary mutation leaves workbook formulas requiring recalculation.",
            )
            if cached_degraded:
                degradations.append(_cached_formula_degradation(summary))
            if signature_degraded:
                degradations.append(signature_degradation())
            result = write_candidate_result(
                schemas,
                request,
                candidate,
                validation,
                operation_result,
                warnings=warnings,
                source=source,
                status="degraded" if degraded else "success",
                degraded=degraded,
                degradations=degradations,
            )
            assert_source_preserved(source.path, source.sha256)
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


def _summary_edits(summary: SummaryBuild) -> list[dict[str, Any]]:
    edits: list[dict[str, Any]] = [
        {
            "sheet": summary.target_sheet,
            "type": "sheet_add",
            "ref": "",
            "position": 1_000_000,
        }
    ]
    start = parse_ref(summary.target_start_cell)
    assert start is not None
    first_column = col_to_num(start[0])
    rows = [
        tuple(OutputCell(value, "string") for value in summary.headers),
        *summary.rows,
    ]
    for row_offset, row in enumerate(rows):
        for column_offset, cell in enumerate(row):
            if cell.kind == "empty":
                continue
            edits.append(
                {
                    "sheet": summary.target_sheet,
                    "type": "cell_value",
                    "ref": f"{num_to_col(first_column + column_offset)}{start[1] + row_offset}",
                    "value": cell.value,
                    "style": None,
                    "cell_value_type": cell.kind,
                }
            )
    edits.append(
        {
            "sheet": summary.target_sheet,
            "type": "table_add",
            "ref": summary.target_range,
            "name": summary.table_name,
            "table_style": summary.table_style,
        }
    )
    return edits


def _assert_summary_mutation(
    candidate: Path,
    source: Path,
    edits: list[dict[str, Any]],
    summary: SummaryBuild,
) -> dict[str, Any]:
    edits_evidence = assert_edits_applied(candidate, edits, source=source)
    summary_evidence = assert_summary_written(candidate, summary)
    return {**edits_evidence, **summary_evidence}


def _with_summary_truthfulness_gate(
    validation: dict[str, Any],
    summary: SummaryBuild,
) -> dict[str, Any]:
    gates = list(validation.get("gates", []))
    gates.append(
        gate_record(
            "operation.ordinary-summary-not-pivot",
            "pass",
            evidence={
                "summary_kind": "ordinary_table",
                "native_pivot": False,
                "sheet": summary.target_sheet,
                "table_name": summary.table_name,
            },
        )
    )
    return {**validation, "gates": gates}


def _cached_formula_warnings(summary: SummaryBuild) -> list[dict[str, Any]]:
    if not summary.formula_cells_used:
        return []
    return [
        {
            "code": "DS_SUMMARY_CACHED_FORMULA_VALUES",
            "message": "Summary aggregation used stored formula caches without recalculation.",
            "details": {"cells": list(summary.formula_cells_used)},
        }
    ]


def _cached_formula_degradation(summary: SummaryBuild) -> dict[str, Any]:
    return {
        "code": "summary-cached-formula-values",
        "semantic_difference": "Summary values came from formula caches that were not recalculated.",
        "missing_capabilities": ["recalculation"],
        "recommended_providers": ["libreoffice"],
    }
