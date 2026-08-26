"""Shared bounded primitives for DOCX operation contracts."""

from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SEMANTIC_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_DEFAULT_PUBLIC_PNG_TOTAL_BYTES = 512 * 1024
_MAX_PUBLIC_PNG_TOTAL_BYTES = 1_000_000

def _bounded_argument_text(
    value: Any,
    field: str,
    maximum_bytes: int,
    *,
    allow_empty: bool = True,
) -> str:
    text = _text(value, field, allow_empty=allow_empty)
    if len(text.encode("utf-8", errors="strict")) > maximum_bytes:
        _invalid("Text exceeds the operation byte limit.", field=field)
    return text


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown DOCX operation argument.", unknown=unknown)


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
