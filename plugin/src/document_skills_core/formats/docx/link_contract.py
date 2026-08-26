"""Closed public payloads for bookmarks and internal hyperlinks."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_BOOKMARK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")


def parse_bookmark_name(value: Any, field: str) -> str:
    if type(value) is not str or _BOOKMARK.fullmatch(value) is None:
        _invalid("Bookmark name must be a bounded ASCII Word name.", field=field)
    return value


def parse_link_text(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        _invalid("Hyperlink text must be non-empty text.", field=field)
    if len(value.encode("utf-8", errors="strict")) > 32_768:
        _invalid("Hyperlink text exceeds the byte limit.", field=field)
    return value


def parse_link_match(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.match"
    if type(value) is not dict:
        _invalid("Hyperlink match must be an object.", field=field)
    extras = sorted(set(value) - {"bookmark_name", "expected_matches", "text"})
    if extras:
        _invalid("Unexpected hyperlink match keys.", fields=extras)
    expected = value.get("expected_matches")
    if type(expected) is not int or not 1 <= expected <= 1_000:
        _invalid("Hyperlink expected_matches must be 1 through 1000.", field=f"{field}.expected_matches")
    return {
        "bookmark_name": parse_bookmark_name(value.get("bookmark_name"), f"{field}.bookmark_name"),
        "text": parse_link_text(value.get("text"), f"{field}.text"),
        "expected_matches": expected,
    }


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.REQUEST_INVALID, message, status="invalid_request", details=details)
