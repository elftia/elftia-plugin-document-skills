"""Bounded public contract for PDF image extraction.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_PAGES

DEFAULT_MAX_IMAGES = 100
MAX_EXTRACTED_IMAGES = 10_000
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_TOTAL_BYTES = 128 * 1024 * 1024


def parse_images_extract_arguments(value: dict[str, Any]) -> dict[str, Any]:
    """Parse a closed, bounded ``pdf.images.extract`` argument object."""
    unknown = sorted(set(value) - {"pages", "max_images", "max_total_bytes"})
    if unknown:
        _invalid("Unknown PDF image extraction argument.", unknown=unknown)

    pages = value.get("pages")
    parsed_pages = None
    if pages is not None:
        if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
            _invalid(
                "pages must be a non-empty bounded array when supplied.",
                field="pages",
            )
        parsed_pages = [_integer(page, 1, MAX_PAGES, "pages") for page in pages]
        if len(set(parsed_pages)) != len(parsed_pages):
            _invalid("pages must not contain duplicates.", field="pages")
        parsed_pages.sort()

    return {
        "pages": parsed_pages,
        "max_images": _integer(
            value.get("max_images", DEFAULT_MAX_IMAGES),
            1,
            MAX_EXTRACTED_IMAGES,
            "max_images",
        ),
        "max_total_bytes": _integer(
            value.get("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES),
            1,
            MAX_EXTRACTED_TOTAL_BYTES,
            "max_total_bytes",
        ),
    }


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or type(value) is bool or not minimum <= value <= maximum:
        _invalid(
            f"Integer must be between {minimum} and {maximum}.",
            field=field,
        )
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
