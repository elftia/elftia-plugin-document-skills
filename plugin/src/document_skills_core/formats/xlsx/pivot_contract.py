"""Bounded typed contract for native ``xlsx.pivot.create`` requests."""

from __future__ import annotations

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})")
_NAME = re.compile(r"[A-Za-z_\\][A-Za-z0-9_.\\]*")
_PIVOT_STYLE = re.compile(r"PivotStyle(?:Light|Medium|Dark)(?:[1-9]|1\d|2[0-8])")
_VALUE_FUNCTIONS = frozenset({"sum", "average", "min", "max", "count"})


def parse_pivot_arguments(value: dict[str, Any]) -> dict[str, Any]:
    """Parse the deliberately narrow first native-pivot authoring contract."""

    _exact_keys(
        value,
        {
            "source",
            "rows",
            "columns",
            "values",
            "filters",
            "target",
            "formula_policy",
            "numeric_policy",
            "recalculation",
            "keep_vba",
            "limits",
        },
    )
    source = _object(value.get("source"), "source")
    _exact_nested_keys(source, {"sheet", "range"}, "source")
    source_sheet = _sheet_name(source.get("sheet"), "source.sheet")
    source_range = _cell_range(source.get("range"), "source.range")

    rows = _axes(value.get("rows"), "rows", minimum=1, maximum=1)
    columns = _axes(value.get("columns", []), "columns", minimum=0, maximum=1)
    values = _values(value.get("values"))
    filters = _filters(value.get("filters", []))
    selected = [
        *(item["column"] for item in rows),
        *(item["column"] for item in columns),
        *(item["column"] for item in values),
        *(item["column"] for item in filters),
    ]
    if len({item.casefold() for item in selected}) != len(selected):
        _invalid("Pivot row, column, value, and filter fields must be distinct.")

    target = _object(value.get("target", {}), "target")
    _exact_nested_keys(target, {"sheet", "start_cell", "name", "style"}, "target")
    target_sheet = _sheet_name(target.get("sheet", "Pivot"), "target.sheet")
    start_cell = _cell_ref(target.get("start_cell", "A1"), "target.start_cell")
    name = _defined_name(target.get("name", "PivotTable1"), "target.name")
    style = _text(target.get("style", "PivotStyleMedium9"), "target.style", 64)
    if _PIVOT_STYLE.fullmatch(style) is None:
        _invalid("target.style must be a supported built-in pivot style.", field="target.style")

    formula_policy = _choice(
        value.get("formula_policy", "reject"),
        {"reject", "cached"},
        "formula_policy",
    )
    numeric_policy = _choice(
        value.get("numeric_policy", "strict"),
        {"strict", "coerce-text"},
        "numeric_policy",
    )
    recalculation = _choice(value.get("recalculation", "skip"), {"skip"}, "recalculation")
    keep_vba = value.get("keep_vba", False)
    if type(keep_vba) is not bool:
        _invalid("keep_vba must be boolean.", field="keep_vba")

    limits = _object(value.get("limits", {}), "limits")
    _exact_nested_keys(
        limits,
        {"max_source_rows", "max_source_columns", "max_axis_items", "max_output_cells"},
        "limits",
    )
    parsed_limits = {
        "max_source_rows": _integer(
            limits.get("max_source_rows", 100_000), 1, 1_048_575, "limits.max_source_rows"
        ),
        "max_source_columns": _integer(
            limits.get("max_source_columns", 256), 1, 16_384, "limits.max_source_columns"
        ),
        "max_axis_items": _integer(
            limits.get("max_axis_items", 1_000), 1, 10_000, "limits.max_axis_items"
        ),
        "max_output_cells": _integer(
            limits.get("max_output_cells", 100_000), 1, 250_000, "limits.max_output_cells"
        ),
    }
    return {
        "source": {"sheet": source_sheet, "range": source_range},
        "rows": rows,
        "columns": columns,
        "values": values,
        "filters": filters,
        "target": {
            "sheet": target_sheet,
            "start_cell": start_cell,
            "name": name,
            "style": style,
        },
        "formula_policy": formula_policy,
        "numeric_policy": numeric_policy,
        "recalculation": recalculation,
        "keep_vba": keep_vba,
        "limits": parsed_limits,
    }


def _axes(value: Any, field: str, *, minimum: int, maximum: int) -> list[dict[str, str]]:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _invalid(f"{field} must contain between {minimum} and {maximum} fields.", field=field)
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        item_field = f"{field}.{index}"
        item = _object(item, item_field)
        _exact_nested_keys(item, {"column", "sort"}, item_field)
        result.append(
            {
                "column": _text(item.get("column"), f"{item_field}.column", 255),
                "sort": _choice(item.get("sort", "asc"), {"asc", "desc"}, f"{item_field}.sort"),
            }
        )
    return result


def _values(value: Any) -> list[dict[str, str]]:
    if type(value) is not list or len(value) != 1:
        _invalid("values must contain exactly one data field.", field="values")
    item = _object(value[0], "values.0")
    _exact_nested_keys(item, {"column", "function", "as"}, "values.0")
    return [
        {
            "column": _text(item.get("column"), "values.0.column", 255),
            "function": _choice(item.get("function"), _VALUE_FUNCTIONS, "values.0.function"),
            "as": _text(item.get("as"), "values.0.as", 255),
        }
    ]


def _filters(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > 1:
        _invalid("filters must contain at most one page field.", field="filters")
    if not value:
        return []
    item = _object(value[0], "filters.0")
    _exact_nested_keys(item, {"column", "value"}, "filters.0")
    selected = item.get("value")
    if selected is not None and type(selected) not in {str, int, float, bool}:
        _invalid("Filter value must be a JSON scalar or null.", field="filters.0.value")
    return [
        {
            "column": _text(item.get("column"), "filters.0.column", 255),
            "value": selected,
        }
    ]


def _cell_range(value: Any, field: str) -> str:
    text = _text(value, field, 32)
    first, separator, last = text.partition(":")
    first_ref = _cell_ref(first, field)
    last_ref = _cell_ref(last if separator else first, field)
    first_bounds = _cell_bounds(first_ref)
    last_bounds = _cell_bounds(last_ref)
    if first_bounds[0] > last_bounds[0] or first_bounds[1] >= last_bounds[1]:
        _invalid("Pivot source range must be ascending and include a header plus data rows.", field=field)
    return f"{first_ref}:{last_ref}"


def _cell_ref(value: Any, field: str) -> str:
    text = _text(value, field, 16).replace("$", "").upper()
    match = _CELL.fullmatch(text)
    if match is None or _column_number(match.group(1)) > 16_384 or int(match.group(2)) > 1_048_576:
        _invalid("Cell reference must be in-bounds A1 notation.", field=field)
    return text


def _cell_bounds(value: str) -> tuple[int, int]:
    match = _CELL.fullmatch(value)
    assert match is not None
    return _column_number(match.group(1)), int(match.group(2))


def _sheet_name(value: Any, field: str) -> str:
    text = _text(value, field, 31)
    if any(character in text for character in "[]:*?/\\") or text.startswith("'") or text.endswith("'"):
        _invalid("Worksheet name is invalid.", field=field)
    return text


def _defined_name(value: Any, field: str) -> str:
    text = _text(value, field, 255)
    if _NAME.fullmatch(text) is None or re.fullmatch(r"[A-Za-z]{1,3}\d+", text):
        _invalid("Pivot name is invalid.", field=field)
    return text


def _column_number(value: str) -> int:
    result = 0
    for character in value.upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Value must be an object.", field=field)
    return value


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _text(value: Any, field: str, maximum: int) -> str:
    if type(value) is not str or not value:
        _invalid("Value must be a non-empty string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > maximum:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _choice(value: Any, choices: set[str] | frozenset[str], field: str) -> str:
    if type(value) is not str or value not in choices:
        _invalid("Value is not an accepted enum member.", field=field, accepted=sorted(choices))
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    _exact_nested_keys(value, allowed, "arguments")


def _exact_nested_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown XLSX pivot argument.", field=field, unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
