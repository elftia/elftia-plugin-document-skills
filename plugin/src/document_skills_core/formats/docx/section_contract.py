"""Closed public payloads for section and header/footer edits."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_MARGIN_KEYS = {
    "bottom_twips", "footer_twips", "gutter_twips", "header_twips",
    "left_twips", "right_twips", "top_twips",
}


def parse_section_target(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.target"
    if type(value) is not dict:
        _invalid("Section target must be an object.", field=field)
    _exact_keys(value, {"expected_section_sha256", "section_index", "story"})
    if value.get("story") != "body":
        _invalid("Section edits target only the body story.", field=f"{field}.story")
    digest = value.get("expected_section_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid("Expected section SHA-256 must be hexadecimal.", field=f"{field}.expected_section_sha256")
    return {
        "story": "body",
        "section_index": _integer(value.get("section_index"), 0, 10_000, f"{field}.section_index"),
        "expected_section_sha256": digest.casefold(),
    }


def parse_section_updates(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.updates"
    if type(value) is not dict or not value:
        _invalid("Section updates must be a non-empty object.", field=field)
    _exact_keys(value, {"break_type", "margins", "orientation", "page_size"})
    parsed: dict[str, Any] = {}
    if "orientation" in value:
        if value["orientation"] not in {"portrait", "landscape"}:
            _invalid("Section orientation must be portrait or landscape.", field=f"{field}.orientation")
        parsed["orientation"] = value["orientation"]
    if "break_type" in value:
        if value["break_type"] not in {"continuous", "evenPage", "nextColumn", "nextPage", "oddPage"}:
            _invalid("Section break type is invalid.", field=f"{field}.break_type")
        parsed["break_type"] = value["break_type"]
    if "page_size" in value:
        page_size = value["page_size"]
        if type(page_size) is not dict:
            _invalid("Section page_size must be an object.", field=f"{field}.page_size")
        _exact_keys(page_size, {"height_twips", "width_twips"})
        parsed["page_size"] = {
            "width_twips": _integer(page_size.get("width_twips"), 1, 31_680, f"{field}.page_size.width_twips"),
            "height_twips": _integer(page_size.get("height_twips"), 1, 31_680, f"{field}.page_size.height_twips"),
        }
    if "margins" in value:
        margins = value["margins"]
        if type(margins) is not dict or not margins:
            _invalid("Section margins must be a non-empty object.", field=f"{field}.margins")
        _exact_keys(margins, _MARGIN_KEYS)
        parsed["margins"] = {
            name: _integer(number, 0, 31_680, f"{field}.margins.{name}")
            for name, number in margins.items()
        }
    return parsed


def parse_story_hash(value: Any, edit_index: int) -> str | None:
    if value is None:
        return None
    field = f"edits.{edit_index}.expected_story_sha256"
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid("Expected header/footer story SHA-256 must be hexadecimal or null.", field=field)
    return value.casefold()


def parse_story_text(value: Any, edit_index: int) -> str:
    field = f"edits.{edit_index}.text"
    if type(value) is not str or len(value.encode("utf-8", errors="strict")) > 32_768:
        _invalid("Header/footer text must be bounded text.", field=field)
    return value


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected DOCX section argument keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.REQUEST_INVALID, message, status="invalid_request", details=details)
