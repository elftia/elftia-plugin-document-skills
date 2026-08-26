"""Closed typed contracts for footnote and endnote edits."""

from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


def parse_note_insert(
    edit: dict[str, Any],
    index: int,
    parse_target: Callable[[Any, int], dict[str, Any]],
) -> dict[str, Any]:
    _exact_keys(edit, {"kind", "placement", "target", "text", "type"})
    kind = _kind(edit.get("kind"), f"edits.{index}.kind")
    placement = edit.get("placement")
    if placement not in {"append", "prepend"}:
        _invalid("Note placement must be append or prepend.", field=f"edits.{index}.placement")
    return {
        "type": "note_insert",
        "target": parse_target(edit.get("target"), index),
        "kind": kind,
        "placement": placement,
        "text": _text(edit.get("text"), f"edits.{index}.text"),
    }


def parse_note_delete(edit: dict[str, Any], index: int) -> dict[str, Any]:
    _exact_keys(edit, {"selector", "type"})
    selector = edit.get("selector")
    if type(selector) is not dict:
        _invalid("Note selector must be an object.", field=f"edits.{index}.selector")
    _exact_keys(selector, {"expected_text", "id", "kind"})
    note_id = selector.get("id")
    if type(note_id) is not str or not note_id.isdigit() or not 1 <= int(note_id) <= 2_147_483_647:
        _invalid("Note id must be a positive decimal identifier.", field=f"edits.{index}.selector.id")
    return {
        "type": "note_delete",
        "selector": {
            "kind": _kind(selector.get("kind"), f"edits.{index}.selector.kind"),
            "id": note_id,
            "expected_text": _text(
                selector.get("expected_text"),
                f"edits.{index}.selector.expected_text",
            ),
        },
    }


def _kind(value: Any, field: str) -> str:
    if value not in {"endnote", "footnote"}:
        _invalid("Note kind must be footnote or endnote.", field=field)
    return value


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8", errors="strict")) > 32_768:
        _invalid("Note text must be bounded and non-empty.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected note edit keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
