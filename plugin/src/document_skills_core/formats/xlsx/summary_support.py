"""Source projection and typed stored-value helpers for XLSX summaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import col_to_num, num_to_col, parse_ref


@dataclass(frozen=True)
class OutputCell:
    value: str
    kind: str


def worksheet(workbook: dict[str, Any], name: str) -> dict[str, Any]:
    match = next((item for item in workbook["sheets"] if item["name"] == name), None)
    if match is None:
        invalid("Summary source worksheet was not found.", sheet=name)
    return match


def cell_index(sheet: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in sheet.get("rows", []):
        for cell in row.get("cells", []):
            parsed = parse_ref(cell["ref"])
            if parsed is not None:
                result[(col_to_num(parsed[0]), parsed[1])] = cell
    return result


def source_bounds(
    cells: dict[tuple[int, int], dict[str, Any]],
    requested: str | None,
) -> tuple[int, int, int, int]:
    if requested is not None:
        return range_bounds(requested)
    if not cells:
        invalid("Summary source worksheet has no cells.")
    columns = [item[0] for item in cells]
    rows = [item[1] for item in cells]
    return min(columns), min(rows), max(columns), max(rows)


def headers(
    cells: dict[tuple[int, int], dict[str, Any]],
    bounds: tuple[int, int, int, int],
    *,
    sheet_name: str,
    formula_policy: str,
    formula_cells: set[str],
) -> list[str]:
    first_column, first_row, last_column, _last_row = bounds
    result: list[str] = []
    for column in range(first_column, last_column + 1):
        ref = f"{num_to_col(column)}{first_row}"
        item = scalar(
            cells.get((column, first_row)),
            formula_policy=formula_policy,
            formula_cells=formula_cells,
            ref=f"{sheet_name}!{ref}",
        )
        if item.kind != "string" or not item.value:
            invalid("Every summary source column requires a text header.", cell=ref)
        if item.value.casefold() in {existing.casefold() for existing in result}:
            invalid("Summary source headers must be unique.", cell=ref)
        result.append(item.value)
    return result


def scalar(
    cell: dict[str, Any] | None,
    *,
    formula_policy: str,
    formula_cells: set[str],
    ref: str,
) -> OutputCell:
    if cell is None:
        return OutputCell("", "empty")
    if cell.get("formula"):
        if formula_policy == "reject":
            enhancement(
                "Summary source contains a formula; request cached values explicitly.",
                cell=ref,
                capability="xlsx.summary.cached-formula-values",
            )
        if cell.get("cached_value") is None:
            failed("Summary source formula has no cached value.", cell=ref)
        formula_cells.add(ref)
    elif cell.get("value") is None:
        return OutputCell("", "empty")
    cell_type = cell.get("type", "n")
    value = str(cell.get("cached_value") if cell.get("formula") else cell.get("value"))
    if cell_type in {"s", "str", "inlineStr"}:
        return OutputCell(value, "string")
    if cell_type == "b":
        return OutputCell("1" if value in {"1", "true", "TRUE"} else "0", "boolean")
    if cell_type == "e":
        failed("Summary source contains an error cell.", cell=ref, value=value)
    return OutputCell(value, "number")


def numeric_value(
    item: OutputCell,
    column: str,
    numeric_policy: str,
) -> Decimal | None:
    if item.kind == "empty":
        return None
    can_coerce = numeric_policy == "coerce-text" and item.kind == "string"
    if item.kind != "number" and not can_coerce:
        failed(
            "Numeric aggregation encountered a non-numeric value.",
            column=column,
            value=item.value,
        )
    try:
        result = Decimal(item.value)
    except InvalidOperation:
        failed(
            "Numeric aggregation encountered an invalid decimal.",
            column=column,
            value=item.value,
        )
    if not result.is_finite():
        failed("Numeric aggregation requires finite values.", column=column, value=item.value)
    return result


def resolve_names(names: list[str], index: dict[str, int], field: str) -> list[int]:
    return [resolve_name(name, index, field) for name in names]


def resolve_name(name: str | None, index: dict[str, int], field: str) -> int:
    assert name is not None
    resolved = index.get(name.casefold())
    if resolved is None:
        invalid("Summary column name was not found.", field=field, column=name)
    return resolved


def range_bounds(value: str) -> tuple[int, int, int, int]:
    first, separator, last = value.partition(":")
    first_ref = parse_ref(first)
    last_ref = parse_ref(last if separator else first)
    assert first_ref is not None and last_ref is not None
    return col_to_num(first_ref[0]), first_ref[1], col_to_num(last_ref[0]), last_ref[1]


def target_range(start: str, columns: int, rows: int) -> str:
    parsed = parse_ref(start)
    assert parsed is not None
    first_column = col_to_num(parsed[0])
    last_column = first_column + columns - 1
    last_row = parsed[1] + rows - 1
    if last_column > 16_384 or last_row > 1_048_576:
        invalid("Summary target range exceeds worksheet bounds.")
    end = f"{num_to_col(last_column)}{last_row}"
    return f"{start}:{end}"


def format_range(bounds: tuple[int, int, int, int]) -> str:
    return f"{num_to_col(bounds[0])}{bounds[1]}:{num_to_col(bounds[2])}{bounds[3]}"


def decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)


def enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
