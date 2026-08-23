"""Run-aware cell/row/column/sheet mutation with style preservation and dependent invalidation."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS, SHARED_STRINGS_PART
from .formula_state import (
    derive_edit_state,
    parse_formula_references,
    build_formula_cell_state,
    normalize_ref,
)
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest
from .shared_strings import read_shared_strings
from .shared_strings import build_shared_strings_xml

_MAIN_NS = NS["main"]


def edit_xlsx(
    source: str | Path,
    destination: str | Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], PreservationManifest]:
    """Apply edits to an XLSX workbook with run-aware style preservation.

    Returns (operation_result, manifest).
    """
    package = OpcPackage.open(source)
    edits = arguments.get("edits", [])
    parts = dict(package.parts)
    shared = read_shared_strings(parts)

    # Map the workbook to get current state
    workbook = map_workbook(package)
    sheet_lookup = {s["name"]: s for s in workbook["sheets"]}

    # Track changed parts
    changed_parts: dict[str, bytes] = {}
    worksheet_roots: dict[str, Element] = {}
    # Track formula state for all formulas (existing + edited)
    all_formula_cells: dict[str, dict[str, Any]] = dict(workbook.get("formula_cells", {}))
    # Track invalidated dependents
    invalidated: set[str] = set()
    edit_counts: dict[str, int] = {}
    # Track new/edited shared strings
    new_shared = list(shared)

    # Process each edit
    for edit in edits:
        sheet_name = edit["sheet"]
        edit_type = edit["type"]
        ref = edit["ref"]
        value = edit.get("value")
        sheet = sheet_lookup.get(sheet_name)
        if sheet is None:
            continue
        # Find the worksheet part
        sheet_idx = [s["name"] for s in workbook["sheets"]].index(sheet_name)
        sheet_part = f"xl/worksheets/sheet{sheet_idx + 1}.xml"
        sheet_root = worksheet_roots.setdefault(sheet_part, package.xml(sheet_part))

        if edit_type == "cell_value":
            _apply_cell_value(sheet_root, ref, value, new_shared, all_formula_cells, invalidated, sheet_name)
            edit_counts["cell_value"] = edit_counts.get("cell_value", 0) + 1
        elif edit_type == "cell_formula":
            _apply_cell_formula(sheet_root, ref, value, all_formula_cells, invalidated, sheet_name)
            edit_counts["cell_formula"] = edit_counts.get("cell_formula", 0) + 1
        elif edit_type in ("row_insert", "row_delete", "column_insert", "column_delete"):
            _apply_structural(sheet_root, edit_type, ref, all_formula_cells, invalidated, sheet_name)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type == "sheet_rename":
            # Rename is handled at workbook level
            edit_counts["sheet_rename"] = edit_counts.get("sheet_rename", 0) + 1

    for sheet_part, sheet_root in worksheet_roots.items():
        changed_parts[sheet_part] = tostring(
            sheet_root,
            encoding="UTF-8",
            xml_declaration=True,
        )

    # Rebuild shared strings if changed
    if new_shared != shared:
        changed_parts[SHARED_STRINGS_PART] = build_shared_strings_xml(new_shared)

    # Handle sheet rename at workbook level
    workbook_changed = False
    workbook_root = package.xml("xl/workbook.xml")
    for edit in edits:
        if edit["type"] == "sheet_rename":
            old_name = edit["sheet"]
            new_name = edit.get("value", "")
            if new_name and _rename_sheet_in_workbook(workbook_root, old_name, new_name):
                workbook_changed = True
    if workbook_changed:
        changed_parts["xl/workbook.xml"] = tostring(
            workbook_root,
            encoding="UTF-8",
            xml_declaration=True,
        )

    # Update formula state for invalidated dependents
    for ref_key in invalidated:
        if ref_key in all_formula_cells:
            all_formula_cells[ref_key] = build_formula_cell_state(
                state=derive_edit_state(),
                formula=all_formula_cells[ref_key].get("formula", ""),
                cached_value=all_formula_cells[ref_key].get("cached_value"),
                precedents_count=all_formula_cells[ref_key].get("precedents_count", 0),
                dependents_count=all_formula_cells[ref_key].get("dependents_count", 0),
            )

    # Write the mutated package
    manifest = package.write_copy(destination, changed_parts=changed_parts)

    operation_result: dict[str, Any] = {
        "edit_counts": edit_counts,
        "invalidated_dependents": sorted(invalidated),
        "preservation": manifest.as_dict(),
        "shared_strings_count": len(new_shared),
        "formula_state": {
            "cells": all_formula_cells,
        },
    }
    return operation_result, manifest


def _apply_cell_value(
    sheet_root: Element,
    ref: str,
    value: str | None,
    shared: list[str],
    formula_cells: dict[str, dict[str, Any]],
    invalidated: set[str],
    sheet_name: str,
) -> None:
    """Apply a cell value edit, preserving existing style."""
    sheet_data = sheet_root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        return
    cell = _find_or_create_cell(sheet_data, ref)
    # Preserve style attribute
    old_style = cell.attrib.get("s")
    # Clear existing content
    for child in list(cell):
        cell.remove(child)
    # Set new value
    if value is not None:
        # Try numeric first
        try:
            float(value)
            cell.attrib.pop("t", None)
            v = SubElement(cell, f"{{{_MAIN_NS}}}v")
            v.text = value
        except ValueError:
            # String value — use shared strings
            if value not in shared:
                shared.append(value)
            idx = shared.index(value)
            cell.attrib["t"] = "s"
            v = SubElement(cell, f"{{{_MAIN_NS}}}v")
            v.text = str(idx)
    # Restore style
    if old_style is not None:
        cell.attrib["s"] = old_style
    # Check if this cell is a precedent of any formula and invalidate
    _invalidate_dependents(ref, sheet_name, formula_cells, invalidated)


def _apply_cell_formula(
    sheet_root: Element,
    ref: str,
    formula: str | None,
    formula_cells: dict[str, dict[str, Any]],
    invalidated: set[str],
    sheet_name: str,
) -> None:
    """Apply a cell formula edit, preserving existing style."""
    sheet_data = sheet_root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        return
    cell = _find_or_create_cell(sheet_data, ref)
    old_style = cell.attrib.get("s")
    for child in list(cell):
        cell.remove(child)
    if formula:
        f = SubElement(cell, f"{{{_MAIN_NS}}}f")
        f.text = formula
        ref_key = f"{sheet_name}!{ref}"
        precedents = parse_formula_references(formula)
        formula_cells[ref_key] = build_formula_cell_state(
            state=derive_edit_state(),
            formula=formula,
            cached_value=None,
            precedents_count=len(precedents),
            dependents_count=0,
        )
    if old_style is not None:
        cell.attrib["s"] = old_style
    # The edited formula's precedents may have changed
    _invalidate_dependents(ref, sheet_name, formula_cells, invalidated)


def _apply_structural(
    sheet_root: Element,
    op: str,
    ref: str,
    formula_cells: dict[str, dict[str, Any]],
    invalidated: set[str],
    sheet_name: str,
) -> None:
    """Apply a row/column insert/delete operation.

    For structural operations, all formulas whose reference set was touched
    report recalculation_required.
    """
    # Structural operations affect all formulas on the sheet
    for ref_key in formula_cells:
        if ref_key.startswith(f"{sheet_name}!"):
            invalidated.add(ref_key)


def _invalidate_dependents(
    ref: str,
    sheet_name: str,
    formula_cells: dict[str, dict[str, Any]],
    invalidated: set[str],
) -> None:
    """Find formulas that reference the edited cell and mark them for invalidation."""
    target_ref = normalize_ref(ref)
    target_key = f"{sheet_name}!{target_ref}"
    bare_target = target_ref  # Also check unsheeted references
    for ref_key, info in formula_cells.items():
        formula = info.get("formula", "")
        precedents = parse_formula_references(formula)
        # Check if the edited ref is in the precedents
        if bare_target in precedents or target_key.split("!")[-1] in precedents:
            invalidated.add(ref_key)


def _find_or_create_cell(sheet_data: Element, ref: str) -> Element:
    """Find an existing cell by reference or create a new one in the correct row."""
    # Parse row number from ref
    import re
    match = re.match(r"^([A-Z]+)(\d+)$", ref.upper().replace("$", ""))
    if not match:
        raise ValueError(f"Invalid cell reference: {ref}")
    row_num = match.group(2)
    # Find the row
    row_elem = None
    for row in sheet_data.findall(f"{{{_MAIN_NS}}}row"):
        if row.attrib.get("r") == row_num:
            row_elem = row
            break
    if row_elem is None:
        row_elem = SubElement(sheet_data, f"{{{_MAIN_NS}}}row", attrib={"r": row_num})
    # Find the cell
    for cell in row_elem.findall(f"{{{_MAIN_NS}}}c"):
        if cell.attrib.get("r") == ref:
            return cell
    # Create new cell
    return SubElement(row_elem, f"{{{_MAIN_NS}}}c", attrib={"r": ref})


def _rename_sheet_in_workbook(workbook_root: Element, old_name: str, new_name: str) -> bool:
    """Rename a sheet in the workbook XML. Returns True if renamed."""
    sheets_elem = workbook_root.find(f"{{{_MAIN_NS}}}sheets")
    if sheets_elem is None:
        return False
    for sheet in sheets_elem.findall(f"{{{_MAIN_NS}}}sheet"):
        if sheet.attrib.get("name") == old_name:
            sheet.attrib["name"] = new_name
            return True
    return False
