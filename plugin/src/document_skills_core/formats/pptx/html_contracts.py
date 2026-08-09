"""Bounded public contract for browser-backed HTML deck conversion."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_MAX_METADATA_BYTES = 4_096
_FALLBACK_POLICIES = frozenset({"element-rasterize", "fail"})


def parse_html_create_arguments(value: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - {"metadata", "fallback_policy"})
    if unknown:
        _invalid("Unknown HTML conversion argument.", unknown=unknown)
    metadata = value.get("metadata", {})
    if type(metadata) is not dict:
        _invalid("metadata must be an object.", field="metadata")
    unknown_metadata = sorted(set(metadata) - {"title", "creator", "subject"})
    if unknown_metadata:
        _invalid("Unknown metadata field.", unknown=unknown_metadata)
    fallback_policy = value.get("fallback_policy", "element-rasterize")
    if fallback_policy not in _FALLBACK_POLICIES:
        _invalid("fallback_policy is not supported.", field="fallback_policy")
    return {
        "metadata": {
            "title": _text(metadata.get("title", "Elftia Presentation"), "metadata.title"),
            "creator": _text(
                metadata.get("creator", "Elftia Document Skills"),
                "metadata.creator",
            ),
            "subject": _text(metadata.get("subject", ""), "metadata.subject"),
        },
        "fallback_policy": fallback_policy,
    }


def _text(value: Any, field: str) -> str:
    if type(value) is not str:
        _invalid("Metadata values must be strings.", field=field)
    if len(value.encode("utf-8", errors="strict")) > _MAX_METADATA_BYTES:
        _invalid("Metadata value exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
