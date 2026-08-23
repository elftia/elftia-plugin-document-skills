"""Cell, formula, and cached-value mapping for SpreadsheetML structured read."""

import re
from typing import Any

from .constants import NS, qn
from .formula_state import (
    derive_read_state,
    parse_formula_references,
    build_formula_cell_state,
)
from .shared_strings import read_shared_strings
from .styles import read_styles, resolve_style_index

_MAIN_NS = NS["main"]
_COL_ROW_RE = re.compile(r"^([A-Z]+)(\d+)$")


def col_to_num(col: str) -> int:
    result = 0
    for char in col.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def num_to_col(num: int) -> str:
    result = ""
    while num > 0:
        num, rem = divmod(num - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def parse_ref(ref: str) -> tuple[str, int] | None:
    match = _COL_ROW_RE.match(ref.upper().replace("$", ""))
    if not match:
        return None
    return match.group(1), int(match.group(2))


def map_workbook(package: Any) -> dict[str, Any]:
    """Map an entire workbook into a structured representation.

    Returns a dict with: sheets, defined_names, shared_strings_count, formula_state.
    """
    parts = package.parts
    shared = read_shared_strings(parts)
    styles = read_styles(parts)
    workbook_root = package.xml("xl/workbook.xml")
    sheets = _map_sheets(package, workbook_root, shared, styles)
    defined_names = _map_defined_names(workbook_root)
    formula_cells = _collect_formula_cells(sheets)
    full_calc = _detect_full_calc_on_load(workbook_root)
    return {
        "sheets": sheets,
        "defined_names": defined_names,
        "shared_strings_count": len(shared),
        "shared_strings_unique_count": len(shared),
        "full_calc_on_load": full_calc,
        "formula_cells": formula_cells,
    }


def _map_sheets(
    package: Any,
    workbook_root: Any,
    shared: list[str],
    styles: dict[str, Any],
) -> list[dict[str, Any]]:
    sheets_elem = workbook_root.find(f"{{{_MAIN_NS}}}sheets")
    if sheets_elem is None:
        return []
    result: list[dict[str, Any]] = []
    sheet_rels = {
        r.relationship_id: r
        for r in package.relationships
        if r.source_part == "xl/workbook.xml"
    }
    for idx, sheet_elem in enumerate(sheets_elem.findall(f"{{{_MAIN_NS}}}sheet")):
        name = sheet_elem.attrib.get("name", f"Sheet{idx + 1}")
        rel_id = sheet_elem.attrib.get(f"{{{NS['r']}}}id", "")
        sheet_state = sheet_elem.attrib.get("state", "visible")
        rel = sheet_rels.get(rel_id)
        sheet_part = rel.resolved_target if rel else None
        sheet_data: dict[str, Any] = {
            "name": name,
            "part": sheet_part,
            "order": idx,
            "state": sheet_state,
            "rows": [],
            "columns": [],
            "dimension": "",
            "protection": False,
        }
        if sheet_part and sheet_part in package.parts:
            _fill_sheet_data(package, sheet_part, sheet_data, shared, styles)
        result.append(sheet_data)
    return result


def _fill_sheet_data(
    package: Any,
    sheet_part: str,
    sheet_data: dict[str, Any],
    shared: list[str],
    styles: dict[str, Any],
) -> None:
    root = package.xml(sheet_part)
    main_ns = _MAIN_NS
    # Dimension
    dim = root.find(f"{{{main_ns}}}dimension")
    if dim is not None:
        sheet_data["dimension"] = dim.attrib.get("ref", "")
    # Sheet protection
    sheet_data["protection"] = root.find(f"{{{main_ns}}}sheetProtection") is not None
    columns = _map_columns(root, styles)
    sheet_data["columns"] = columns
    # Rows and cells
    sheet_data_root = root.find(f"{{{main_ns}}}sheetData")
    if sheet_data_root is None:
        return
    rows: list[dict[str, Any]] = []
    for row_elem in sheet_data_root.findall(f"{{{main_ns}}}row"):
        row_ref = row_elem.attrib.get("r", "")
        row_style = int(row_elem.attrib.get("s", "0"))
        hidden = row_elem.attrib.get("hidden") == "1"
        height = row_elem.attrib.get("ht")
        cells: list[dict[str, Any]] = []
        for c_elem in row_elem.findall(f"{{{main_ns}}}c"):
            column_style = _column_style_index(columns, c_elem.attrib.get("r", ""))
            cell = _map_cell(
                c_elem,
                shared,
                styles,
                row_style_index=row_style,
                column_style_index=column_style,
            )
            cells.append(cell)
        rows.append({
            "ref": row_ref,
            "style_index": row_style,
            "style": resolve_style_index(styles, row_style),
            "hidden": hidden,
            "height": float(height) if height is not None else None,
            "cells": cells,
        })
    sheet_data["rows"] = rows


def _map_cell(
    c_elem: Any,
    shared: list[str],
    styles: dict[str, Any],
    *,
    row_style_index: int = 0,
    column_style_index: int = 0,
) -> dict[str, Any]:
    main_ns = _MAIN_NS
    ref = c_elem.attrib.get("r", "")
    cell_type = c_elem.attrib.get("t", "n")
    raw_style_index = int(c_elem.attrib.get("s", "0"))
    if "s" in c_elem.attrib:
        resolved_style_index = raw_style_index
        style_source = "cell"
    elif row_style_index:
        resolved_style_index = row_style_index
        style_source = "row"
    elif column_style_index:
        resolved_style_index = column_style_index
        style_source = "column"
    else:
        resolved_style_index = 0
        style_source = "default"
    formula_elem = c_elem.find(f"{{{main_ns}}}f")
    value_elem = c_elem.find(f"{{{main_ns}}}v")
    inline_str_elem = c_elem.find(f"{{{main_ns}}}is")
    formula_text = ""
    if formula_elem is not None:
        formula_text = formula_elem.text or ""
    has_cached_value = value_elem is not None
    cached_value = value_elem.text if value_elem is not None else None
    # Resolve value by type
    value: str | None = None
    if cell_type == "s" and value_elem is not None:
        idx = int(value_elem.text or "0")
        value = shared[idx] if 0 <= idx < len(shared) else None
    elif cell_type == "inlineStr" and inline_str_elem is not None:
        t = inline_str_elem.find(f"{{{main_ns}}}t")
        value = t.text if t is not None else None
    elif value_elem is not None:
        value = value_elem.text
    # Resolve style
    resolved_style = resolve_style_index(styles, resolved_style_index)
    cell_data: dict[str, Any] = {
        "ref": ref,
        "type": cell_type,
        "value": value,
        "style_index": raw_style_index,
        "resolved_style_index": resolved_style_index,
        "style_source": style_source,
        "style": resolved_style,
        "number_format": resolved_style.get("num_fmt_code", ""),
        "formula": formula_text if formula_text else None,
        "cached_value": cached_value,
    }
    # Formula state
    if formula_text:
        precedents = parse_formula_references(formula_text)
        state = derive_read_state(has_cached_value=has_cached_value)
        cell_data["formula_state"] = build_formula_cell_state(
            state=state,
            formula=formula_text,
            cached_value=cached_value,
            precedents_count=len(precedents),
            dependents_count=0,
        )
    return cell_data


def _map_columns(root: Any, styles: dict[str, Any]) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    container = root.find(f"{{{_MAIN_NS}}}cols")
    if container is None:
        return columns
    for column in container.findall(f"{{{_MAIN_NS}}}col"):
        first = int(column.attrib.get("min", "1"))
        last = int(column.attrib.get("max", str(first)))
        style_index = int(column.attrib.get("style", "0"))
        width = column.attrib.get("width")
        columns.append(
            {
                "min": first,
                "max": last,
                "ref": (
                    num_to_col(first)
                    if first == last
                    else f"{num_to_col(first)}:{num_to_col(last)}"
                ),
                "width": float(width) if width is not None else None,
                "hidden": column.attrib.get("hidden") == "1",
                "style_index": style_index,
                "style": resolve_style_index(styles, style_index),
            }
        )
    return columns


def _column_style_index(columns: list[dict[str, Any]], cell_ref: str) -> int:
    parsed = parse_ref(cell_ref)
    if parsed is None:
        return 0
    column_number = col_to_num(parsed[0])
    for column in columns:
        if column["min"] <= column_number <= column["max"]:
            return column["style_index"]
    return 0


def _map_defined_names(workbook_root: Any) -> list[dict[str, str]]:
    names_elem = workbook_root.find(f"{{{_MAIN_NS}}}definedNames")
    if names_elem is None:
        return []
    result: list[dict[str, str]] = []
    for dn in names_elem.findall(f"{{{_MAIN_NS}}}definedName"):
        result.append({
            "name": dn.attrib.get("name", ""),
            "ref": dn.text or "",
            "scope": dn.attrib.get("localSheetId", "workbook"),
        })
    return result


def _collect_formula_cells(sheets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collect all formula cells across all sheets into a flat map."""
    result: dict[str, dict[str, Any]] = {}
    for sheet in sheets:
        sheet_name = sheet["name"]
        for row in sheet.get("rows", []):
            for cell in row.get("cells", []):
                if cell.get("formula_state"):
                    ref_key = f"{sheet_name}!{cell['ref']}"
                    result[ref_key] = cell["formula_state"]
    return result


def _detect_full_calc_on_load(workbook_root: Any) -> bool:
    calc_pr = workbook_root.find(f"{{{_MAIN_NS}}}calcPr")
    if calc_pr is None:
        return False
    return calc_pr.attrib.get("fullCalcOnLoad") == "1"
