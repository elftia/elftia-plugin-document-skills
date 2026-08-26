"""Shared bounded scalar, style, identity, and geometry helpers for SVG."""

import math
import re
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
MAX_SVG_BYTES = 4 * 1024 * 1024
MAX_NODES = 4_096
MAX_GROUP_DEPTH = 64
MAX_GRADIENTS = 64
SOURCE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
LENGTH = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?:px)?$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
UNSAFE_TAGS = {
    "animate", "animateMotion", "animateTransform", "foreignObject", "script", "set", "use",
}
GRAPHICS = {"ellipse", "image", "line", "path", "polygon", "rect", "text"}


def local(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def namespace(value: str) -> str:
    return value[1:].split("}", 1)[0] if value.startswith("{") else ""


def number(value: str | None, field: str) -> float:
    if value is None or LENGTH.fullmatch(value.strip()) is None:
        invalid("SVG numeric attribute is missing or invalid.", field=field)
    result = float(value.removesuffix("px"))
    if not math.isfinite(result) or abs(result) > 100_000:
        invalid("SVG numeric attribute exceeds policy.", field=field)
    return result


def positive_number(value: str | None, field: str) -> float:
    result = number(value, field)
    if result <= 0:
        invalid("SVG numeric attribute must be positive.", field=field)
    return result


def length(element: Element, name: str, default: float | None = None) -> float:
    value = element.attrib.get(name)
    if value is None and default is not None:
        return default
    return number(value, name)


def positive_length(element: Element, name: str) -> float:
    return positive_number(element.attrib.get(name), name)


def length_value(value: str) -> float:
    return max(0.0, number(value, "stroke-width"))


def unit_interval(value: str, field: str) -> float:
    result = number(value, field)
    if not 0 <= result <= 1:
        invalid("SVG opacity must be between zero and one.", field=field)
    return result


def color(value: str, field: str) -> str:
    if value in {"none", "transparent"}:
        return "transparent"
    if COLOR.fullmatch(value) is None:
        invalid("SVG color is outside the closed profile.", field=field)
    return value.upper()


def paint(value: str, opacity: str, field: str) -> str:
    """Normalize one SVG paint while retaining paint-specific alpha."""

    normalized = color(value, field)
    alpha = unit_interval(opacity, f"{field}-opacity")
    if normalized == "transparent" or alpha <= 0:
        return "transparent"
    if alpha >= 1:
        return normalized
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    return f"rgba({red}, {green}, {blue}, {alpha:.6f})"


def offset(value: str | None) -> float:
    if value is None:
        invalid("SVG gradient stop requires an offset.")
    result = number(value[:-1], "offset") / 100 if value.endswith("%") else number(value, "offset")
    if not 0 <= result <= 1:
        invalid("SVG gradient offset is outside zero to one.")
    return result


def href(element: Element) -> str:
    values = [value for name, value in element.attrib.items() if local(name) == "href"]
    if len(values) != 1 or not values[0] or ":" in values[0] or values[0].startswith(("/", "\\", "#")):
        unsafe("SVG image references must be bounded local relative files.")
    return values[0]


def text_style(style: dict[str, str]) -> dict[str, Any]:
    return {
        "color": paint(
            style.get("fill", "#000000"),
            style.get("fill-opacity", "1"),
            "fill",
        ),
        "font_family": style.get("font-family", "Arial")[:128],
        "font_size": positive_number(style.get("font-size", "16"), "font-size"),
        "font_style": style.get("font-style", "normal"),
        "font_weight": style.get("font-weight", "400"),
        "letter_spacing": "normal",
        "line_height": "normal",
        "text_align": alignment(style.get("text-anchor", "start")),
        "text_decoration": style.get("text-decoration", "none"),
    }


def alignment(value: str) -> str:
    mapping = {"end": "right", "middle": "center", "start": "left"}
    if value not in mapping:
        invalid("SVG text-anchor is unsupported.")
    return mapping[value]


def assert_canvas_geometry(value: dict[str, float]) -> None:
    x, y = value["x"], value["y"]
    width, height = value["width"], value["height"]
    if (
        not all(math.isfinite(item) for item in (x, y, width, height))
        or x < -0.01
        or y < -0.01
        or width <= 0
        or height <= 0
        or x + width > 1920.01
        or y + height > 1080.01
    ):
        invalid("SVG object geometry leaves the fixed slide canvas.")


def union_bounds(items: list[dict[str, Any]]) -> dict[str, float]:
    left = min(item["x"] for item in items)
    top = min(item["y"] for item in items)
    right = max(item["x"] + item["width"] for item in items)
    bottom = max(item["y"] + item["height"] for item in items)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top, "rotation": 0.0}


def invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        message,
        status="failed",
        details=details,
    )


__all__ = [
    "GRAPHICS", "MAX_GRADIENTS", "MAX_GROUP_DEPTH", "MAX_NODES", "MAX_SVG_BYTES", "SOURCE_ID",
    "SVG_NAMESPACE", "UNSAFE_TAGS", "XLINK_NAMESPACE", "alignment",
    "assert_canvas_geometry", "color", "href", "invalid", "length", "length_value",
    "local", "namespace", "number", "offset", "paint", "positive_length", "positive_number",
    "text_style", "union_bounds", "unit_interval", "unsafe",
]
