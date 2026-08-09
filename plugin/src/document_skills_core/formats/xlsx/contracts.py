"""Strict bounded argument contracts for the four Core XLSX operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import MAX_ARGUMENT_TEXT, MAX_EDIT_OPS, MAX_SHEETS

XLSX_OPERATIONS = frozenset(
    {
        "xlsx.read",
        "xlsx.inspect.structure",
        "xlsx.create",
        "xlsx.edit",
    }
)


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
    for index, edit in enumerate(edits):
        if type(edit) is not dict:
            _invalid("Each edit must be an object.", field=f"edits.{index}")
        _exact_keys(edit, {"sheet", "type", "ref", "value", "style"})
        sheet = _text(edit.get("sheet"), f"edits.{index}.sheet", allow_empty=False)
        edit_type = edit.get("type")
        if edit_type not in {"cell_value", "cell_formula", "row_insert", "row_delete", "column_insert", "column_delete", "sheet_rename"}:
            _invalid("Unknown edit type.", field=f"edits.{index}.type")
        ref = _text(edit.get("ref", ""), f"edits.{index}.ref", allow_empty=False)
        cell_value = _optional_text(edit.get("value"), f"edits.{index}.value")
        style = edit.get("style")
        if style is not None and type(style) is not dict:
            _invalid("Style must be an object.", field=f"edits.{index}.style")
        parsed_edits.append(
            {"sheet": sheet, "type": edit_type, "ref": ref, "value": cell_value, "style": style}
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
    for idx, sheet in enumerate(sheets):
        if type(sheet) is not dict:
            _invalid(f"Sheet {idx} must be an object.", field=f"sheets.{idx}")
        _exact_keys(sheet, {"name", "rows", "number_formats"})
        name = _text(sheet.get("name", f"Sheet{idx + 1}"), f"sheets.{idx}.name", allow_empty=False)
        rows = sheet.get("rows", [])
        if type(rows) is not list:
            _invalid(f"Sheet {idx} rows must be an array.", field=f"sheets.{idx}.rows")
        parsed_rows = []
        for row_idx, row in enumerate(rows):
            if type(row) is not dict:
                _invalid(f"Row {row_idx} must be an object.", field=f"sheets.{idx}.rows.{row_idx}")
            _exact_keys(row, {"cells", "style"})
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
                cell_style = cell.get("style")
                if cell_style is not None and type(cell_style) is not dict:
                    _invalid("Cell style must be an object.", field="cell.style")
                parsed_cells.append(
                    {"ref": ref, "value": val, "formula": formula, "type": cell_type, "style": cell_style, "cached_value": cached}
                )
            row_style = row.get("style")
            if row_style is not None and type(row_style) is not dict:
                _invalid("Row style must be an object.", field=f"sheets.{idx}.rows.{row_idx}.style")
            parsed_rows.append({"cells": parsed_cells, "style": row_style})
        number_formats = sheet.get("number_formats", [])
        if type(number_formats) is not list:
            _invalid("number_formats must be an array.", field=f"sheets.{idx}.number_formats")
        parsed_formats = []
        for nf_idx, nf in enumerate(number_formats):
            if type(nf) is not dict:
                _invalid("number_format must be an object.", field=f"sheets.{idx}.number_formats.{nf_idx}")
            _exact_keys(nf, {"id", "code"})
            parsed_formats.append(
                {"id": _integer(nf.get("id"), 0, 500), "code": _text(nf.get("code", ""), "number_format.code")}
            )
        parsed_sheets.append(
            {"name": name, "rows": parsed_rows, "number_formats": parsed_formats}
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


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


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
