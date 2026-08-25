"""Closed contracts for bounded PDF page-list edits.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import MAX_ARGUMENT_TEXT, MAX_PAGES
from .font_contracts import parse_sha256


def parse_merge_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """Parse a bounded list of hash-bound PDF merge inputs."""
    field = f"primitives.{index}.inputs"
    unknown = sorted(set(primitive) - {"type", "inputs"})
    if unknown:
        _invalid("Unknown merge argument.", field=field, unknown=unknown)
    inputs = primitive.get("inputs")
    if type(inputs) is not list or not 2 <= len(inputs) <= 10:
        _invalid("merge.inputs must contain 2-10 hash-bound inputs.", field=field)
    parsed: list[dict[str, str]] = []
    for input_index, item in enumerate(inputs):
        item_field = f"{field}.{input_index}"
        if type(item) is not dict:
            _invalid("Each merge input must be an object.", field=item_field)
        item_unknown = sorted(set(item) - {"input", "source_sha256"})
        if item_unknown:
            _invalid(
                "Unknown merge input argument.",
                field=item_field,
                unknown=item_unknown,
            )
        source = item.get("input")
        if type(source) is not str or not source or len(source) > MAX_ARGUMENT_TEXT:
            _invalid("merge input must be a bounded path.", field=f"{item_field}.input")
        resolved = Path(source).expanduser().resolve(strict=False)
        if resolved.suffix.casefold() != ".pdf":
            _invalid("merge input must use the .pdf extension.", field=f"{item_field}.input")
        source_sha256 = parse_sha256(
            item.get("source_sha256"),
            f"{item_field}.source_sha256",
        )
        if source_sha256 is None:
            _invalid(
                "merge input source_sha256 is required.",
                field=f"{item_field}.source_sha256",
            )
        if any(same_path(resolved, Path(existing["input"])) for existing in parsed):
            _invalid("merge inputs must be unique.", field=f"{item_field}.input")
        parsed.append({
            "input": str(resolved),
            "source_sha256": source_sha256,
        })
    return {"type": "merge", "inputs": parsed}


def parse_page_insert_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    field = f"primitives.{index}"
    unknown = sorted(
        set(primitive) - {"type", "input", "source_sha256", "at", "pages"}
    )
    if unknown:
        _invalid("Unknown page_insert argument.", field=field, unknown=unknown)
    source = primitive.get("input")
    if type(source) is not str or not source or len(source) > MAX_ARGUMENT_TEXT:
        _invalid("page_insert.input must be a bounded path.", field=f"{field}.input")
    source_sha256 = parse_sha256(
        primitive.get("source_sha256"),
        f"{field}.source_sha256",
    )
    if source_sha256 is None:
        _invalid(
            "page_insert.source_sha256 is required.",
            field=f"{field}.source_sha256",
        )
    pages = primitive.get("pages")
    parsed_pages = None
    if pages is not None:
        if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
            _invalid(
                "page_insert.pages must be a non-empty bounded array.",
                field=f"{field}.pages",
            )
        parsed_pages = [
            _bounded_integer(page, 1, MAX_PAGES, f"{field}.pages")
            for page in pages
        ]
        if len(parsed_pages) != len(set(parsed_pages)):
            _invalid(
                "page_insert.pages cannot contain duplicates.",
                field=f"{field}.pages",
            )
    return {
        "type": "page_insert",
        "input": str(Path(source).expanduser().resolve(strict=False)),
        "source_sha256": source_sha256,
        "at": _bounded_integer(primitive.get("at"), 1, MAX_PAGES, f"{field}.at"),
        "pages": parsed_pages,
    }


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
