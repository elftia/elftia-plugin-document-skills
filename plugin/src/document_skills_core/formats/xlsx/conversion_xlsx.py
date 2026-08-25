"""XLSX adapters for the canonical tabular conversion model."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .contracts import parse_xlsx_request
from .conversion_model import normalize_json_cell, validate_dataset
from .create import create_xlsx
from .formula_analysis import analyze_formulas
from .mapping import map_workbook
from .package import OpcPackage
from .validation import validate_created


def read_xlsx_dataset(
    path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = analyze_formulas(path)
    if analysis["categories"].get("external_reference", 0):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "External-workbook formulas cannot enter tabular conversion.",
            details={"formula_analysis": analysis},
        )
    if arguments["values"]["formula_policy"] == "reject" and analysis["formula_cells"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Conversion formula policy rejected a formula-bearing XLSX source.",
            details={"formula_policy": "reject", "formula_cells": analysis["formula_cells"]},
        )
    special = [
        name
        for name in ("shared", "array", "data_table")
        if analysis["categories"].get(name, 0)
    ]
    if special:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Tabular conversion does not flatten shared, array, or data-table formula semantics.",
            status="enhancement_required",
            details={"formula_types": special},
        )
    workbook = map_workbook(OpcPackage.open(path))
    options = {**arguments["values"], **arguments["limits"]}
    sheets: list[dict[str, Any]] = []
    for source_sheet in workbook["sheets"]:
        sparse: dict[tuple[int, int], dict[str, Any]] = {}
        maximum_row = maximum_column = 0
        for source_row in source_sheet["rows"]:
            row_number = _positive_integer(source_row.get("ref"))
            maximum_row = max(maximum_row, row_number)
            for source_cell in source_row["cells"]:
                row, column = _cell_coordinate(source_cell.get("ref", ""))
                maximum_row = max(maximum_row, row)
                maximum_column = max(maximum_column, column)
                sparse[(row, column)] = _mapped_cell(source_cell, options)
        _assert_dimensions(source_sheet["name"], maximum_row, maximum_column, arguments["limits"])
        rows = [
            [
                sparse.get((row, column), {"type": "null", "value": None})
                for column in range(1, maximum_column + 1)
            ]
            for row in range(1, maximum_row + 1)
        ]
        sheets.append({"name": source_sheet["name"], "rows": rows})
    dataset = {"sheets": sheets}
    stats = validate_dataset(dataset, arguments["limits"])
    return dataset, {
        "strategy": "bounded-in-memory-opc-projection",
        "stats": stats,
        "formula_analysis": {
            "formula_cells": analysis["formula_cells"],
            "categories": analysis["categories"],
            "scope": analysis["scope"],
            "calculation_engine": False,
        },
    }


def write_xlsx_dataset(
    path: Path,
    dataset: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    workbook, losses = _build_workbook(dataset)
    parsed = parse_xlsx_request(
        {
            "operation": "xlsx.create",
            "output": str(path),
            "arguments": {"workbook": workbook, "recalculation": "skip"},
        }
    )
    creation = create_xlsx(path, parsed.arguments["workbook"])
    validation = validate_created(path, parsed.arguments["workbook"], creation=creation)
    evidence = {
        "strategy": "bounded-direct-ooxml-emission",
        "stats": validate_dataset(dataset, arguments["limits"]),
        "formula_cells": 0,
    }
    return evidence, validation, losses


def _mapped_cell(cell: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    if cell.get("formula"):
        cached = None
        if cell.get("cached_value") is not None:
            cached_source = dict(cell)
            cached_source["formula"] = None
            cached_source["value"] = cell["cached_value"]
            cached = _mapped_cell(cached_source, options)
        return {
            "type": "formula",
            "value": None,
            "formula": cell["formula"],
            "cached": cached,
        }
    cell_type = cell.get("type", "n")
    value = cell.get("value")
    if value is None:
        return {"type": "null", "value": None}
    if cell_type in {"s", "str", "inlineStr"}:
        return {"type": "empty" if value == "" else "string", "value": value}
    if cell_type == "b":
        return {"type": "boolean", "value": value == "1"}
    if cell_type == "e":
        return {"type": "error", "value": value}
    temporal_kind = _temporal_format_kind(cell.get("number_format", ""))
    if temporal_kind is not None:
        converted = _excel_temporal(value, temporal_kind)
        if converted is not None:
            return converted
    return normalize_json_cell({"type": "number", "value": value}, options)


def _build_workbook(
    dataset: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sheets: list[dict[str, Any]] = []
    timezone_text = null_cells = large_integers = 0
    for sheet in dataset["sheets"]:
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(sheet["rows"], start=1):
            cells: list[dict[str, Any]] = []
            for column_number, cell in enumerate(row, start=1):
                if cell["type"] == "null":
                    null_cells += 1
                    continue
                target, timezone_preserved = _xlsx_cell(
                    cell,
                    f"{_column_name(column_number)}{row_number}",
                )
                timezone_text += int(timezone_preserved)
                if (
                    cell["type"] == "number"
                    and re.fullmatch(r"[+-]?\d{16,}", str(cell.get("value", "")))
                ):
                    large_integers += 1
                cells.append(target)
            rows.append({"cells": cells})
        sheets.append(
            {
                "name": sheet["name"],
                "rows": rows,
                "columns": [],
                "number_formats": [],
                "data_validations": [],
                "conditional_formats": [],
                "hyperlinks": [],
                "comments": [],
            }
        )
    losses: list[dict[str, Any]] = []
    if null_cells:
        losses.append(
            {
                "code": "null-values-mapped-to-blank-cells",
                "description": "XLSX has no distinct stored null value; nulls became absent cells.",
                "count": null_cells,
            }
        )
    if timezone_text:
        losses.append(
            {
                "code": "timezone-values-preserved-as-text",
                "description": "Offset-aware date/time values were preserved as ISO text.",
                "count": timezone_text,
            }
        )
    if large_integers:
        losses.append(
            {
                "code": "large-integer-xlsx-precision-risk",
                "description": "Integers longer than 15 digits were explicitly emitted as XLSX numbers.",
                "count": large_integers,
            }
        )
    return {
        "metadata": {"title": "Converted workbook", "creator": "Elftia Document Skills", "subject": ""},
        "sheets": sheets,
        "defined_names": [],
        "tables": [],
        "charts": [],
        "chart_reference": None,
        "page_setup": None,
    }, losses


def _xlsx_cell(cell: dict[str, Any], ref: str) -> tuple[dict[str, Any], bool]:
    kind = cell["type"]
    value = cell.get("value")
    target: dict[str, Any] = {"ref": ref, "formula": None, "cached_value": None, "style": None}
    if kind in {"string", "empty"}:
        target.update({"type": "s", "value": str(value)})
        return target, False
    if kind == "boolean":
        target.update({"type": "b", "value": "1" if value else "0"})
        return target, False
    if kind == "number":
        target.update({"type": "n", "value": str(value)})
        return target, False
    if kind == "error":
        target.update({"type": "e", "value": str(value)})
        return target, False
    if kind in {"date", "time", "datetime"}:
        temporal = _parse_iso(kind, str(value))
        if temporal is None:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Typed temporal value became invalid before XLSX emission.",
            )
        if kind != "date" and temporal.tzinfo is not None:
            target.update({"type": "s", "value": str(value)})
            return target, True
        target.update(
            {
                "type": "n",
                "value": _to_excel_serial(temporal),
                "style": {
                    "number_format": {
                        "code": {
                            "date": "yyyy-mm-dd",
                            "time": "hh:mm:ss",
                            "datetime": 'yyyy-mm-dd"T"hh:mm:ss',
                        }[kind]
                    }
                },
            }
        )
        return target, False
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Unsupported canonical cell reached XLSX emission.",
        details={"cell_type": kind},
    )


def _excel_temporal(value: str, kind: str) -> dict[str, Any] | None:
    try:
        serial = Decimal(value)
    except InvalidOperation:
        return None
    if not serial.is_finite() or serial < 0:
        return None
    whole = int(serial.to_integral_value(rounding=ROUND_FLOOR))
    fraction = serial - Decimal(whole)
    if kind == "time":
        return {"type": "time", "value": _fraction_time(fraction).isoformat()}
    if whole == 60:
        if kind == "date" and fraction == 0:
            return {"type": "string", "value": "1900-02-29"}
        return None
    adjusted = whole + (1 if 0 < whole < 60 else 0)
    day = date(1899, 12, 30) + timedelta(days=adjusted)
    if kind == "date" and fraction == 0:
        return {"type": "date", "value": day.isoformat()}
    clock = _fraction_time(fraction)
    return {
        "type": "datetime",
        "value": datetime.combine(day, clock).isoformat(),
        "timezone": False,
    }


def _fraction_time(value: Decimal) -> time:
    micros = int((value * Decimal(86_400_000_000)).to_integral_value())
    micros %= 86_400_000_000
    hours, remainder = divmod(micros, 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    return time(hours, minutes, seconds, microseconds)


def _to_excel_serial(value: date | time | datetime) -> str:
    if isinstance(value, time):
        seconds = value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000
        return str(Decimal(str(seconds)) / Decimal(86_400))
    day = value.date() if isinstance(value, datetime) else value
    days = (day - date(1899, 12, 30)).days
    if day < date(1900, 3, 1):
        days -= 1
    fraction = Decimal(0)
    if isinstance(value, datetime):
        seconds = value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000
        fraction = Decimal(str(seconds)) / Decimal(86_400)
    return str(Decimal(days) + fraction)


def _parse_iso(kind: str, value: str) -> date | time | datetime | None:
    try:
        if kind == "date":
            return date.fromisoformat(value)
        if kind == "time":
            return time.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _temporal_format_kind(format_code: str) -> str | None:
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", format_code.casefold())
    has_date = "y" in code or "d" in code
    has_time = "h" in code or "s" in code or "am/pm" in code
    if has_date and has_time:
        return "datetime"
    if has_date:
        return "date"
    if has_time:
        return "time"
    return None


def _assert_dimensions(name: str, rows: int, columns: int, limits: dict[str, int]) -> None:
    if rows > limits["max_rows_per_sheet"] or columns > limits["max_columns"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "XLSX worksheet exceeds configured conversion dimensions.",
            details={"sheet": name, "rows": rows, "columns": columns},
        )
    if rows * columns > limits["max_cells"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "XLSX rectangular projection exceeds the configured cell limit.",
            details={"sheet": name, "rectangular_cells": rows * columns},
        )


def _positive_integer(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _cell_coordinate(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", value)
    if match is None:
        raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "XLSX cell reference is invalid.")
    column = 0
    for character in match.group(1).upper():
        column = column * 26 + ord(character) - ord("A") + 1
    return int(match.group(2)), column


def _column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
