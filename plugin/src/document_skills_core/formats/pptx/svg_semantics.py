"""Typed semantic payloads carried by constrained scene-export SVG groups."""

import json
import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_CHART_KINDS = {"area", "bar", "column", "doughnut", "line", "pie", "scatter"}
_MAX_MODEL_BYTES = 64_000


def encode_semantic_model(kind: str, value: dict[str, Any]) -> str:
    normalized = validate_semantic_model(kind, value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def decode_semantic_model(kind: str, value: str) -> dict[str, Any]:
    if type(value) is not str or len(value.encode("utf-8")) > _MAX_MODEL_BYTES:
        _invalid("SVG semantic model is missing or exceeds policy.")
    try:
        decoded = json.loads(value)
    except (UnicodeError, json.JSONDecodeError) as error:
        _invalid("SVG semantic model is not canonical JSON.", reason=type(error).__name__)
    return validate_semantic_model(kind, decoded)


def validate_semantic_model(kind: str, value: Any) -> dict[str, Any]:
    if kind == "table":
        return _table(value)
    if kind == "chart":
        return _chart(value)
    _invalid("SVG semantic kind is unsupported.", kind=kind)


def _table(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"header_rows", "rows"}:
        _invalid("SVG table model fields are invalid.")
    rows = value["rows"]
    if type(rows) is not list or not 1 <= len(rows) <= 100:
        _invalid("SVG table row count is invalid.")
    width = None
    normalized_rows: list[list[str]] = []
    for row in rows:
        if type(row) is not list or not 1 <= len(row) <= 50:
            _invalid("SVG table column count is invalid.")
        if width is None:
            width = len(row)
        elif len(row) != width:
            _invalid("SVG table rows must have equal width.")
        normalized: list[str] = []
        for cell in row:
            if type(cell) not in {str, int, float} and cell is not None:
                _invalid("SVG table cells must be scalar values.")
            if type(cell) is float and not math.isfinite(cell):
                _invalid("SVG table cells must be finite.")
            text = "" if cell is None else str(cell)
            if len(text.encode("utf-8")) > 4_096:
                _invalid("SVG table cell exceeds policy.")
            normalized.append(text)
        normalized_rows.append(normalized)
    header_rows = value["header_rows"]
    if type(header_rows) is not int or not 0 <= header_rows <= len(normalized_rows):
        _invalid("SVG table header row count is invalid.")
    return {"header_rows": header_rows, "rows": normalized_rows}


def _chart(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"categories", "chart_type", "series"}:
        _invalid("SVG chart model fields are invalid.")
    chart_type = value["chart_type"]
    categories = value["categories"]
    series = value["series"]
    if chart_type not in _CHART_KINDS:
        _invalid("SVG chart type is unsupported.")
    if (
        type(categories) is not list
        or not 1 <= len(categories) <= 100
        or any(type(item) is not str or len(item.encode("utf-8")) > 512 for item in categories)
    ):
        _invalid("SVG chart categories are invalid.")
    if type(series) is not list or not 1 <= len(series) <= 20:
        _invalid("SVG chart series count is invalid.")
    normalized_series = []
    for item in series:
        if type(item) is not dict or set(item) != {"name", "values"}:
            _invalid("SVG chart series fields are invalid.")
        name = item["name"]
        values = item["values"]
        if type(name) is not str or not name or len(name.encode("utf-8")) > 512:
            _invalid("SVG chart series name is invalid.")
        if type(values) is not list or len(values) != len(categories):
            _invalid("SVG chart values must align with categories.")
        normalized_values = []
        for member in values:
            if member is None:
                normalized_values.append(None)
            elif type(member) in {int, float} and math.isfinite(member):
                normalized_values.append(float(member))
            else:
                _invalid("SVG chart values must be finite numbers or null.")
        normalized_series.append({"name": name, "values": normalized_values})
    return {
        "categories": list(categories),
        "chart_type": chart_type,
        "series": normalized_series,
    }


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


__all__ = ["decode_semantic_model", "encode_semantic_model", "validate_semantic_model"]
