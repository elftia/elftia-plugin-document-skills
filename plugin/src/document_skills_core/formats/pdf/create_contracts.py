"""Typed create-only contract helpers for page, text, and vector styling.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import PAGE_SIZES
from .font_contracts import (
    parse_fallback_fonts,
    parse_text_direction,
    parse_text_language,
)

DEFAULT_MARGIN = {"top": 72.0, "right": 72.0, "bottom": 72.0, "left": 72.0}


def parse_page_size(value: Any, field: str, *, optional: bool = False) -> str | dict[str, float] | None:
    """Parse a named or explicit page size in PDF points."""
    if value is None and optional:
        return None
    if type(value) is str:
        if value not in PAGE_SIZES:
            _invalid("Page size must be A4, Letter, or Legal.", field=field)
        return value
    if type(value) is not dict:
        _invalid("Page size must be a named size or width/height object.", field=field)
    _exact_keys(value, {"width", "height"}, field)
    return {
        "width": _bounded_number(value.get("width"), f"{field}.width", 36.0, 2_000.0),
        "height": _bounded_number(value.get("height"), f"{field}.height", 36.0, 2_000.0),
    }


def parse_page_margin(
    value: Any,
    field: str,
    page_size: str | dict[str, float],
    *,
    default_margin: dict[str, float] | None = None,
) -> dict[str, float]:
    """Parse four-sided page margins and ensure a positive content box."""
    defaults = default_margin or DEFAULT_MARGIN
    if value is None:
        parsed = dict(defaults)
    else:
        if type(value) is not dict:
            _invalid("Page margin must be an object.", field=field)
        _exact_keys(value, {"top", "right", "bottom", "left"}, field)
        parsed = {
            side: _bounded_number(value.get(side, defaults[side]), f"{field}.{side}", 0.0, 1_000.0)
            for side in ("top", "right", "bottom", "left")
        }
    width, height = resolved_page_size(page_size)
    if parsed["left"] + parsed["right"] >= width:
        _invalid("Horizontal margins leave no usable page width.", field=field)
    if parsed["top"] + parsed["bottom"] >= height:
        _invalid("Vertical margins leave no usable page height.", field=field)
    return parsed


def parse_block_style(
    value: Any,
    field: str,
    *,
    font_ids: set[str] | None = None,
    palette: dict[str, list[float]] | None = None,
) -> dict[str, Any] | None:
    """Parse built-in or explicitly registered embedded-font text style."""
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("Style must be an object.", field=field)
    _exact_keys(
        value,
        {
            "font_family",
            "font_size",
            "font_weight",
            "font_style",
            "color",
            "line_height",
            "alignment",
            "fallback_fonts",
            "direction",
            "language",
        },
        field,
    )
    family = value.get("font_family", "Helvetica")
    known_fonts = font_ids or set()
    if type(family) is not str or (family != "Helvetica" and family not in known_fonts):
        _invalid("font_family must be Helvetica or a registered font id.", field=f"{field}.font_family")
    weight = value.get("font_weight", "normal")
    if weight not in {"normal", "bold"}:
        _invalid("font_weight must be normal or bold.", field=f"{field}.font_weight")
    font_style = value.get("font_style", "normal")
    if font_style not in {"normal", "italic"}:
        _invalid("font_style must be normal or italic.", field=f"{field}.font_style")
    alignment = value.get("alignment", "left")
    if alignment not in {"left", "center", "right"}:
        _invalid("alignment must be left, center, or right.", field=f"{field}.alignment")
    fallback_fonts = parse_fallback_fonts(
        value.get("fallback_fonts"),
        f"{field}.fallback_fonts",
        known_fonts,
    )
    if family in fallback_fonts:
        _invalid("fallback_fonts must not repeat font_family.", field=f"{field}.fallback_fonts")
    if family != "Helvetica" and (weight != "normal" or font_style != "normal"):
        _enhancement(
            "Embedded font ids identify an exact face; synthetic bold or italic is not allowed.",
            field=field,
            capability="pdf.embedded-font-face-variants",
        )
    return {
        "font_family": family,
        "font_size": _bounded_number(value.get("font_size", 12.0), f"{field}.font_size", 1.0, 200.0),
        "font_weight": weight,
        "font_style": font_style,
        "color": parse_color(
            value.get("color", [0.0, 0.0, 0.0]),
            f"{field}.color",
            palette=palette,
        ),
        "line_height": _bounded_number(value.get("line_height", 14.0), f"{field}.line_height", 1.0, 400.0),
        "alignment": alignment,
        "fallback_fonts": fallback_fonts,
        "direction": parse_text_direction(value.get("direction"), f"{field}.direction"),
        "language": parse_text_language(value.get("language"), f"{field}.language"),
    }


def parse_rgb(value: Any, field: str) -> list[float] | None:
    """Parse an optional normalized RGB triplet."""
    if value is None:
        return None
    if type(value) is not list or len(value) != 3:
        _invalid("Color must be an RGB array with three values.", field=field)
    return [
        _bounded_number(component, f"{field}.{index}", 0.0, 1.0)
        for index, component in enumerate(value)
    ]


def parse_color(
    value: Any,
    field: str,
    *,
    palette: dict[str, list[float]] | None = None,
) -> list[float] | None:
    """Resolve a normalized RGB value or a caller-defined palette token."""
    if type(value) is str:
        colors = palette or {}
        if value not in colors:
            _invalid("Color token is not defined in the document palette.", field=field)
        return list(colors[value])
    return parse_rgb(value, field)


def parse_dash(value: Any, field: str) -> list[float]:
    """Parse a bounded PDF dash array."""
    if value is None:
        return []
    if type(value) is not list or len(value) > 16:
        _invalid("dash must be a bounded array.", field=field)
    parsed = [
        _bounded_number(item, f"{field}.{index}", 0.0, 1_000.0)
        for index, item in enumerate(value)
    ]
    if parsed and not any(parsed):
        _invalid("dash must contain at least one positive value.", field=field)
    return parsed


def resolved_page_size(value: str | dict[str, float]) -> tuple[float, float]:
    if isinstance(value, str):
        return PAGE_SIZES[value]
    return value["width"], value["height"]


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PDF create argument.", field=field, unknown=unknown)


def _bounded_number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if (type(value) is not int and type(value) is not float) or type(value) is bool:
        _invalid("Value must be a number.", field=field)
    number = float(value)
    if not minimum <= number <= maximum:
        _invalid(f"Value must be between {minimum} and {maximum}.", field=field)
    return number


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
