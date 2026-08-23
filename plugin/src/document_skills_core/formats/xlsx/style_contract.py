"""Closed typed contracts for XLSX styles, dimensions, and number formats."""

from __future__ import annotations

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT

_COLOR_RE = re.compile(r"^#?(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
_COLUMN_RE = re.compile(r"^(?P<first>[A-Za-z]{1,3})(?::(?P<last>[A-Za-z]{1,3}))?$")
_FONT_KEYS = {"name", "size", "bold", "italic", "underline", "color"}
_FILL_KEYS = {"pattern", "color", "background_color"}
_BORDER_KEYS = {
    "left",
    "right",
    "top",
    "bottom",
    "diagonal",
    "diagonal_up",
    "diagonal_down",
    "outline",
}
_BORDER_SIDE_KEYS = {"style", "color"}
_ALIGNMENT_KEYS = {
    "horizontal",
    "vertical",
    "wrap",
    "rotation",
    "shrink_to_fit",
    "indent",
}
_PROTECTION_KEYS = {"locked", "hidden"}
_STYLE_KEYS = {"font", "fill", "border", "alignment", "protection", "number_format"}

_UNDERLINES = {"single", "double", "singleAccounting", "doubleAccounting"}
_FILL_PATTERNS = {
    "none",
    "solid",
    "mediumGray",
    "darkGray",
    "lightGray",
    "darkHorizontal",
    "darkVertical",
    "darkDown",
    "darkUp",
    "darkGrid",
    "darkTrellis",
    "lightHorizontal",
    "lightVertical",
    "lightDown",
    "lightUp",
    "lightGrid",
    "lightTrellis",
    "gray125",
    "gray0625",
}
_BORDER_STYLES = {
    "dashDot",
    "dashDotDot",
    "dashed",
    "dotted",
    "double",
    "hair",
    "medium",
    "mediumDashDot",
    "mediumDashDotDot",
    "mediumDashed",
    "slantDashDot",
    "thick",
    "thin",
}
_HORIZONTAL_ALIGNMENTS = {
    "general",
    "left",
    "center",
    "right",
    "fill",
    "justify",
    "centerContinuous",
    "distributed",
}
_VERTICAL_ALIGNMENTS = {"top", "center", "bottom", "justify", "distributed"}


def parse_style(value: Any, field: str) -> dict[str, Any] | None:
    """Parse a style object into the canonical nested representation."""

    if value is None:
        return None
    if type(value) is not dict:
        _invalid("Style must be an object.", field=field)
    _exact_keys(value, _STYLE_KEYS, field)
    result: dict[str, Any] = {}
    if "font" in value:
        result["font"] = _parse_font(value["font"], f"{field}.font")
    if "fill" in value:
        result["fill"] = _parse_fill(value["fill"], f"{field}.fill")
    if "border" in value:
        result["border"] = _parse_border(value["border"], f"{field}.border")
    if "alignment" in value:
        result["alignment"] = _parse_alignment(
            value["alignment"], f"{field}.alignment"
        )
    if "protection" in value:
        result["protection"] = _parse_protection(
            value["protection"], f"{field}.protection"
        )
    if "number_format" in value:
        result["number_format"] = _parse_number_format(
            value["number_format"], f"{field}.number_format"
        )
    return result or None


def parse_number_format_definition(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("number_format must be an object.", field=field)
    _exact_keys(value, {"id", "code"}, field)
    format_id = _integer(value.get("id"), 164, 65_535, f"{field}.id")
    code = _text(value.get("code"), f"{field}.code", allow_empty=False)
    return {"id": format_id, "code": code}


def parse_column(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Column definition must be an object.", field=field)
    _exact_keys(value, {"ref", "width", "hidden", "style"}, field)
    ref = _text(value.get("ref"), f"{field}.ref", allow_empty=False).upper()
    first, last = _parse_column_ref(ref, f"{field}.ref")
    width = value.get("width")
    if width is not None:
        width = _number(width, 0.0, 255.0, f"{field}.width")
    hidden = _boolean(value.get("hidden", False), f"{field}.hidden")
    style = parse_style(value.get("style"), f"{field}.style")
    return {
        "ref": ref,
        "min": first,
        "max": last,
        "width": width,
        "hidden": hidden,
        "style": style,
    }


def custom_number_format_id(style: dict[str, Any] | None) -> int | None:
    if not style:
        return None
    number_format = style.get("number_format")
    if not number_format or "id" not in number_format:
        return None
    format_id = number_format["id"]
    return format_id if format_id >= 164 else None


def _parse_font(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("font must be an object.", field=field)
    _exact_keys(value, _FONT_KEYS, field)
    result: dict[str, Any] = {}
    if "name" in value:
        result["name"] = _text(value["name"], f"{field}.name", allow_empty=False)
    if "size" in value:
        result["size"] = _number(value["size"], 1.0, 409.0, f"{field}.size")
    for key in ("bold", "italic"):
        if key in value:
            result[key] = _boolean(value[key], f"{field}.{key}")
    if "underline" in value:
        underline = _text(value["underline"], f"{field}.underline", allow_empty=False)
        if underline not in _UNDERLINES:
            _invalid("Unknown underline style.", field=f"{field}.underline")
        result["underline"] = underline
    if "color" in value:
        result["color"] = _color(value["color"], f"{field}.color")
    return result


def _parse_fill(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("fill must be an object.", field=field)
    _exact_keys(value, _FILL_KEYS, field)
    result: dict[str, Any] = {}
    if "pattern" in value:
        pattern = _text(value["pattern"], f"{field}.pattern", allow_empty=False)
        if pattern not in _FILL_PATTERNS:
            _invalid("Unknown fill pattern.", field=f"{field}.pattern")
        result["pattern"] = pattern
    if "color" in value:
        result["color"] = _color(value["color"], f"{field}.color")
        result.setdefault("pattern", "solid")
    if "background_color" in value:
        result["background_color"] = _color(
            value["background_color"], f"{field}.background_color"
        )
    return result


def _parse_border(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("border must be an object.", field=field)
    _exact_keys(value, _BORDER_KEYS, field)
    result: dict[str, Any] = {}
    for side in ("left", "right", "top", "bottom", "diagonal"):
        if side in value:
            result[side] = _parse_border_side(value[side], f"{field}.{side}")
    for key in ("diagonal_up", "diagonal_down", "outline"):
        if key in value:
            result[key] = _boolean(value[key], f"{field}.{key}")
    return result


def _parse_border_side(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Border side must be an object.", field=field)
    _exact_keys(value, _BORDER_SIDE_KEYS, field)
    result: dict[str, Any] = {}
    if "style" in value:
        style = _text(value["style"], f"{field}.style", allow_empty=False)
        if style not in _BORDER_STYLES:
            _invalid("Unknown border style.", field=f"{field}.style")
        result["style"] = style
    if "color" in value:
        result["color"] = _color(value["color"], f"{field}.color")
    if result.get("color") and not result.get("style"):
        _invalid("Border color requires a border style.", field=field)
    return result


def _parse_alignment(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("alignment must be an object.", field=field)
    _exact_keys(value, _ALIGNMENT_KEYS, field)
    result: dict[str, Any] = {}
    if "horizontal" in value:
        horizontal = _text(
            value["horizontal"], f"{field}.horizontal", allow_empty=False
        )
        if horizontal not in _HORIZONTAL_ALIGNMENTS:
            _invalid("Unknown horizontal alignment.", field=f"{field}.horizontal")
        result["horizontal"] = horizontal
    if "vertical" in value:
        vertical = _text(value["vertical"], f"{field}.vertical", allow_empty=False)
        if vertical not in _VERTICAL_ALIGNMENTS:
            _invalid("Unknown vertical alignment.", field=f"{field}.vertical")
        result["vertical"] = vertical
    for key in ("wrap", "shrink_to_fit"):
        if key in value:
            result[key] = _boolean(value[key], f"{field}.{key}")
    if "rotation" in value:
        result["rotation"] = _integer(value["rotation"], -90, 90, f"{field}.rotation")
    if "indent" in value:
        result["indent"] = _integer(value["indent"], 0, 250, f"{field}.indent")
    return result


def _parse_protection(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("protection must be an object.", field=field)
    _exact_keys(value, _PROTECTION_KEYS, field)
    return {
        key: _boolean(value[key], f"{field}.{key}")
        for key in ("locked", "hidden")
        if key in value
    }


def _parse_number_format(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("number_format must be an object.", field=field)
    _exact_keys(value, {"id", "code"}, field)
    if set(value) not in ({"id"}, {"code"}):
        _invalid("number_format requires exactly one of id or code.", field=field)
    if "id" in value:
        return {"id": _integer(value["id"], 0, 65_535, f"{field}.id")}
    return {"code": _text(value["code"], f"{field}.code", allow_empty=False)}


def _parse_column_ref(value: str, field: str) -> tuple[int, int]:
    match = _COLUMN_RE.fullmatch(value)
    if match is None:
        _invalid("Column ref must use A or A:C notation.", field=field)
    first = _column_to_number(match.group("first"))
    last = _column_to_number(match.group("last") or match.group("first"))
    if first > last or last > 16_384:
        _invalid("Column ref is outside the XLSX column range.", field=field)
    return first, last


def _column_to_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _color(value: Any, field: str) -> str:
    text = _text(value, field, allow_empty=False)
    if _COLOR_RE.fullmatch(text) is None:
        _invalid("Color must be 6- or 8-digit RGB hex.", field=field)
    normalized = text.removeprefix("#").upper()
    return normalized if len(normalized) == 8 else f"FF{normalized}"


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown XLSX style field.", field=field, unknown=unknown)


def _number(value: Any, minimum: float, maximum: float, field: str) -> int | float:
    if type(value) not in {int, float} or not minimum <= value <= maximum:
        _invalid(f"Number must be between {minimum} and {maximum}.", field=field)
    return value


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _text(value: Any, field: str, *, allow_empty: bool = True) -> str:
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
