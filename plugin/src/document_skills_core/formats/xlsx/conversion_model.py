"""Canonical typed tabular model and value semantics for XLSX conversion."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

CELL_TYPES = frozenset(
    {"null", "empty", "string", "boolean", "number", "date", "time", "datetime", "error", "formula"}
)
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[Ee][+-]?\d+)?$")
_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_INJECTION_RE = re.compile(r"^\s*[=+\-@]")


def infer_text_cell(text: str, options: dict[str, Any]) -> dict[str, Any]:
    """Infer a delimited-text field without sacrificing risky numeric strings."""

    _check_cell_bytes(text, options)
    if text == options["null_token"]:
        return {"type": "null", "value": None}
    if text == "":
        return {"type": "empty", "value": ""}
    if not options["infer_types"]:
        return {"type": "string", "value": text}
    if text.casefold() == options["true_token"].casefold():
        return {"type": "boolean", "value": True}
    if text.casefold() == options["false_token"].casefold():
        return {"type": "boolean", "value": False}
    temporal = _infer_temporal(text, options["timezone_policy"])
    if temporal is not None:
        return temporal
    numeric = _infer_number(text, options)
    return numeric or {"type": "string", "value": text}


def normalize_json_cell(value: Any, options: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) - {"type", "value", "formula", "cached"}:
        _invalid_json("Each JSON cell must be a closed typed object.")
    kind = value.get("type")
    if kind not in CELL_TYPES:
        _invalid_json("JSON cell type is not supported.", cell_type=kind)
    if kind == "formula":
        formula = value.get("formula")
        if type(formula) is not str or not formula or formula.startswith("="):
            _invalid_json("Formula cells require expression text without a leading equals sign.")
        _check_cell_bytes(formula, options)
        cached = value.get("cached")
        if cached is not None:
            cached = normalize_json_cell(cached, options)
            if cached["type"] == "formula":
                _invalid_json("Formula cached values cannot contain another formula.")
        return {"type": "formula", "value": None, "formula": formula, "cached": cached}
    raw = value.get("value")
    if kind == "null":
        if raw is not None:
            _invalid_json("Null cells require a null value.")
        return {"type": kind, "value": None}
    if kind == "empty":
        if raw != "":
            _invalid_json("Empty cells require an empty string value.")
        return {"type": kind, "value": ""}
    if kind == "boolean":
        if type(raw) is not bool:
            _invalid_json("Boolean cells require a JSON boolean.")
        return {"type": kind, "value": raw}
    if kind == "number":
        if type(raw) not in {str, int, float} or type(raw) is bool:
            _invalid_json("Number cells require a finite decimal string or JSON number.")
        numeric = _infer_number(str(raw), {**options, "decimal_separator": "."})
        if numeric is None:
            _invalid_json("Number cell value is not a finite decimal.")
        return numeric
    if type(raw) is not str:
        _invalid_json(f"{kind} cells require a string value.")
    _check_cell_bytes(raw, options)
    if kind in {"date", "time", "datetime"}:
        parsed = _typed_temporal(kind, raw, options["timezone_policy"])
        if parsed is None:
            _invalid_json(f"{kind} cell value is not valid ISO 8601.")
        return parsed
    return {"type": kind, "value": raw}


def resolve_formula_policy(
    dataset: dict[str, Any],
    policy: str,
) -> tuple[int, list[dict[str, Any]]]:
    """Replace formula cells according to the explicit conversion policy."""

    count = 0
    losses: list[dict[str, Any]] = []
    for sheet in dataset["sheets"]:
        for row in sheet["rows"]:
            for index, cell in enumerate(row):
                if cell["type"] != "formula":
                    continue
                count += 1
                if policy == "reject":
                    raise DocumentSkillsError(
                        ErrorCode.VALIDATION_FAILED,
                        "Conversion formula policy rejected a formula-bearing source.",
                        details={"sheet": sheet["name"], "formula_policy": policy},
                    )
                if policy == "evaluated":
                    if cell.get("cached") is None:
                        raise DocumentSkillsError(
                            ErrorCode.ENHANCEMENT_REQUIRED,
                            "Evaluated formula conversion requires a cached value for every formula.",
                            status="enhancement_required",
                            details={"sheet": sheet["name"], "formula_policy": policy},
                        )
                    row[index] = deepcopy(cell["cached"])
                else:
                    row[index] = {"type": "string", "value": f"={cell['formula']}"}
    if count:
        losses.append(
            {
                "code": (
                    "formulas-replaced-with-cached-values"
                    if policy == "evaluated"
                    else "formulas-preserved-as-text"
                ),
                "description": (
                    "Formula expressions were replaced with unverified cached values."
                    if policy == "evaluated"
                    else "Formula expressions were emitted as inert text."
                ),
                "count": count,
            }
        )
    return count, losses


def validate_dataset(dataset: dict[str, Any], limits: dict[str, int]) -> dict[str, int]:
    sheets = dataset.get("sheets")
    if type(sheets) is not list or not sheets:
        _invalid_json("Tabular data requires at least one sheet.")
    seen: set[str] = set()
    total_rows = total_cells = maximum_columns = 0
    for sheet in sheets:
        if type(sheet) is not dict or set(sheet) != {"name", "rows"}:
            _invalid_json("Each sheet must contain exactly name and rows.")
        name = sheet["name"]
        _validate_sheet_name(name)
        if name.casefold() in seen:
            _invalid_json("Sheet names must be unique.", sheet=name)
        seen.add(name.casefold())
        rows = sheet["rows"]
        if type(rows) is not list or len(rows) > limits["max_rows_per_sheet"]:
            _limit("Sheet row limit exceeded.", sheet=name)
        total_rows += len(rows)
        for row in rows:
            if type(row) is not list or len(row) > limits["max_columns"]:
                _limit("Sheet column limit exceeded.", sheet=name)
            maximum_columns = max(maximum_columns, len(row))
            total_cells += len(row)
            if total_cells > limits["max_cells"]:
                _limit("Conversion cell limit exceeded.")
            for cell in row:
                if type(cell) is not dict or cell.get("type") not in CELL_TYPES:
                    _invalid_json("Dataset contains an invalid typed cell.")
                for field in ("value", "formula"):
                    text = cell.get(field)
                    if type(text) is str and len(text.encode("utf-8", errors="strict")) > limits["max_cell_bytes"]:
                        _limit("Cell text exceeds the configured byte limit.", sheet=name)
    return {
        "sheets": len(sheets),
        "rows": total_rows,
        "cells": total_cells,
        "max_columns": maximum_columns,
    }


def select_output_sheets(
    dataset: dict[str, Any],
    *,
    sheet_name: str | None,
    target_format: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sheets = dataset["sheets"]
    if sheet_name is not None:
        selected = [sheet for sheet in sheets if sheet["name"] == sheet_name]
        if not selected:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Requested conversion sheet was not found.",
                status="invalid_request",
                details={"sheet": sheet_name, "available": [item["name"] for item in sheets]},
            )
        sheets = selected
    losses: list[dict[str, Any]] = []
    if target_format in {"csv", "tsv"} and len(sheets) > 1:
        losses.append(
            {
                "code": "additional-sheets-dropped",
                "description": "Delimited output contains only the first selected worksheet.",
                "count": len(sheets) - 1,
            }
        )
        sheets = sheets[:1]
    return {"sheets": deepcopy(sheets)}, losses


def cell_to_text(
    cell: dict[str, Any],
    options: dict[str, Any],
    *,
    protect_csv: bool,
) -> tuple[str, bool]:
    kind = cell["type"]
    if kind == "null":
        text = options["null_token"]
    elif kind == "empty":
        text = ""
    elif kind == "boolean":
        text = options["true_token"] if cell["value"] else options["false_token"]
    elif kind == "number":
        text = str(cell["value"])
        if options["decimal_separator"] == ",":
            text = _decimal_separator(text, ",")
    else:
        text = str(cell["value"])
    if not protect_csv or kind == "number" or not _INJECTION_RE.match(text):
        return text, False
    policy = options["csv_injection_policy"]
    if policy == "reject":
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "CSV injection policy rejected a dangerous text cell.",
            details={"csv_injection_policy": policy, "prefix": text[:1]},
        )
    if policy == "escape":
        return f"'{text}", True
    return text, False


def canonical_json_cell(cell: dict[str, Any]) -> dict[str, Any]:
    return {"type": cell["type"], "value": cell.get("value")}


def _infer_number(text: str, options: dict[str, Any]) -> dict[str, Any] | None:
    if not _NUMBER_RE.fullmatch(text):
        return None
    decimal_separator = options["decimal_separator"]
    other = "," if decimal_separator == "." else "."
    if other in text:
        return None
    normalized = text.replace(decimal_separator, ".")
    if _INTEGER_RE.fullmatch(normalized):
        digits = normalized.lstrip("+-")
        if len(digits) > 1 and digits.startswith("0") and options["leading_zero_policy"] == "preserve-text":
            return {"type": "string", "value": text}
        if len(digits) > 15:
            policy = options["large_integer_policy"]
            if policy == "reject":
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Large integer policy rejected a value longer than 15 digits.",
                    details={"digits": len(digits)},
                )
            if policy == "preserve-text":
                return {"type": "string", "value": text}
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return {"type": "number", "value": str(number)}


def _infer_temporal(text: str, timezone_policy: str) -> dict[str, Any] | None:
    if "T" in text or " " in text:
        parsed = _typed_temporal("datetime", text, timezone_policy)
        if parsed is not None:
            return parsed
    if ":" in text:
        parsed = _typed_temporal("time", text, timezone_policy)
        if parsed is not None:
            return parsed
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return _typed_temporal("date", text, timezone_policy)
    return None


def _typed_temporal(kind: str, text: str, timezone_policy: str) -> dict[str, Any] | None:
    try:
        if kind == "date":
            parsed: date | time | datetime = date.fromisoformat(text)
        elif kind == "time":
            parsed = time.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    aware = kind != "date" and parsed.tzinfo is not None
    if aware and timezone_policy == "reject":
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Timezone policy rejected an offset-aware value.",
            details={"timezone_policy": timezone_policy},
        )
    if aware and timezone_policy == "utc":
        if isinstance(parsed, datetime):
            text = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            anchor = datetime.combine(date(2000, 1, 1), parsed)
            text = anchor.astimezone(timezone.utc).timetz().isoformat().replace("+00:00", "Z")
    return {"type": kind, "value": text, "timezone": aware}


def _decimal_separator(text: str, separator: str) -> str:
    exponent_at = max(text.find("E"), text.find("e"))
    if exponent_at < 0:
        return text.replace(".", separator)
    return text[:exponent_at].replace(".", separator) + text[exponent_at:]


def _validate_sheet_name(value: Any) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > 31
        or any(character in value for character in "[]:*?/\\")
        or value.startswith("'")
        or value.endswith("'")
    ):
        _invalid_json("Sheet name is invalid.", sheet=value)


def _check_cell_bytes(text: str, options: dict[str, Any]) -> None:
    if len(text.encode("utf-8", errors="strict")) > options["max_cell_bytes"]:
        _limit("Cell text exceeds the configured byte limit.")


def _limit(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)


def _invalid_json(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)
