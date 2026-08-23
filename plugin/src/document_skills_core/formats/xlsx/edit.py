"""Run-aware cell/row/column/sheet mutation with style preservation and dependent invalidation."""

from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .annotations import apply_hyperlink_edit
from .comment_edit import apply_comment_edit
from .constants import NS, SHARED_STRINGS_PART
from .conditional_format import apply_conditional_format_edit
from .chart_edit import apply_chart_edit
from .data_validation import apply_data_validation_edit
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
from .sheet_edit import apply_sheet_edit
from .style_patch import ExistingStyleRegistry
from .structural_edit import StructuralEditContext
from .table_edit import apply_table_edit
from .worksheet_edit import apply_defined_name_edit, apply_worksheet_edit
from .worksheet_metadata import apply_worksheet_metadata_edit
from .workbook_properties import apply_workbook_properties_edit

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
    # Track changed parts
    changed_parts: dict[str, bytes] = {}
    structural_context = StructuralEditContext(package, workbook)
    # Track formula state for all formulas (existing + edited)
    all_formula_cells: dict[str, dict[str, Any]] = dict(workbook.get("formula_cells", {}))
    # Track invalidated dependents
    invalidated: set[str] = set()
    edit_counts: dict[str, int] = {}
    # Track new/edited shared strings
    new_shared = list(shared)
    use_shared_strings = SHARED_STRINGS_PART in package.parts
    style_registry = ExistingStyleRegistry(package.xml("xl/styles.xml"))

    # Process each edit
    for edit in edits:
        sheet_name = edit["sheet"]
        edit_type = edit["type"]
        ref = edit["ref"]
        value = edit.get("value")
        if edit_type == "workbook_properties":
            apply_workbook_properties_edit(structural_context, edit["properties"])
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
            continue
        if edit_type in {
            "sheet_add",
            "sheet_delete",
            "sheet_copy",
            "sheet_reorder",
            "sheet_rename",
        }:
            apply_sheet_edit(structural_context, edit)
            _apply_structural(all_formula_cells, invalidated)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
            continue
        sheet = next(
            (item for item in structural_context.workbook["sheets"] if item["name"] == sheet_name),
            None,
        )
        if sheet is None:
            _invalid_edit("Edit sheet was not found.", sheet=sheet_name)
        sheet_part = sheet.get("part")
        if not sheet_part:
            _invalid_edit("Edit sheet relationship was not found.", sheet=sheet_name)
        sheet_root = structural_context.worksheet(sheet_part)
        mark_sheet_dirty = True

        if edit_type == "cell_value":
            _apply_cell_value(
                sheet_root,
                ref,
                value,
                new_shared,
                all_formula_cells,
                invalidated,
                sheet_name,
                use_shared_strings=use_shared_strings,
            )
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
            axis = "row" if edit_type.startswith("row") else "column"
            index = int(ref) if axis == "row" else _column_number(ref)
            structural_context.apply_axis_mutation(
                sheet_name=sheet_name,
                axis=axis,
                index=index,
                count=edit["count"],
                delete=edit_type.endswith("delete"),
            )
            _apply_structural(all_formula_cells, invalidated)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {
            "row_height",
            "row_hidden",
            "column_width",
            "column_hidden",
            "cells_merge",
            "cells_unmerge",
            "range_clear",
            "freeze_panes",
            "auto_filter",
            "auto_filter_clear",
            "row_page_break",
            "column_page_break",
        }:
            apply_worksheet_edit(sheet_root, edit)
            if edit_type == "range_clear" and edit["clear"] in {"contents", "all"}:
                _apply_structural(all_formula_cells, invalidated)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {"page_setup", "header_footer", "sheet_view"}:
            apply_worksheet_metadata_edit(sheet_root, edit)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {"hyperlink_add", "hyperlink_update", "hyperlink_delete"}:
            apply_hyperlink_edit(sheet_root, edit)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {"comment_add", "comment_update", "comment_delete"}:
            apply_comment_edit(structural_context, sheet_part, edit)
            mark_sheet_dirty = False
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {
            "table_add",
            "table_resize",
            "table_rename",
            "table_style",
            "table_delete",
        }:
            apply_table_edit(structural_context, edit, new_shared)
            mark_sheet_dirty = False
            if edit_type != "table_style":
                _apply_structural(all_formula_cells, invalidated)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {
            "data_validation_add",
            "data_validation_update",
            "data_validation_delete",
        }:
            apply_data_validation_edit(sheet_root, edit)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {
            "conditional_format_add",
            "conditional_format_update",
            "conditional_format_delete",
        }:
            apply_conditional_format_edit(sheet_root, edit, style_registry)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {"chart_add", "chart_update", "chart_delete"}:
            apply_chart_edit(structural_context, edit)
            mark_sheet_dirty = False
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        elif edit_type in {
            "print_area",
            "print_area_clear",
            "defined_name_add",
            "defined_name_update",
            "defined_name_delete",
            "print_titles",
            "print_titles_clear",
        }:
            apply_defined_name_edit(structural_context.workbook_root, workbook["sheets"], edit)
            structural_context.mark_dirty("xl/workbook.xml")
            mark_sheet_dirty = False
            if edit_type.startswith("defined_name_"):
                _apply_structural(all_formula_cells, invalidated)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1
        if mark_sheet_dirty:
            structural_context.mark_dirty(sheet_part)

    # Rebuild shared strings if changed
    if new_shared != shared:
        changed_parts[SHARED_STRINGS_PART] = build_shared_strings_xml(new_shared)
    if style_registry.changed:
        changed_parts["xl/styles.xml"] = style_registry.to_bytes()

    changed_parts.update(structural_context.changed_parts())

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
    manifest = package.write_copy(
        destination,
        changed_parts=changed_parts,
        added_parts=structural_context.added_parts(),
        removed_parts=structural_context.removed,
    )
    if any(
        edit_type in edit_counts
        for edit_type in (
            "row_insert",
            "row_delete",
            "column_insert",
            "column_delete",
            "range_clear",
            "defined_name_add",
            "defined_name_update",
            "defined_name_delete",
            "sheet_add",
            "sheet_delete",
            "sheet_copy",
            "sheet_reorder",
            "sheet_rename",
            "table_add",
            "table_resize",
            "table_rename",
            "table_delete",
        )
    ):
        all_formula_cells = _structural_formula_state(destination)

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


def _structural_formula_state(path: str | Path) -> dict[str, dict[str, Any]]:
    """Reopen structural output so formula keys and text use final coordinates."""

    mapped = map_workbook(OpcPackage.open(path))
    result: dict[str, dict[str, Any]] = {}
    for ref_key, record in mapped.get("formula_cells", {}).items():
        formula = record.get("formula", "")
        result[ref_key] = build_formula_cell_state(
            state=derive_edit_state(),
            formula=formula,
            cached_value=record.get("cached_value"),
            precedents_count=len(parse_formula_references(formula)),
            dependents_count=record.get("dependents_count", 0),
        )
    return result


def _apply_cell_value(
    sheet_root: Element,
    ref: str,
    value: str | None,
    shared: list[str],
    formula_cells: dict[str, dict[str, Any]],
    invalidated: set[str],
    sheet_name: str,
    *,
    use_shared_strings: bool,
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
            if use_shared_strings:
                if value not in shared:
                    shared.append(value)
                cell.attrib["t"] = "s"
                v = SubElement(cell, f"{{{_MAIN_NS}}}v")
                v.text = str(shared.index(value))
            else:
                cell.attrib["t"] = "inlineStr"
                inline = SubElement(cell, f"{{{_MAIN_NS}}}is")
                text = SubElement(inline, f"{{{_MAIN_NS}}}t")
                text.text = value
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
    formula_cells: dict[str, dict[str, Any]],
    invalidated: set[str],
) -> None:
    """Apply a row/column insert/delete operation.

    For structural operations, all formulas whose reference set was touched
    report recalculation_required.
    """
    # Structural operations can migrate cross-sheet references, so every formula is stale.
    for ref_key in formula_cells:
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


def _invalid_edit(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
