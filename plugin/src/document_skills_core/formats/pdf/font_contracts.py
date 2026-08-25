"""Closed contracts for hash-bound local TrueType font assets."""

import re
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

MAX_DOCUMENT_FONTS = 8
_FONT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,3}$")


def parse_font_assets(value: Any, field: str = "fonts") -> list[dict[str, str]]:
    """Parse a bounded font registry without opening caller-selected files."""
    if value is None:
        return []
    if type(value) is not list or len(value) > MAX_DOCUMENT_FONTS:
        _invalid("document.fonts must be a bounded array.", field=field)
    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_field = f"{field}.{index}"
        if type(item) is not dict:
            _invalid("Each font asset must be an object.", field=item_field)
        unknown = sorted(set(item) - {"id", "filename", "sha256"})
        if unknown:
            _invalid("Unknown font asset argument.", field=item_field, unknown=unknown)
        font_id = item.get("id")
        if type(font_id) is not str or _FONT_ID.fullmatch(font_id) is None:
            _invalid("font.id must be a stable ASCII identifier.", field=f"{item_field}.id")
        if font_id in seen:
            _invalid("font.id values must be unique.", field=f"{item_field}.id")
        seen.add(font_id)
        filename = item.get("filename")
        if type(filename) is not str or not filename or len(filename.encode("utf-8")) > 4_096:
            _invalid("font.filename must be a bounded local path.", field=f"{item_field}.filename")
        if "://" in filename or filename.casefold().startswith(("data:", "file:")):
            _invalid("font.filename must not be a URL.", field=f"{item_field}.filename")
        resolved = Path(filename).expanduser().resolve(strict=False)
        if resolved.suffix.casefold() != ".ttf":
            _enhancement(
                "The Unicode font path currently accepts TrueType .ttf assets only.",
                field=f"{item_field}.filename",
                capability="pdf.embedded-truetype",
            )
        sha256 = item.get("sha256")
        if type(sha256) is not str or _SHA256.fullmatch(sha256) is None:
            _invalid("font.sha256 must be a complete SHA-256 digest.", field=f"{item_field}.sha256")
        parsed.append({
            "id": font_id,
            "filename": str(resolved),
            "sha256": sha256.casefold(),
        })
    return parsed


def parse_fallback_fonts(value: Any, field: str, font_ids: set[str]) -> list[str]:
    if value is None:
        return []
    if type(value) is not list or len(value) > MAX_DOCUMENT_FONTS:
        _invalid("fallback_fonts must be a bounded array.", field=field)
    parsed: list[str] = []
    for index, font_id in enumerate(value):
        if type(font_id) is not str or font_id not in font_ids:
            _invalid("fallback_fonts contains an unknown font id.", field=f"{field}.{index}")
        if font_id in parsed:
            _invalid("fallback_fonts must not contain duplicates.", field=f"{field}.{index}")
        parsed.append(font_id)
    return parsed


def parse_text_direction(value: Any, field: str) -> str:
    direction = "auto" if value is None else value
    if direction not in {"auto", "ltr", "rtl"}:
        _invalid("direction must be auto, ltr, or rtl.", field=field)
    return direction


def parse_text_language(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _LANGUAGE.fullmatch(value) is None:
        _invalid("language must be a bounded BCP-47 style tag.", field=field)
    return value


def parse_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid("value must be a complete SHA-256 digest.", field=field)
    return value.casefold()


def require_unicode_font(text: str, style: dict[str, Any] | None, field: str) -> None:
    try:
        text.encode("latin-1", errors="strict")
        return
    except UnicodeEncodeError:
        pass
    if style is not None and (
        style["font_family"] != "Helvetica" or style["fallback_fonts"]
    ):
        return
    _enhancement(
        "Unicode text requires an explicit embedded font or fallback chain.",
        field=field,
        capability="pdf.embedded-font",
    )


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
