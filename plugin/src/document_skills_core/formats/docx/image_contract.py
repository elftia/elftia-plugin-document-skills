"""Closed public payloads for typed DOCX image edits."""

import math
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_RELATIONSHIP_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9._:-]{0,127}$")


def parse_image_target(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.target"
    if type(value) is not dict:
        _invalid("Image target must be an object.", field=field)
    _exact_keys(
        value,
        {
            "expected_alt_text",
            "expected_media_sha256",
            "relationship_id",
            "story",
        },
    )
    if value.get("story") != "body":
        _invalid(
            "Image replacement currently targets only the body story.",
            field=f"{field}.story",
        )
    relationship_id = value.get("relationship_id")
    if (
        type(relationship_id) is not str
        or _RELATIONSHIP_ID.fullmatch(relationship_id) is None
    ):
        _invalid("Image relationship id is invalid.", field=f"{field}.relationship_id")
    digest = value.get("expected_media_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid(
            "Expected image media SHA-256 must be a 64-digit hexadecimal value.",
            field=f"{field}.expected_media_sha256",
        )
    return {
        "story": "body",
        "relationship_id": relationship_id,
        "expected_alt_text": _bounded_text(
            value.get("expected_alt_text"),
            f"{field}.expected_alt_text",
            2_048,
        ),
        "expected_media_sha256": digest.casefold(),
    }


def parse_edit_image(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.image"
    if type(value) is not dict:
        _invalid("Edit image must be an object.", field=field)
    _exact_keys(value, {"alt_text", "crop", "path", "width_inches"})
    raw_path = _bounded_text(
        value.get("path"), f"{field}.path", 32_768, allow_empty=False
    )
    if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
        _invalid("Image path must reference a local file.", field=f"{field}.path")
    width = value.get("width_inches", 4)
    if (
        type(width) not in {int, float}
        or not math.isfinite(float(width))
        or not 0.25 <= float(width) <= 10
    ):
        _invalid(
            "Image width must be between 0.25 and 10 inches.",
            field=f"{field}.width_inches",
        )
    alt_text = _bounded_text(
        value.get("alt_text", "Document image"),
        f"{field}.alt_text",
        2_048,
    )
    if any(ord(character) < 32 for character in alt_text):
        _invalid(
            "Image alt text contains a control character.",
            field=f"{field}.alt_text",
        )
    return {
        "path": Path(raw_path).expanduser().resolve(strict=False),
        "alt_text": alt_text,
        "width_inches": float(width),
        "crop": _parse_crop(value.get("crop"), field),
    }


def _parse_crop(value: Any, image_field: str) -> dict[str, float] | None:
    if value is None:
        return None
    field = f"{image_field}.crop"
    if type(value) is not dict:
        _invalid("Image crop must be an object.", field=field)
    _exact_keys(value, {"bottom", "left", "right", "top"})
    crop: dict[str, float] = {}
    for side in ("left", "top", "right", "bottom"):
        number = value.get(side, 0)
        if (
            type(number) not in {int, float}
            or not math.isfinite(float(number))
            or not 0 <= float(number) <= 100
        ):
            _invalid(
                "Image crop percentages must be finite numbers from 0 through 100.",
                field=f"{field}.{side}",
            )
        crop[side] = float(number)
    if crop["left"] + crop["right"] >= 100 or crop["top"] + crop["bottom"] >= 100:
        _invalid(
            "Opposing image crop percentages must total less than 100.",
            field=field,
        )
    return crop


def _bounded_text(
    value: Any,
    field: str,
    maximum_bytes: int,
    *,
    allow_empty: bool = True,
) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Expected a text value.", field=field)
    if len(value.encode("utf-8", errors="strict")) > maximum_bytes:
        _invalid("Text exceeds the operation byte limit.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected DOCX argument keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
