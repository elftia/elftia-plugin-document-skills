"""Closed contracts for bounded PDF page-list edits.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_PAGES


def parse_page_sequence_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    unknown = sorted(set(primitive) - {"type", "pages"})
    field = f"primitives.{index}.pages"
    if unknown:
        _invalid("Unknown page_sequence argument.", field=field, unknown=unknown)
    pages = primitive.get("pages")
    if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
        _invalid("page_sequence.pages must be a non-empty bounded array.", field=field)
    parsed: list[int] = []
    for page in pages:
        if type(page) is not int or type(page) is bool or not 1 <= page <= MAX_PAGES:
            _invalid("page_sequence page number is outside the bound.", field=field)
        parsed.append(page)
    if len(set(parsed)) != len(parsed):
        _invalid("page_sequence.pages cannot contain duplicates.", field=field)
    return {"type": "page_sequence", "pages": parsed}


def parse_page_labels_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    unknown = sorted(set(primitive) - {"type", "action", "ranges"})
    field = f"primitives.{index}"
    if unknown:
        _invalid("Unknown page_labels argument.", field=field, unknown=unknown)
    action = primitive.get("action")
    if action not in {"set", "clear"}:
        _invalid("page_labels.action must be set or clear.", field=f"{field}.action")
    ranges = primitive.get("ranges")
    if action == "clear":
        if ranges not in (None, []):
            _invalid("page_labels clear does not accept ranges.", field=f"{field}.ranges")
        return {"type": "page_labels", "action": "clear", "ranges": []}
    if type(ranges) is not list or not ranges or len(ranges) > 128:
        _invalid("page_labels set requires a non-empty bounded ranges array.", field=f"{field}.ranges")
    parsed_ranges = [
        _parse_label_range(item, field=f"{field}.ranges.{range_index}")
        for range_index, item in enumerate(ranges)
    ]
    pages = [item["page"] for item in parsed_ranges]
    if pages[0] != 1 or pages != sorted(set(pages)):
        _invalid(
            "page_labels ranges must start at page 1 and be strictly increasing.",
            field=f"{field}.ranges",
        )
    return {"type": "page_labels", "action": "set", "ranges": parsed_ranges}


def _parse_label_range(value: Any, *, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Page-label range must be an object.", field=field)
    unknown = sorted(set(value) - {"page", "style", "prefix", "start"})
    if unknown:
        _invalid("Unknown page-label range argument.", field=field, unknown=unknown)
    style = value.get("style")
    if style not in {
        "decimal", "roman-upper", "roman-lower", "letters-upper", "letters-lower", "none",
    }:
        _invalid("Unknown page-label numbering style.", field=f"{field}.style")
    prefix = value.get("prefix", "")
    if type(prefix) is not str or len(prefix) > MAX_ARGUMENT_TEXT:
        _invalid("Page-label prefix is invalid or exceeds the bound.", field=f"{field}.prefix")
    try:
        prefix.encode("latin-1", errors="strict")
    except UnicodeEncodeError as error:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Core page-label prefixes currently require Latin-1 text.",
            status="enhancement_required",
            details={"field": f"{field}.prefix", "capability": "pdf.page-label-unicode"},
        ) from error
    page = _bounded_integer(value.get("page"), 1, MAX_PAGES, f"{field}.page")
    start = _bounded_integer(value.get("start", 1), 1, 1_000_000, f"{field}.start")
    return {"page": page, "style": style, "prefix": prefix, "start": start}


def _bounded_integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or type(value) is bool or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
