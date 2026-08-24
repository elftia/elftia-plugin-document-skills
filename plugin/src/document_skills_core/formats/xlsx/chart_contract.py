"""Bounded typed contracts for native SpreadsheetML charts."""

from __future__ import annotations

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart_series_contract import parse_chart_series

_CHART_TYPES = frozenset(
    {"column", "bar", "line", "pie", "scatter", "area", "radar", "bubble", "combo"}
)
_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})")


def parse_chart(
    value: Any,
    field: str,
    *,
    known_sheets: set[str] | None,
) -> dict[str, Any]:
    """Parse one native chart definition without importing the main XLSX contract."""

    chart = _object(value, field)
    _exact_keys(
        chart,
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
            "secondary_x_axis_title",
            "secondary_y_axis_title",
            "secondary_x_axis_number_format",
            "secondary_y_axis_number_format",
            "data_labels",
            "style",
            "radar_style",
            "bubble_scale",
        },
    )
    name = _text(chart.get("name"), f"{field}.name")
    sheet = _text(chart.get("sheet"), f"{field}.sheet")
    if known_sheets is not None and sheet not in known_sheets:
        _invalid("Chart placement sheet was not found.", field=f"{field}.sheet")
    chart_type = _choice(chart.get("type"), _CHART_TYPES, f"{field}.type")
    anchor = _cell_range(chart.get("anchor"), f"{field}.anchor")
    bounds = _range_bounds(anchor)
    if bounds[0] == bounds[2] or bounds[1] == bounds[3]:
        _invalid(
            "Chart anchor must span at least two rows and two columns.",
            field=f"{field}.anchor",
        )
    series = chart.get("series")
    if type(series) is not list or not 1 <= len(series) <= 50:
        _invalid("Chart series must be a non-empty bounded array.", field=f"{field}.series")
    parsed_series = [
        parse_chart_series(
            item,
            f"{field}.series.{index}",
            chart_type=chart_type,
            known_sheets=known_sheets,
        )
        for index, item in enumerate(series)
    ]
    _validate_series_mix(parsed_series, chart_type, field)
    axis_values = {
        key: _optional_text(chart.get(key), f"{field}.{key}")
        for key in (
            "x_axis_title",
            "y_axis_title",
            "x_axis_number_format",
            "y_axis_number_format",
            "secondary_x_axis_title",
            "secondary_y_axis_title",
            "secondary_x_axis_number_format",
            "secondary_y_axis_number_format",
        )
    }
    if chart_type in {"pie", "radar"} and any(axis_values.values()):
        _invalid("Pie and radar charts do not accept axis fields.", field=field)
    secondary_requested = any(item.get("axis") == "secondary" for item in parsed_series)
    if not secondary_requested and any(
        axis_values[key]
        for key in axis_values
        if key.startswith("secondary_")
    ):
        _invalid("Secondary-axis metadata requires a secondary series.", field=field)
    radar_style = _choice(
        chart.get("radar_style", "standard"),
        {"standard", "marker", "filled"},
        f"{field}.radar_style",
    )
    if chart_type != "radar" and "radar_style" in chart:
        _invalid("radar_style is only valid for radar charts.", field=f"{field}.radar_style")
    bubble_scale = _integer(chart.get("bubble_scale", 100), 0, 300, f"{field}.bubble_scale")
    if chart_type != "bubble" and "bubble_scale" in chart:
        _invalid("bubble_scale is only valid for bubble charts.", field=f"{field}.bubble_scale")
    labels = _parse_data_labels(chart.get("data_labels", {}), f"{field}.data_labels")
    return {
        "name": name,
        "sheet": sheet,
        "type": chart_type,
        "title": _text(chart.get("title", ""), f"{field}.title", allow_empty=True),
        "anchor": anchor,
        "series": parsed_series,
        "show_legend": _boolean(chart.get("show_legend", True), f"{field}.show_legend"),
        "legend_position": _choice(
            chart.get("legend_position", "r"),
            {"l", "r", "t", "b", "tr"},
            f"{field}.legend_position",
        ),
        **axis_values,
        "data_labels": labels,
        "style": _integer(chart.get("style", 2), 1, 48, f"{field}.style"),
        "radar_style": radar_style,
        "bubble_scale": bubble_scale,
    }


def _validate_series_mix(series: list[dict[str, Any]], chart_type: str, field: str) -> None:
    if not any(item.get("axis", "primary") == "primary" for item in series):
        _invalid("A chart requires at least one primary-axis series.", field=f"{field}.series")
    if chart_type == "combo" and len({item["chart_type"] for item in series}) < 2:
        _invalid("Combo charts require at least two distinct series chart types.", field=field)


def _parse_data_labels(value: Any, field: str) -> dict[str, bool]:
    item = _object(value, field)
    keys = {
        "show_value",
        "show_category_name",
        "show_series_name",
        "show_legend_key",
        "show_percentage",
    }
    _exact_keys(item, keys)
    return {key: _boolean(item.get(key, False), f"{field}.{key}") for key in keys}


def _cell_range(value: Any, field: str) -> str:
    text = _text(value, field).replace("$", "").upper()
    first, separator, last = text.partition(":")
    first_bounds = _cell_bounds(first, field)
    last_bounds = _cell_bounds(last if separator else first, field)
    if first_bounds[0] > last_bounds[0] or first_bounds[1] > last_bounds[1]:
        _invalid("Cell range must be ascending.", field=field)
    return first if not separator else f"{first}:{last}"


def _range_bounds(value: str) -> tuple[int, int, int, int]:
    first, _, last = value.partition(":")
    first_bounds = _cell_bounds(first, "range")
    last_bounds = _cell_bounds(last or first, "range")
    return first_bounds[0], first_bounds[1], last_bounds[0], last_bounds[1]


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


def _object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Value must be an object.", field=field)
    return value


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be text.", field=field)
    if len(value.encode("utf-8", errors="strict")) > 1_024:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _optional_text(value: Any, field: str) -> str | None:
    return None if value is None else _text(value, field)


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


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown chart field.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
