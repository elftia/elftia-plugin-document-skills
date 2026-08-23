"""Run-aware cell/row/column/sheet mutation with style preservation and dependent invalidation."""

from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

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
from .style_patch import ExistingStyleRegistry

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
    style_registry = ExistingStyleRegistry(package.xml("xl/styles.xml"))

    # Process each edit
    for edit in edits:
        sheet_name = edit["sheet"]
        edit_type = edit["type"]
        ref = edit["ref"]
        value = edit.get("value")
        sheet = sheet_lookup.get(sheet_name)
        if sheet is None:
            _invalid_edit("Edit sheet was not found.", sheet=sheet_name)
        # Find the worksheet part
        sheet_idx = [s["name"] for s in workbook["sheets"]].index(sheet_name)
        sheet_part = f"xl/worksheets/sheet{sheet_idx + 1}.xml"
        sheet_root = worksheet_roots.setdefault(sheet_part, package.xml(sheet_part))

        if edit_type == "cell_value":
            _apply_cell_value(sheet_root, ref, value, new_shared, all_formula_cells, invalidated, sheet_name)
            if edit.get("style"):
                _apply_cell_style(sheet_root, ref, edit["style"], style_registry)
            edit_counts["cell_value"] = edit_counts.get("cell_value", 0) + 1
        elif edit_type == "cell_formula":
            _apply_cell_formula(sheet_root, ref, value, all_formula_cells, invalidated, sheet_name)
            if edit.get("style"):
                _apply_cell_style(sheet_root, ref, edit["style"], style_registry)
            edit_counts["cell_formula"] = edit_counts.get("cell_formula", 0) + 1
        elif edit_type == "cell_style":
            _apply_cell_style(sheet_root, ref, edit["style"], style_registry)
            edit_counts["cell_style"] = edit_counts.get("cell_style", 0) + 1
        elif edit_type == "row_style":
            _apply_row_style(sheet_root, ref, edit["style"], style_registry)
            edit_counts["row_style"] = edit_counts.get("row_style", 0) + 1
        elif edit_type == "column_style":
            _apply_column_style(sheet_root, ref, edit["style"], style_registry)
            edit_counts["column_style"] = edit_counts.get("column_style", 0) + 1
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
    if style_registry.changed:
        changed_parts["xl/styles.xml"] = style_registry.to_bytes()

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

    expected_edits = arguments.get("expected_edits")
    actual_edits = sum(edit_counts.values())
    if expected_edits is not None and actual_edits != expected_edits:
        _invalid_edit(
            "The number of changed edits did not match expected_edits.",
            expected_edits=expected_edits,
            actual_edits=actual_edits,
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


def _apply_cell_style(
    sheet_root: Element,
    ref: str,
    style: dict[str, Any],
    registry: ExistingStyleRegistry,
) -> None:
    sheet_data = sheet_root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        _invalid_edit("Worksheet is missing sheetData.")
    cell = _find_or_create_cell(sheet_data, ref)
    base_style_id = int(cell.attrib.get("s", "0"))
    cell.attrib["s"] = str(registry.apply(base_style_id, style))


def _apply_row_style(
    sheet_root: Element,
    ref: str,
    style: dict[str, Any],
    registry: ExistingStyleRegistry,
) -> int:
    first, last = _parse_index_range(ref, maximum=1_048_576, kind="row")
    sheet_data = sheet_root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        _invalid_edit("Worksheet is missing sheetData.")
    rows = {
        int(row.attrib["r"]): row
        for row in sheet_data.findall(f"{{{_MAIN_NS}}}row")
        if row.attrib.get("r", "").isdigit()
    }
    for row_number in range(first, last + 1):
        row = rows.get(row_number)
        if row is None:
            row = Element(f"{{{_MAIN_NS}}}row", attrib={"r": str(row_number)})
            _insert_row(sheet_data, row, row_number)
        row.attrib["s"] = str(registry.apply(int(row.attrib.get("s", "0")), style))
        row.attrib["customFormat"] = "1"
    return last - first + 1


def _apply_column_style(
    sheet_root: Element,
    ref: str,
    style: dict[str, Any],
    registry: ExistingStyleRegistry,
) -> int:
    first, last = _parse_column_range(ref)
    columns = sheet_root.find(f"{{{_MAIN_NS}}}cols")
    if columns is None:
        columns = Element(f"{{{_MAIN_NS}}}cols")
        sheet_data = sheet_root.find(f"{{{_MAIN_NS}}}sheetData")
        insert_at = list(sheet_root).index(sheet_data) if sheet_data is not None else 0
        sheet_root.insert(insert_at, columns)
    target = None
    for column in columns.findall(f"{{{_MAIN_NS}}}col"):
        existing_first = int(column.attrib.get("min", "1"))
        existing_last = int(column.attrib.get("max", str(existing_first)))
        overlaps = existing_first <= last and first <= existing_last
        if existing_first == first and existing_last == last:
            target = column
            break
        if overlaps:
            _invalid_edit(
                "Column style ref partially overlaps an existing column definition.",
                ref=ref,
                existing_ref=f"{existing_first}:{existing_last}",
            )
    if target is None:
        target = SubElement(
            columns,
            f"{{{_MAIN_NS}}}col",
            attrib={"min": str(first), "max": str(last)},
        )
    target.attrib["style"] = str(
        registry.apply(int(target.attrib.get("style", "0")), style)
    )
    return last - first + 1


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


def _insert_row(sheet_data: Element, row: Element, row_number: int) -> None:
    for index, existing in enumerate(sheet_data.findall(f"{{{_MAIN_NS}}}row")):
        existing_number = int(existing.attrib.get("r", "0"))
        if existing_number > row_number:
            sheet_data.insert(index, row)
            return
    sheet_data.append(row)


def _parse_index_range(ref: str, *, maximum: int, kind: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?::(\d+))?", ref)
    if match is None:
        _invalid_edit(f"{kind.title()} ref must use 1 or 1:3 notation.", ref=ref)
    first = int(match.group(1))
    last = int(match.group(2) or match.group(1))
    if first < 1 or last < first or last > maximum:
        _invalid_edit(f"{kind.title()} ref is outside the XLSX range.", ref=ref)
    return first, last


def _parse_column_range(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Za-z]{1,3})(?::([A-Za-z]{1,3}))?", ref)
    if match is None:
        _invalid_edit("Column ref must use A or A:C notation.", ref=ref)
    first = _column_number(match.group(1))
    last = _column_number(match.group(2) or match.group(1))
    if first > last or last > 16_384:
        _invalid_edit("Column ref is outside the XLSX range.", ref=ref)
    return first, last


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


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


def _invalid_edit(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
