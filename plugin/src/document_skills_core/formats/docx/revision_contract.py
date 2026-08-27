"""Closed public filters and selectors for tracked-revision operations."""

from datetime import datetime
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT

_REVISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_REVISION_TYPES = frozenset({"insertion", "deletion", "move-from", "move-to"})
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_revisions_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"filters", "max_revisions", "scope"})
    parsed: dict[str, Any] = {
        "max_revisions": _integer(value.get("max_revisions", 1_000), 1, 10_000),
    }
    if "filters" in value:
        parsed["filters"] = _parse_filters(value["filters"])
    if "scope" in value:
        parsed["scope"] = _parse_scope(value["scope"])
    return parsed


def parse_revisions_apply(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"action", "filters", "revision_ids", "scope"})
    action = value.get("action")
    if action not in {"accept", "reject"}:
        _invalid("Revision action must be 'accept' or 'reject'.", field="action")
    raw_ids = value.get("revision_ids", [])
    if type(raw_ids) is not list or len(raw_ids) > 1_000:
        _invalid("revision_ids must be a bounded array.", field="revision_ids")
    revision_ids: list[str] = []
    for index, raw_id in enumerate(raw_ids):
        if type(raw_id) is not str or _REVISION_ID.fullmatch(raw_id) is None:
            _invalid(
                "Revision ids must be bounded portable identifiers.",
                field=f"revision_ids.{index}",
            )
        if raw_id in revision_ids:
            _invalid("Revision ids must be unique.", field=f"revision_ids.{index}")
        revision_ids.append(raw_id)
    parsed: dict[str, Any] = {"action": action, "revision_ids": revision_ids}
    if "filters" in value:
        parsed["filters"] = _parse_filters(value["filters"])
    if "scope" in value:
        parsed["scope"] = _parse_scope(value["scope"])
    return parsed


def _parse_filters(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Revision filters must be an object.", field="filters")
    _exact_keys(value, {"authors", "date_from", "date_to", "types"})
    parsed: dict[str, Any] = {}
    if "authors" in value:
        parsed["authors"] = _unique_text_array(
            value["authors"], "filters.authors", maximum=64, text_ceiling=1_024
        )
    if "types" in value:
        types = _unique_text_array(
            value["types"], "filters.types", maximum=4, text_ceiling=32
        )
        if any(item not in _REVISION_TYPES for item in types):
            _invalid("Revision filters contain an unknown type.", field="filters.types")
        parsed["types"] = types
    date_from = _optional_date(value.get("date_from"), "filters.date_from")
    date_to = _optional_date(value.get("date_to"), "filters.date_to")
    if date_from is not None:
        parsed["date_from"] = date_from
    if date_to is not None:
        parsed["date_to"] = date_to
    if date_from is not None and date_to is not None and date_from > date_to:
        _invalid("Revision date_from must not be later than date_to.", field="filters")
    return parsed


def _parse_scope(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Revision scope must be an object.", field="scope")
    if value.get("story") != "body":
        _invalid("Revision scopes currently target only the body story.", field="scope.story")
    range_name = value.get("range")
    if range_name == "paragraph":
        _exact_keys(value, {"expected_text", "paragraph_index", "range", "story"})
        return {
            "story": "body",
            "range": "paragraph",
            "paragraph_index": _integer(value.get("paragraph_index"), 0, 10_000),
            "expected_text": _text(value.get("expected_text"), "scope.expected_text"),
        }
    if range_name == "table":
        _exact_keys(
            value,
            {"expected_table_sha256", "range", "story", "table_index"},
        )
        digest = value.get("expected_table_sha256")
        if type(digest) is not str or _SHA256.fullmatch(digest) is None:
            _invalid(
                "Revision table scope requires a 64-digit SHA-256.",
                field="scope.expected_table_sha256",
            )
        return {
            "story": "body",
            "range": "table",
            "table_index": _integer(value.get("table_index"), 0, 10_000),
            "expected_table_sha256": digest.casefold(),
        }
    _invalid("Revision scope range must be 'paragraph' or 'table'.", field="scope.range")


def _unique_text_array(
    value: Any,
    field: str,
    *,
    maximum: int,
    text_ceiling: int,
) -> list[str]:
    if type(value) is not list or not 1 <= len(value) <= maximum:
        _invalid("Revision filter must be a non-empty bounded array.", field=field)
    parsed: list[str] = []
    for index, item in enumerate(value):
        text = _text(item, f"{field}.{index}", maximum_bytes=text_ceiling, allow_empty=False)
        if text in parsed:
            _invalid("Revision filter values must be unique.", field=f"{field}.{index}")
        parsed.append(text)
    return parsed


def _optional_date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field, maximum_bytes=20, allow_empty=False)
    try:
        datetime.strptime(text, _DATE_FORMAT)
    except ValueError:
        _invalid("Revision dates must be canonical UTC timestamps.", field=field)
    return text


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


def _text(
    value: Any,
    field: str,
    *,
    maximum_bytes: int = MAX_ARGUMENT_TEXT,
    allow_empty: bool = True,
) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > maximum_bytes:
        _invalid("Text exceeds the operation byte limit.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown revision operation argument.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
