"""Closed bounded contract for low-confidence Core table extraction."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_PAGES


def parse_table_extract_arguments(value: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - {"pages", "min_rows", "min_columns", "max_tables"})
    if unknown:
        _invalid("Unknown PDF table extraction argument.", unknown=unknown)
    pages = value.get("pages")
    parsed_pages = None
    if pages is not None:
        if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
            _invalid("pages must be a non-empty bounded array when supplied.", field="pages")
        parsed_pages = [_integer(page, 1, MAX_PAGES, "pages") for page in pages]
        if len(set(parsed_pages)) != len(parsed_pages):
            _invalid("pages must not contain duplicates.", field="pages")
        parsed_pages.sort()
    return {
        "pages": parsed_pages,
        "min_rows": _integer(value.get("min_rows", 2), 1, 1_000, "min_rows"),
        "min_columns": _integer(
            value.get("min_columns", 2),
            2,
            32,
            "min_columns",
        ),
        "max_tables": _integer(
            value.get("max_tables", 100),
            1,
            1_000,
            "max_tables",
        ),
    }


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
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
