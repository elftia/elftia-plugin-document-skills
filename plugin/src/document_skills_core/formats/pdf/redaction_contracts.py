"""Closed contract for safe literal-text PDF redaction.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_PAGES


def parse_redact_text_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    unknown = sorted(set(primitive) - {"type", "page", "text"})
    field = f"primitives.{index}"
    if unknown:
        _invalid("Unknown redact_text argument.", field=field, unknown=unknown)
    page = primitive.get("page")
    if type(page) is not int or type(page) is bool or not 1 <= page <= MAX_PAGES:
        _invalid("redact_text.page is outside the bound.", field=f"{field}.page")
    text = primitive.get("text")
    if type(text) is not str or not text or len(text) > MAX_ARGUMENT_TEXT:
        _invalid("redact_text.text must be non-empty and bounded.", field=f"{field}.text")
    try:
        text.encode("latin-1", errors="strict")
    except UnicodeEncodeError as error:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Core literal-text redaction currently requires Latin-1 text.",
            status="enhancement_required",
            details={"field": f"{field}.text", "capability": "pdf.redaction-font-encoding"},
        ) from error
    return {"type": "redact_text", "page": page, "text": text}


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
