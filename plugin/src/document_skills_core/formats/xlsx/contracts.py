"""Strict bounded argument contracts for the four Core XLSX operations."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import MAX_ARGUMENT_TEXT, MAX_EDIT_OPS, MAX_SHEETS
from .style_contract import (
    custom_number_format_id,
    parse_column,
    parse_number_format_definition,
    parse_style,
)

XLSX_OPERATIONS = frozenset(
    {
        "xlsx.read",
        "xlsx.inspect.structure",
        "xlsx.create",
        "xlsx.edit",
    }
)

_STRUCTURAL_EDIT_TYPES = {
    "row_insert",
    "row_delete",
    "column_insert",
    "column_delete",
}
_WORKSHEET_EDIT_TYPES = {
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
    "print_area",
    "print_area_clear",
    "row_page_break",
    "column_page_break",
    "defined_name_add",
    "defined_name_update",
    "defined_name_delete",
}
_SHEET_EDIT_TYPES = {
    "sheet_add",
    "sheet_delete",
    "sheet_copy",
    "sheet_reorder",
    "sheet_rename",
}


@dataclass(frozen=True)
class ParsedXlsxRequest:
    operation: str
    input_path: Path | None
    output_path: Path | None
    arguments: dict[str, Any]
    requested_fidelity: str


def parse_xlsx_request(request: dict[str, Any]) -> ParsedXlsxRequest:
    operation = request.get("operation")
    if operation not in XLSX_OPERATIONS:
        _invalid("The operation is not a Core XLSX operation.", field="operation")
    arguments = request.get("arguments", {})
    if type(arguments) is not dict:
        _invalid("XLSX arguments must be an object.", field="arguments")
    input_path = _optional_path(request.get("input"), "input")
    output_path = _optional_path(request.get("output"), "output")
    options = request.get("options", {})
    fidelity = options.get("fidelity", "core") if type(options) is dict else "core"
    in_place = options.get("in_place", False) if type(options) is dict else False
    if operation in {"xlsx.read", "xlsx.inspect.structure"}:
        if input_path is None:
            _invalid("This XLSX operation requires an input path.", field="input")
        if output_path is not None:
            _invalid("Read-only XLSX operations do not accept output.", field="output")
    elif operation == "xlsx.create":
        if output_path is None:
            _invalid("XLSX creation requires an explicit output path.", field="output")
        if input_path is not None:
            _invalid("XLSX creation does not accept input.", field="input")
    elif input_path is None or output_path is None:
        _invalid("XLSX mutation requires distinct input and output paths.")
    if input_path is not None and input_path.suffix.casefold() != ".xlsx":
        _invalid("XLSX input path must use the .xlsx extension.", field="input")
    if output_path is not None and output_path.suffix.casefold() != ".xlsx":
        _invalid("XLSX output path must use the .xlsx extension.", field="output")
    if operation in {"xlsx.edit"}:
        assert input_path is not None and output_path is not None
        if in_place or same_path(input_path, output_path):
            raise DocumentSkillsError(
                ErrorCode.OUTPUT_EQUALS_INPUT,
                "Core XLSX mutations require a distinct output and do not support in-place mode.",
                status="invalid_request",
            )
    elif in_place:
        _invalid("in_place is not meaningful for this XLSX operation.", field="options.in_place")
    parsed = {
        "xlsx.read": _parse_read,
        "xlsx.inspect.structure": _parse_inspect,
        "xlsx.create": _parse_create,
        "xlsx.edit": _parse_edit,
    }[operation](arguments)
    return ParsedXlsxRequest(operation, input_path, output_path, parsed, fidelity)


def _parse_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_formulas", "max_rows", "max_cells_per_sheet", "sheet"})
    return {
        "include_formulas": _boolean(value.get("include_formulas", True), "include_formulas"),
        "max_rows": _integer(value.get("max_rows", 5_000), 1, 10_000),
        "max_cells_per_sheet": _integer(
            value.get("max_cells_per_sheet", 10_000), 1, 100_000
        ),
        "sheet": _optional_text(value.get("sheet"), "sheet"),
    }


def _parse_inspect(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_hashes", "max_parts", "max_relationships"})
    return {
        "include_hashes": _boolean(value.get("include_hashes", True), "include_hashes"),
        "max_parts": _integer(value.get("max_parts", 2_000), 1, 5_000),
        "max_relationships": _integer(
            value.get("max_relationships", 5_000), 1, 10_000
        ),
    }


def _parse_create(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"workbook"})
    workbook = value.get("workbook")
    if type(workbook) is not dict:
        _invalid("create requires a workbook object.", field="workbook")
    wb = _parse_workbook(workbook)
    return {"workbook": wb}


def _parse_edit(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"edits", "expected_edits"})
    edits = value.get("edits")
    if type(edits) is not list or not edits or len(edits) > MAX_EDIT_OPS:
        _invalid("edits must be a non-empty bounded array.", field="edits")
    parsed_edits = []
    defined_name_targets: set[tuple[str, str, str]] = set()
    for index, edit in enumerate(edits):
        if type(edit) is not dict:
            _invalid("Each edit must be an object.", field=f"edits.{index}")
        _exact_keys(
            edit,
            {
                "sheet",
                "type",
                "ref",
                "value",
                "style",
                "count",
                "height",
                "width",
                "hidden",
                "position",
                "name",
                "scope",
                "clear",
                "enabled",
            },
        )
        sheet = _text(edit.get("sheet"), f"edits.{index}.sheet", allow_empty=False)
        edit_type = edit.get("type")
        if edit_type not in {
            "cell_value",
            "cell_formula",
            "cell_style",
            "row_style",
            "column_style",
            "row_insert",
            "row_delete",
            "column_insert",
            "column_delete",
            *_WORKSHEET_EDIT_TYPES,
            *_SHEET_EDIT_TYPES,
        }:
            _invalid("Unknown edit type.", field=f"edits.{index}.type")
        ref_optional = edit_type in {
            "sheet_add",
            "sheet_delete",
            "sheet_copy",
            "sheet_reorder",
            "sheet_rename",
            "auto_filter_clear",
            "print_area_clear",
            "defined_name_delete",
        }
        ref = _text(
            edit.get("ref", ""),
            f"edits.{index}.ref",
            allow_empty=ref_optional,
        )
        count = edit.get("count")
        if edit_type in {"row_insert", "row_delete"}:
            _validate_structural_ref(ref, "row", f"edits.{index}.ref")
            count = _integer(1 if count is None else count, 1, 10_000)
            if int(ref) + count - 1 > 1_048_576:
                _invalid("Row structural edit exceeds the XLSX range.", field=f"edits.{index}.count")
        elif edit_type in {"column_insert", "column_delete"}:
            _validate_structural_ref(ref, "column", f"edits.{index}.ref")
            count = _integer(1 if count is None else count, 1, 1_024)
            if _column_number(ref) + count - 1 > 16_384:
                _invalid("Column structural edit exceeds the XLSX range.", field=f"edits.{index}.count")
        elif count is not None:
            _invalid("count is only valid for structural edits.", field=f"edits.{index}.count")
        cell_value = _optional_text(edit.get("value"), f"edits.{index}.value")
        style = parse_style(edit.get("style"), f"edits.{index}.style")
        if edit_type in {"cell_style", "row_style", "column_style"} and not style:
            _invalid(
                "Style edit requires a non-empty style object.",
                field=f"edits.{index}.style",
            )
        if edit_type == "sheet_rename" and style:
            _invalid(
                "sheet_rename does not accept style.",
                field=f"edits.{index}.style",
            )
        height = edit.get("height")
        width = edit.get("width")
        hidden = edit.get("hidden")
        position = edit.get("position")
        name = edit.get("name")
        scope = edit.get("scope")
        clear = edit.get("clear")
        enabled = edit.get("enabled")
        if edit_type == "row_height":
            _validate_index_range(ref, "row", f"edits.{index}.ref")
            height = _number(height, 0, 409, f"edits.{index}.height")
        elif height is not None:
            _invalid("height is only valid for row_height.", field=f"edits.{index}.height")
        if edit_type == "column_width":
            _validate_index_range(ref, "column", f"edits.{index}.ref")
            width = _number(width, 0, 255, f"edits.{index}.width")
        elif width is not None:
            _invalid("width is only valid for column_width.", field=f"edits.{index}.width")
        if edit_type in {"row_hidden", "column_hidden"}:
            _validate_index_range(
                ref,
                "row" if edit_type.startswith("row") else "column",
                f"edits.{index}.ref",
            )
            hidden = _boolean(hidden, f"edits.{index}.hidden")
        elif hidden is not None:
            _invalid("hidden is only valid for row_hidden or column_hidden.", field=f"edits.{index}.hidden")
        if edit_type in {"cells_merge", "cells_unmerge", "range_clear", "auto_filter", "print_area"}:
            _validate_cell_range(ref, f"edits.{index}.ref")
        elif edit_type == "freeze_panes":
            _validate_cell_ref(ref, f"edits.{index}.ref")
        elif edit_type == "row_page_break":
            _validate_structural_ref(ref, "row", f"edits.{index}.ref")
        elif edit_type == "column_page_break":
            _validate_structural_ref(ref, "column", f"edits.{index}.ref")
        if edit_type == "range_clear":
            clear = "contents" if clear is None else clear
            if clear not in {"contents", "styles", "all"}:
                _invalid("range_clear clear must be contents, styles, or all.", field=f"edits.{index}.clear")
        elif clear is not None:
            _invalid("clear is only valid for range_clear.", field=f"edits.{index}.clear")
        if edit_type in {"row_page_break", "column_page_break"}:
            enabled = _boolean(True if enabled is None else enabled, f"edits.{index}.enabled")
        elif enabled is not None:
            _invalid("enabled is only valid for page-break edits.", field=f"edits.{index}.enabled")
        if edit_type in {"sheet_add", "sheet_copy", "sheet_reorder"}:
            position = _integer(
                MAX_SHEETS - 1 if position is None else position,
                0,
                MAX_SHEETS - 1,
            )
        elif position is not None:
            _invalid("position is only valid for sheet edits.", field=f"edits.{index}.position")
        if edit_type in {"sheet_copy", "defined_name_add", "defined_name_update", "defined_name_delete"}:
            name = _text(name, f"edits.{index}.name", allow_empty=False)
        elif name is not None:
            _invalid("name is not valid for this edit type.", field=f"edits.{index}.name")
        if edit_type in {"defined_name_add", "defined_name_update", "defined_name_delete"}:
            scope = "workbook" if scope is None else scope
            if scope not in {"workbook", "sheet"}:
                _invalid("Defined-name scope must be workbook or sheet.", field=f"edits.{index}.scope")
            _validate_defined_name(name, f"edits.{index}.name")
            defined_name_target = (
                scope,
                sheet.casefold() if scope == "sheet" else "",
                name.casefold(),
            )
            if defined_name_target in defined_name_targets:
                _invalid(
                    "A request cannot mutate the same defined name more than once.",
                    field=f"edits.{index}.name",
                )
            defined_name_targets.add(defined_name_target)
        elif scope is not None:
            _invalid("scope is only valid for defined-name edits.", field=f"edits.{index}.scope")
        if edit_type == "sheet_add":
            _validate_sheet_name(sheet, f"edits.{index}.sheet")
        elif edit_type == "sheet_copy":
            _validate_sheet_name(name, f"edits.{index}.name")
        elif edit_type == "sheet_rename":
            _validate_sheet_name(cell_value, f"edits.{index}.value")
        parsed_edits.append(
            {
                "sheet": sheet,
                "type": edit_type,
                "ref": ref,
                "value": cell_value,
                "style": style,
                "count": count,
                "height": height,
                "width": width,
                "hidden": hidden,
                "position": position,
                "name": name,
                "scope": scope,
                "clear": clear,
                "enabled": enabled,
            }
        )
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {"edits": parsed_edits, "expected_edits": expected}


def _parse_workbook(workbook: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(workbook, {"metadata", "sheets", "defined_names", "tables", "chart_reference", "page_setup"})
    metadata = workbook.get("metadata")
    if type(metadata) is not dict:
        _invalid("workbook.metadata must be an object.", field="metadata")
    _exact_keys(metadata, {"title", "creator", "subject"})
    parsed_meta = {
        "title": _text(metadata.get("title", "Elftia Workbook"), "metadata.title"),
        "creator": _text(metadata.get("creator", "Elftia Document Skills"), "metadata.creator"),
        "subject": _text(metadata.get("subject", ""), "metadata.subject"),
    }
    sheets = workbook.get("sheets")
    if type(sheets) is not list or not sheets or len(sheets) > MAX_SHEETS:
        _invalid("workbook.sheets must be a non-empty bounded array.", field="sheets")
    parsed_sheets = []
    parsed_styles: list[dict[str, Any]] = []
    custom_formats: dict[int, str] = {}
    custom_format_codes: dict[str, int] = {}
    for idx, sheet in enumerate(sheets):
        if type(sheet) is not dict:
            _invalid(f"Sheet {idx} must be an object.", field=f"sheets.{idx}")
        _exact_keys(sheet, {"name", "rows", "columns", "number_formats"})
        name = _text(sheet.get("name", f"Sheet{idx + 1}"), f"sheets.{idx}.name", allow_empty=False)
        columns = sheet.get("columns", [])
        if type(columns) is not list:
            _invalid("Sheet columns must be an array.", field=f"sheets.{idx}.columns")
        parsed_columns = []
        occupied_columns: set[int] = set()
        for column_idx, column in enumerate(columns):
            parsed_column = parse_column(
                column,
                f"sheets.{idx}.columns.{column_idx}",
            )
            column_range = set(range(parsed_column["min"], parsed_column["max"] + 1))
            if occupied_columns.intersection(column_range):
                _invalid(
                    "Column definitions must not overlap.",
                    field=f"sheets.{idx}.columns.{column_idx}.ref",
                )
            occupied_columns.update(column_range)
            if parsed_column["style"]:
                parsed_styles.append(parsed_column["style"])
            parsed_columns.append(parsed_column)
        rows = sheet.get("rows", [])
        if type(rows) is not list:
            _invalid(f"Sheet {idx} rows must be an array.", field=f"sheets.{idx}.rows")
        parsed_rows = []
        for row_idx, row in enumerate(rows):
            if type(row) is not dict:
                _invalid(f"Row {row_idx} must be an object.", field=f"sheets.{idx}.rows.{row_idx}")
            _exact_keys(row, {"cells", "style", "height", "hidden"})
            cells = row.get("cells", [])
            if type(cells) is not list:
                _invalid(f"Row {row_idx} cells must be an array.", field=f"sheets.{idx}.rows.{row_idx}.cells")
            parsed_cells = []
            for cell_idx, cell in enumerate(cells):
                if type(cell) is not dict:
                    _invalid(f"Cell must be an object.", field=f"sheets.{idx}.rows.{row_idx}.cells.{cell_idx}")
                _exact_keys(cell, {"ref", "value", "formula", "type", "style", "cached_value"})
                ref = _text(cell.get("ref", ""), "cell.ref", allow_empty=False)
                cell_type = cell.get("type", "n")
                if cell_type not in {"n", "s", "str", "inlineStr", "b", "e"}:
                    _invalid("Invalid cell type.", field="cell.type")
                val = _optional_text(cell.get("value"), "cell.value")
                formula = _optional_text(cell.get("formula"), "cell.formula")
                cached = _optional_text(cell.get("cached_value"), "cell.cached_value")
                cell_style = parse_style(
                    cell.get("style"),
                    f"sheets.{idx}.rows.{row_idx}.cells.{cell_idx}.style",
                )
                if cell_style:
                    parsed_styles.append(cell_style)
                parsed_cells.append(
                    {"ref": ref, "value": val, "formula": formula, "type": cell_type, "style": cell_style, "cached_value": cached}
                )
            row_style = parse_style(
                row.get("style"),
                f"sheets.{idx}.rows.{row_idx}.style",
            )
            if row_style:
                parsed_styles.append(row_style)
            height = row.get("height")
            if height is not None:
                if type(height) not in {int, float} or not 0 <= height <= 409:
                    _invalid(
                        "Row height must be between 0 and 409 points.",
                        field=f"sheets.{idx}.rows.{row_idx}.height",
                    )
            hidden = _boolean(
                row.get("hidden", False),
                f"sheets.{idx}.rows.{row_idx}.hidden",
            )
            parsed_rows.append(
                {
                    "cells": parsed_cells,
                    "style": row_style,
                    "height": height,
                    "hidden": hidden,
                }
            )
        number_formats = sheet.get("number_formats", [])
        if type(number_formats) is not list:
            _invalid("number_formats must be an array.", field=f"sheets.{idx}.number_formats")
        parsed_formats = []
        for nf_idx, nf in enumerate(number_formats):
            parsed_format = parse_number_format_definition(
                nf,
                f"sheets.{idx}.number_formats.{nf_idx}",
            )
            format_id = parsed_format["id"]
            code = parsed_format["code"]
            if format_id in custom_formats and custom_formats[format_id] != code:
                _invalid(
                    "Custom number format id maps to multiple codes.",
                    field=f"sheets.{idx}.number_formats.{nf_idx}.id",
                )
            if code in custom_format_codes and custom_format_codes[code] != format_id:
                _invalid(
                    "Custom number format code maps to multiple ids.",
                    field=f"sheets.{idx}.number_formats.{nf_idx}.code",
                )
            custom_formats[format_id] = code
            custom_format_codes[code] = format_id
            parsed_formats.append(parsed_format)
        parsed_sheets.append(
            {
                "name": name,
                "columns": parsed_columns,
                "rows": parsed_rows,
                "number_formats": parsed_formats,
            }
        )
    for style in parsed_styles:
        format_id = custom_number_format_id(style)
        if format_id is not None and format_id not in custom_formats:
            _invalid(
                "Custom number format id must be declared in sheet.number_formats.",
                field="style.number_format.id",
                id=format_id,
            )
    defined_names = workbook.get("defined_names", [])
    if type(defined_names) is not list:
        _invalid("defined_names must be an array.", field="defined_names")
    parsed_dn = []
    for dn_idx, dn in enumerate(defined_names):
        if type(dn) is not dict:
            _invalid("defined_name must be an object.", field=f"defined_names.{dn_idx}")
        _exact_keys(dn, {"name", "ref", "scope"})
        parsed_dn.append(
            {
                "name": _text(dn.get("name", ""), "defined_name.name", allow_empty=False),
                "ref": _text(dn.get("ref", ""), "defined_name.ref", allow_empty=False),
                "scope": _text(dn.get("scope", "workbook"), "defined_name.scope"),
            }
        )
    tables = workbook.get("tables", [])
    if type(tables) is not list:
        _invalid("tables must be an array.", field="tables")
    if tables:
        _enhancement(
            "XLSX tables are not connected to a consumer-accepted package.",
            field="tables",
            capability="xlsx.table",
        )
    parsed_tables = []
    for tbl_idx, tbl in enumerate(tables):
        if type(tbl) is not dict:
            _invalid("table must be an object.", field=f"tables.{tbl_idx}")
        _exact_keys(tbl, {"name", "ref", "sheet", "style"})
        parsed_tables.append(
            {
                "name": _text(tbl.get("name", ""), "table.name", allow_empty=False),
                "ref": _text(tbl.get("ref", ""), "table.ref", allow_empty=False),
                "sheet": _text(tbl.get("sheet", ""), "table.sheet", allow_empty=False),
                "style": _text(tbl.get("style", "TableStyleMedium2"), "table.style"),
            }
        )
    chart_ref = workbook.get("chart_reference")
    if chart_ref is not None:
        if type(chart_ref) is not dict:
            _invalid("chart_reference must be an object.", field="chart_reference")
        _enhancement(
            "XLSX chart references are not connected to a consumer-accepted package.",
            field="chart_reference",
            capability="xlsx.chart",
        )
        _exact_keys(chart_ref, {"title", "data_ref", "sheet"})
        chart_ref = {
            "title": _text(chart_ref.get("title", ""), "chart_reference.title"),
            "data_ref": _text(chart_ref.get("data_ref", ""), "chart_reference.data_ref", allow_empty=False),
            "sheet": _text(chart_ref.get("sheet", ""), "chart_reference.sheet", allow_empty=False),
        }
    page_setup = workbook.get("page_setup")
    if page_setup is not None:
        if type(page_setup) is not dict:
            _invalid("page_setup must be an object.", field="page_setup")
        _enhancement(
            "XLSX page setup is not connected to worksheet output.",
            field="page_setup",
            capability="xlsx.page-setup",
        )
        _exact_keys(page_setup, {"orientation", "header", "footer"})
        page_setup = {
            "orientation": _text(page_setup.get("orientation", "portrait"), "page_setup.orientation"),
            "header": _text(page_setup.get("header", ""), "page_setup.header"),
            "footer": _text(page_setup.get("footer", ""), "page_setup.footer"),
        }
    return {
        "metadata": parsed_meta,
        "sheets": parsed_sheets,
        "defined_names": parsed_dn,
        "tables": parsed_tables,
        "chart_reference": chart_ref,
        "page_setup": page_setup,
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown XLSX operation argument.", unknown=unknown)


def _validate_structural_ref(ref: str, kind: str, field: str) -> None:
    pattern = r"\d+" if kind == "row" else r"[A-Za-z]{1,3}"
    if re.fullmatch(pattern, ref) is None:
        _invalid(f"{kind.title()} structural ref is invalid.", field=field)
    if kind == "row" and not 1 <= int(ref) <= 1_048_576:
        _invalid("Row structural ref is outside the XLSX range.", field=field)
    if kind == "column":
        number = _column_number(ref)
        if number > 16_384:
            _invalid("Column structural ref is outside the XLSX range.", field=field)


def _validate_index_range(ref: str, kind: str, field: str) -> None:
    parts = ref.split(":", 1)
    if len(parts) == 1:
        parts.append(parts[0])
    for part in parts:
        _validate_structural_ref(part, kind, field)
    first = int(parts[0]) if kind == "row" else _column_number(parts[0])
    last = int(parts[1]) if kind == "row" else _column_number(parts[1])
    if first > last:
        _invalid(f"{kind.title()} range must be ascending.", field=field)


def _validate_cell_ref(ref: str, field: str) -> None:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})", ref)
    if match is None:
        _invalid("Cell reference must use A1 notation.", field=field)
    if _column_number(match.group(1)) > 16_384 or int(match.group(2)) > 1_048_576:
        _invalid("Cell reference is outside the XLSX range.", field=field)


def _validate_cell_range(ref: str, field: str) -> None:
    parts = ref.split(":", 1)
    for part in parts:
        _validate_cell_ref(part, field)
    if len(parts) == 2:
        first = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", parts[0])
        last = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", parts[1])
        assert first is not None and last is not None
        if (
            _column_number(first.group(1)) > _column_number(last.group(1))
            or int(first.group(2)) > int(last.group(2))
        ):
            _invalid("Cell range must be ascending.", field=field)


def _validate_sheet_name(value: str | None, field: str) -> None:
    if value is None or len(value) > 31 or any(char in value for char in "[]:*?/\\"):
        _invalid("Sheet name is invalid.", field=field)
    if value.startswith("'") or value.endswith("'"):
        _invalid("Sheet name cannot begin or end with an apostrophe.", field=field)


def _validate_defined_name(value: str | None, field: str) -> None:
    if value is None or re.fullmatch(r"[A-Za-z_\\][A-Za-z0-9_.\\]*", value) is None:
        _invalid("Defined name is invalid.", field=field)
    if re.fullmatch(r"[A-Za-z]{1,3}\d+", value) is not None:
        _invalid("Defined name cannot be a cell reference.", field=field)


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


def _number(value: Any, minimum: float, maximum: float, field: str) -> float:
    if type(value) not in {int, float} or not minimum <= value <= maximum:
        _invalid(f"Number must be between {minimum} and {maximum}.", field=field)
    return float(value)


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
