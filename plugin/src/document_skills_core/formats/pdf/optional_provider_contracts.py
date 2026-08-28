"""Closed bounded contracts for optional PDF render and OCR providers."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_PAGES
from .font_contracts import parse_sha256

DEFAULT_MAX_PIXELS = 40_000_000
MAX_PROVIDER_PIXELS = 100_000_000
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PROVIDER_TOTAL_BYTES = 128 * 1024 * 1024
MAX_RENDER_PAGES = 256
MAX_OCR_PAGES = 64
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
    _exact_keys(
        value,
        {
            "pages",
            "dpi",
            "format",
            "max_pixels",
            "max_total_bytes",
            "compare_to",
            "reference_sha256",
            "expected_change_regions",
            "channel_tolerance",
            "max_unexpected_change_ratio",
            "minimum_expected_change_ratio",
        },
    )
    output_format = value.get("format", "png")
    if output_format not in {"png", "jpeg"}:
        _invalid("format must be png or jpeg.", field="format")
    compare_to = _optional_pdf_path(value.get("compare_to"), "compare_to")
    reference_sha256 = parse_sha256(
        value.get("reference_sha256"),
        "reference_sha256",
    )
    regions = _change_regions(value.get("expected_change_regions"))
    comparison_fields = {
        "reference_sha256",
        "expected_change_regions",
        "channel_tolerance",
        "max_unexpected_change_ratio",
        "minimum_expected_change_ratio",
    }
    if compare_to is None and any(field in value for field in comparison_fields):
        _invalid(
            "Render comparison fields require compare_to.",
            field="compare_to",
        )
    if compare_to is not None and reference_sha256 is None:
        _invalid(
            "Render comparison requires a bound reference_sha256.",
            field="reference_sha256",
        )
    minimum_expected_change_ratio = _ratio(
        value.get("minimum_expected_change_ratio", 0.0),
        "minimum_expected_change_ratio",
    )
    if minimum_expected_change_ratio > 0.0 and not regions:
        _invalid(
            "A positive minimum_expected_change_ratio requires expected_change_regions.",
            field="expected_change_regions",
        )
    return {
        "pages": _pages(value.get("pages"), maximum_count=MAX_RENDER_PAGES),
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
        "compare_to": compare_to,
        "reference_sha256": reference_sha256,
        "expected_change_regions": regions,
        "channel_tolerance": _integer(
            value.get("channel_tolerance", 0),
            0,
            255,
            "channel_tolerance",
        ),
        "max_unexpected_change_ratio": _ratio(
            value.get("max_unexpected_change_ratio", 0.0),
            "max_unexpected_change_ratio",
        ),
        "minimum_expected_change_ratio": minimum_expected_change_ratio,
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
        "pages": _pages(value.get("pages"), maximum_count=MAX_OCR_PAGES),
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


def _pages(value: Any, *, maximum_count: int) -> list[int] | None:
    if value is None:
        return None
    if type(value) is not list or not value or len(value) > maximum_count:
        _invalid("pages must be a non-empty bounded array when supplied.", field="pages")
    parsed = [_integer(item, 1, MAX_PAGES, "pages") for item in value]
    if len(set(parsed)) != len(parsed):
        _invalid("pages must not contain duplicates.", field="pages")
    return sorted(parsed)


def _optional_pdf_path(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value.encode("utf-8")) > 4_096:
        _invalid("Render reference must be a bounded local path.", field=field)
    if "://" in value or value.casefold().startswith(("data:", "file:")):
        _invalid("Render reference must not be a URL.", field=field)
    from pathlib import Path

    resolved = Path(value).expanduser().resolve(strict=False)
    if resolved.suffix.casefold() != ".pdf":
        _invalid("Render reference must use the .pdf extension.", field=field)
    return str(resolved)


def _change_regions(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if type(value) is not list or len(value) > 256:
        _invalid("expected_change_regions must be a bounded array.", field="expected_change_regions")
    parsed: list[dict[str, Any]] = []
    for index, region in enumerate(value):
        field = f"expected_change_regions.{index}"
        if type(region) is not dict:
            _invalid("Expected change region must be an object.", field=field)
        _exact_keys(region, {"page", "bbox"})
        bbox = region.get("bbox")
        if type(bbox) is not list or len(bbox) != 4:
            _invalid("Expected change bbox must contain four numbers.", field=f"{field}.bbox")
        coordinates = [
            _bounded_number(item, -100_000.0, 100_000.0, f"{field}.bbox.{offset}")
            for offset, item in enumerate(bbox)
        ]
        if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
            _invalid("Expected change bbox must have positive area.", field=f"{field}.bbox")
        parsed.append({
            "page": _integer(region.get("page"), 1, MAX_PAGES, f"{field}.page"),
            "bbox": coordinates,
        })
    return parsed


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown optional PDF provider argument.", unknown=unknown)


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or type(value) is bool or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _bounded_number(value: Any, minimum: float, maximum: float, field: str) -> float:
    if (type(value) is not int and type(value) is not float) or type(value) is bool:
        _invalid("Value must be a number.", field=field)
    number = float(value)
    if not minimum <= number <= maximum:
        _invalid(f"Value must be between {minimum} and {maximum}.", field=field)
    return number


def _ratio(value: Any, field: str) -> float:
    return _bounded_number(value, 0.0, 1.0, field)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
