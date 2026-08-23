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
    parse_color,
    parse_column,
    parse_number_format_definition,
    parse_style,
)
from .structural_refs import has_external_workbook_reference

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
                "table_style",
                "validation",
                "priority",
                "rule",
                "chart",
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
            "table_add",
            "table_resize",
            "table_rename",
            "table_style",
            "table_delete",
            "data_validation_add",
            "data_validation_update",
            "data_validation_delete",
            "conditional_format_add",
            "conditional_format_update",
            "conditional_format_delete",
            "chart_add",
            "chart_update",
            "chart_delete",
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
            "table_rename",
            "table_style",
            "table_delete",
            "data_validation_add",
            "conditional_format_add",
            "chart_add",
            "chart_update",
            "chart_delete",
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
        table_style = edit.get("table_style")
        validation = edit.get("validation")
        priority = edit.get("priority")
        rule = edit.get("rule")
        chart = edit.get("chart")
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
        if edit_type in {
            "sheet_copy",
            "defined_name_add",
            "defined_name_update",
            "defined_name_delete",
            "table_add",
            "table_resize",
            "table_rename",
            "table_style",
            "table_delete",
            "chart_update",
            "chart_delete",
        }:
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
        if edit_type in {"table_add", "table_resize"}:
            _validate_cell_range(ref, f"edits.{index}.ref")
            bounds = _cell_range_bounds(ref)
            if bounds[1] == bounds[3]:
                _invalid(
                    "Table range must include a header and at least one data row.",
                    field=f"edits.{index}.ref",
                )
        if edit_type.startswith("table_"):
            _validate_defined_name(name, f"edits.{index}.name")
        if edit_type in {"table_add", "table_rename"}:
            _validate_defined_name(
                name if edit_type == "table_add" else cell_value,
                f"edits.{index}.{'name' if edit_type == 'table_add' else 'value'}",
            )
        if edit_type in {"table_add", "table_style"}:
            table_style = _text(
                "TableStyleMedium2" if table_style is None else table_style,
                f"edits.{index}.table_style",
                allow_empty=False,
            )
            _validate_table_style(table_style, f"edits.{index}.table_style")
        elif table_style is not None:
            _invalid(
                "table_style is only valid for table_add or table_style.",
                field=f"edits.{index}.table_style",
            )
        if edit_type in {"data_validation_add", "data_validation_update"}:
            validation = _parse_data_validation(
                validation,
                f"edits.{index}.validation",
            )
        elif validation is not None:
            _invalid(
                "validation is only valid for data-validation edits.",
                field=f"edits.{index}.validation",
            )
        if edit_type in {"data_validation_update", "data_validation_delete"}:
            _validate_cell_range(ref, f"edits.{index}.ref")
        if edit_type in {"conditional_format_add", "conditional_format_update"}:
            rule = _parse_conditional_format(rule, f"edits.{index}.rule")
        elif rule is not None:
            _invalid(
                "rule is only valid for conditional-format edits.",
                field=f"edits.{index}.rule",
            )
        if edit_type in {"conditional_format_update", "conditional_format_delete"}:
            _validate_cell_range(ref, f"edits.{index}.ref")
            priority = _integer(priority, 1, 65_535)
        elif priority is not None:
            _invalid(
                "priority is only valid for conditional-format update/delete selectors.",
                field=f"edits.{index}.priority",
            )
        if edit_type in {"chart_add", "chart_update"}:
            chart = _parse_chart(chart, f"edits.{index}.chart", known_sheets=None)
            if chart["sheet"] != sheet:
                _invalid(
                    "Chart edit sheet must match chart.sheet.",
                    field=f"edits.{index}.chart.sheet",
                )
        elif chart is not None:
            _invalid(
                "chart is only valid for chart add/update edits.",
                field=f"edits.{index}.chart",
            )
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
                "table_style": table_style,
                "validation": validation,
                "priority": priority,
                "rule": rule,
                "chart": chart,
            }
        )
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {"edits": parsed_edits, "expected_edits": expected}


def _parse_workbook(workbook: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        workbook,
        {
            "metadata",
            "sheets",
            "defined_names",
            "tables",
            "charts",
            "chart_reference",
            "page_setup",
        },
    )
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
        _exact_keys(
            sheet,
            {
                "name",
                "rows",
                "columns",
                "number_formats",
                "data_validations",
                "conditional_formats",
            },
        )
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
        data_validations = sheet.get("data_validations", [])
        if type(data_validations) is not list:
            _invalid(
                "data_validations must be an array.",
                field=f"sheets.{idx}.data_validations",
            )
        parsed_validations = []
        validation_ranges: list[tuple[int, int, int, int]] = []
        for validation_idx, validation in enumerate(data_validations):
            field = f"sheets.{idx}.data_validations.{validation_idx}"
            parsed_validation = _parse_data_validation(validation, field)
            bounds = _cell_range_bounds(parsed_validation["ref"])
            if any(_ranges_overlap(bounds, existing) for existing in validation_ranges):
                _invalid(
                    "Data-validation ranges cannot overlap in a create request.",
                    field=f"{field}.ref",
                )
            validation_ranges.append(bounds)
            parsed_validations.append(parsed_validation)
        conditional_formats = sheet.get("conditional_formats", [])
        if type(conditional_formats) is not list:
            _invalid(
                "conditional_formats must be an array.",
                field=f"sheets.{idx}.conditional_formats",
            )
        parsed_conditional_formats = []
        for rule_idx, rule in enumerate(conditional_formats):
            parsed_rule = _parse_conditional_format(
                rule,
                f"sheets.{idx}.conditional_formats.{rule_idx}",
            )
            parsed_rule["priority"] = rule_idx + 1
            parsed_conditional_formats.append(parsed_rule)
        parsed_sheets.append(
            {
                "name": name,
                "columns": parsed_columns,
                "rows": parsed_rows,
                "number_formats": parsed_formats,
                "data_validations": parsed_validations,
                "conditional_formats": parsed_conditional_formats,
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
    parsed_tables = []
    table_names: set[str] = set()
    table_ranges: dict[str, list[tuple[int, int, int, int]]] = {}
    parsed_sheet_map = {sheet["name"]: sheet for sheet in parsed_sheets}
    for tbl_idx, tbl in enumerate(tables):
        if type(tbl) is not dict:
            _invalid("table must be an object.", field=f"tables.{tbl_idx}")
        _exact_keys(tbl, {"name", "ref", "sheet", "style"})
        name = _text(tbl.get("name", ""), "table.name", allow_empty=False)
        ref = _text(tbl.get("ref", ""), "table.ref", allow_empty=False)
        sheet_name = _text(tbl.get("sheet", ""), "table.sheet", allow_empty=False)
        style = _text(tbl.get("style", "TableStyleMedium2"), "table.style")
        _validate_defined_name(name, f"tables.{tbl_idx}.name")
        if name.casefold() in table_names:
            _invalid("Table display names must be unique.", field=f"tables.{tbl_idx}.name")
        if sheet_name not in parsed_sheet_map:
            _invalid("Table sheet was not found.", field=f"tables.{tbl_idx}.sheet")
        _validate_cell_range(ref, f"tables.{tbl_idx}.ref")
        bounds = _cell_range_bounds(ref)
        if bounds[1] == bounds[3]:
            _invalid("Table range must include a header and at least one data row.", field=f"tables.{tbl_idx}.ref")
        if any(_ranges_overlap(bounds, existing) for existing in table_ranges.get(sheet_name, [])):
            _invalid("Native table ranges cannot overlap.", field=f"tables.{tbl_idx}.ref")
        _validate_table_style(style, f"tables.{tbl_idx}.style")
        headers = _table_headers(parsed_sheet_map[sheet_name], bounds, f"tables.{tbl_idx}.ref")
        table_names.add(name.casefold())
        table_ranges.setdefault(sheet_name, []).append(bounds)
        parsed_tables.append(
            {
                "name": name,
                "ref": _normalize_cell_range(ref),
                "sheet": sheet_name,
                "style": style,
                "columns": headers,
            }
        )
    charts = workbook.get("charts", [])
    if type(charts) is not list:
        _invalid("charts must be an array.", field="charts")
    parsed_charts = []
    chart_names: set[str] = set()
    known_sheets = set(parsed_sheet_map)
    for chart_idx, chart in enumerate(charts):
        parsed_chart = _parse_chart(
            chart,
            f"charts.{chart_idx}",
            known_sheets=known_sheets,
        )
        folded_name = parsed_chart["name"].casefold()
        if folded_name in chart_names:
            _invalid("Chart names must be unique.", field=f"charts.{chart_idx}.name")
        chart_names.add(folded_name)
        parsed_charts.append(parsed_chart)
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
        "charts": parsed_charts,
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


def _cell_range_bounds(ref: str) -> tuple[int, int, int, int]:
    first, separator, last = ref.partition(":")
    first_match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", first)
    last_match = re.fullmatch(
        r"\$?([A-Za-z]{1,3})\$?(\d+)",
        last if separator else first,
    )
    assert first_match is not None and last_match is not None
    return (
        _column_number(first_match.group(1)),
        int(first_match.group(2)),
        _column_number(last_match.group(1)),
        int(last_match.group(2)),
    )


def _ranges_overlap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _table_headers(
    sheet: dict[str, Any],
    bounds: tuple[int, int, int, int],
    field: str,
) -> list[str]:
    cells = {
        cell["ref"].replace("$", "").upper(): cell
        for row in sheet.get("rows", [])
        for cell in row.get("cells", [])
    }
    headers: list[str] = []
    for column in range(bounds[0], bounds[2] + 1):
        ref = f"{_column_name(column)}{bounds[1]}"
        cell = cells.get(ref)
        value = None if cell is None else cell.get("value")
        if (
            cell is None
            or cell.get("formula")
            or cell.get("type") not in {"s", "str", "inlineStr"}
            or not value
        ):
            _invalid("Every table column requires a non-empty text header cell.", field=field, cell=ref)
        if value.casefold() in {item.casefold() for item in headers}:
            _invalid("Table column headers must be unique.", field=field, cell=ref)
        headers.append(value)
    return headers


def _normalize_cell_range(ref: str) -> str:
    return ":".join(item.replace("$", "").upper() for item in ref.split(":"))


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


def _validate_table_style(value: str, field: str) -> None:
    if re.fullmatch(
        r"TableStyle(?:Light(?:[1-9]|1\d|2[01])|Medium(?:[1-9]|1\d|2[0-8])|Dark(?:[1-9]|1[01]))",
        value,
    ) is None:
        _invalid("Table style must be a supported built-in style.", field=field)


def _parse_data_validation(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Data validation must be an object.", field=field)
    _exact_keys(
        value,
        {
            "ref",
            "type",
            "operator",
            "formula1",
            "formula2",
            "allow_blank",
            "show_input_message",
            "show_error_message",
            "prompt_title",
            "prompt",
            "error_title",
            "error",
            "error_style",
        },
    )
    ref = _text(value.get("ref", ""), f"{field}.ref", allow_empty=False)
    _validate_cell_range(ref, f"{field}.ref")
    validation_type = _text(
        value.get("type", ""),
        f"{field}.type",
        allow_empty=False,
    )
    if validation_type not in {
        "list",
        "whole",
        "decimal",
        "date",
        "time",
        "textLength",
        "custom",
    }:
        _invalid("Data-validation type is not supported.", field=f"{field}.type")
    formula1 = _text(
        value.get("formula1", ""),
        f"{field}.formula1",
        allow_empty=False,
    )
    formula2 = _optional_text(value.get("formula2"), f"{field}.formula2")
    for formula_field, formula in (("formula1", formula1), ("formula2", formula2)):
        if formula is not None and has_external_workbook_reference(formula):
            _invalid(
                "Data-validation formulas do not accept external workbook references.",
                field=f"{field}.{formula_field}",
            )
    operator = value.get("operator")
    if validation_type in {"list", "custom"}:
        if operator is not None:
            _invalid(
                "list and custom data validations do not accept operator.",
                field=f"{field}.operator",
            )
        if formula2 is not None:
            _invalid(
                "list and custom data validations do not accept formula2.",
                field=f"{field}.formula2",
            )
    else:
        operator = _text(operator, f"{field}.operator", allow_empty=False)
        if operator not in {
            "between",
            "notBetween",
            "equal",
            "notEqual",
            "greaterThan",
            "lessThan",
            "greaterThanOrEqual",
            "lessThanOrEqual",
        }:
            _invalid(
                "Data-validation operator is not supported.",
                field=f"{field}.operator",
            )
        if operator in {"between", "notBetween"} and formula2 is None:
            _invalid(
                "between and notBetween data validations require formula2.",
                field=f"{field}.formula2",
            )
        if operator not in {"between", "notBetween"} and formula2 is not None:
            _invalid(
                "formula2 is only valid with between or notBetween.",
                field=f"{field}.formula2",
            )
    error_style = value.get("error_style", "stop")
    error_style = _text(error_style, f"{field}.error_style", allow_empty=False)
    if error_style not in {"stop", "warning", "information"}:
        _invalid("Data-validation error_style is not supported.", field=f"{field}.error_style")
    return {
        "ref": _normalize_cell_range(ref),
        "type": validation_type,
        "operator": operator,
        "formula1": formula1,
        "formula2": formula2,
        "allow_blank": _boolean(value.get("allow_blank", False), f"{field}.allow_blank"),
        "show_input_message": _boolean(
            value.get("show_input_message", False),
            f"{field}.show_input_message",
        ),
        "show_error_message": _boolean(
            value.get("show_error_message", False),
            f"{field}.show_error_message",
        ),
        "prompt_title": _optional_text(value.get("prompt_title"), f"{field}.prompt_title"),
        "prompt": _optional_text(value.get("prompt"), f"{field}.prompt"),
        "error_title": _optional_text(value.get("error_title"), f"{field}.error_title"),
        "error": _optional_text(value.get("error"), f"{field}.error"),
        "error_style": error_style,
    }


def _parse_conditional_format(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Conditional-format rule must be an object.", field=field)
    _exact_keys(
        value,
        {
            "ref",
            "type",
            "operator",
            "formulas",
            "style",
            "stop_if_true",
            "thresholds",
            "colors",
            "color",
            "show_value",
            "icon_set",
            "reverse",
        },
    )
    ref = _text(value.get("ref", ""), f"{field}.ref", allow_empty=False)
    _validate_cell_range(ref, f"{field}.ref")
    rule_type = _text(value.get("type", ""), f"{field}.type", allow_empty=False)
    if rule_type not in {"cellIs", "expression", "colorScale", "dataBar", "iconSet"}:
        _invalid("Conditional-format type is not supported.", field=f"{field}.type")
    formulas = value.get("formulas", [])
    if type(formulas) is not list:
        _invalid("Conditional-format formulas must be an array.", field=f"{field}.formulas")
    parsed_formulas = [
        _text(formula, f"{field}.formulas.{index}", allow_empty=False)
        for index, formula in enumerate(formulas)
    ]
    if any(has_external_workbook_reference(formula) for formula in parsed_formulas):
        _invalid(
            "Conditional-format formulas do not accept external workbook references.",
            field=f"{field}.formulas",
        )
    operator = value.get("operator")
    style = parse_style(value.get("style"), f"{field}.style")
    if style and set(style) - {"font", "fill", "border"}:
        _invalid(
            "Conditional-format differential styles support font, fill, and border.",
            field=f"{field}.style",
        )
    thresholds = value.get("thresholds", [])
    colors = value.get("colors", [])
    color = value.get("color")
    icon_set = value.get("icon_set")
    if rule_type == "cellIs":
        operator = _text(operator, f"{field}.operator", allow_empty=False)
        if operator not in {
            "between",
            "notBetween",
            "equal",
            "notEqual",
            "greaterThan",
            "lessThan",
            "greaterThanOrEqual",
            "lessThanOrEqual",
        }:
            _invalid("cellIs operator is not supported.", field=f"{field}.operator")
        expected_formulas = 2 if operator in {"between", "notBetween"} else 1
        if len(parsed_formulas) != expected_formulas:
            _invalid(
                "cellIs formula count does not match its operator.",
                field=f"{field}.formulas",
            )
        if not style:
            _invalid("cellIs requires a differential style.", field=f"{field}.style")
    elif rule_type == "expression":
        if operator is not None:
            _invalid("expression does not accept operator.", field=f"{field}.operator")
        if len(parsed_formulas) != 1:
            _invalid("expression requires exactly one formula.", field=f"{field}.formulas")
        if not style:
            _invalid("expression requires a differential style.", field=f"{field}.style")
    else:
        if operator is not None or parsed_formulas or style:
            _invalid(
                "Visual conditional formats do not accept operator, formulas, or style.",
                field=field,
            )
    parsed_thresholds: list[dict[str, Any]] = []
    if rule_type in {"colorScale", "dataBar", "iconSet"}:
        if type(thresholds) is not list:
            _invalid("thresholds must be an array.", field=f"{field}.thresholds")
        parsed_thresholds = [
            _parse_cf_threshold(item, f"{field}.thresholds.{index}")
            for index, item in enumerate(thresholds)
        ]
    elif thresholds:
        _invalid("thresholds are only valid for visual rules.", field=f"{field}.thresholds")
    parsed_colors: list[str] = []
    parsed_color = None
    parsed_icon_set = None
    if rule_type == "colorScale":
        if len(parsed_thresholds) not in {2, 3}:
            _invalid("colorScale requires two or three thresholds.", field=f"{field}.thresholds")
        if type(colors) is not list or len(colors) != len(parsed_thresholds):
            _invalid("colorScale colors must match threshold count.", field=f"{field}.colors")
        parsed_colors = [
            parse_color(item, f"{field}.colors.{index}")
            for index, item in enumerate(colors)
        ]
    elif colors:
        _invalid("colors is only valid for colorScale.", field=f"{field}.colors")
    if rule_type == "dataBar":
        if len(parsed_thresholds) != 2:
            _invalid("dataBar requires exactly two thresholds.", field=f"{field}.thresholds")
        parsed_color = parse_color(color, f"{field}.color")
    elif color is not None:
        _invalid("color is only valid for dataBar.", field=f"{field}.color")
    if rule_type == "iconSet":
        parsed_icon_set = _text(icon_set, f"{field}.icon_set", allow_empty=False)
        icon_counts = {
            "3Arrows": 3,
            "3ArrowsGray": 3,
            "3Flags": 3,
            "3TrafficLights1": 3,
            "3TrafficLights2": 3,
            "3Signs": 3,
            "3Symbols": 3,
            "3Symbols2": 3,
            "4Arrows": 4,
            "4ArrowsGray": 4,
            "4RedToBlack": 4,
            "4Rating": 4,
            "4TrafficLights": 4,
            "5Arrows": 5,
            "5ArrowsGray": 5,
            "5Rating": 5,
            "5Quarters": 5,
        }
        if parsed_icon_set not in icon_counts:
            _invalid("icon_set is not supported.", field=f"{field}.icon_set")
        if len(parsed_thresholds) != icon_counts[parsed_icon_set]:
            _invalid(
                "iconSet threshold count does not match the selected icon set.",
                field=f"{field}.thresholds",
            )
    elif icon_set is not None:
        _invalid("icon_set is only valid for iconSet.", field=f"{field}.icon_set")
    return {
        "ref": _normalize_cell_range(ref),
        "type": rule_type,
        "operator": operator,
        "formulas": parsed_formulas,
        "style": style,
        "stop_if_true": _boolean(
            value.get("stop_if_true", False),
            f"{field}.stop_if_true",
        ),
        "thresholds": parsed_thresholds,
        "colors": parsed_colors,
        "color": parsed_color,
        "show_value": _boolean(value.get("show_value", True), f"{field}.show_value"),
        "icon_set": parsed_icon_set,
        "reverse": _boolean(value.get("reverse", False), f"{field}.reverse"),
    }


def _parse_cf_threshold(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Conditional-format threshold must be an object.", field=field)
    _exact_keys(value, {"type", "value", "gte"})
    threshold_type = _text(value.get("type", ""), f"{field}.type", allow_empty=False)
    if threshold_type not in {"min", "max", "num", "percent", "percentile", "formula"}:
        _invalid("Conditional-format threshold type is not supported.", field=f"{field}.type")
    threshold_value = value.get("value")
    if threshold_type in {"min", "max"}:
        if threshold_value is not None:
            _invalid("min/max thresholds do not accept value.", field=f"{field}.value")
    else:
        threshold_value = _text(threshold_value, f"{field}.value", allow_empty=False)
        if threshold_type == "formula" and has_external_workbook_reference(threshold_value):
            _invalid(
                "Conditional-format threshold formulas do not accept external references.",
                field=f"{field}.value",
            )
    return {
        "type": threshold_type,
        "value": threshold_value,
        "gte": _boolean(value.get("gte", True), f"{field}.gte"),
    }


def _parse_chart(
    value: Any,
    field: str,
    *,
    known_sheets: set[str] | None,
) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Chart must be an object.", field=field)
    _exact_keys(
        value,
        {
            "name",
            "sheet",
            "type",
            "title",
            "anchor",
            "series",
            "show_legend",
            "legend_position",
            "x_axis_title",
            "y_axis_title",
            "x_axis_number_format",
            "y_axis_number_format",
            "data_labels",
        },
    )
    name = _text(value.get("name", ""), f"{field}.name", allow_empty=False)
    sheet = _text(value.get("sheet", ""), f"{field}.sheet", allow_empty=False)
    if known_sheets is not None and sheet not in known_sheets:
        _invalid("Chart placement sheet was not found.", field=f"{field}.sheet")
    chart_type = _text(value.get("type", ""), f"{field}.type", allow_empty=False)
    if chart_type not in {"column", "bar", "line", "pie", "scatter"}:
        _invalid("Chart type is not supported.", field=f"{field}.type")
    anchor = _text(value.get("anchor", ""), f"{field}.anchor", allow_empty=False)
    _validate_cell_range(anchor, f"{field}.anchor")
    anchor_bounds = _cell_range_bounds(anchor)
    if anchor_bounds[0] == anchor_bounds[2] or anchor_bounds[1] == anchor_bounds[3]:
        _invalid(
            "Chart anchor must span at least two rows and two columns.",
            field=f"{field}.anchor",
        )
    series = value.get("series")
    if type(series) is not list or not series or len(series) > 50:
        _invalid("Chart series must be a non-empty bounded array.", field=f"{field}.series")
    parsed_series = [
        _parse_chart_series(
            item,
            f"{field}.series.{index}",
            chart_type=chart_type,
            known_sheets=known_sheets,
        )
        for index, item in enumerate(series)
    ]
    legend_position = _text(
        value.get("legend_position", "r"),
        f"{field}.legend_position",
        allow_empty=False,
    )
    if legend_position not in {"l", "r", "t", "b", "tr"}:
        _invalid("Chart legend position is not supported.", field=f"{field}.legend_position")
    data_labels = value.get("data_labels", {})
    if type(data_labels) is not dict:
        _invalid("Chart data_labels must be an object.", field=f"{field}.data_labels")
    _exact_keys(
        data_labels,
        {
            "show_value",
            "show_category_name",
            "show_series_name",
            "show_legend_key",
            "show_percentage",
        },
    )
    parsed_labels = {
        key: _boolean(data_labels.get(key, False), f"{field}.data_labels.{key}")
        for key in (
            "show_value",
            "show_category_name",
            "show_series_name",
            "show_legend_key",
            "show_percentage",
        )
    }
    axis_values = {
        key: _optional_text(value.get(key), f"{field}.{key}")
        for key in (
            "x_axis_title",
            "y_axis_title",
            "x_axis_number_format",
            "y_axis_number_format",
        )
    }
    if chart_type == "pie" and any(axis_values.values()):
        _invalid("Pie charts do not accept axis fields.", field=field)
    return {
        "name": name,
        "sheet": sheet,
        "type": chart_type,
        "title": _text(value.get("title", ""), f"{field}.title"),
        "anchor": _normalize_cell_range(anchor),
        "series": parsed_series,
        "show_legend": _boolean(value.get("show_legend", True), f"{field}.show_legend"),
        "legend_position": legend_position,
        **axis_values,
        "data_labels": parsed_labels,
    }


def _parse_chart_series(
    value: Any,
    field: str,
    *,
    chart_type: str,
    known_sheets: set[str] | None,
) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Chart series must be an object.", field=field)
    _exact_keys(value, {"name", "categories", "values", "x_values", "y_values", "color"})
    name = _text(value.get("name", ""), f"{field}.name", allow_empty=False)
    color = parse_color(value.get("color", "4472C4"), f"{field}.color")
    if chart_type == "scatter":
        if value.get("categories") is not None or value.get("values") is not None:
            _invalid("Scatter series use x_values and y_values.", field=field)
        x_values = _parse_chart_range(
            value.get("x_values"),
            f"{field}.x_values",
            known_sheets=known_sheets,
        )
        y_values = _parse_chart_range(
            value.get("y_values"),
            f"{field}.y_values",
            known_sheets=known_sheets,
        )
        if _chart_range_length(x_values) != _chart_range_length(y_values):
            _invalid("Scatter x/y ranges must have equal length.", field=field)
        return {
            "name": name,
            "categories": None,
            "values": None,
            "x_values": x_values,
            "y_values": y_values,
            "color": color,
        }
    if value.get("x_values") is not None or value.get("y_values") is not None:
        _invalid("Non-scatter series use categories and values.", field=field)
    categories = _parse_chart_range(
        value.get("categories"),
        f"{field}.categories",
        known_sheets=known_sheets,
    )
    values = _parse_chart_range(
        value.get("values"),
        f"{field}.values",
        known_sheets=known_sheets,
    )
    if _chart_range_length(categories) != _chart_range_length(values):
        _invalid("Chart category/value ranges must have equal length.", field=field)
    return {
        "name": name,
        "categories": categories,
        "values": values,
        "x_values": None,
        "y_values": None,
        "color": color,
    }


def _parse_chart_range(
    value: Any,
    field: str,
    *,
    known_sheets: set[str] | None,
) -> str:
    text = _text(value, field, allow_empty=False)
    if has_external_workbook_reference(text):
        _invalid("Chart ranges do not accept external workbooks.", field=field)
    match = re.fullmatch(
        r"(?:'(?P<quoted>(?:[^']|'')+)'|(?P<plain>[^!']+))!"
        r"(?P<range>\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)",
        text,
    )
    if match is None:
        _invalid("Chart range must include a sheet and use A1 notation.", field=field)
    sheet = (match.group("quoted") or match.group("plain")).replace("''", "'")
    if known_sheets is not None and sheet not in known_sheets:
        _invalid("Chart data sheet was not found.", field=field, sheet=sheet)
    cell_range = match.group("range")
    _validate_cell_range(cell_range, field)
    bounds = _cell_range_bounds(cell_range)
    if bounds[0] != bounds[2] and bounds[1] != bounds[3]:
        _invalid("Chart data range must be one-dimensional.", field=field)
    absolute = ":".join(_absolute_cell(item) for item in cell_range.split(":"))
    return f"'{sheet.replace(chr(39), chr(39) * 2)}'!{absolute}"


def _chart_range_length(value: str) -> int:
    cell_range = value.rsplit("!", 1)[1]
    first_col, first_row, last_col, last_row = _cell_range_bounds(cell_range)
    return max(last_col - first_col, last_row - first_row) + 1


def _absolute_cell(ref: str) -> str:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    assert match is not None
    return f"${match.group(1).upper()}${match.group(2)}"


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
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
