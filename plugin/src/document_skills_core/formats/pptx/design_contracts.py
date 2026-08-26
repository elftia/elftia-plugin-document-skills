"""Typed theme tokens and bounded layout-recipe contracts."""

from copy import deepcopy
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT

LAYOUT_RECIPES = (
    "cover",
    "section",
    "content",
    "two-column",
    "image-focus",
    "comparison",
    "summary",
)

DEFAULT_THEME: dict[str, Any] = {
    "name": "Elftia Office",
    "palette": {
        "dk1": "000000",
        "lt1": "FFFFFF",
        "dk2": "44546A",
        "lt2": "E7E6E6",
        "accent1": "4472C4",
        "accent2": "ED7D31",
        "accent3": "A5A5A5",
        "accent4": "FFC000",
        "accent5": "5B9BD5",
        "accent6": "70AD47",
        "hlink": "0563C1",
        "folHlink": "954F72",
    },
    "fonts": {"major": "Calibri Light", "minor": "Calibri"},
    "effects": {
        "shadow": {
            "enabled": False,
            "blur": 50_800,
            "distance": 38_100,
            "direction": 270.0,
            "color": "000000",
            "opacity": 0.25,
        },
    },
    "background": "FFFFFF",
    "default_text": {
        "title_color": "000000",
        "body_color": "222222",
        "title_size": 30.0,
        "body_size": 18.0,
        "bold_titles": True,
    },
    "default_shape": {
        "fill": "FFFFFF",
        "line": "D9E2F3",
        "opacity": 1.0,
    },
    "default_chart": {
        "colors": ["4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"],
    },
}

DEFAULT_LAYOUT_TOKENS: dict[str, Any] = {
    "safe_margins": {
        "top": 365_760,
        "right": 457_200,
        "bottom": 365_760,
        "left": 457_200,
    },
    "grid": {"columns": 12, "gutter": 182_880},
    "spacing": {
        "xs": 91_440,
        "sm": 182_880,
        "md": 274_320,
        "lg": 457_200,
        "xl": 731_520,
    },
    "typography_scale": {
        "title": 30.0,
        "section": 24.0,
        "body": 18.0,
        "caption": 12.0,
    },
}


def parse_theme(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return deepcopy(DEFAULT_THEME)
    if type(value) is not dict:
        _invalid("Theme tokens must be an object.", field=field)
    _exact_keys(
        value,
        {
            "background", "default_chart", "default_shape", "default_text",
            "effects", "fonts", "name", "palette",
        },
        field,
    )
    result = deepcopy(DEFAULT_THEME)
    if "name" in value:
        result["name"] = _text(value["name"], f"{field}.name", False)
    if "palette" in value:
        palette = value["palette"]
        if type(palette) is not dict:
            _invalid("Theme palette must be an object.", field=f"{field}.palette")
        _exact_keys(palette, set(DEFAULT_THEME["palette"]), f"{field}.palette")
        result["palette"].update({
            key: _color(color, f"{field}.palette.{key}")
            for key, color in palette.items()
        })
    if "fonts" in value:
        fonts = value["fonts"]
        if type(fonts) is not dict:
            _invalid("Theme fonts must be an object.", field=f"{field}.fonts")
        _exact_keys(fonts, {"major", "minor"}, f"{field}.fonts")
        result["fonts"].update({
            key: _text(font, f"{field}.fonts.{key}", False)
            for key, font in fonts.items()
        })
    if "effects" in value:
        result["effects"].update(
            _parse_effects(value["effects"], f"{field}.effects")
        )
    if "background" in value:
        result["background"] = _color(value["background"], f"{field}.background")
    if "default_text" in value:
        result["default_text"].update(
            _parse_default_text(value["default_text"], f"{field}.default_text")
        )
    if "default_shape" in value:
        result["default_shape"].update(
            _parse_default_shape(value["default_shape"], f"{field}.default_shape")
        )
    if "default_chart" in value:
        result["default_chart"].update(
            _parse_default_chart(value["default_chart"], f"{field}.default_chart")
        )
    return result


def parse_layout_tokens(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return deepcopy(DEFAULT_LAYOUT_TOKENS)
    if type(value) is not dict:
        _invalid("Layout tokens must be an object.", field=field)
    _exact_keys(
        value,
        {"grid", "safe_margins", "spacing", "typography_scale"},
        field,
    )
    result = deepcopy(DEFAULT_LAYOUT_TOKENS)
    if "safe_margins" in value:
        result["safe_margins"].update(
            _integer_map(
                value["safe_margins"],
                {"bottom", "left", "right", "top"},
                0,
                10_000_000,
                f"{field}.safe_margins",
            )
        )
    if "grid" in value:
        grid = value["grid"]
        if type(grid) is not dict:
            _invalid("Layout grid must be an object.", field=f"{field}.grid")
        _exact_keys(grid, {"columns", "gutter"}, f"{field}.grid")
        if "columns" in grid:
            result["grid"]["columns"] = _integer(
                grid["columns"], 2, 24, f"{field}.grid.columns"
            )
        if "gutter" in grid:
            result["grid"]["gutter"] = _integer(
                grid["gutter"], 0, 5_000_000, f"{field}.grid.gutter"
            )
    if "spacing" in value:
        result["spacing"].update(
            _integer_map(
                value["spacing"],
                {"lg", "md", "sm", "xl", "xs"},
                0,
                5_000_000,
                f"{field}.spacing",
            )
        )
    if "typography_scale" in value:
        scale = value["typography_scale"]
        if type(scale) is not dict:
            _invalid("Typography scale must be an object.", field=f"{field}.typography_scale")
        _exact_keys(scale, {"body", "caption", "section", "title"}, f"{field}.typography_scale")
        result["typography_scale"].update({
            key: _number(size, 1.0, 400.0, f"{field}.typography_scale.{key}")
            for key, size in scale.items()
        })
    return result


def parse_recipe(value: Any, layout: str, field: str) -> str:
    if value is None:
        value = "cover" if layout == "title" else "content"
    recipe = _text(value, field, False)
    if recipe not in LAYOUT_RECIPES:
        _invalid("Unsupported PPTX layout recipe.", field=field, recipe=recipe)
    return recipe


def _parse_default_text(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Default text style must be an object.", field=field)
    _exact_keys(
        value,
        {"body_color", "body_size", "bold_titles", "title_color", "title_size"},
        field,
    )
    result = dict(value)
    for key in ("body_color", "title_color"):
        if key in result:
            result[key] = _color(result[key], f"{field}.{key}")
    for key in ("body_size", "title_size"):
        if key in result:
            result[key] = _number(result[key], 1.0, 400.0, f"{field}.{key}")
    if "bold_titles" in result and type(result["bold_titles"]) is not bool:
        _invalid("bold_titles must be boolean.", field=f"{field}.bold_titles")
    return result


def _parse_effects(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Theme effects must be an object.", field=field)
    _exact_keys(value, {"shadow"}, field)
    shadow = value.get("shadow")
    if type(shadow) is not dict:
        _invalid("Theme shadow effect must be an object.", field=f"{field}.shadow")
    _exact_keys(
        shadow,
        {"blur", "color", "direction", "distance", "enabled", "opacity"},
        f"{field}.shadow",
    )
    result = dict(DEFAULT_THEME["effects"]["shadow"])
    if "enabled" in shadow:
        if type(shadow["enabled"]) is not bool:
            _invalid("Theme shadow enabled must be boolean.", field=f"{field}.shadow.enabled")
        result["enabled"] = shadow["enabled"]
    for key in ("blur", "distance"):
        if key in shadow:
            result[key] = _integer(shadow[key], 0, 10_000_000, f"{field}.shadow.{key}")
    if "direction" in shadow:
        result["direction"] = _number(
            shadow["direction"], 0.0, 360.0, f"{field}.shadow.direction"
        )
    if "opacity" in shadow:
        result["opacity"] = _number(
            shadow["opacity"], 0.0, 1.0, f"{field}.shadow.opacity"
        )
    if "color" in shadow:
        result["color"] = _color(shadow["color"], f"{field}.shadow.color")
    return {"shadow": result}


def _parse_default_shape(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Default shape style must be an object.", field=field)
    _exact_keys(value, {"fill", "line", "opacity"}, field)
    result = dict(value)
    for key in ("fill", "line"):
        if key in result:
            result[key] = _color(result[key], f"{field}.{key}")
    if "opacity" in result:
        result["opacity"] = _number(result["opacity"], 0.0, 1.0, f"{field}.opacity")
    return result


def _parse_default_chart(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Default chart style must be an object.", field=field)
    _exact_keys(value, {"colors"}, field)
    colors = value.get("colors")
    if type(colors) is not list or not colors or len(colors) > 64:
        _invalid("Default chart colors must be a non-empty bounded array.", field=f"{field}.colors")
    return {
        "colors": [
            _color(color, f"{field}.colors.{index}")
            for index, color in enumerate(colors)
        ]
    }


def _integer_map(
    value: Any,
    allowed: set[str],
    minimum: int,
    maximum: int,
    field: str,
) -> dict[str, int]:
    if type(value) is not dict:
        _invalid("Layout token group must be an object.", field=field)
    _exact_keys(value, allowed, field)
    return {
        key: _integer(item, minimum, maximum, f"{field}.{key}")
        for key, item in value.items()
    }


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PPTX design token.", field=field, unknown=unknown)


def _color(value: Any, field: str) -> str:
    normalized = _text(value, field, False).lstrip("#").upper()
    if len(normalized) != 6 or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        _invalid("Color must be a six-digit RGB value.", field=field)
    return normalized


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _number(value: Any, minimum: float, maximum: float, field: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _invalid("Value must be numeric.", field=field)
    number = float(value)
    if not minimum <= number <= maximum:
        _invalid(f"Number must be between {minimum} and {maximum}.", field=field)
    return number


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
