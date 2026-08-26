"""Bounded public contracts for typed PPTX image and chart objects."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT


def parse_image_reference(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("image_reference must be an object.", field=field)
    _exact_keys(
        value,
        {
            "alt_text", "content_type", "crop", "filename", "fit", "frame",
            "expected_sha256", "opacity", "path", "rotation", "z_order",
        },
    )
    raw_path = _text(value.get("path", value.get("filename")), f"{field}.path", False)
    if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
        _invalid("Image path must reference a local file.", field=f"{field}.path")
    content_type = value.get("content_type")
    if content_type is not None:
        content_type = _text(content_type, f"{field}.content_type", False)
        if content_type not in {"image/png", "image/jpeg", "image/gif"}:
            _invalid("Image content_type must be PNG, JPEG, or GIF.", field=f"{field}.content_type")
    fit = _text(value.get("fit", "contain"), f"{field}.fit", False)
    if fit not in {"contain", "cover", "stretch"}:
        _invalid("Image fit must be contain, cover, or stretch.", field=f"{field}.fit")
    return {
        "path": Path(raw_path).expanduser().resolve(strict=False),
        "expected_sha256": _sha256(
            value.get("expected_sha256"),
            f"{field}.expected_sha256",
        ),
        "content_type": content_type,
        "fit": fit,
        "crop": _parse_crop(value.get("crop"), f"{field}.crop"),
        "opacity": _number(value.get("opacity", 1.0), 0.0, 1.0, f"{field}.opacity"),
        "rotation": _number(value.get("rotation", 0.0), -360.0, 360.0, f"{field}.rotation"),
        "alt_text": _text(value.get("alt_text", "Presentation image"), f"{field}.alt_text"),
        "z_order": _integer(value.get("z_order", 100), 0, 10_000),
        "frame": _parse_frame(value.get("frame"), f"{field}.frame"),
    }


def _sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    digest = _text(value, field, False)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        _invalid("expected_sha256 must be a lowercase SHA-256 digest.", field=field)
    return digest


def parse_chart_reference(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("chart_reference must be an object.", field=field)
    _exact_keys(
        value,
        {"axes", "categories", "chart_type", "colors", "data_labels", "legend", "series", "title"},
    )
    chart_type = _text(value.get("chart_type", "bar"), f"{field}.chart_type", False)
    if chart_type not in {"bar", "column", "line", "pie", "scatter"}:
        _invalid("Unsupported native chart type.", field=f"{field}.chart_type")
    categories = value.get("categories", ["Category 1"])
    if type(categories) is not list or not categories or len(categories) > 1_000:
        _invalid("Chart categories must be a non-empty bounded array.", field=f"{field}.categories")
    parsed_categories = [
        _text(item, f"{field}.categories.{index}") for index, item in enumerate(categories)
    ]
    series = value.get("series")
    if series is None:
        series = [{"name": value.get("title") or "Series 1", "values": [1.0]}]
    if type(series) is not list or not series or len(series) > 64:
        _invalid("Chart series must be a non-empty bounded array.", field=f"{field}.series")
    parsed_series = [
        _parse_chart_series(item, chart_type, len(parsed_categories), f"{field}.series.{index}")
        for index, item in enumerate(series)
    ]
    colors = value.get("colors", [])
    if type(colors) is not list or len(colors) > 64:
        _invalid("Chart colors must be a bounded array.", field=f"{field}.colors")
    parsed_colors = []
    for index, color in enumerate(colors):
        color = _text(color, f"{field}.colors.{index}", False).lstrip("#").upper()
        if len(color) != 6 or any(character not in "0123456789ABCDEF" for character in color):
            _invalid("Chart colors must be six-digit RGB values.", field=f"{field}.colors.{index}")
        parsed_colors.append(color)
    return {
        "title": _text(value.get("title", ""), f"{field}.title"),
        "chart_type": chart_type,
        "categories": parsed_categories,
        "series": parsed_series,
        "legend": _parse_chart_legend(value.get("legend"), f"{field}.legend"),
        "axes": _parse_chart_axes(value.get("axes"), f"{field}.axes"),
        "data_labels": _parse_chart_data_labels(value.get("data_labels"), f"{field}.data_labels"),
        "colors": parsed_colors,
    }


def _parse_crop(value: Any, field: str) -> dict[str, float] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("Image crop must be an object.", field=field)
    _exact_keys(value, {"bottom", "left", "right", "top"})
    result = {
        side: _number(value.get(side, 0.0), 0.0, 0.99, f"{field}.{side}")
        for side in ("left", "top", "right", "bottom")
    }
    if result["left"] + result["right"] >= 1.0 or result["top"] + result["bottom"] >= 1.0:
        _invalid("Image crop must leave a visible area.", field=field)
    return result


def _parse_frame(value: Any, field: str) -> dict[str, int] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("Object frame must be an object.", field=field)
    _exact_keys(value, {"x", "y", "cx", "cy"})
    return {
        "x": _integer(value.get("x"), 0, 100_000_000),
        "y": _integer(value.get("y"), 0, 100_000_000),
        "cx": _integer(value.get("cx"), 1, 100_000_000),
        "cy": _integer(value.get("cy"), 1, 100_000_000),
    }


def _parse_chart_series(
    value: Any, chart_type: str, category_count: int, field: str
) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Chart series must be an object.", field=field)
    if chart_type == "scatter":
        _exact_keys(value, {"name", "x_values", "y_values"})
        x_values = _number_array(value.get("x_values"), f"{field}.x_values")
        y_values = _number_array(value.get("y_values"), f"{field}.y_values")
        if len(x_values) != len(y_values):
            _invalid("Scatter x_values and y_values must have equal length.", field=field)
        return {
            "name": _text(value.get("name", "Series"), f"{field}.name"),
            "x_values": x_values,
            "y_values": y_values,
        }
    _exact_keys(value, {"name", "values"})
    values = _number_array(value.get("values"), f"{field}.values")
    if len(values) != category_count:
        _invalid("Chart series values must match category count.", field=f"{field}.values")
    return {"name": _text(value.get("name", "Series"), f"{field}.name"), "values": values}


def _number_array(value: Any, field: str) -> list[float]:
    if type(value) is not list or not value or len(value) > 1_000:
        _invalid("Chart values must be a non-empty bounded array.", field=field)
    return [_number(item, -1.0e15, 1.0e15, f"{field}.{index}") for index, item in enumerate(value)]


def _parse_chart_legend(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {"show": True, "position": "right"}
    if type(value) is not dict:
        _invalid("Chart legend must be an object.", field=field)
    _exact_keys(value, {"position", "show"})
    position = _text(value.get("position", "right"), f"{field}.position", False)
    if position not in {"bottom", "left", "right", "top", "top_right"}:
        _invalid("Unsupported chart legend position.", field=f"{field}.position")
    return {"show": _boolean(value.get("show", True), f"{field}.show"), "position": position}


def _parse_chart_axes(value: Any, field: str) -> dict[str, Any]:
    value = {} if value is None else value
    if type(value) is not dict:
        _invalid("Chart axes must be an object.", field=field)
    _exact_keys(value, {"category", "value", "x", "y"})
    return {
        name: _parse_chart_axis(value.get(name), f"{field}.{name}")
        for name in ("category", "value", "x", "y")
    }


def _parse_chart_axis(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {"title": "", "number_format": "General"}
    if type(value) is not dict:
        _invalid("Chart axis must be an object.", field=field)
    _exact_keys(value, {"number_format", "title"})
    return {
        "title": _text(value.get("title", ""), f"{field}.title"),
        "number_format": _text(value.get("number_format", "General"), f"{field}.number_format", False),
    }


def _parse_chart_data_labels(value: Any, field: str) -> dict[str, bool]:
    value = {} if value is None else value
    if type(value) is not dict:
        _invalid("Chart data_labels must be an object.", field=field)
    _exact_keys(value, {"show_category_name", "show_series_name", "show_value"})
    return {
        key: _boolean(value.get(key, False), f"{field}.{key}")
        for key in ("show_category_name", "show_series_name", "show_value")
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PPTX typed object argument.", unknown=unknown)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


def _number(value: Any, minimum: float, maximum: float, field: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool) or not minimum <= float(value) <= maximum:
        _invalid(f"Number must be between {minimum} and {maximum}.", field=field)
    return float(value)


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


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
