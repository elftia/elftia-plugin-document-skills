"""Closed public payload for the bounded typed DOCX edit transaction."""

import math
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_control_contract import parse_content_control_update
from .field_contract import parse_field_insert, parse_field_refresh, parse_toc_insert
from .image_contract import parse_edit_image, parse_image_target
from .link_contract import parse_bookmark_name, parse_link_match, parse_link_text
from .note_contract import parse_note_delete, parse_note_insert
from .section_contract import (
    parse_section_target,
    parse_section_updates,
    parse_story_hash,
    parse_story_text,
)
from .table_contract import (
    parse_cell_selector,
    parse_cells,
    parse_merge_range,
    parse_row_selector,
    parse_table_payload,
    parse_table_target,
    parse_table_text,
)

_HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")
_STYLE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_HIGHLIGHTS = {
    "black", "blue", "cyan", "darkBlue", "darkCyan", "darkGray", "darkGreen",
    "darkMagenta", "darkRed", "darkYellow", "green", "lightGray", "magenta",
    "none", "red", "white", "yellow",
}


def parse_edit(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"edits", "keep_vba"})
    keep_vba = value.get("keep_vba", False)
    if type(keep_vba) is not bool:
        _invalid("keep_vba must be boolean.", field="keep_vba")
    edits = value.get("edits")
    if type(edits) is not list or not edits or len(edits) > 100:
        _invalid("edits must be a non-empty bounded array.", field="edits")
    parsed: list[dict[str, Any]] = []
    for index, edit in enumerate(edits):
        if type(edit) is not dict:
            _invalid("Each edit must be an object.", field=f"edits.{index}")
        edit_type = edit.get("type")
        if edit_type == "paragraph_delete":
            _exact_keys(edit, {"target", "type"})
            parsed.append({"type": edit_type, "target": _paragraph_target(edit.get("target"), index)})
        elif edit_type == "paragraph_insert":
            _exact_keys(edit, {"position", "style", "target", "text", "type"})
            position = _position(edit.get("position"), index, "Paragraph")
            style = edit.get("style", "Normal")
            _paragraph_style(style, f"edits.{index}.style")
            parsed.append({
                "type": edit_type,
                "target": _paragraph_target(edit.get("target"), index),
                "position": position,
                "text": _text(edit.get("text"), f"edits.{index}.text", 32_768),
                "style": style,
            })
        elif edit_type == "paragraph_style":
            _exact_keys(edit, {"style", "target", "type"})
            style = edit.get("style")
            _paragraph_style(style, f"edits.{index}.style")
            parsed.append({"type": edit_type, "target": _formatting_target(edit.get("target"), index), "style": style})
        elif edit_type == "run_style":
            _exact_keys(edit, {"match", "style", "target", "type"})
            parsed.append({
                "type": edit_type,
                "target": _formatting_target(edit.get("target"), index),
                "match": _run_match(edit.get("match"), index),
                "style": _run_style(edit.get("style"), index),
            })
        elif edit_type == "image_insert":
            _exact_keys(edit, {"image", "position", "target", "type"})
            parsed.append({
                "type": edit_type,
                "target": _paragraph_target(edit.get("target"), index),
                "position": _position(edit.get("position"), index, "Image"),
                "image": parse_edit_image(edit.get("image"), index),
            })
        elif edit_type == "image_replace":
            _exact_keys(edit, {"image", "target", "type"})
            parsed.append({"type": edit_type, "target": parse_image_target(edit.get("target"), index), "image": parse_edit_image(edit.get("image"), index)})
        elif edit_type == "table_insert":
            _exact_keys(edit, {"position", "table", "target", "type"})
            parsed.append({
                "type": edit_type,
                "target": _paragraph_target(edit.get("target"), index),
                "position": _position(edit.get("position"), index, "Table"),
                "table": parse_table_payload(edit.get("table"), f"edits.{index}.table"),
            })
        elif edit_type == "table_cell_update":
            _exact_keys(edit, {"cell", "target", "text", "type"})
            parsed.append({
                "type": edit_type,
                "target": parse_table_target(edit.get("target"), index),
                "cell": parse_cell_selector(edit.get("cell"), index),
                "text": parse_table_text(edit.get("text"), f"edits.{index}.text"),
            })
        elif edit_type == "table_row_insert":
            _exact_keys(edit, {"anchor", "cells", "position", "target", "type"})
            parsed.append({
                "type": edit_type,
                "target": parse_table_target(edit.get("target"), index),
                "anchor": parse_row_selector(edit.get("anchor"), index, "anchor"),
                "position": _position(edit.get("position"), index, "Table row"),
                "cells": parse_cells(edit.get("cells"), f"edits.{index}.cells"),
            })
        elif edit_type == "table_row_delete":
            _exact_keys(edit, {"row", "target", "type"})
            parsed.append({"type": edit_type, "target": parse_table_target(edit.get("target"), index), "row": parse_row_selector(edit.get("row"), index, "row")})
        elif edit_type == "table_cells_merge":
            _exact_keys(edit, {"range", "target", "text", "type"})
            parsed.append({
                "type": edit_type,
                "target": parse_table_target(edit.get("target"), index),
                "range": parse_merge_range(edit.get("range"), index),
                "text": parse_table_text(edit.get("text"), f"edits.{index}.text"),
            })
        elif edit_type == "table_cell_split":
            _exact_keys(edit, {"cell", "target", "texts", "type"})
            parsed.append({
                "type": edit_type,
                "target": parse_table_target(edit.get("target"), index),
                "cell": parse_cell_selector(edit.get("cell"), index),
                "texts": parse_cells(edit.get("texts"), f"edits.{index}.texts", minimum=2),
            })
        elif edit_type == "section_update":
            _exact_keys(edit, {"target", "type", "updates"})
            parsed.append({
                "type": edit_type,
                "target": parse_section_target(edit.get("target"), index),
                "updates": parse_section_updates(edit.get("updates"), index),
            })
        elif edit_type == "header_footer_update":
            link = edit.get("link_to_previous")
            allowed = {
                "expected_story_sha256", "kind", "link_to_previous", "target",
                "type", "variant",
            }
            if link is False:
                allowed.add("text")
            _exact_keys(edit, allowed)
            if type(link) is not bool:
                _invalid("link_to_previous must be boolean.", field=f"edits.{index}.link_to_previous")
            if edit.get("kind") not in {"header", "footer"}:
                _invalid("Header/footer kind is invalid.", field=f"edits.{index}.kind")
            if edit.get("variant") not in {"default", "even", "first"}:
                _invalid("Header/footer variant is invalid.", field=f"edits.{index}.variant")
            parsed.append({
                "type": edit_type,
                "target": parse_section_target(edit.get("target"), index),
                "kind": edit["kind"],
                "variant": edit["variant"],
                "expected_story_sha256": parse_story_hash(edit.get("expected_story_sha256"), index),
                "link_to_previous": link,
                "text": parse_story_text(edit.get("text"), index) if not link else None,
            })
        elif edit_type == "bookmark_insert":
            _exact_keys(edit, {"name", "range", "target", "type"})
            if edit.get("range") != "paragraph":
                _invalid("Bookmark range must be 'paragraph'.", field=f"edits.{index}.range")
            parsed.append({
                "type": edit_type,
                "target": _paragraph_target(edit.get("target"), index),
                "name": parse_bookmark_name(edit.get("name"), f"edits.{index}.name"),
                "range": "paragraph",
            })
        elif edit_type == "hyperlink_insert":
            _exact_keys(edit, {"bookmark_name", "placement", "target", "text", "type"})
            if edit.get("placement") not in {"append", "prepend"}:
                _invalid("Hyperlink placement must be append or prepend.", field=f"edits.{index}.placement")
            parsed.append({
                "type": edit_type,
                "target": _paragraph_target(edit.get("target"), index),
                "bookmark_name": parse_bookmark_name(edit.get("bookmark_name"), f"edits.{index}.bookmark_name"),
                "placement": edit["placement"],
                "text": parse_link_text(edit.get("text"), f"edits.{index}.text"),
            })
        elif edit_type == "hyperlink_update":
            _exact_keys(edit, {"bookmark_name", "match", "target", "text", "type"})
            if "bookmark_name" not in edit and "text" not in edit:
                _invalid("Hyperlink update requires text or bookmark_name.", field=f"edits.{index}")
            parsed.append({
                "type": edit_type,
                "target": _paragraph_target(edit.get("target"), index),
                "match": parse_link_match(edit.get("match"), index),
                "bookmark_name": (
                    parse_bookmark_name(edit["bookmark_name"], f"edits.{index}.bookmark_name")
                    if "bookmark_name" in edit else None
                ),
                "text": (
                    parse_link_text(edit["text"], f"edits.{index}.text")
                    if "text" in edit else None
                ),
            })
        elif edit_type == "field_insert":
            parsed.append(parse_field_insert(edit, index, _paragraph_target))
        elif edit_type == "toc_insert":
            parsed.append(parse_toc_insert(edit, index, _paragraph_target))
        elif edit_type == "field_refresh":
            parsed.append(parse_field_refresh(edit, index))
        elif edit_type == "note_insert":
            parsed.append(parse_note_insert(edit, index, _paragraph_target))
        elif edit_type == "note_delete":
            parsed.append(parse_note_delete(edit, index))
        elif edit_type == "content_control_text_update":
            parsed.append(parse_content_control_update(edit, index))
        elif edit_type == "paragraph_numbering_update":
            _exact_keys(edit, {"numbering", "target", "type"})
            numbering = edit.get("numbering")
            if type(numbering) is not dict:
                _invalid("Numbering must be an object.", field=f"edits.{index}.numbering")
            _exact_keys(numbering, {"level", "num_id"})
            num_id = numbering.get("num_id")
            level = numbering.get("level")
            if type(num_id) is not str or not num_id.isdigit() or not 1 <= int(num_id) <= 2_147_483_647:
                _invalid("Numbering num_id must be a positive decimal id.", field=f"edits.{index}.numbering.num_id")
            if type(level) is not int or not 0 <= level <= 8:
                _invalid("Numbering level must be between 0 and 8.", field=f"edits.{index}.numbering.level")
            parsed.append(
                {
                    "type": edit_type,
                    "target": _paragraph_target(edit.get("target"), index),
                    "numbering": {"num_id": num_id, "level": level},
                }
            )
        else:
            _invalid("Unsupported DOCX edit primitive.", field=f"edits.{index}.type")
    result: dict[str, Any] = {"edits": parsed}
    if "keep_vba" in value:
        result["keep_vba"] = keep_vba
    return result


def _paragraph_target(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.target"
    if type(value) is not dict:
        _invalid("Paragraph target must be an object.", field=field)
    _exact_keys(value, {"expected_text", "paragraph_index", "story"})
    if value.get("story") != "body":
        _invalid("This edit primitive targets only the body story.", field=f"{field}.story")
    return {
        "story": "body",
        "paragraph_index": _integer(value.get("paragraph_index"), 0, 10_000, f"{field}.paragraph_index"),
        "expected_text": _text(value.get("expected_text"), f"{field}.expected_text", 32_768),
    }


def _formatting_target(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.target"
    if type(value) is not dict:
        _invalid("Formatting target must be an object.", field=field)
    _exact_keys(value, {"expected_text", "paragraph_index", "part", "story"})
    story = value.get("story")
    if story not in {"body", "footer", "header"}:
        _invalid("Formatting story is invalid.", field=f"{field}.story")
    part = value.get("part")
    if story == "body":
        if part is not None and part != "word/document.xml":
            _invalid("Body formatting part is invalid.", field=f"{field}.part")
    elif (
        type(part) is not str
        or re.fullmatch(rf"word/{story}[A-Za-z0-9_.-]{{0,127}}\.xml", part) is None
    ):
        _invalid(
            "Header/footer formatting requires its public story part.",
            field=f"{field}.part",
        )
    result = {
        "story": story,
        "paragraph_index": _integer(
            value.get("paragraph_index"),
            0,
            10_000,
            f"{field}.paragraph_index",
        ),
        "expected_text": _text(
            value.get("expected_text"),
            f"{field}.expected_text",
            32_768,
        ),
    }
    if part is not None:
        result["part"] = part
    return result


def _run_match(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.match"
    if type(value) is not dict:
        _invalid("Run style match must be an object.", field=field)
    _exact_keys(value, {"expected_matches", "text"})
    return {
        "text": _text(value.get("text"), f"{field}.text", 32_768, allow_empty=False),
        "expected_matches": _integer(value.get("expected_matches"), 1, 1_000, f"{field}.expected_matches"),
    }


def _run_style(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.style"
    if type(value) is not dict or not value:
        _invalid("Run style must be a non-empty object.", field=field)
    _exact_keys(value, {"bold", "color", "font_family", "font_size_pt", "highlight", "italic", "underline"})
    parsed: dict[str, Any] = {}
    for name in ("bold", "italic", "underline"):
        if name in value:
            if type(value[name]) is not bool:
                _invalid("Value must be boolean.", field=f"{field}.{name}")
            parsed[name] = value[name]
    if "font_family" in value:
        family = _text(value["font_family"], f"{field}.font_family", 256, allow_empty=False)
        if any(ord(character) < 32 for character in family):
            _invalid("Font family contains a control character.", field=f"{field}.font_family")
        parsed["font_family"] = family
    if "font_size_pt" in value:
        size = value["font_size_pt"]
        if type(size) not in {int, float} or not math.isfinite(float(size)) or not 1 <= float(size) <= 400 or not (float(size) * 2).is_integer():
            _invalid("Font size must be 1–400 points in half-point increments.", field=f"{field}.font_size_pt")
        parsed["font_size_pt"] = size
    if "color" in value:
        color = value["color"]
        if type(color) is not str or _HEX_COLOR.fullmatch(color) is None:
            _invalid("Run color must be a six-digit hexadecimal value.", field=f"{field}.color")
        parsed["color"] = color.upper()
    if "highlight" in value:
        if value["highlight"] not in _HIGHLIGHTS:
            _invalid("Run highlight is not an accepted Word highlight value.", field=f"{field}.highlight")
        parsed["highlight"] = value["highlight"]
    return parsed


def _position(value: Any, edit_index: int, label: str) -> str:
    if value not in {"before", "after"}:
        _invalid(f"{label} insert position must be 'before' or 'after'.", field=f"edits.{edit_index}.position")
    return value


def _paragraph_style(value: Any, field: str) -> None:
    if type(value) is not str or _STYLE_ID.fullmatch(value) is None:
        _invalid("Paragraph style id is not portable.", field=field)


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _text(value: Any, field: str, maximum: int, *, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Expected a text value.", field=field)
    if len(value.encode("utf-8", errors="strict")) > maximum:
        _invalid("Text exceeds the operation byte limit.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown DOCX operation argument.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.REQUEST_INVALID, message, status="invalid_request", details=details)
