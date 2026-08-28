"""Closed design-token contract for PDF creation defaults."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_contracts import (
    DEFAULT_MARGIN,
    parse_block_style,
    parse_page_margin,
    parse_page_size,
    parse_rgb,
)

MAX_PALETTE_COLORS = 32
_TOKEN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_TYPOGRAPHY_DEFAULTS: dict[str, dict[str, Any]] = {
    "heading": {
        "font_family": "Helvetica",
        "font_size": 16.0,
        "font_weight": "bold",
        "font_style": "normal",
        "color": [0.0, 0.0, 0.0],
        "line_height": 28.0,
        "alignment": "left",
        "fallback_fonts": [],
        "direction": "auto",
        "language": None,
    },
    "paragraph": {
        "font_family": "Helvetica",
        "font_size": 12.0,
        "font_weight": "normal",
        "font_style": "normal",
        "color": [0.0, 0.0, 0.0],
        "line_height": 14.0,
        "alignment": "left",
        "fallback_fonts": [],
        "direction": "auto",
        "language": None,
    },
    "table": {
        "font_family": "Helvetica",
        "font_size": 10.0,
        "font_weight": "normal",
        "font_style": "normal",
        "color": [0.0, 0.0, 0.0],
        "line_height": 12.0,
        "alignment": "left",
        "fallback_fonts": [],
        "direction": "auto",
        "language": None,
    },
}
DEFAULT_SPACING = {
    "heading_gap": 8.0,
    "paragraph_gap": 8.0,
    "table_gap": 10.0,
    "image_gap": 20.0,
}


def design_token_page_size(value: Any) -> str | dict[str, float] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("document.design_tokens must be an object.", field="design_tokens")
    page_size = value.get("page_size")
    return parse_page_size(
        page_size,
        "design_tokens.page_size",
        optional=True,
    )


def parse_design_tokens(
    value: Any,
    *,
    font_ids: set[str],
    page_size: str | dict[str, float],
) -> dict[str, Any]:
    if value is None:
        return default_design_tokens()
    if type(value) is not dict:
        _invalid("document.design_tokens must be an object.", field="design_tokens")
    _exact_keys(
        value,
        {"page_size", "margin", "palette", "typography", "spacing"},
        "design_tokens",
    )
    palette = _parse_palette(value.get("palette"))
    typography = _parse_typography(
        value.get("typography"),
        font_ids=font_ids,
        palette=palette,
    )
    return {
        "page_size": design_token_page_size(value),
        "margin": parse_page_margin(
            value.get("margin"),
            "design_tokens.margin",
            page_size,
        ),
        "palette": palette,
        "typography": typography,
        "spacing": _parse_spacing(value.get("spacing")),
    }


def default_design_tokens() -> dict[str, Any]:
    """Return a fresh default token set for trusted direct Core callers."""
    return {
        "page_size": None,
        "margin": dict(DEFAULT_MARGIN),
        "palette": {},
        "typography": {},
        "spacing": dict(DEFAULT_SPACING),
    }


def merge_block_style(
    block_type: str,
    value: Any,
    *,
    tokens: dict[str, Any],
    font_ids: set[str],
    field: str,
) -> dict[str, Any] | None:
    role = "table" if block_type == "table" else block_type
    token_style = tokens["typography"].get(role)
    if value is None:
        return token_style
    if type(value) is not dict:
        _invalid("Style must be an object.", field=field)
    merged = {**(token_style or {}), **value}
    return parse_block_style(
        merged,
        field,
        font_ids=font_ids,
        palette=tokens["palette"],
    )


def _parse_palette(value: Any) -> dict[str, list[float]]:
    if value is None:
        return {}
    if type(value) is not dict or len(value) > MAX_PALETTE_COLORS:
        _invalid("design_tokens.palette must be a bounded object.", field="design_tokens.palette")
    parsed: dict[str, list[float]] = {}
    for name, color in value.items():
        if type(name) is not str or _TOKEN_NAME.fullmatch(name) is None:
            _invalid("Palette names must be stable ASCII tokens.", field="design_tokens.palette")
        parsed_color = parse_rgb(color, f"design_tokens.palette.{name}")
        assert parsed_color is not None
        parsed[name] = parsed_color
    return parsed


def _parse_typography(
    value: Any,
    *,
    font_ids: set[str],
    palette: dict[str, list[float]],
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if type(value) is not dict:
        _invalid("design_tokens.typography must be an object.", field="design_tokens.typography")
    _exact_keys(value, set(_TYPOGRAPHY_DEFAULTS), "design_tokens.typography")
    parsed: dict[str, dict[str, Any]] = {}
    for role, style in value.items():
        if type(style) is not dict:
            _invalid("Typography tokens must be style objects.", field=f"design_tokens.typography.{role}")
        resolved = parse_block_style(
            {**_TYPOGRAPHY_DEFAULTS[role], **style},
            f"design_tokens.typography.{role}",
            font_ids=font_ids,
            palette=palette,
        )
        assert resolved is not None
        parsed[role] = resolved
    return parsed


def _parse_spacing(value: Any) -> dict[str, float]:
    if value is None:
        return dict(DEFAULT_SPACING)
    if type(value) is not dict:
        _invalid("design_tokens.spacing must be an object.", field="design_tokens.spacing")
    _exact_keys(value, set(DEFAULT_SPACING), "design_tokens.spacing")
    parsed = dict(DEFAULT_SPACING)
    for name, raw in value.items():
        if (type(raw) is not int and type(raw) is not float) or type(raw) is bool:
            _invalid("Spacing tokens must be numbers.", field=f"design_tokens.spacing.{name}")
        number = float(raw)
        if not 0.0 <= number <= 400.0:
            _invalid("Spacing tokens must be between 0 and 400 points.", field=f"design_tokens.spacing.{name}")
        parsed[name] = number
    return parsed


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PDF design token.", field=field, unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
