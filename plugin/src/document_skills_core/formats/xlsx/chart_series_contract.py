"""Typed series, trendline, and error-bar contracts for native charts."""

from __future__ import annotations

import math
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .structural_refs import has_external_workbook_reference
from .style_contract import parse_color

_COMBO_TYPES = frozenset({"column", "line", "area"})
_TRENDLINE_TYPES = frozenset(
    {"linear", "exponential", "logarithmic", "polynomial", "power", "moving_average"}
)
_ERROR_TYPES = frozenset(
    {"fixed", "percentage", "standard_deviation", "standard_error", "custom"}
)
_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})")


def parse_chart_series(
    value: Any,
    field: str,
    *,
    chart_type: str,
    known_sheets: set[str] | None,
) -> dict[str, Any]:
    item = _object(value, field)
    _exact_keys(
        item,
        {
            "name",
            "categories",
            "values",
            "x_values",
            "y_values",
            "bubble_sizes",
            "color",
            "chart_type",
            "axis",
            "trendline",
            "error_bars",
        },
    )
    series_type = chart_type
    if chart_type == "combo":
        series_type = _choice(item.get("chart_type"), _COMBO_TYPES, f"{field}.chart_type")
    elif "chart_type" in item:
        _invalid("chart_type is only valid for combo-chart series.", field=f"{field}.chart_type")
    axis = _choice(item.get("axis", "primary"), {"primary", "secondary"}, f"{field}.axis")
    if series_type in {"pie", "radar"} and axis != "primary":
        _invalid("Pie and radar series cannot use a secondary axis.", field=f"{field}.axis")
    parsed: dict[str, Any] = {
        "name": _text(item.get("name"), f"{field}.name"),
        "categories": None,
        "values": None,
        "x_values": None,
        "y_values": None,
        "bubble_sizes": None,
        "color": parse_color(item.get("color", "4472C4"), f"{field}.color"),
    }
    if series_type in {"scatter", "bubble"}:
        _forbid(item, {"categories", "values"}, field, f"{series_type} series")
        parsed["x_values"] = _chart_range(item.get("x_values"), f"{field}.x_values", known_sheets)
        parsed["y_values"] = _chart_range(item.get("y_values"), f"{field}.y_values", known_sheets)
        lengths = [_range_length(parsed["x_values"]), _range_length(parsed["y_values"])]
        if series_type == "bubble":
            parsed["bubble_sizes"] = _chart_range(
                item.get("bubble_sizes"),
                f"{field}.bubble_sizes",
                known_sheets,
            )
            lengths.append(_range_length(parsed["bubble_sizes"]))
        elif item.get("bubble_sizes") is not None:
            _invalid("bubble_sizes is only valid for bubble series.", field=f"{field}.bubble_sizes")
        if len(set(lengths)) != 1:
            _invalid("Chart numeric series ranges must have equal length.", field=field)
    else:
        _forbid(item, {"x_values", "y_values", "bubble_sizes"}, field, "category series")
        parsed["categories"] = _chart_range(
            item.get("categories"),
            f"{field}.categories",
            known_sheets,
        )
        parsed["values"] = _chart_range(
            item.get("values"),
            f"{field}.values",
            known_sheets,
        )
        if _range_length(parsed["categories"]) != _range_length(parsed["values"]):
            _invalid("Chart category/value ranges must have equal length.", field=field)
    if chart_type == "combo":
        parsed["chart_type"] = series_type
    if axis == "secondary":
        parsed["axis"] = axis
    trendline = item.get("trendline")
    if trendline is not None:
        if series_type in {"pie", "radar"}:
            _invalid("This chart series does not support trendlines.", field=f"{field}.trendline")
        parsed["trendline"] = _parse_trendline(trendline, f"{field}.trendline")
    error_bars = item.get("error_bars")
    if error_bars is not None:
        if series_type in {"pie", "radar"}:
            _invalid("This chart series does not support error bars.", field=f"{field}.error_bars")
        parsed["error_bars"] = _parse_error_bars(
            error_bars,
            f"{field}.error_bars",
            series_type=series_type,
            expected_length=_series_length(parsed),
            known_sheets=known_sheets,
        )
    return parsed


def _parse_trendline(value: Any, field: str) -> dict[str, Any]:
    item = _object(value, field)
    _exact_keys(
        item,
        {
            "type",
            "order",
            "period",
            "display_equation",
            "display_r_squared",
            "forward",
            "backward",
            "intercept",
        },
    )
    kind = _choice(item.get("type"), _TRENDLINE_TYPES, f"{field}.type")
    order = item.get("order")
    period = item.get("period")
    if kind == "polynomial":
        order = _integer(order, 2, 6, f"{field}.order")
    elif order is not None:
        _invalid("order is only valid for polynomial trendlines.", field=f"{field}.order")
    if kind == "moving_average":
        period = _integer(period, 2, 255, f"{field}.period")
    elif period is not None:
        _invalid("period is only valid for moving-average trendlines.", field=f"{field}.period")
    return {
        "type": kind,
        "order": order,
        "period": period,
        "display_equation": _boolean(
            item.get("display_equation", False),
            f"{field}.display_equation",
        ),
        "display_r_squared": _boolean(
            item.get("display_r_squared", False),
            f"{field}.display_r_squared",
        ),
        "forward": _number(item.get("forward", 0), 0, 100_000, f"{field}.forward"),
        "backward": _number(item.get("backward", 0), 0, 100_000, f"{field}.backward"),
        "intercept": (
            None
            if item.get("intercept") is None
            else _number(item["intercept"], -1e100, 1e100, f"{field}.intercept")
        ),
    }


def _parse_error_bars(
    value: Any,
    field: str,
    *,
    series_type: str,
    expected_length: int,
    known_sheets: set[str] | None,
) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= 2:
        _invalid("error_bars must contain one or two definitions.", field=field)
    result: list[dict[str, Any]] = []
    directions: set[str] = set()
    for index, raw in enumerate(value):
        item_field = f"{field}.{index}"
        item = _object(raw, item_field)
        _exact_keys(item, {"direction", "type", "value", "plus", "minus", "end_style"})
        direction = _choice(item.get("direction", "y"), {"x", "y"}, f"{item_field}.direction")
        if direction == "x" and series_type not in {"scatter", "bubble"}:
            _invalid("X-direction error bars require scatter or bubble series.", field=item_field)
        if direction in directions:
            _invalid("Error-bar directions must be unique.", field=item_field)
        directions.add(direction)
        kind = _choice(item.get("type"), _ERROR_TYPES, f"{item_field}.type")
        plus = minus = None
        numeric_value = item.get("value")
        if kind == "custom":
            if numeric_value is not None:
                _invalid("Custom error bars do not accept value.", field=f"{item_field}.value")
            plus = _chart_range(item.get("plus"), f"{item_field}.plus", known_sheets)
            minus = _chart_range(item.get("minus"), f"{item_field}.minus", known_sheets)
            if _range_length(plus) != expected_length or _range_length(minus) != expected_length:
                _invalid("Custom error-bar ranges must match the series length.", field=item_field)
        else:
            if item.get("plus") is not None or item.get("minus") is not None:
                _invalid("Only custom error bars accept plus/minus ranges.", field=item_field)
            if kind in {"fixed", "percentage", "standard_deviation"}:
                numeric_value = _number(numeric_value, 0, 1e100, f"{item_field}.value")
            elif numeric_value is not None:
                _invalid("Standard-error bars do not accept value.", field=f"{item_field}.value")
        result.append(
            {
                "direction": direction,
                "type": kind,
                "value": numeric_value,
                "plus": plus,
                "minus": minus,
                "end_style": _boolean(item.get("end_style", True), f"{item_field}.end_style"),
            }
        )
    return result


def _chart_range(value: Any, field: str, known_sheets: set[str] | None) -> str:
    text = _text(value, field)
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
    bounds = _range_bounds(cell_range)
    if bounds[0] != bounds[2] and bounds[1] != bounds[3]:
        _invalid("Chart data range must be one-dimensional.", field=field)
    absolute = ":".join(_absolute_cell(item) for item in cell_range.split(":"))
    return f"'{sheet.replace(chr(39), chr(39) * 2)}'!{absolute}"


def _range_bounds(value: str) -> tuple[int, int, int, int]:
    first, _, last = value.partition(":")
    first_bounds = _cell_bounds(first)
    last_bounds = _cell_bounds(last or first)
    if first_bounds[0] > last_bounds[0] or first_bounds[1] > last_bounds[1]:
        _invalid("Cell range must be ascending.")
    return first_bounds[0], first_bounds[1], last_bounds[0], last_bounds[1]


def _range_length(value: str) -> int:
    bounds = _range_bounds(value.rsplit("!", 1)[1])
    return max(bounds[2] - bounds[0], bounds[3] - bounds[1]) + 1


def _cell_bounds(value: str) -> tuple[int, int]:
    match = _CELL.fullmatch(value)
    if match is None:
        _invalid("Cell reference must use A1 notation.")
    column = 0
    for character in match.group(1).upper():
        column = column * 26 + ord(character) - ord("A") + 1
    row = int(match.group(2))
    if column > 16_384 or row < 1 or row > 1_048_576:
        _invalid("Cell reference exceeds worksheet bounds.")
    return column, row


def _absolute_cell(value: str) -> str:
    match = _CELL.fullmatch(value)
    assert match is not None
    return f"${match.group(1).upper()}${match.group(2)}"


def _series_length(series: dict[str, Any]) -> int:
    value = series.get("values") or series.get("y_values")
    assert value is not None
    return _range_length(value)


def _forbid(item: dict[str, Any], keys: set[str], field: str, label: str) -> None:
    present = sorted(key for key in keys if item.get(key) is not None)
    if present:
        _invalid(f"{label} does not accept these fields.", field=field, fields=present)


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


def _choice(value: Any, choices: set[str] | frozenset[str], field: str) -> str:
    if type(value) is not str or value not in choices:
        _invalid("Value is not an accepted enum member.", field=field, accepted=sorted(choices))
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _number(value: Any, minimum: float, maximum: float, field: str) -> int | float:
    if type(value) not in {int, float} or not math.isfinite(value) or not minimum <= value <= maximum:
        _invalid("Value must be a finite number within bounds.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown chart-series field.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
