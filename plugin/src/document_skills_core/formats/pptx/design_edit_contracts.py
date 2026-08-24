"""Closed contracts for native PPTX master, layout, and theme edits."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT
from .design_contracts import parse_theme

DESIGN_EDIT_TYPES = frozenset({
    "layout_add",
    "layout_copy",
    "layout_delete",
    "master_add",
    "master_copy",
    "master_delete",
    "theme_update",
})

_LAYOUT_TYPES = {"blank", "cust", "obj", "title", "twoObj"}
_PLACEHOLDER_TYPES = {
    "body", "chart", "clipArt", "ctrTitle", "dgm", "media", "obj", "pic",
    "subTitle", "tbl", "title",
}
_PART_PATTERN = re.compile(r"^ppt/(slideMasters/slideMaster|slideLayouts/slideLayout)\d+\.xml$")


def parse_design_edit(edit: dict[str, Any], index: int) -> dict[str, Any]:
    edit_type = edit.get("type")
    if edit_type not in DESIGN_EDIT_TYPES:
        _invalid("Unknown PPTX design edit type.", field=f"edits.{index}.type")
    field = f"edits.{index}"
    if edit_type == "master_add":
        _exact_keys(edit, {"master", "type"}, field)
        master = edit.get("master")
        if type(master) is not dict:
            _invalid("master_add requires a master object.", field=f"{field}.master")
        _exact_keys(master, {"layout", "name", "theme"}, f"{field}.master")
        return {
            "master": {
                "layout": _parse_layout(master.get("layout"), f"{field}.master.layout"),
                "name": _text(master.get("name", "Custom Master"), f"{field}.master.name", False),
                "theme": parse_theme(master.get("theme"), f"{field}.master.theme"),
            },
            "type": edit_type,
        }
    if edit_type in {"master_copy", "master_delete"}:
        _exact_keys(edit, {"master", "type"}, field)
        return {
            "master": _part(edit.get("master"), "slideMasters", f"{field}.master"),
            "type": edit_type,
        }
    if edit_type == "layout_add":
        _exact_keys(edit, {"layout", "master", "type"}, field)
        return {
            "layout": _parse_layout(edit.get("layout"), f"{field}.layout"),
            "master": _part(edit.get("master"), "slideMasters", f"{field}.master"),
            "type": edit_type,
        }
    if edit_type == "layout_copy":
        _exact_keys(edit, {"layout", "master", "type"}, field)
        return {
            "layout": _part(edit.get("layout"), "slideLayouts", f"{field}.layout"),
            "master": _part(edit.get("master"), "slideMasters", f"{field}.master"),
            "type": edit_type,
        }
    if edit_type == "layout_delete":
        _exact_keys(edit, {"layout", "type"}, field)
        return {
            "layout": _part(edit.get("layout"), "slideLayouts", f"{field}.layout"),
            "type": edit_type,
        }
    _exact_keys(edit, {"master", "theme", "type"}, field)
    return {
        "master": _part(edit.get("master"), "slideMasters", f"{field}.master"),
        "theme": parse_theme(edit.get("theme"), f"{field}.theme"),
        "type": edit_type,
    }


def _parse_layout(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Layout definition must be an object.", field=field)
    _exact_keys(
        value,
        {
            "background", "date", "footer", "name", "placeholders",
            "show_master_shapes", "slide_number", "type",
        },
        field,
    )
    layout_type = _text(value.get("type", "cust"), f"{field}.type", False)
    if layout_type not in _LAYOUT_TYPES:
        _invalid("Unsupported PresentationML layout type.", field=f"{field}.type")
    placeholders = value.get("placeholders", [])
    if type(placeholders) is not list or len(placeholders) > 64:
        _invalid("Layout placeholders must be a bounded array.", field=f"{field}.placeholders")
    parsed_placeholders = [
        _parse_placeholder(item, f"{field}.placeholders.{index}")
        for index, item in enumerate(placeholders)
    ]
    keys = [(item["type"], item["idx"]) for item in parsed_placeholders]
    if len(keys) != len(set(keys)):
        _invalid("Layout placeholder type/index pairs must be unique.", field=f"{field}.placeholders")
    background = value.get("background")
    if background is not None:
        background = _color(background, f"{field}.background")
    show_master = value.get("show_master_shapes", True)
    if type(show_master) is not bool:
        _invalid("show_master_shapes must be boolean.", field=f"{field}.show_master_shapes")
    return {
        "background": background,
        "date": _parse_footer_slot(value.get("date"), "date", f"{field}.date"),
        "footer": _parse_footer_slot(value.get("footer"), "footer", f"{field}.footer"),
        "name": _text(value.get("name", "Custom Layout"), f"{field}.name", False),
        "placeholders": parsed_placeholders,
        "show_master_shapes": show_master,
        "slide_number": _parse_footer_slot(
            value.get("slide_number"), "slide_number", f"{field}.slide_number"
        ),
        "type": layout_type,
    }


def _parse_placeholder(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Layout placeholder must be an object.", field=field)
    _exact_keys(value, {"frame", "idx", "name", "type"}, field)
    placeholder_type = _text(value.get("type"), f"{field}.type", False)
    if placeholder_type not in _PLACEHOLDER_TYPES:
        _invalid("Unsupported layout placeholder type.", field=f"{field}.type")
    return {
        "frame": _frame(value.get("frame"), f"{field}.frame"),
        "idx": _integer(value.get("idx"), 0, 100_000, f"{field}.idx"),
        "name": _text(value.get("name", placeholder_type), f"{field}.name", False),
        "type": placeholder_type,
    }


def _parse_footer_slot(value: Any, kind: str, field: str) -> dict[str, Any]:
    defaults = {
        "date": {"x": 457_200, "y": 6_400_800, "cx": 2_743_200, "cy": 274_320},
        "footer": {"x": 3_200_400, "y": 6_400_800, "cx": 3_657_600, "cy": 274_320},
        "slide_number": {"x": 7_772_400, "y": 6_400_800, "cx": 914_400, "cy": 274_320},
    }
    if value is None:
        return {"enabled": False, "frame": defaults[kind], "text": ""}
    if type(value) is not dict:
        _invalid("Layout footer slot must be an object.", field=field)
    _exact_keys(value, {"enabled", "frame", "text"}, field)
    enabled = value.get("enabled", True)
    if type(enabled) is not bool:
        _invalid("Layout footer slot enabled must be boolean.", field=f"{field}.enabled")
    return {
        "enabled": enabled,
        "frame": _frame(value.get("frame", defaults[kind]), f"{field}.frame"),
        "text": _text(value.get("text", ""), f"{field}.text"),
    }


def _frame(value: Any, field: str) -> dict[str, int]:
    if type(value) is not dict:
        _invalid("Placeholder frame must be an object.", field=field)
    _exact_keys(value, {"cx", "cy", "x", "y"}, field)
    return {
        "x": _integer(value.get("x"), 0, 100_000_000, f"{field}.x"),
        "y": _integer(value.get("y"), 0, 100_000_000, f"{field}.y"),
        "cx": _integer(value.get("cx"), 1, 100_000_000, f"{field}.cx"),
        "cy": _integer(value.get("cy"), 1, 100_000_000, f"{field}.cy"),
    }


def _part(value: Any, kind: str, field: str) -> str:
    part = _text(value, field, False)
    if not _PART_PATTERN.fullmatch(part) or f"ppt/{kind}/" not in part:
        _invalid("Design selector must be an exact master/layout part name.", field=field)
    return part


def _color(value: Any, field: str) -> str:
    color = _text(value, field, False).lstrip("#").upper()
    if len(color) != 6 or any(character not in "0123456789ABCDEF" for character in color):
        _invalid("Color must be a six-digit RGB value.", field=field)
    return color


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PPTX design edit field.", field=field, unknown=unknown)


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
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
