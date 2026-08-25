"""Shared scalar validators for PDF request contracts."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT


def exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        invalid("Unknown PDF operation argument.", unknown=unknown)


def optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or type(value) is bool or not minimum <= value <= maximum:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            f"Integer must be between {minimum} and {maximum}.",
            status="invalid_request",
        )
    return value


def number(value: Any, field: str) -> float:
    if (type(value) is not int and type(value) is not float) or type(value) is bool:
        invalid("Value must be a number.", field=field)
    return float(value)


def bounded_number(value: Any, field: str, minimum: float, maximum: float) -> float:
    parsed = number(value, field)
    if not minimum <= parsed <= maximum:
        invalid(
            f"Value must be between {minimum} and {maximum}.",
            field=field,
        )
    return parsed


def boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        invalid("Value must be boolean.", field=field)
    return value


def optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return text(value, field)


def text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        invalid("Text exceeds the byte limit.", field=field)
    return value


def invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )


def require_lossless_text(text_value: str, field: str, *, encoding: str) -> None:
    try:
        text_value.encode(encoding, errors="strict")
    except UnicodeEncodeError as error:
        enhancement(
            "Requested PDF text is not representable by the active Core font path.",
            field=field,
            capability="pdf.lossless-text",
            encoding=encoding,
            codepoint=f"U+{ord(text_value[error.start]):04X}",
        )
