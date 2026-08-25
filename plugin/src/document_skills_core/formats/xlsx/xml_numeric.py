"""Bounded parsing for numeric values read from untrusted SpreadsheetML XML."""

from __future__ import annotations

import math
import re

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

MAX_NUMERIC_TEXT_CHARS = 64
MAX_UNSIGNED_INT = 4_294_967_295
MAX_SIGNED_INT = 2_147_483_647
MIN_SIGNED_INT = -2_147_483_648

_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(
    r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[Ee][+-]?[0-9]+)?"
)


def parse_xml_int(
    value: str,
    *,
    attribute: str,
    minimum: int = MIN_SIGNED_INT,
    maximum: int = MAX_SIGNED_INT,
) -> int:
    """Parse a bounded XML integer or fail with a sanitized archive error."""

    normalized = value.strip()
    if (
        len(value) > MAX_NUMERIC_TEXT_CHARS
        or _INTEGER.fullmatch(normalized) is None
    ):
        _unsafe_numeric(attribute, "integer")
    parsed = int(normalized)
    if not minimum <= parsed <= maximum:
        _unsafe_numeric(attribute, "integer")
    return parsed


def parse_optional_xml_int(
    value: str | None,
    *,
    attribute: str,
    minimum: int = MIN_SIGNED_INT,
    maximum: int = MAX_SIGNED_INT,
) -> int | None:
    """Parse an optional bounded XML integer."""

    if value is None:
        return None
    return parse_xml_int(
        value,
        attribute=attribute,
        minimum=minimum,
        maximum=maximum,
    )


def parse_xml_number(
    value: str,
    *,
    attribute: str,
    minimum: float = -1e100,
    maximum: float = 1e100,
) -> int | float:
    """Parse a finite, bounded XML decimal/double without accepting extensions."""

    normalized = value.strip()
    if len(value) > MAX_NUMERIC_TEXT_CHARS or _NUMBER.fullmatch(normalized) is None:
        _unsafe_numeric(attribute, "number")
    parsed = float(normalized)
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        _unsafe_numeric(attribute, "number")
    return int(parsed) if parsed.is_integer() else parsed


def parse_optional_xml_number(
    value: str | None,
    *,
    attribute: str,
    minimum: float = -1e100,
    maximum: float = 1e100,
) -> int | float | None:
    """Parse an optional finite, bounded XML decimal/double."""

    if value is None:
        return None
    return parse_xml_number(
        value,
        attribute=attribute,
        minimum=minimum,
        maximum=maximum,
    )


def _unsafe_numeric(attribute: str, expected: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "SpreadsheetML contains an unsafe numeric attribute.",
        details={"attribute": attribute, "expected": expected},
    )
