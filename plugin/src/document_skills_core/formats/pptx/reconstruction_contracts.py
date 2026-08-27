"""Bounded public contract for provider-backed raster reconstruction."""

import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_MAX_METADATA_BYTES = 4_096
_PROVIDER_POLICY = {
    "provider": "ocr-vision",
    "on_unavailable": "fail",
}


def parse_reconstruction_arguments(value: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(
        set(value)
        - {
            "audit_asset_policy",
            "confidence_threshold",
            "metadata",
            "provider_policy",
        }
    )
    if unknown:
        _invalid("Unknown reconstruction argument.", unknown=unknown)
    provider_policy = value.get("provider_policy")
    if type(provider_policy) is not dict or provider_policy != _PROVIDER_POLICY:
        _invalid(
            "provider_policy must require the ocr-vision provider without fallback.",
            field="provider_policy",
        )
    audit_policy = value.get("audit_asset_policy")
    if type(audit_policy) is not str or audit_policy not in {"retain", "discard"}:
        _invalid(
            "audit_asset_policy must be retain or discard.",
            field="audit_asset_policy",
        )
    threshold = value.get("confidence_threshold", 0.75)
    if (
        type(threshold) not in {int, float}
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        _invalid(
            "confidence_threshold must be a finite number between zero and one.",
            field="confidence_threshold",
        )
    metadata = value.get("metadata", {})
    if type(metadata) is not dict:
        _invalid("metadata must be an object.", field="metadata")
    unknown_metadata = sorted(set(metadata) - {"title", "creator", "subject"})
    if unknown_metadata:
        _invalid("Unknown metadata field.", unknown=unknown_metadata)
    return {
        "provider_policy": dict(_PROVIDER_POLICY),
        "audit_asset_policy": audit_policy,
        "confidence_threshold": float(threshold),
        "metadata": {
            "title": _text(
                metadata.get("title", "Elftia Presentation"),
                "metadata.title",
            ),
            "creator": _text(
                metadata.get("creator", "Elftia Document Skills"),
                "metadata.creator",
            ),
            "subject": _text(metadata.get("subject", ""), "metadata.subject"),
        },
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
