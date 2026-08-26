"""Closed contract for explicit template style overlays."""

from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_STYLE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")


def parse_style_overlay(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("style_overlay must be an object.", field="style_overlay")
    _exact_keys(
        value,
        {
            "conflict_policy",
            "expected_source_sha256",
            "source",
            "style_ids",
        },
    )
    raw_source = value.get("source")
    if (
        type(raw_source) is not str
        or not raw_source
        or len(raw_source.encode("utf-8", errors="strict")) > 32_768
        or "://" in raw_source
        or raw_source.startswith(("\\\\", "//"))
    ):
        _invalid("Style overlay source must be a bounded local path.", field="style_overlay.source")
    source = Path(raw_source).expanduser().resolve(strict=False)
    if source.suffix.casefold() not in {".docx", ".dotx"}:
        _invalid("Style overlay source must use .docx or .dotx.", field="style_overlay.source")
    digest = value.get("expected_source_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid(
            "Style overlay source SHA-256 must be 64 hexadecimal digits.",
            field="style_overlay.expected_source_sha256",
        )
    style_ids = value.get("style_ids")
    if type(style_ids) is not list or not style_ids or len(style_ids) > 128:
        _invalid("style_ids must be a non-empty bounded array.", field="style_overlay.style_ids")
    parsed_ids: list[str] = []
    for index, style_id in enumerate(style_ids):
        if type(style_id) is not str or _STYLE_ID.fullmatch(style_id) is None:
            _invalid("Style id is not a portable Word identifier.", field=f"style_overlay.style_ids.{index}")
        if style_id in parsed_ids:
            _invalid("Style ids must be unique.", field=f"style_overlay.style_ids.{index}")
        parsed_ids.append(style_id)
    conflict_policy = value.get("conflict_policy")
    if conflict_policy not in {"keep-base", "replace-existing"}:
        _invalid(
            "Style conflict policy must be keep-base or replace-existing.",
            field="style_overlay.conflict_policy",
        )
    return {
        "source": source,
        "expected_source_sha256": digest.casefold(),
        "style_ids": tuple(sorted(parsed_ids)),
        "conflict_policy": conflict_policy,
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected style overlay keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
