"""Bounded public DOCX comment projections and assertions."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import document_stories, iter_paragraphs, map_paragraph
from .package import OpcPackage

_COMMENT_FIELDS = frozenset(
    {
        "id",
        "parent_comment_id",
        "thread_id",
        "resolved",
        "author",
        "date",
        "text",
        "anchor",
    }
)
_ANCHOR_FIELDS = frozenset({"story", "paragraph_index", "range"})


def project_comment_records(
    raw_records: object,
    *,
    max_comments: int,
) -> dict[str, Any]:
    """Validate provider JSON and return a bounded comment projection."""

    if type(raw_records) is not list or len(raw_records) > max_comments + 1:
        _provider_failed("Comment provider returned an invalid bounded array.")
    records: list[dict[str, Any]] = []
    for index, raw_record in enumerate(raw_records):
        if type(raw_record) is not dict or set(raw_record) != _COMMENT_FIELDS:
            _provider_failed(
                "Comment provider returned an invalid record shape.",
                record_index=index,
            )
        records.append(
            {
                "id": _comment_id(raw_record["id"], index, "id"),
                "parent_comment_id": _optional_comment_id(
                    raw_record["parent_comment_id"], index, "parent_comment_id"
                ),
                "thread_id": _comment_id(
                    raw_record["thread_id"], index, "thread_id"
                ),
                "resolved": _boolean(raw_record["resolved"], index, "resolved"),
                "author": _text(raw_record["author"], 1_024, index, "author"),
                "date": _text(raw_record["date"], 128, index, "date"),
                "text": _text(raw_record["text"], 32_768, index, "text"),
                "anchor": _anchor(raw_record["anchor"], index),
            }
        )
    _validate_thread_graph(records)
    truncated = len(records) > max_comments
    items = records[:max_comments]
    return {"items": items, "returned": len(items), "truncated": truncated}


def assert_comment_anchor(package: OpcPackage, anchor: dict[str, Any]) -> None:
    """Enforce the stable paragraph selector before a provider mutation."""

    story = document_stories(package, include_headers_footers=False)[0]
    paragraphs = list(iter_paragraphs(story.root))
    index = anchor["paragraph_index"]
    if index >= len(paragraphs):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Comment anchor paragraph does not exist.",
            details={"paragraph_index": index},
        )
    actual = "".join(group.text for group in map_paragraph(paragraphs[index]).groups)
    if actual != anchor["expected_text"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Comment anchor text precondition did not match.",
            details={"paragraph_index": index},
        )


def assert_added_comment(
    raw_records: object,
    *,
    comment_id: str,
    author: str,
    text: str,
    anchor: dict[str, Any] | None,
    parent_comment_id: str | None,
) -> dict[str, Any]:
    projection = project_comment_records(raw_records, max_comments=10_000)
    if projection["truncated"]:
        _provider_failed("Comment assertion exceeded the provider output bound.")
    expected_anchor = (
        {
            "story": anchor["story"],
            "paragraph_index": anchor["paragraph_index"],
            "range": anchor["range"],
        }
        if anchor is not None
        else None
    )
    matched = [
        item
        for item in projection["items"]
        if item["id"] == comment_id
        and item["parent_comment_id"] == parent_comment_id
        and item["thread_id"] == (parent_comment_id or comment_id)
        and item["resolved"] is False
        and item["author"] == author
        and item["text"] == text
    ]
    if matched and expected_anchor is not None and matched[0]["anchor"] != expected_anchor:
        matched = []
    if matched and parent_comment_id is not None:
        parent = next(
            (
                item
                for item in projection["items"]
                if item["id"] == parent_comment_id
            ),
            None,
        )
        if parent is None or matched[0]["anchor"] != parent["anchor"]:
            matched = []
    if len(matched) != 1:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Added comment could not be verified at its requested anchor.",
            details={"comment_id": comment_id},
        )
    return matched[0]


def assert_resolved_comment(
    raw_records: object,
    *,
    comment_id: str,
    resolved: bool,
) -> dict[str, Any]:
    projection = project_comment_records(raw_records, max_comments=10_000)
    if projection["truncated"]:
        _provider_failed("Comment assertion exceeded the provider output bound.")
    roots = [
        item
        for item in projection["items"]
        if item["id"] == comment_id
        and item["parent_comment_id"] is None
        and item["thread_id"] == comment_id
        and item["resolved"] is resolved
    ]
    if len(roots) != 1:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Resolved comment thread could not be verified.",
            details={"comment_id": comment_id, "resolved": resolved},
        )
    thread = [
        item for item in projection["items"] if item["thread_id"] == comment_id
    ]
    if not thread or any(item["resolved"] is not resolved for item in thread):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Comment replies did not inherit the requested thread state.",
            details={"comment_id": comment_id, "resolved": resolved},
        )
    return roots[0]


def _validate_thread_graph(records: list[dict[str, Any]]) -> None:
    by_id = {item["id"]: item for item in records}
    if len(by_id) != len(records):
        _provider_failed("Comment provider returned duplicate comment ids.")
    for item in records:
        parent_id = item["parent_comment_id"]
        if parent_id is None:
            if item["thread_id"] != item["id"]:
                _provider_failed("Comment provider returned an invalid root thread id.")
            continue
        parent = by_id.get(parent_id)
        if (
            parent is None
            or parent["parent_comment_id"] is not None
            or item["thread_id"] != parent_id
            or item["resolved"] is not parent["resolved"]
        ):
            _provider_failed("Comment provider returned an invalid reply graph.")


def _anchor(value: object, index: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != _ANCHOR_FIELDS:
        _provider_failed("Comment provider returned an invalid anchor.", record_index=index)
    paragraph_index = value["paragraph_index"]
    if (
        value["story"] != "body"
        or value["range"] != "paragraph"
        or type(paragraph_index) is not int
        or not 0 <= paragraph_index <= 10_000
    ):
        _provider_failed("Comment provider returned an unsupported anchor.", record_index=index)
    return {
        "story": "body",
        "paragraph_index": paragraph_index,
        "range": "paragraph",
    }


def _comment_id(value: object, index: int, field: str) -> str:
    comment_id = _text(value, 10, index, field, allow_empty=False)
    if (
        not comment_id.isascii()
        or not comment_id.isdecimal()
        or int(comment_id) > 2_147_483_647
    ):
        _provider_failed(
            "Comment provider returned an invalid comment id.",
            record_index=index,
            field=field,
        )
    return comment_id


def _optional_comment_id(value: object, index: int, field: str) -> str | None:
    return None if value is None else _comment_id(value, index, field)


def _boolean(value: object, index: int, field: str) -> bool:
    if type(value) is not bool:
        _provider_failed(
            "Comment provider returned an invalid boolean.",
            record_index=index,
            field=field,
        )
    return value


def _text(
    value: object,
    ceiling: int,
    index: int,
    field: str,
    *,
    allow_empty: bool = True,
) -> str:
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or len(value.encode("utf-8", errors="strict")) > ceiling
    ):
        _provider_failed(
            "Comment provider returned invalid text.",
            record_index=index,
            field=field,
        )
    return value


def _provider_failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message, details=details)
