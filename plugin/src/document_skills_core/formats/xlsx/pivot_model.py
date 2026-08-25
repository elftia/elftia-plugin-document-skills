"""Stored-value model and deterministic layout for native pivot creation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import map_workbook, num_to_col
from .pivot_layout import build_pivot_layout
from .summary_support import (
    OutputCell,
    cell_index,
    decimal_text,
    headers,
    range_bounds,
    scalar,
    worksheet,
)


@dataclass(frozen=True)
class PivotCacheField:
    name: str
    items: tuple[OutputCell, ...]


@dataclass(frozen=True)
class PivotAxis:
    column: str
    field_index: int
    sort: str
    items: tuple[OutputCell, ...]
    cache_indices: tuple[int, ...]
    visible_positions: tuple[int, ...]


@dataclass(frozen=True)
class PivotFilter:
    column: str
    field_index: int
    items: tuple[OutputCell, ...]
    cache_indices: tuple[int, ...]
    selected_position: int | None


@dataclass(frozen=True)
class PivotValue:
    column: str
    field_index: int
    function: str
    alias: str


@dataclass(frozen=True)
class PivotBuild:
    source_sheet: str
    source_range: str
    source_headers: tuple[str, ...]
    record_count: int
    cache_fields: tuple[PivotCacheField, ...]
    cache_records: tuple[tuple[int, ...], ...]
    row_axis: PivotAxis
    column_axis: PivotAxis | None
    page_filter: PivotFilter | None
    value: PivotValue
    formula_cells_used: tuple[str, ...]
    target_sheet: str
    target_start_cell: str
    location_ref: str
    display_ref: str
    name: str
    style: str
    output_cells: tuple[tuple[str, OutputCell], ...]


def build_pivot(package: Any, arguments: dict[str, Any]) -> PivotBuild:
    workbook = map_workbook(package)
    source_sheet = worksheet(workbook, arguments["source"]["sheet"])
    target_sheet = arguments["target"]["sheet"]
    if any(item["name"].casefold() == target_sheet.casefold() for item in workbook["sheets"]):
        _invalid("Pivot target worksheet already exists.", sheet=target_sheet)

    cells = cell_index(source_sheet)
    bounds = range_bounds(arguments["source"]["range"])
    first_column, first_row, last_column, last_row = bounds
    source_rows = last_row - first_row
    source_columns = last_column - first_column + 1
    if source_rows > arguments["limits"]["max_source_rows"]:
        _failed("Pivot source exceeds the configured row limit.", rows=source_rows)
    if source_columns > arguments["limits"]["max_source_columns"]:
        _failed("Pivot source exceeds the configured column limit.", columns=source_columns)

    formula_cells: set[str] = set()
    source_headers = headers(
        cells,
        bounds,
        sheet_name=source_sheet["name"],
        formula_policy=arguments["formula_policy"],
        formula_cells=formula_cells,
    )
    header_index = {name.casefold(): index for index, name in enumerate(source_headers)}
    records = _source_records(
        cells,
        bounds,
        source_sheet["name"],
        arguments["formula_policy"],
        formula_cells,
    )
    if not records:
        _failed("Pivot source range contains no data records.")

    row_definition = arguments["rows"][0]
    column_definition = arguments["columns"][0] if arguments["columns"] else None
    filter_definition = arguments["filters"][0] if arguments["filters"] else None
    value_definition = arguments["values"][0]
    row_index = _field_index(row_definition["column"], header_index, "rows.0.column")
    column_index = (
        _field_index(column_definition["column"], header_index, "columns.0.column")
        if column_definition is not None
        else None
    )
    filter_index = (
        _field_index(filter_definition["column"], header_index, "filters.0.column")
        if filter_definition is not None
        else None
    )
    value_index = _field_index(value_definition["column"], header_index, "values.0.column")

    cache_fields, cache_records = _cache(records, source_headers)
    selected_filter = None
    if filter_definition is not None and filter_definition["value"] is not None:
        selected_filter = _request_scalar(filter_definition["value"])
    filtered = [
        record
        for record in records
        if filter_index is None
        or selected_filter is None
        or _same(record[filter_index], selected_filter)
    ]
    if not filtered:
        _failed("Pivot page filter selected no source records.")

    row_axis = _axis(
        records,
        filtered,
        cache_fields[row_index],
        row_definition,
        row_index,
        arguments["limits"]["max_axis_items"],
    )
    column_axis = (
        _axis(
            records,
            filtered,
            cache_fields[column_index],
            column_definition,
            column_index,
            arguments["limits"]["max_axis_items"],
        )
        if column_definition is not None and column_index is not None
        else None
    )
    page_filter = (
        _page_filter(cache_fields[filter_index], filter_definition, filter_index, selected_filter)
        if filter_definition is not None and filter_index is not None
        else None
    )
    value = PivotValue(
        value_definition["column"],
        value_index,
        value_definition["function"],
        value_definition["as"],
    )
    location_ref, display_ref, output_cells = build_pivot_layout(
        arguments["target"]["start_cell"],
        row_axis,
        column_axis,
        page_filter,
        value,
        filtered,
        numeric_policy=arguments["numeric_policy"],
    )
    if len(output_cells) > arguments["limits"]["max_output_cells"]:
        _failed("Pivot output exceeds the configured cell limit.", cells=len(output_cells))
    return PivotBuild(
        source_sheet=source_sheet["name"],
        source_range=arguments["source"]["range"],
        source_headers=tuple(source_headers),
        record_count=len(records),
        cache_fields=cache_fields,
        cache_records=cache_records,
        row_axis=row_axis,
        column_axis=column_axis,
        page_filter=page_filter,
        value=value,
        formula_cells_used=tuple(sorted(formula_cells)),
        target_sheet=target_sheet,
        target_start_cell=arguments["target"]["start_cell"],
        location_ref=location_ref,
        display_ref=display_ref,
        name=arguments["target"]["name"],
        style=arguments["target"]["style"],
        output_cells=output_cells,
    )


def _source_records(
    cells: dict[tuple[int, int], dict[str, Any]],
    bounds: tuple[int, int, int, int],
    sheet_name: str,
    formula_policy: str,
    formula_cells: set[str],
) -> list[tuple[OutputCell, ...]]:
    first_column, first_row, last_column, last_row = bounds
    result: list[tuple[OutputCell, ...]] = []
    for row in range(first_row + 1, last_row + 1):
        values = tuple(
            scalar(
                cells.get((column, row)),
                formula_policy=formula_policy,
                formula_cells=formula_cells,
                ref=f"{sheet_name}!{num_to_col(column)}{row}",
            )
            for column in range(first_column, last_column + 1)
        )
        _validate_record_values(values, row)
        if any(item.kind != "empty" for item in values):
            result.append(values)
    return result


def _validate_record_values(values: tuple[OutputCell, ...], row: int) -> None:
    for item in values:
        if item.kind != "number":
            continue
        try:
            number = Decimal(item.value)
        except InvalidOperation:
            _failed("Pivot cache encountered an invalid numeric value.", row=row)
        if not number.is_finite():
            _failed("Pivot cache requires finite numeric values.", row=row)


def _cache(
    records: list[tuple[OutputCell, ...]],
    source_headers: list[str],
) -> tuple[tuple[PivotCacheField, ...], tuple[tuple[int, ...], ...]]:
    fields: list[PivotCacheField] = []
    indexes: list[dict[tuple[str, str], int]] = []
    for column, name in enumerate(source_headers):
        items: list[OutputCell] = []
        lookup: dict[tuple[str, str], int] = {}
        for record in records:
            item = record[column]
            key = (item.kind, item.value)
            if key not in lookup:
                lookup[key] = len(items)
                items.append(item)
        fields.append(PivotCacheField(name, tuple(items)))
        indexes.append(lookup)
    cache_records = tuple(
        tuple(indexes[column][(item.kind, item.value)] for column, item in enumerate(record))
        for record in records
    )
    return tuple(fields), cache_records


def _axis(
    all_records: list[tuple[OutputCell, ...]],
    filtered_records: list[tuple[OutputCell, ...]],
    cache_field: PivotCacheField,
    definition: dict[str, str],
    field_index: int,
    limit: int,
) -> PivotAxis:
    items = _ordered_distinct((record[field_index] for record in all_records), definition["sort"])
    if len(items) > limit:
        _failed("Pivot axis exceeds the configured item limit.", column=definition["column"])
    cache_lookup = {(item.kind, item.value): index for index, item in enumerate(cache_field.items)}
    position_lookup = {(item.kind, item.value): index for index, item in enumerate(items)}
    visible_keys = {(record[field_index].kind, record[field_index].value) for record in filtered_records}
    visible_positions = tuple(
        index for key, index in position_lookup.items() if key in visible_keys
    )
    return PivotAxis(
        definition["column"],
        field_index,
        definition["sort"],
        items,
        tuple(cache_lookup[(item.kind, item.value)] for item in items),
        visible_positions,
    )


def _page_filter(
    cache_field: PivotCacheField,
    definition: dict[str, Any],
    field_index: int,
    selected: OutputCell | None,
) -> PivotFilter:
    items = _ordered_distinct(cache_field.items, "asc")
    cache_lookup = {(item.kind, item.value): index for index, item in enumerate(cache_field.items)}
    selected_position = None
    if selected is not None:
        selected_position = next(
            (index for index, item in enumerate(items) if _same(item, selected)),
            None,
        )
        if selected_position is None:
            _failed("Pivot page filter item was not found.", column=definition["column"])
    return PivotFilter(
        definition["column"],
        field_index,
        items,
        tuple(cache_lookup[(item.kind, item.value)] for item in items),
        selected_position,
    )


def _ordered_distinct(values: Any, direction: str) -> tuple[OutputCell, ...]:
    distinct: dict[tuple[str, str], OutputCell] = {}
    for item in values:
        distinct.setdefault((item.kind, item.value), item)
    return tuple(
        sorted(distinct.values(), key=_sort_key, reverse=direction == "desc")
    )


def _sort_key(item: OutputCell) -> tuple[int, Any]:
    if item.kind == "number":
        try:
            return 0, Decimal(item.value)
        except InvalidOperation:
            pass
    if item.kind == "boolean":
        return 1, int(item.value)
    if item.kind == "empty":
        return 3, ""
    return 2, item.value.casefold()


def _request_scalar(value: str | int | float | bool) -> OutputCell:
    if type(value) is bool:
        return OutputCell("1" if value else "0", "boolean")
    if type(value) in {int, float}:
        if type(value) is float and not math.isfinite(value):
            _invalid("Pivot filter number must be finite.")
        return OutputCell(decimal_text(Decimal(str(value))), "number")
    return OutputCell(value, "string")


def _field_index(name: str, index: dict[str, int], field: str) -> int:
    result = index.get(name.casefold())
    if result is None:
        _invalid("Pivot source column was not found.", field=field, column=name)
    return result


def _same(first: OutputCell, second: OutputCell) -> bool:
    return first.kind == second.kind and first.value == second.value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)
