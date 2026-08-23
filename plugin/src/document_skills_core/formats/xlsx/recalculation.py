"""Accepted-provider formula harvesting with copy-through XLSX promotion safety."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import FORMULA_STATE_RECALCULATED, NS
from .formula_state import build_formula_cell_state
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest

_MAIN_NS = NS["main"]
FORMULA_ERROR_TOKENS = (
    "#REF!",
    "#DIV/0!",
    "#VALUE!",
    "#NAME?",
    "#N/A",
    "#NUM!",
)
_FORMULA_RESULT_TYPES = {"n", "str", "b", "e"}


def apply_provider_recalculation(
    candidate: Path,
    provider_candidate: Path,
    destination: Path,
) -> tuple[dict[str, dict[str, Any]], PreservationManifest, dict[str, Any]]:
    """Validate provider output, harvest values, and patch only formula-bearing parts."""

    package = OpcPackage.open(candidate)
    provider_package = OpcPackage.open(provider_candidate)
    expected = _formula_records(package)
    actual = _formula_records(provider_package)
    _assert_formula_identity(expected, actual)
    errors = _formula_errors(actual)
    if errors:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "LibreOffice recalculation produced formula error tokens.",
            details={"formula_errors": errors},
        )
    changed_parts, states = _patch_formula_values(package, expected, actual)
    manifest = package.write_copy(destination, changed_parts=changed_parts)
    _assert_patched_values(destination, actual)
    evidence = {
        "provider": "libreoffice",
        "formula_cells": len(actual),
        "cached_values": sum(
            record.get("cached_value") is not None for record in actual.values()
        ),
        "formula_errors": [],
        "provider_artifact_bytes": provider_candidate.stat().st_size,
        "copy_through_preserved_parts": len(manifest.preserved),
    }
    return states, manifest, evidence


def compare_final_preservation(
    source: Path,
    output: Path,
    *,
    allowed_changed: set[str],
    expected_added: set[str],
    expected_removed: set[str],
) -> PreservationManifest:
    """Build a final source-to-output manifest after Core and provider-backed patches."""

    source_package = OpcPackage.open(source)
    output_package = OpcPackage.open(output)
    input_names = set(source_package.parts)
    output_names = set(output_package.parts)
    added = output_names - input_names
    removed = input_names - output_names
    changed = {
        part
        for part in input_names & output_names
        if source_package.part_hashes[part] != output_package.part_hashes[part]
    }
    unexpected_changed = changed - allowed_changed
    if (
        added != expected_added
        or removed != expected_removed
        or unexpected_changed
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Recalculated XLSX violated the declared mutation preservation boundary.",
            details={
                "added_parts": sorted(added),
                "expected_added_parts": sorted(expected_added),
                "removed_parts": sorted(removed),
                "expected_removed_parts": sorted(expected_removed),
                "unexpected_changed_parts": sorted(unexpected_changed),
            },
        )
    preserved = sorted(input_names - changed - removed)
    return PreservationManifest(
        tuple(sorted(changed)),
        tuple(sorted(added)),
        tuple(sorted(removed)),
        tuple(preserved),
        dict(sorted(source_package.part_hashes.items())),
        dict(sorted(output_package.part_hashes.items())),
    )


def formula_count(path: Path) -> int:
    return len(_formula_records(OpcPackage.open(path)))


def _formula_records(package: OpcPackage) -> dict[str, dict[str, Any]]:
    workbook = map_workbook(package)
    result: dict[str, dict[str, Any]] = {}
    for sheet in workbook.get("sheets", []):
        part = sheet.get("part")
        root = package.xml(part) if part else None
        xml_cells = (
            {
                item.attrib["r"]: item
                for item in root.findall(f".//{{{_MAIN_NS}}}c")
                if "r" in item.attrib
            }
            if root is not None
            else {}
        )
        for row in sheet.get("rows", []):
            for cell in row.get("cells", []):
                if cell.get("formula") is None:
                    continue
                formula_state = cell.get("formula_state", {})
                xml_cell = xml_cells.get(cell["ref"])
                result[f"{sheet['name']}!{cell['ref']}"] = {
                    "formula": cell["formula"],
                    "cached_value": cell.get("cached_value"),
                    "type": cell.get("type", "n"),
                    "part": part,
                    "ref": cell["ref"],
                    "has_cached_value_element": (
                        xml_cell is not None
                        and xml_cell.find(f"{{{_MAIN_NS}}}v") is not None
                    ),
                    "precedents_count": formula_state.get("precedents_count", 0),
                    "dependents_count": formula_state.get("dependents_count", 0),
                }
    return result


def _assert_formula_identity(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> None:
    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    changed = sorted(
        ref
        for ref in set(expected) & set(actual)
        if expected[ref]["formula"] != actual[ref]["formula"]
    )
    invalid_types = sorted(
        ref
        for ref, record in actual.items()
        if record.get("type") not in _FORMULA_RESULT_TYPES
    )
    missing_cached_values = sorted(
        ref
        for ref, record in actual.items()
        if not record.get("has_cached_value_element")
    )
    if missing or added or changed or invalid_types or missing_cached_values:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "LibreOffice recalculation changed the workbook formula identity.",
            details={
                "missing_formulas": missing,
                "added_formulas": added,
                "changed_formulas": changed,
                "invalid_result_types": invalid_types,
                "missing_cached_values": missing_cached_values,
            },
        )


def _formula_errors(records: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for ref, record in records.items():
        value = record.get("cached_value")
        if value is None:
            continue
        normalized = str(value).upper()
        token = next((item for item in FORMULA_ERROR_TOKENS if item in normalized), None)
        if token is not None:
            errors.append({"ref": ref, "token": token})
    return errors


def _patch_formula_values(
    package: OpcPackage,
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    roots: dict[str, Element] = {}
    cells_by_part: dict[str, dict[str, Element]] = {}
    states: dict[str, dict[str, Any]] = {}
    for ref, source_record in expected.items():
        part = source_record["part"]
        if not part:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Formula worksheet relationship is missing.",
                details={"ref": ref},
            )
        if part not in roots:
            roots[part] = package.xml(part)
            cells_by_part[part] = {
                item.attrib["r"]: item
                for item in roots[part].findall(f".//{{{_MAIN_NS}}}c")
                if "r" in item.attrib
            }
        root = roots[part]
        cell = cells_by_part[part].get(source_record["ref"])
        if cell is None:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Formula cell disappeared before provider value harvest.",
                details={"ref": ref},
            )
        provider_record = actual[ref]
        result_type = provider_record["type"]
        if result_type == "n":
            cell.attrib.pop("t", None)
        else:
            cell.attrib["t"] = result_type
        for value in list(cell.findall(f"{{{_MAIN_NS}}}v")):
            cell.remove(value)
        value = SubElement(cell, f"{{{_MAIN_NS}}}v")
        value.text = provider_record.get("cached_value")
        original_state = source_record
        states[ref] = build_formula_cell_state(
            state=FORMULA_STATE_RECALCULATED,
            formula=source_record["formula"],
            cached_value=provider_record.get("cached_value"),
            precedents_count=original_state.get("precedents_count", 0),
            dependents_count=original_state.get("dependents_count", 0),
        )
    workbook_root = package.xml("xl/workbook.xml")
    calc_properties = workbook_root.find(f"{{{_MAIN_NS}}}calcPr")
    if calc_properties is None:
        calc_properties = SubElement(workbook_root, f"{{{_MAIN_NS}}}calcPr")
    calc_properties.attrib.update(
        {"calcMode": "auto", "fullCalcOnLoad": "0", "forceFullCalc": "0"}
    )
    changed_parts = {
        part: tostring(root, encoding="UTF-8", xml_declaration=True)
        for part, root in roots.items()
    }
    changed_parts["xl/workbook.xml"] = tostring(
        workbook_root,
        encoding="UTF-8",
        xml_declaration=True,
    )
    return changed_parts, states


def _assert_patched_values(
    path: Path,
    expected: dict[str, dict[str, Any]],
) -> None:
    actual = _formula_records(OpcPackage.open(path))
    mismatched = sorted(
        ref
        for ref in expected
        if ref not in actual
        or actual[ref]["formula"] != expected[ref]["formula"]
        or actual[ref].get("cached_value") != expected[ref].get("cached_value")
        or actual[ref].get("type") != expected[ref].get("type")
    )
    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Reopened XLSX did not retain accepted provider formula values.",
            details={"mismatched_formulas": mismatched},
        )
