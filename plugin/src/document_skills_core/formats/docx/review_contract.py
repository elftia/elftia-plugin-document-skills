"""Review, comment, and schema operation contracts."""

from typing import Any

from .contract_utils import (
    _boolean,
    _bounded_argument_text,
    _exact_keys,
    _integer,
    _invalid,
)

def _parse_revisions_read(value: dict[str, Any]) -> dict[str, Any]:
    from .revision_contract import parse_revisions_read

    return parse_revisions_read(value)


def _parse_revisions_apply(value: dict[str, Any]) -> dict[str, Any]:
    from .revision_contract import parse_revisions_apply

    return parse_revisions_apply(value)


def _parse_comments_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"max_comments"})
    return {"max_comments": _integer(value.get("max_comments", 1_000), 1, 10_000)}


def _parse_comments_add(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"anchor", "author", "parent_comment_id", "text"})
    author = _bounded_argument_text(value.get("author"), "author", 256, allow_empty=False)
    text = _bounded_argument_text(value.get("text"), "text", 32_768, allow_empty=False)
    has_anchor = "anchor" in value
    has_parent = "parent_comment_id" in value
    if has_anchor == has_parent:
        _invalid(
            "Comment add requires exactly one of anchor or parent_comment_id.",
            field="arguments",
        )
    parsed_anchor = None
    parent_comment_id = None
    if has_anchor:
        anchor = value.get("anchor")
        if type(anchor) is not dict:
            _invalid("Comment anchor must be an object.", field="anchor")
        _exact_keys(anchor, {"expected_text", "paragraph_index", "range", "story"})
        if anchor.get("story") != "body" or anchor.get("range") != "paragraph":
            _invalid(
                "Only an explicit body paragraph range is supported.",
                field="anchor",
            )
        parsed_anchor = {
            "story": "body",
            "paragraph_index": _integer(anchor.get("paragraph_index"), 0, 10_000),
            "expected_text": _bounded_argument_text(
                anchor.get("expected_text"),
                "anchor.expected_text",
                32_768,
            ),
            "range": "paragraph",
        }
    else:
        parent_comment_id = _comment_id(
            value.get("parent_comment_id"),
            "parent_comment_id",
        )
    return {
        "author": author,
        "text": text,
        "anchor": parsed_anchor,
        "parent_comment_id": parent_comment_id,
    }


def _parse_comments_resolve(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"comment_id", "resolved"})
    return {
        "comment_id": _comment_id(value.get("comment_id"), "comment_id"),
        "resolved": _boolean(value.get("resolved"), "resolved"),
    }


def _comment_id(value: Any, field: str) -> str:
    comment_id = _bounded_argument_text(value, field, 10, allow_empty=False)
    if not comment_id.isascii() or not comment_id.isdecimal():
        _invalid("Comment id must be a decimal string.", field=field)
    if int(comment_id) > 2_147_483_647:
        _invalid("Comment id exceeds the supported range.", field=field)
    return comment_id


def _parse_schema_validation(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"max_errors"})
    return {"max_errors": _integer(value.get("max_errors", 100), 1, 1_000)}
