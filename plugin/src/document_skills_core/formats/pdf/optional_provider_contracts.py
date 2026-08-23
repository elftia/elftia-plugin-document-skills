"""Closed bounded contracts for optional PDF render and OCR providers."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_PAGES

DEFAULT_MAX_PIXELS = 40_000_000
MAX_PROVIDER_PIXELS = 100_000_000
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PROVIDER_TOTAL_BYTES = 128 * 1024 * 1024
_LANGUAGE = re.compile(r"^[A-Za-z0-9_]{2,16}$")


def parse_optional_provider_arguments(
    operation: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    if operation == "pdf.render":
        return _parse_render(value)
    if operation == "pdf.ocr":
        return _parse_ocr(value)
    raise AssertionError(f"unsupported optional PDF operation: {operation}")


def _parse_render(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"pages", "dpi", "format", "max_pixels", "max_total_bytes"})
    output_format = value.get("format", "png")
    if output_format not in {"png", "jpeg"}:
        _invalid("format must be png or jpeg.", field="format")
    return {
        "pages": _pages(value.get("pages")),
        "dpi": _integer(value.get("dpi", 144), 36, 300, "dpi"),
        "format": output_format,
        "max_pixels": _integer(
            value.get("max_pixels", DEFAULT_MAX_PIXELS),
            1,
            MAX_PROVIDER_PIXELS,
            "max_pixels",
        ),
        "max_total_bytes": _integer(
            value.get("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES),
            1,
            MAX_PROVIDER_TOTAL_BYTES,
            "max_total_bytes",
        ),
    }


def _parse_ocr(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "pages",
            "dpi",
            "languages",
            "skip_text_pages",
            "max_pixels",
            "max_total_bytes",
        },
    )
    languages = value.get("languages", ["eng"])
    if type(languages) is not list or not languages or len(languages) > 8:
        _invalid("languages must be a non-empty bounded array.", field="languages")
    if any(type(item) is not str or _LANGUAGE.fullmatch(item) is None for item in languages):
        _invalid("languages contains an invalid Tesseract language id.", field="languages")
    if len(set(languages)) != len(languages):
        _invalid("languages must not contain duplicates.", field="languages")
    skip_text_pages = value.get("skip_text_pages", True)
    if type(skip_text_pages) is not bool:
        _invalid("skip_text_pages must be boolean.", field="skip_text_pages")
    return {
        "pages": _pages(value.get("pages")),
        "dpi": _integer(value.get("dpi", 300), 72, 300, "dpi"),
        "languages": sorted(languages),
        "skip_text_pages": skip_text_pages,
        "max_pixels": _integer(
            value.get("max_pixels", DEFAULT_MAX_PIXELS),
            1,
            MAX_PROVIDER_PIXELS,
            "max_pixels",
        ),
        "max_total_bytes": _integer(
            value.get("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES),
            1,
            MAX_PROVIDER_TOTAL_BYTES,
            "max_total_bytes",
        ),
    }


def _pages(value: Any) -> list[int] | None:
    if value is None:
        return None
    if type(value) is not list or not value or len(value) > MAX_PAGES:
        _invalid("pages must be a non-empty bounded array when supplied.", field="pages")
    parsed = [_integer(item, 1, MAX_PAGES, "pages") for item in value]
    if len(set(parsed)) != len(parsed):
        _invalid("pages must not contain duplicates.", field="pages")
    return sorted(parsed)


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown optional PDF provider argument.", unknown=unknown)


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
