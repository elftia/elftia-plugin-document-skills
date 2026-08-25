"""Bounded typed contract for ``xlsx.summary.aggregate``."""

from __future__ import annotations

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_AGGREGATE_FUNCTIONS = frozenset(
    {"sum", "average", "min", "max", "count", "count_nonblank", "count_distinct"}
)
_TABLE_STYLE = re.compile(
    r"TableStyle(?:Light(?:[1-9]|1\d|2[01])|Medium(?:[1-9]|1\d|2[0-8])|Dark(?:[1-9]|1[01]))"
)
_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})")
_NAME = re.compile(r"[A-Za-z_\\][A-Za-z0-9_.\\]*")


def parse_summary_arguments(value: dict[str, Any]) -> dict[str, Any]:
    """Parse the public ordinary-summary request without importing the main contract."""

    _exact_keys(
        value,
        {
            "source",
            "group_by",
            "aggregates",
            "sort",
            "top_n",
            "target",
            "formula_policy",
            "numeric_policy",
            "recalculation",
            "keep_vba",
            "limits",
        },
    )
    source = _object(value.get("source"), "source")
    _exact_keys(source, {"sheet", "range"})
    source_sheet = _sheet_name(source.get("sheet"), "source.sheet")
    source_range = source.get("range")
    if source_range is not None:
        source_range = _cell_range(source_range, "source.range")

    group_by = _text_array(value.get("group_by"), "group_by", 1, 8)
    aggregates = _aggregates(value.get("aggregates"))
    output_names = [*group_by, *(item["as"] for item in aggregates)]
    if len({item.casefold() for item in output_names}) != len(output_names):
        _invalid("Group and aggregate output names must be unique.", field="aggregates")

    sort = _sort(value.get("sort", []))
    top_n = value.get("top_n")
    if top_n is not None:
        top_n = _integer(top_n, 1, 10_000, "top_n")
        if not sort:
            _invalid("top_n requires at least one explicit sort key.", field="top_n")

    target = _object(value.get("target", {}), "target")
    _exact_keys(target, {"sheet", "start_cell", "table_name", "table_style"})
    target_sheet = _sheet_name(target.get("sheet", "Summary"), "target.sheet")
    start_cell = _cell_ref(target.get("start_cell", "A1"), "target.start_cell")
    table_name = _defined_name(
        target.get("table_name", "SummaryTable"),
        "target.table_name",
    )
    table_style = _text(
        target.get("table_style", "TableStyleMedium2"),
        "target.table_style",
        maximum=64,
    )
    if _TABLE_STYLE.fullmatch(table_style) is None:
        _invalid("target.table_style must be a supported built-in table style.")

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
    recalculation = _choice(
        value.get("recalculation", "skip"),
        {"skip"},
        "recalculation",
    )
    keep_vba = value.get("keep_vba", False)
    if type(keep_vba) is not bool:
        _invalid("keep_vba must be boolean.", field="keep_vba")

    limits = _object(value.get("limits", {}), "limits")
    _exact_keys(
        limits,
        {"max_source_rows", "max_source_columns", "max_groups", "max_output_cells"},
    )
    parsed_limits = {
        "max_source_rows": _integer(
            limits.get("max_source_rows", 100_000),
            1,
            1_048_575,
            "limits.max_source_rows",
        ),
        "max_source_columns": _integer(
            limits.get("max_source_columns", 256),
            1,
            16_384,
            "limits.max_source_columns",
        ),
        "max_groups": _integer(
            limits.get("max_groups", 1_000),
            1,
            10_000,
            "limits.max_groups",
        ),
        "max_output_cells": _integer(
            limits.get("max_output_cells", 100_000),
            1,
            250_000,
            "limits.max_output_cells",
        ),
    }
    return {
        "source": {"sheet": source_sheet, "range": source_range},
        "group_by": group_by,
        "aggregates": aggregates,
        "sort": sort,
        "top_n": top_n,
        "target": {
            "sheet": target_sheet,
            "start_cell": start_cell,
            "table_name": table_name,
            "table_style": table_style,
        },
        "formula_policy": formula_policy,
        "numeric_policy": numeric_policy,
        "recalculation": recalculation,
        "keep_vba": keep_vba,
        "limits": parsed_limits,
    }


def _aggregates(value: Any) -> list[dict[str, str | None]]:
    if type(value) is not list or not 1 <= len(value) <= 16:
        _invalid("aggregates must contain between 1 and 16 definitions.", field="aggregates")
    result: list[dict[str, str | None]] = []
    aliases: set[str] = set()
    for index, item in enumerate(value):
        field = f"aggregates.{index}"
        item = _object(item, field)
        _exact_keys(item, {"column", "function", "as"})
        function = _choice(item.get("function"), _AGGREGATE_FUNCTIONS, f"{field}.function")
        column = item.get("column")
        if function == "count":
            if column is not None:
                _invalid("count aggregates rows and does not accept column.", field=f"{field}.column")
        else:
            column = _text(column, f"{field}.column", maximum=255)
        alias = _text(item.get("as"), f"{field}.as", maximum=255)
        if alias.casefold() in aliases:
            _invalid("Aggregate aliases must be unique.", field=f"{field}.as")
        aliases.add(alias.casefold())
        result.append({"column": column, "function": function, "as": alias})
    return result


def _sort(value: Any) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > 8:
        _invalid("sort must be a bounded array.", field="sort")
    result: list[dict[str, str]] = []
    columns: set[str] = set()
    for index, item in enumerate(value):
        field = f"sort.{index}"
        item = _object(item, field)
        _exact_keys(item, {"column", "direction"})
        column = _text(item.get("column"), f"{field}.column", maximum=255)
        if column.casefold() in columns:
            _invalid("Sort columns must be unique.", field=f"{field}.column")
        columns.add(column.casefold())
        result.append(
            {
                "column": column,
                "direction": _choice(
                    item.get("direction", "asc"),
                    {"asc", "desc"},
                    f"{field}.direction",
                ),
            }
        )
    return result


def _text_array(value: Any, field: str, minimum: int, maximum: int) -> list[str]:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _invalid(f"{field} must contain between {minimum} and {maximum} names.", field=field)
    result = [_text(item, f"{field}.{index}", maximum=255) for index, item in enumerate(value)]
    if len({item.casefold() for item in result}) != len(result):
        _invalid(f"{field} names must be unique.", field=field)
    return result


def _cell_range(value: Any, field: str) -> str:
    text = _text(value, field, maximum=32)
    first, separator, last = text.partition(":")
    first_ref = _cell_ref(first, field)
    last_ref = _cell_ref(last if separator else first, field)
    first_bounds = _cell_bounds(first_ref)
    last_bounds = _cell_bounds(last_ref)
    if first_bounds[0] > last_bounds[0] or first_bounds[1] > last_bounds[1]:
        _invalid("Cell range must be ascending.", field=field)
    return first_ref if not separator else f"{first_ref}:{last_ref}"


def _cell_ref(value: Any, field: str) -> str:
    text = _text(value, field, maximum=16).replace("$", "").upper()
    match = _CELL.fullmatch(text)
    if match is None or _column_number(match.group(1)) > 16_384 or int(match.group(2)) > 1_048_576:
        _invalid("Cell reference must be in-bounds A1 notation.", field=field)
    return text


def _cell_bounds(value: str) -> tuple[int, int]:
    match = _CELL.fullmatch(value)
    assert match is not None
    return _column_number(match.group(1)), int(match.group(2))


def _sheet_name(value: Any, field: str) -> str:
    text = _text(value, field, maximum=31)
    if any(character in text for character in "[]:*?/\\") or text.startswith("'") or text.endswith("'"):
        _invalid("Worksheet name is invalid.", field=field)
    return text


def _defined_name(value: Any, field: str) -> str:
    text = _text(value, field, maximum=255)
    if _NAME.fullmatch(text) is None or re.fullmatch(r"[A-Za-z]{1,3}\d+", text):
        _invalid("Table name is invalid.", field=field)
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


def _text(value: Any, field: str, *, maximum: int) -> str:
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
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown XLSX summary argument.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
