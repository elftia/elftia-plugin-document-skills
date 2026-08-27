"""Bounded public contracts for editable PPTX equation blocks."""

from __future__ import annotations

import math
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .equation_ast import normalize_equation_source


EMU_PER_INCH = 914_400
_MAX_COORDINATE_INCHES = 56.0
_EQUATION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")


def parse_equation_block(
    value: Any,
    field: str,
    *,
    slide_size: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Equation block must be an object.", field=field)
    _exact_keys(value, {"bbox", "fallback", "id", "source", "type", "z_order"}, field)
    if value.get("type") != "equation":
        _invalid("Equation block type must be equation.", field=f"{field}.type")
    equation_id = value.get("id")
    if type(equation_id) is not str or not _EQUATION_ID.fullmatch(equation_id):
        _invalid(
            "Equation id must be a bounded stable identifier.", field=f"{field}.id"
        )
    fallback = value.get("fallback", "reject")
    if fallback != "reject":
        raise DocumentSkillsError(
            ErrorCode.UNSUPPORTED_FEATURE,
            "Editable equations support only fallback: reject.",
            details={"fallback": fallback},
        )
    bbox = _parse_bbox(value.get("bbox"), f"{field}.bbox")
    frame = {
        "x": round(bbox["x"] * EMU_PER_INCH),
        "y": round(bbox["y"] * EMU_PER_INCH),
        "cx": round(bbox["w"] * EMU_PER_INCH),
        "cy": round(bbox["h"] * EMU_PER_INCH),
    }
    if frame["cx"] <= 0 or frame["cy"] <= 0:
        _invalid(
            "Equation bbox extent must be at least one EMU.",
            field=f"{field}.bbox",
        )
    if slide_size is not None:
        validate_equation_frame(frame, slide_size, field)
    source = normalize_equation_source(value.get("source"), f"{field}.source")
    z_order = value.get("z_order", 100)
    if (
        type(z_order) is not int
        or isinstance(z_order, bool)
        or not 0 <= z_order <= 10_000
    ):
        _invalid(
            "Equation z_order must be an integer from 0 through 10000.",
            field=f"{field}.z_order",
        )
    return {
        "type": "equation",
        "id": equation_id,
        "bbox": bbox,
        "fallback": fallback,
        "source_kind": source["source_kind"],
        "canonical_ast": source["canonical_ast"],
        "canonical_latex": source["canonical_latex"],
        "frame": frame,
        "z_order": z_order,
        "z_order_explicit": "z_order" in value,
    }


def public_equation_record(
    equation: dict[str, Any],
    *,
    slide: int,
    shape_id: str | None = None,
) -> dict[str, Any]:
    result = {
        "canonical_ast": equation["canonical_ast"],
        "canonical_latex": equation["canonical_latex"],
        "consumer_compatibility": {
            "libreoffice": {"status": "not_run"},
            "powerpoint": {"status": "not_run"},
        },
        "editable": True,
        "fallback": "native",
        "format": "office-math",
        "id": equation["id"],
        "slide": slide,
        "source_kind": equation["source_kind"],
    }
    if shape_id is not None:
        result["selector"] = {
            "id": shape_id,
            "name": equation["id"],
            "type": "equation",
        }
    return result


def equation_records(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for slide_number, slide in enumerate(slides, 1):
        shape_id = 2 + (1 if slide.get("title") else 0)
        for shape in slide.get("shapes", []):
            if shape.get("type") == "equation":
                records.append(
                    public_equation_record(
                        shape,
                        slide=slide_number,
                        shape_id=str(shape_id),
                    )
                )
            shape_id += 1
    return records


def frame_to_bbox(frame: dict[str, int]) -> dict[str, float]:
    return {
        "x": frame["x"] / EMU_PER_INCH,
        "y": frame["y"] / EMU_PER_INCH,
        "w": frame["cx"] / EMU_PER_INCH,
        "h": frame["cy"] / EMU_PER_INCH,
    }


def _parse_bbox(value: Any, field: str) -> dict[str, float]:
    if type(value) is not dict:
        _invalid("Equation bbox must be an object.", field=field)
    _exact_keys(value, {"h", "w", "x", "y"}, field)
    result = {
        key: _number(value.get(key), f"{field}.{key}") for key in ("x", "y", "w", "h")
    }
    if result["x"] < 0 or result["y"] < 0:
        _invalid("Equation bbox origin cannot be negative.", field=field)
    if result["w"] <= 0 or result["h"] <= 0:
        _invalid("Equation bbox extent must be positive.", field=field)
    if any(item > _MAX_COORDINATE_INCHES for item in result.values()):
        _invalid("Equation bbox exceeds the coordinate ceiling.", field=field)
    return result


def validate_equation_frame(
    frame: dict[str, int],
    slide_size: dict[str, Any],
    field: str,
) -> None:
    try:
        slide_width = int(slide_size["cx"])
        slide_height = int(slide_size["cy"])
    except (KeyError, TypeError, ValueError):
        _invalid("Slide size is invalid for equation placement.", field=field)
    if slide_width <= 0 or slide_height <= 0:
        _invalid("Slide size is invalid for equation placement.", field=field)
    if (
        frame["x"] + frame["cx"] > slide_width
        or frame["y"] + frame["cy"] > slide_height
    ):
        _invalid("Equation bbox exceeds the slide bounds.", field=field)


def _number(value: Any, field: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _invalid("Equation bbox coordinate must be numeric.", field=field)
    result = float(value)
    if not math.isfinite(result):
        _invalid("Equation bbox coordinate must be finite.", field=field)
    return result


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown equation block field.", field=field, unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


__all__ = [
    "EMU_PER_INCH",
    "equation_records",
    "frame_to_bbox",
    "parse_equation_block",
    "public_equation_record",
    "validate_equation_frame",
]
