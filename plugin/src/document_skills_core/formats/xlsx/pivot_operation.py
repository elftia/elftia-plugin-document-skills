"""Transactional public ``xlsx.pivot.create`` orchestration."""

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
from .package import OpcPackage, PreservationManifest
from .pivot_model import PivotBuild, build_pivot
from .pivot_package import PivotPackageParts, append_pivot_parts
from .pivot_projection import project_pivot_tables
from .pivot_validation import assert_pivot_written
from .results import with_formula_gate, with_recalculation_gate
from .service_support import formula_degradations
from .transaction import promote_candidate, write_candidate_result
from .validation import assert_edits_applied, validate_mutation


def execute_pivot_create(
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
            pivot = build_pivot(source_package, request.arguments)
            edits = _pivot_edits(pivot)
            worksheet_candidate = private_root / f"pivot-sheet{request.output_path.suffix.casefold()}"
            edit_result, edit_manifest = edit_xlsx(
                request.input_path,
                worksheet_candidate,
                {"edits": edits, "expected_edits": len(edits)},
            )
            worksheet_package = OpcPackage.open(
                worksheet_candidate,
                allowed_inert_categories=allowed_inert_categories(source_format),
            )
            candidate = private_root / f"pivot{request.output_path.suffix.casefold()}"
            pivot_manifest, pivot_parts = append_pivot_parts(
                worksheet_package,
                candidate,
                pivot,
            )
            output_package = OpcPackage.open(
                candidate,
                allowed_inert_categories=allowed_inert_categories(source_format),
            )
            assert_package_matches_path(candidate, output_package.workbook_format)
            final_manifest = _final_manifest(
                source_package,
                output_package,
                edit_manifest,
                pivot_manifest,
            )
            validation = validate_mutation(
                candidate,
                source=request.input_path,
                source_sha256=source.sha256,
                manifest=final_manifest,
                assertion=lambda path: _assert_pivot_mutation(
                    path,
                    request.input_path,
                    edits,
                    pivot,
                    pivot_parts,
                ),
            )
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
                "reason": "native-pivot-static-cache",
                "formula_cells": len(formula_cells),
            }
            projected = next(
                item for item in project_pivot_tables(output_package) if item["name"] == pivot.name
            )
            operation_result = {
                "pivot": {
                    **projected,
                    "display_range": pivot.display_ref,
                    "source": {
                        **projected["source"],
                        "records": pivot.record_count,
                        "formula_policy": request.arguments["formula_policy"],
                        "formula_cells_used": list(pivot.formula_cells_used),
                        "numeric_policy": request.arguments["numeric_policy"],
                    },
                },
                "preservation": final_manifest.as_dict(),
                "formula_state": {"cells": formula_cells, "summary": formula_summary},
                "formula_analysis": formula_analysis,
                "recalculation": recalculation,
            }
            if macro_evidence is not None:
                operation_result["macro"] = macro_evidence
            validation = _with_native_pivot_gate(validation, pivot, pivot_parts)
            validation = with_formula_gate(validation, operation_result)
            validation = with_recalculation_gate(validation, recalculation)
            formula_degraded = should_downgrade(formula_summary)
            cached_degraded = bool(pivot.formula_cells_used)
            signature_degraded = signature_invalidated(macro_evidence)
            degraded = formula_degraded or cached_degraded or signature_degraded
            warnings = _cached_formula_warnings(pivot) + signature_warnings(macro_evidence)
            degradations = formula_degradations(
                formula_degraded,
                "Pivot mutation leaves workbook formulas requiring recalculation.",
            )
            if cached_degraded:
                degradations.append(_cached_formula_degradation())
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


def _pivot_edits(pivot: PivotBuild) -> list[dict[str, Any]]:
    edits: list[dict[str, Any]] = [
        {"sheet": pivot.target_sheet, "type": "sheet_add", "ref": "", "position": 1_000_000}
    ]
    for ref, cell in pivot.output_cells:
        if cell.kind == "empty":
            continue
        edits.append(
            {
                "sheet": pivot.target_sheet,
                "type": "cell_value",
                "ref": ref,
                "value": cell.value,
                "style": None,
                "cell_value_type": cell.kind,
            }
        )
    return edits


def _final_manifest(
    source: OpcPackage,
    output: OpcPackage,
    edit_manifest: PreservationManifest,
    pivot_manifest: PreservationManifest,
) -> PreservationManifest:
    return source.compare_preservation(
        output,
        allowed_changed=set(edit_manifest.changed) | set(pivot_manifest.changed),
        expected_added=set(edit_manifest.added) | set(pivot_manifest.added),
        expected_removed=set(edit_manifest.removed) | set(pivot_manifest.removed),
    )


def _assert_pivot_mutation(
    candidate: Path,
    source: Path,
    edits: list[dict[str, Any]],
    pivot: PivotBuild,
    parts: PivotPackageParts,
) -> dict[str, Any]:
    return {
        **assert_edits_applied(candidate, edits, source=source),
        **assert_pivot_written(candidate, pivot, parts),
    }


def _with_native_pivot_gate(
    validation: dict[str, Any],
    pivot: PivotBuild,
    parts: PivotPackageParts,
) -> dict[str, Any]:
    gates = list(validation.get("gates", []))
    gates.append(
        gate_record(
            "operation.native-pivot-table",
            "pass",
            evidence={
                "native_pivot": True,
                "name": pivot.name,
                "cache_id": parts.cache_id,
                "records": pivot.record_count,
            },
        )
    )
    return {**validation, "gates": gates}


def _cached_formula_warnings(pivot: PivotBuild) -> list[dict[str, Any]]:
    if not pivot.formula_cells_used:
        return []
    return [
        {
            "code": "DS_PIVOT_CACHED_FORMULA_VALUES",
            "message": "Pivot cache used stored formula values without recalculation.",
            "details": {"cells": list(pivot.formula_cells_used)},
        }
    ]


def _cached_formula_degradation() -> dict[str, Any]:
    return {
        "code": "pivot-cached-formula-values",
        "semantic_difference": "Pivot cache records came from formula caches that were not recalculated.",
        "missing_capabilities": ["recalculation"],
        "recommended_providers": ["libreoffice"],
    }
