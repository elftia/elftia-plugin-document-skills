"""Visible worksheet layout for the bounded native pivot authoring slice."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import num_to_col, parse_ref
from .summary_support import OutputCell, decimal_text


def build_pivot_layout(
    start_cell: str,
    row_axis: Any,
    column_axis: Any | None,
    page_filter: Any | None,
    value: Any,
    records: list[tuple[OutputCell, ...]],
    *,
    numeric_policy: str,
) -> tuple[str, str, tuple[tuple[str, OutputCell], ...]]:
    output: list[tuple[str, OutputCell]] = []
    table_row_offset = _append_filter(output, start_cell, page_filter)
    table_start = _coordinate(start_cell, 0, table_row_offset)
    if column_axis is None:
        location = _append_row_pivot(
            output,
            table_start,
            row_axis,
            value,
            records,
            numeric_policy,
        )
    else:
        location = _append_matrix_pivot(
            output,
            table_start,
            row_axis,
            column_axis,
            value,
            records,
            numeric_policy,
        )
    return location, _display_range(start_cell, location), tuple(output)


def _append_filter(output: list, start: str, page_filter: Any | None) -> int:
    if page_filter is None:
        return 0
    output.append((_coordinate(start, 0, 0), OutputCell("Filter", "string")))
    output.append((_coordinate(start, 0, 1), OutputCell(page_filter.column, "string")))
    selected = (
        "(All)"
        if page_filter.selected_position is None
        else _label(page_filter.items[page_filter.selected_position])
    )
    output.append((_coordinate(start, 1, 1), OutputCell(selected, "string")))
    return 3


def _append_row_pivot(
    output: list,
    start: str,
    row_axis: Any,
    value: Any,
    records: list[tuple[OutputCell, ...]],
    numeric_policy: str,
) -> str:
    row_items = [row_axis.items[position] for position in row_axis.visible_positions]
    output.append((start, OutputCell(row_axis.column, "string")))
    output.append((_coordinate(start, 1, 0), OutputCell(value.alias, "string")))
    for row_offset, row_item in enumerate(row_items, start=1):
        output.append((_coordinate(start, 0, row_offset), OutputCell(_label(row_item), "string")))
        output.append(
            (
                _coordinate(start, 1, row_offset),
                _aggregate(_matching(records, row_axis, row_item), value, numeric_policy),
            )
        )
    total_row = len(row_items) + 1
    output.append((_coordinate(start, 0, total_row), OutputCell("Grand Total", "string")))
    output.append((_coordinate(start, 1, total_row), _aggregate(records, value, numeric_policy)))
    return _range(start, 2, total_row + 1)


def _append_matrix_pivot(
    output: list,
    start: str,
    row_axis: Any,
    column_axis: Any,
    value: Any,
    records: list[tuple[OutputCell, ...]],
    numeric_policy: str,
) -> str:
    row_items = [row_axis.items[position] for position in row_axis.visible_positions]
    column_items = [column_axis.items[position] for position in column_axis.visible_positions]
    output.append((_coordinate(start, 1, 0), OutputCell(column_axis.column, "string")))
    output.append((_coordinate(start, 0, 1), OutputCell(row_axis.column, "string")))
    for column_offset, column_item in enumerate(column_items, start=1):
        output.append((_coordinate(start, column_offset, 1), OutputCell(_label(column_item), "string")))
    total_column = len(column_items) + 1
    output.append((_coordinate(start, total_column, 1), OutputCell("Grand Total", "string")))
    for row_offset, row_item in enumerate(row_items, start=2):
        output.append((_coordinate(start, 0, row_offset), OutputCell(_label(row_item), "string")))
        row_records = _matching(records, row_axis, row_item)
        for column_offset, column_item in enumerate(column_items, start=1):
            aggregate = _aggregate(
                _matching(row_records, column_axis, column_item),
                value,
                numeric_policy,
            )
            if aggregate.kind != "empty":
                output.append((_coordinate(start, column_offset, row_offset), aggregate))
        output.append(
            (_coordinate(start, total_column, row_offset), _aggregate(row_records, value, numeric_policy))
        )
    total_row = len(row_items) + 2
    output.append((_coordinate(start, 0, total_row), OutputCell("Grand Total", "string")))
    for column_offset, column_item in enumerate(column_items, start=1):
        output.append(
            (
                _coordinate(start, column_offset, total_row),
                _aggregate(_matching(records, column_axis, column_item), value, numeric_policy),
            )
        )
    output.append((_coordinate(start, total_column, total_row), _aggregate(records, value, numeric_policy)))
    return _range(start, total_column + 1, total_row + 1)


def _matching(records: list, axis: Any, item: OutputCell) -> list:
    return [record for record in records if _same(record[axis.field_index], item)]


def _aggregate(records: list, value: Any, numeric_policy: str) -> OutputCell:
    if not records:
        return OutputCell("", "empty")
    cells = [record[value.field_index] for record in records]
    if value.function == "count":
        return OutputCell(str(sum(item.kind != "empty" for item in cells)), "number")
    numbers = [_numeric(item, value.column, numeric_policy) for item in cells if item.kind != "empty"]
    if not numbers:
        return OutputCell("", "empty")
    if value.function == "sum":
        result = sum(numbers, Decimal(0))
    elif value.function == "average":
        result = sum(numbers, Decimal(0)) / Decimal(len(numbers))
    elif value.function == "min":
        result = min(numbers)
    else:
        result = max(numbers)
    return OutputCell(decimal_text(result), "number")


def _numeric(item: OutputCell, column: str, numeric_policy: str) -> Decimal:
    if item.kind != "number" and not (numeric_policy == "coerce-text" and item.kind == "string"):
        _failed("Pivot numeric aggregation encountered a non-numeric value.", column=column)
    try:
        result = Decimal(item.value)
    except InvalidOperation:
        _failed("Pivot numeric aggregation encountered an invalid decimal.", column=column)
    if not result.is_finite():
        _failed("Pivot numeric aggregation requires finite values.", column=column)
    return result


def _same(first: OutputCell, second: OutputCell) -> bool:
    return first.kind == second.kind and first.value == second.value


def _label(item: OutputCell) -> str:
    if item.kind == "empty":
        return "(blank)"
    if item.kind == "boolean":
        return "TRUE" if item.value == "1" else "FALSE"
    return item.value


def _coordinate(start: str, column_offset: int, row_offset: int) -> str:
    parsed = parse_ref(start)
    assert parsed is not None
    column = _column_number(parsed[0]) + column_offset
    row = parsed[1] + row_offset
    if column > 16_384 or row > 1_048_576:
        _invalid("Pivot target range exceeds worksheet bounds.")
    return f"{num_to_col(column)}{row}"


def _range(start: str, columns: int, rows: int) -> str:
    return f"{start}:{_coordinate(start, columns - 1, rows - 1)}"


def _display_range(start: str, location: str) -> str:
    return f"{start}:{location.rsplit(':', 1)[-1]}"


def _column_number(value: str) -> int:
    result = 0
    for character in value:
        result = result * 26 + ord(character.upper()) - ord("A") + 1
    return result


def _invalid(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.REQUEST_INVALID, message, status="invalid_request")


def _failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)
