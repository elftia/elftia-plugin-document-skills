"""Transactional ``xlsx.template.instantiate`` package transition."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import tostring

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

from .constants import CONTENT_TYPES, CONTENT_TYPES_NS, WORKBOOK_CONTENT_TYPES
from .contracts import ParsedXlsxRequest
from .edit import edit_xlsx
from .format_policy import (
    allowed_inert_categories,
    assert_package_matches_path,
    format_id,
)
from .formula_analysis import validate_formula_analysis
from .formula_state import build_formula_state_summary, should_downgrade
from .macro_policy import (
    signature_degradation,
    signature_invalidated,
    signature_warnings,
    validate_macro_preservation,
    with_macro_preservation_gate,
)
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest
from .results import with_formula_gate
from .service_support import allowed_removed_parts, formula_degradations
from .transaction import promote_candidate, write_candidate_result
from .validation import assert_edits_applied, validate_mutation


def execute_template_instantiation(
    request: ParsedXlsxRequest,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None and request.output_path is not None
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    source_format = format_id(request.input_path)
    output_format = format_id(request.output_path)
    try:
        with OperationTempRoot() as private_root:
            source_package = OpcPackage.open(
                request.input_path,
                allowed_inert_categories=allowed_inert_categories(source_format),
            )
            assert_package_matches_path(request.input_path, source_package.workbook_format)
            base = private_root / f"template-base.{output_format}"
            base_manifest = source_package.write_copy(
                base,
                changed_parts={
                    CONTENT_TYPES: _instantiated_content_types(
                        source_package,
                        output_format,
                    )
                },
            )
            candidate, edit_result, edit_manifest = _apply_optional_edits(
                base,
                private_root,
                request,
                base_manifest,
            )
            output_package = OpcPackage.open(
                candidate,
                allowed_inert_categories=allowed_inert_categories(output_format),
            )
            assert_package_matches_path(candidate, output_package.workbook_format)
            manifest = source_package.compare_preservation(
                output_package,
                allowed_changed={CONTENT_TYPES, *edit_manifest.changed},
                expected_added=set(edit_manifest.added),
                expected_removed=set(edit_manifest.removed),
            )
            validation = validate_mutation(
                candidate,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                allowed_removed_parts=allowed_removed_parts(
                    request.arguments["edits"],
                    manifest.removed,
                ),
                assertion=(
                    None
                    if not request.arguments["edits"]
                    else lambda path: assert_edits_applied(
                        path,
                        request.arguments["edits"],
                        source=request.input_path,
                    )
                ),
            )
            validation = _with_template_transition_gate(
                validation,
                source_format=source_format,
                output_format=output_format,
            )
            formula_analysis, validation = validate_formula_analysis(
                candidate,
                validation,
                required=True,
            )
            formula_cells = edit_result.get("formula_state", {}).get("cells")
            if formula_cells is None:
                formula_cells = map_workbook(output_package).get("formula_cells", {})
            formula_summary = build_formula_state_summary(formula_cells)
            macro_evidence = None
            if source_format == "xltm":
                macro_evidence = validate_macro_preservation(
                    source_package,
                    output_package,
                    package_mutated=True,
                )
                validation = with_macro_preservation_gate(validation, macro_evidence)
            operation_result = {
                "template": {
                    "source_format": source_format,
                    "target_format": output_format,
                    "main_content_type_transition": {
                        "from": WORKBOOK_CONTENT_TYPES[source_format],
                        "to": WORKBOOK_CONTENT_TYPES[output_format],
                    },
                    "edit_counts": edit_result.get("edit_counts", {}),
                },
                "preservation": manifest.as_dict(),
                "formula_state": {
                    "cells": formula_cells,
                    "summary": formula_summary,
                },
                "formula_analysis": formula_analysis,
            }
            if macro_evidence is not None:
                operation_result["macro"] = macro_evidence
            degraded = should_downgrade(formula_summary) or signature_invalidated(
                macro_evidence
            )
            validation = with_formula_gate(validation, operation_result)
            warnings = signature_warnings(macro_evidence)
            degradations = formula_degradations(
                should_downgrade(formula_summary),
                "Instantiated formulas require recalculation by an accepted provider.",
            )
            if signature_invalidated(macro_evidence):
                degradations.append(signature_degradation())
            result = write_candidate_result(
                schemas,
                request,
                candidate,
                validation,
                operation_result,
                warnings=warnings,
                source=source_record,
                status="degraded" if degraded else "success",
                degraded=degraded,
                degradations=degradations,
            )
            assert_source_preserved(source_record.path, source_record.sha256)
            return promote_candidate(
                request,
                candidate,
                result,
                source=source_record,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source_record.path, source_record.sha256)
        raise


def _apply_optional_edits(
    base: Path,
    private_root: Path,
    request: ParsedXlsxRequest,
    base_manifest: PreservationManifest,
) -> tuple[Path, dict[str, Any], PreservationManifest]:
    if not request.arguments["edits"]:
        return base, {}, base_manifest
    candidate = private_root / f"instantiated{request.output_path.suffix.casefold()}"
    result, manifest = edit_xlsx(base, candidate, request.arguments)
    return candidate, result, manifest


def _instantiated_content_types(package: OpcPackage, output_format: str) -> bytes:
    root = package.xml(CONTENT_TYPES)
    matches = [
        item
        for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        if item.attrib.get("PartName") == "/xl/workbook.xml"
    ]
    if len(matches) != 1:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Template package must declare one workbook content-type override.",
        )
    matches[0].attrib["ContentType"] = WORKBOOK_CONTENT_TYPES[output_format]
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _with_template_transition_gate(
    validation: dict[str, Any],
    *,
    source_format: str,
    output_format: str,
) -> dict[str, Any]:
    gates = list(validation.get("gates", []))
    gates.append(
        gate_record(
            "operation.template-content-type-transition",
            "pass",
            evidence={"source_format": source_format, "output_format": output_format},
        )
    )
    return {**validation, "gates": gates}
