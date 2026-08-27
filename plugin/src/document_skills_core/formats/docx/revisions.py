"""Bounded public tracked-revision projections, selectors, and assertions."""

from datetime import datetime
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, qn
from .mapping import document_stories, iter_paragraphs, map_paragraph
from .package import OpcPackage
from .projection import table_selector_sha256

_REVISION_FIELDS = frozenset({"author", "date", "id", "location", "type"})
_LOCATION_FIELDS = frozenset({"paragraph_index", "story", "table_index"})
_REVISION_TYPES = frozenset({"insertion", "deletion", "move-from", "move-to"})
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def project_revision_records(
    raw_records: object,
    *,
    max_revisions: int,
    package: OpcPackage,
    filters: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate provider JSON and return a bounded, selector-ready projection."""

    if type(raw_records) is not list or len(raw_records) > max_revisions + 1:
        _provider_failed("Revision provider returned an invalid bounded array.")
    context = _scope_context(package)
    records: list[dict[str, Any]] = []
    for index, raw_record in enumerate(raw_records):
        if type(raw_record) is not dict or set(raw_record) != _REVISION_FIELDS:
            _provider_failed(
                "Revision provider returned an invalid record shape.",
                record_index=index,
            )
        revision_id = _bounded_text(raw_record["id"], 128, index, "id")
        revision_type = _bounded_text(raw_record["type"], 32, index, "type")
        if revision_type not in _REVISION_TYPES:
            _provider_failed(
                "Revision provider returned an unknown revision type.",
                record_index=index,
            )
        record = {
            "id": revision_id,
            "type": revision_type,
            "author": _bounded_text(raw_record["author"], 1_024, index, "author"),
            "date": _revision_date(raw_record["date"], index),
            "location": _location(raw_record["location"], index, context),
        }
        if filters is not None and not revision_matches_filters(record, filters):
            _provider_failed(
                "Revision provider returned a record outside the requested filters.",
                record_index=index,
            )
        if scope is not None and not revision_matches_scope(record, scope):
            _provider_failed(
                "Revision provider returned a record outside the requested scope.",
                record_index=index,
            )
        records.append(
            {
                "id": record["id"],
                "type": record["type"],
                "author": record["author"],
                "date": record["date"],
                "scope": _public_scope(record["location"], context),
            }
        )
    truncated = len(records) > max_revisions
    items = records[:max_revisions]
    return {"items": items, "returned": len(items), "truncated": truncated}


def assert_revision_scope(
    package: OpcPackage,
    scope: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate an immutable public scope and return the provider location filter."""

    if scope is None:
        return None
    context = _scope_context(package)
    if scope["range"] == "paragraph":
        index = scope["paragraph_index"]
        if index >= len(context["paragraphs"]):
            _scope_failed("paragraph-index", paragraph_index=index)
        actual = map_paragraph(context["paragraphs"][index]).full_text
        if actual != scope["expected_text"]:
            _scope_failed(
                "expected-text",
                paragraph_index=index,
                actual_text=actual,
            )
        return {"story": "body", "range": "paragraph", "paragraph_index": index}
    index = scope["table_index"]
    if index >= len(context["tables"]):
        _scope_failed("table-index", table_index=index)
    actual_hash = table_selector_sha256(context["tables"][index])
    if actual_hash != scope["expected_table_sha256"]:
        _scope_failed(
            "expected-table-sha256",
            table_index=index,
            actual_table_sha256=actual_hash,
        )
    return {"story": "body", "range": "table", "table_index": index}


def revision_matches_filters(
    record: dict[str, Any],
    filters: dict[str, Any],
) -> bool:
    if "authors" in filters and record["author"] not in filters["authors"]:
        return False
    if "types" in filters and record["type"] not in filters["types"]:
        return False
    date = record["date"]
    if "date_from" in filters and (not date or date < filters["date_from"]):
        return False
    if "date_to" in filters and (not date or date > filters["date_to"]):
        return False
    return True


def revision_matches_scope(record: dict[str, Any], scope: dict[str, Any]) -> bool:
    location = record["location"]
    if scope["range"] == "paragraph":
        return location["paragraph_index"] == scope["paragraph_index"]
    return location["table_index"] == scope["table_index"]


def normalize_apply_diagnostics(
    raw_diagnostics: object,
    *,
    target_ids: list[str],
) -> dict[str, list[str]]:
    """Validate the helper's match assertion against the requested target set."""

    if type(raw_diagnostics) is not dict or set(raw_diagnostics) != {
        "matched_ids",
        "unmatched_ids",
    }:
        _provider_failed("Revision provider returned invalid mutation diagnostics.")
    matched = _diagnostic_ids(raw_diagnostics["matched_ids"], "matched_ids")
    unmatched = _diagnostic_ids(raw_diagnostics["unmatched_ids"], "unmatched_ids")
    if set(matched).intersection(unmatched) or set(matched + unmatched) != set(target_ids):
        _provider_failed("Revision provider diagnostics do not cover the target ids.")
    return {"matched_ids": matched, "unmatched_ids": unmatched}


def remaining_selected_ids(
    raw_records: object,
    *,
    selected_ids: list[str],
    package: OpcPackage,
) -> list[str]:
    projection = project_revision_records(
        raw_records,
        max_revisions=1_000,
        package=package,
    )
    if projection["truncated"]:
        _provider_failed("Revision assertion exceeded the provider output bound.")
    remaining = {item["id"] for item in projection["items"]}
    return [revision_id for revision_id in selected_ids if revision_id in remaining]


def _scope_context(package: OpcPackage) -> dict[str, Any]:
    story = document_stories(package, include_headers_footers=False)[0]
    paragraphs = list(iter_paragraphs(story.root))
    tables = list(story.root.iter(qn("w", "tbl")))
    paragraph_tables: dict[int, int] = {}
    for table_index, table in enumerate(tables):
        for paragraph in table.iter(qn("w", "p")):
            paragraph_tables[id(paragraph)] = table_index
    return {
        "paragraphs": paragraphs,
        "tables": tables,
        "paragraph_tables": paragraph_tables,
    }


def _location(value: object, index: int, context: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _LOCATION_FIELDS:
        _provider_failed("Revision provider returned an invalid location.", record_index=index)
    paragraph_index = value["paragraph_index"]
    table_index = value["table_index"]
    if (
        value["story"] != "body"
        or type(paragraph_index) is not int
        or not 0 <= paragraph_index < len(context["paragraphs"])
        or not (
            table_index is None
            or type(table_index) is int
            and 0 <= table_index < len(context["tables"])
        )
    ):
        _provider_failed("Revision provider returned an unsupported location.", record_index=index)
    expected_table = context["paragraph_tables"].get(
        id(context["paragraphs"][paragraph_index])
    )
    if table_index != expected_table:
        _provider_failed(
            "Revision provider returned an inconsistent table location.",
            record_index=index,
        )
    return {
        "story": "body",
        "paragraph_index": paragraph_index,
        "table_index": table_index,
    }


def _public_scope(location: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    paragraph = context["paragraphs"][location["paragraph_index"]]
    expected_text = map_paragraph(paragraph).full_text
    if len(expected_text.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _provider_failed("Revision paragraph scope exceeds the public text bound.")
    table_index = location["table_index"]
    return {
        "story": "body",
        "paragraph_index": location["paragraph_index"],
        "expected_text": expected_text,
        "table_index": table_index,
        "expected_table_sha256": (
            table_selector_sha256(context["tables"][table_index])
            if table_index is not None
            else None
        ),
    }


def _revision_date(value: object, index: int) -> str:
    date = _bounded_text(value, 20, index, "date")
    if date:
        try:
            datetime.strptime(date, _DATE_FORMAT)
        except ValueError:
            _provider_failed(
                "Revision provider returned a non-canonical date.",
                record_index=index,
            )
    return date


def _bounded_text(value: object, ceiling: int, index: int, field: str) -> str:
    if type(value) is not str or len(value.encode("utf-8", errors="strict")) > ceiling:
        _provider_failed(
            "Revision provider returned invalid text.",
            record_index=index,
            field=field,
        )
    return value


def _diagnostic_ids(value: object, field: str) -> list[str]:
    if type(value) is not list or len(value) > 1_000:
        _provider_failed("Revision provider returned an invalid id array.", field=field)
    ids: list[str] = []
    for index, item in enumerate(value):
        revision_id = _bounded_text(item, 128, index, field)
        if revision_id in ids:
            _provider_failed(
                "Revision provider returned duplicate ids.",
                field=field,
                record_index=index,
            )
        ids.append(revision_id)
    return ids


def _scope_failed(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Revision scope precondition did not match the immutable input.",
        details={"reason": reason, **details},
    )


def _provider_failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_FAILED,
        message,
        details=details,
    )
