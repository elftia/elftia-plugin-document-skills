"""Bounded typed contract for native worksheet sparklines."""

from __future__ import annotations

import math
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .structural_refs import has_external_workbook_reference
from .style_contract import parse_color

_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})")
_RANGE = re.compile(
    r"(?:'(?P<quoted>(?:[^']|'')+)'|(?P<plain>[^!']+))!"
    r"(?P<range>\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)"
)
_COLORS = {
    "color": "FF376092",
    "negative_color": "FFD00000",
    "axis_color": "FF000000",
    "marker_color": "FF376092",
    "first_color": "FF339966",
    "last_color": "FF339966",
    "high_color": "FF339966",
    "low_color": "FFD00000",
}


def parse_sparklines(
    value: Any,
    field: str,
    *,
    known_sheets: set[str] | None,
) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > 1_000:
        _invalid("sparklines must be a bounded array.", field=field)
    result = [
        parse_sparkline(item, f"{field}.{index}", known_sheets=known_sheets)
        for index, item in enumerate(value)
    ]
    locations = [item["location"].casefold() for item in result]
    if len(set(locations)) != len(locations):
        _invalid("Sparkline locations must be unique on a worksheet.", field=field)
    return result


def parse_sparkline(
    value: Any,
    field: str,
    *,
    known_sheets: set[str] | None,
) -> dict[str, Any]:
    item = _object(value, field)
    _exact_keys(
        item,
        {
            "location",
            "data",
            "type",
            "empty_cells",
            "markers",
            "high_point",
            "low_point",
            "first_point",
            "last_point",
            "negative_points",
            "right_to_left",
            "manual_min",
            "manual_max",
            *_COLORS,
        },
    )
    location = _cell_ref(item.get("location"), f"{field}.location")
    data = _data_range(item.get("data"), f"{field}.data", known_sheets)
    manual_min = _optional_number(item.get("manual_min"), f"{field}.manual_min")
    manual_max = _optional_number(item.get("manual_max"), f"{field}.manual_max")
    if manual_min is not None and manual_max is not None and manual_min >= manual_max:
        _invalid("manual_min must be less than manual_max.", field=field)
    result = {
        "location": location,
        "data": data,
        "type": _choice(
            item.get("type", "line"),
            {"line", "column", "win_loss"},
            f"{field}.type",
        ),
        "empty_cells": _choice(
            item.get("empty_cells", "gap"),
            {"gap", "zero", "connect"},
            f"{field}.empty_cells",
        ),
        "markers": _boolean(item.get("markers", False), f"{field}.markers"),
        "high_point": _boolean(item.get("high_point", False), f"{field}.high_point"),
        "low_point": _boolean(item.get("low_point", False), f"{field}.low_point"),
        "first_point": _boolean(item.get("first_point", False), f"{field}.first_point"),
        "last_point": _boolean(item.get("last_point", False), f"{field}.last_point"),
        "negative_points": _boolean(
            item.get("negative_points", False),
            f"{field}.negative_points",
        ),
        "right_to_left": _boolean(
            item.get("right_to_left", False),
            f"{field}.right_to_left",
        ),
        "manual_min": manual_min,
        "manual_max": manual_max,
    }
    for key, default in _COLORS.items():
        result[key] = parse_color(item.get(key, default), f"{field}.{key}")
    return result


def _data_range(value: Any, field: str, known_sheets: set[str] | None) -> str:
    text = _text(value, field)
    if has_external_workbook_reference(text):
        _invalid("Sparkline data does not accept external workbooks.", field=field)
    match = _RANGE.fullmatch(text)
    if match is None:
        _invalid("Sparkline data must include a sheet and use A1 notation.", field=field)
    sheet = (match.group("quoted") or match.group("plain")).replace("''", "'")
    if known_sheets is not None and sheet not in known_sheets:
        _invalid("Sparkline data sheet was not found.", field=field, sheet=sheet)
    first, separator, last = match.group("range").partition(":")
    first_bounds = _cell_bounds(first, field)
    last_bounds = _cell_bounds(last if separator else first, field)
    if first_bounds[0] > last_bounds[0] or first_bounds[1] > last_bounds[1]:
        _invalid("Sparkline data range must be ascending.", field=field)
    if first_bounds[0] != last_bounds[0] and first_bounds[1] != last_bounds[1]:
        _invalid("Sparkline data range must be one-dimensional.", field=field)
    length = max(last_bounds[0] - first_bounds[0], last_bounds[1] - first_bounds[1]) + 1
    if not 2 <= length <= 10_000:
        _invalid("Sparkline data must contain between 2 and 10000 cells.", field=field)
    normalized = _absolute_cell(first)
    if separator:
        normalized = f"{normalized}:{_absolute_cell(last)}"
    return f"'{sheet.replace(chr(39), chr(39) * 2)}'!{normalized}"


def _cell_ref(value: Any, field: str) -> str:
    text = _text(value, field).replace("$", "").upper()
    _cell_bounds(text, field)
    return text


def _cell_bounds(value: str, field: str) -> tuple[int, int]:
    match = _CELL.fullmatch(value)
    if match is None:
        _invalid("Cell reference must use A1 notation.", field=field)
    column = 0
    for character in match.group(1).upper():
        column = column * 26 + ord(character) - ord("A") + 1
    row = int(match.group(2))
    if column > 16_384 or row < 1 or row > 1_048_576:
        _invalid("Cell reference exceeds worksheet bounds.", field=field)
    return column, row


def _absolute_cell(value: str) -> str:
    match = _CELL.fullmatch(value)
    assert match is not None
    return f"${match.group(1).upper()}${match.group(2)}"


def _optional_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or not -1e100 <= value <= 1e100:
        _invalid("Value must be a finite number within bounds.", field=field)
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Value must be an object.", field=field)
    return value


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        _invalid("Value must be non-empty text.", field=field)
    if len(value.encode("utf-8", errors="strict")) > 1_024:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _choice(value: Any, choices: set[str], field: str) -> str:
    if type(value) is not str or value not in choices:
        _invalid("Value is not an accepted enum member.", field=field, accepted=sorted(choices))
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown sparkline field.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
