"""Closed contract for safe text-only content-control updates."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")


def parse_content_control_update(edit: dict[str, Any], index: int) -> dict[str, Any]:
    _exact_keys(edit, {"selector", "text", "type"})
    selector = edit.get("selector")
    if type(selector) is not dict:
        _invalid("Content-control selector must be an object.", field=f"edits.{index}.selector")
    _exact_keys(selector, {"control_index", "expected_sha256", "expected_text", "story"})
    if selector.get("story") != "body":
        _invalid("Content-control update currently targets the body story.", field=f"edits.{index}.selector.story")
    control_index = selector.get("control_index")
    if type(control_index) is not int or not 0 <= control_index <= 10_000:
        _invalid("Content-control index is out of range.", field=f"edits.{index}.selector.control_index")
    digest = selector.get("expected_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid("Content-control selector hash is invalid.", field=f"edits.{index}.selector.expected_sha256")
    return {
        "type": "content_control_text_update",
        "selector": {
            "story": "body",
            "control_index": control_index,
            "expected_sha256": digest.casefold(),
            "expected_text": _text(selector.get("expected_text"), f"edits.{index}.selector.expected_text"),
        },
        "text": _text(edit.get("text"), f"edits.{index}.text"),
    }


def _text(value: Any, field: str) -> str:
    if type(value) is not str or len(value.encode("utf-8", errors="strict")) > 32_768:
        _invalid("Content-control text must be bounded.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected content-control edit keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
