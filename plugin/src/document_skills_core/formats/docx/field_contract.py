"""Closed typed contracts for safe Word fields and TOC edits."""

from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

SAFE_FIELD_KINDS = frozenset({"AUTHOR", "DATE", "NUMPAGES", "PAGE", "TIME", "TITLE"})


def parse_field_insert(
    edit: dict[str, Any],
    index: int,
    parse_target: Callable[[Any, int], dict[str, Any]],
) -> dict[str, Any]:
    _exact_keys(edit, {"field", "placement", "target", "type"})
    field = edit.get("field")
    if type(field) is not dict:
        _invalid("Field must be an object.", field=f"edits.{index}.field")
    _exact_keys(field, {"display_text", "kind"})
    kind = field.get("kind")
    if kind not in SAFE_FIELD_KINDS:
        _invalid("Field kind is not in the safe closed vocabulary.", field=f"edits.{index}.field.kind")
    placement = edit.get("placement")
    if placement not in {"append", "prepend"}:
        _invalid("Field placement must be append or prepend.", field=f"edits.{index}.placement")
    return {
        "type": "field_insert",
        "target": parse_target(edit.get("target"), index),
        "placement": placement,
        "field": {
            "kind": kind,
            "display_text": _text(
                field.get("display_text"),
                f"edits.{index}.field.display_text",
                256,
            ),
        },
    }


def parse_toc_insert(
    edit: dict[str, Any],
    index: int,
    parse_target: Callable[[Any, int], dict[str, Any]],
) -> dict[str, Any]:
    _exact_keys(edit, {"heading_levels", "position", "target", "type"})
    if edit.get("position") not in {"after", "before"}:
        _invalid("TOC position must be before or after.", field=f"edits.{index}.position")
    levels = edit.get("heading_levels")
    if type(levels) is not dict:
        _invalid("TOC heading_levels must be an object.", field=f"edits.{index}.heading_levels")
    _exact_keys(levels, {"end", "start"})
    start = levels.get("start")
    end = levels.get("end")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= 9:
        _invalid("TOC heading levels must satisfy 1 <= start <= end <= 9.", field=f"edits.{index}.heading_levels")
    return {
        "type": "toc_insert",
        "target": parse_target(edit.get("target"), index),
        "position": edit["position"],
        "heading_levels": {"start": start, "end": end},
    }


def parse_field_refresh(edit: dict[str, Any], index: int) -> dict[str, Any]:
    _exact_keys(edit, {"selector", "type"})
    selector = edit.get("selector")
    if type(selector) is not dict:
        _invalid("Field selector must be an object.", field=f"edits.{index}.selector")
    _exact_keys(selector, {"expected_instruction", "field_index", "story"})
    if selector.get("story") != "body":
        _invalid("Field refresh currently targets the body story.", field=f"edits.{index}.selector.story")
    field_index = selector.get("field_index")
    if type(field_index) is not int or not 0 <= field_index <= 10_000:
        _invalid("Field index is out of range.", field=f"edits.{index}.selector.field_index")
    instruction = normalize_instruction(
        _text(
            selector.get("expected_instruction"),
            f"edits.{index}.selector.expected_instruction",
            512,
        )
    )
    kind = field_kind(instruction)
    if kind not in SAFE_FIELD_KINDS | {"TOC"}:
        _invalid("Field refresh accepts only safe fields and TOC.", field=f"edits.{index}.selector.expected_instruction")
    return {
        "type": "field_refresh",
        "selector": {
            "story": "body",
            "field_index": field_index,
            "expected_instruction": instruction,
        },
    }


def normalize_instruction(value: str) -> str:
    return " ".join(value.split())


def field_kind(instruction: str) -> str:
    return instruction.split(" ", 1)[0].upper() if instruction else ""


def _text(value: Any, field: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8", errors="strict")) > maximum:
        _invalid("Expected bounded non-empty text.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected field edit keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
