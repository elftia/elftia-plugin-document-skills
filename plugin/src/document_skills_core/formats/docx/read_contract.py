"""Read and inspection operation contracts."""

from typing import Any

from .contract_utils import _boolean, _exact_keys, _integer

def _parse_read(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "include_headers_footers",
        "max_content_controls",
        "max_fields",
        "max_notes",
        "max_paragraphs",
        "max_table_rows",
        "max_tables",
        "max_text_chars",
    }
    _exact_keys(value, allowed)
    return {
        "include_headers_footers": _boolean(
            value.get("include_headers_footers", True), "include_headers_footers"
        ),
        "max_paragraphs": _integer(value.get("max_paragraphs", 5_000), 1, 10_000),
        "max_content_controls": _integer(
            value.get("max_content_controls", 1_000), 0, 10_000
        ),
        "max_fields": _integer(value.get("max_fields", 1_000), 0, 10_000),
        "max_notes": _integer(value.get("max_notes", 2_000), 0, 10_000),
        "max_tables": _integer(value.get("max_tables", 500), 0, 1_000),
        "max_table_rows": _integer(value.get("max_table_rows", 5_000), 0, 10_000),
        "max_text_chars": _integer(
            value.get("max_text_chars", 250_000), 1, 1_000_000
        ),
    }


def _parse_inspect(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_hashes", "max_parts", "max_relationships"})
    return {
        "include_hashes": _boolean(value.get("include_hashes", True), "include_hashes"),
        "max_parts": _integer(value.get("max_parts", 2_000), 1, 5_000),
        "max_relationships": _integer(
            value.get("max_relationships", 5_000), 1, 10_000
        ),
    }


def _parse_accessibility(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"max_issues"})
    return {"max_issues": _integer(value.get("max_issues", 100), 1, 1_000)}
