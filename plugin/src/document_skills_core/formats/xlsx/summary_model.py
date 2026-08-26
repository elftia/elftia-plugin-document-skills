"""Deterministic ordinary-summary aggregation over stored SpreadsheetML values."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .mapping import map_workbook, num_to_col
from .summary_support import (
    OutputCell,
    cell_index,
    decimal_text,
    failed,
    format_range,
    headers,
    invalid,
    numeric_value,
    resolve_name,
    resolve_names,
    scalar,
    source_bounds,
    target_range,
    worksheet,
)


@dataclass(frozen=True)
class SummaryBuild:
    source_sheet: str
    source_range: str
    rows_scanned: int
    rows_included: int
    groups_before_top_n: int
    headers: tuple[str, ...]
    rows: tuple[tuple[OutputCell, ...], ...]
    formula_cells_used: tuple[str, ...]
    target_sheet: str
    target_start_cell: str
    target_range: str
    table_name: str
    table_style: str

    @property
    def groups_written(self) -> int:
        return len(self.rows)


def build_summary(package: Any, arguments: dict[str, Any]) -> SummaryBuild:
    workbook = map_workbook(package)
    source_sheet = worksheet(workbook, arguments["source"]["sheet"])
    target_sheet = arguments["target"]["sheet"]
    if any(item["name"].casefold() == target_sheet.casefold() for item in workbook["sheets"]):
        invalid("Summary target worksheet already exists.", sheet=target_sheet)
    cells = cell_index(source_sheet)
    bounds = source_bounds(cells, arguments["source"]["range"])
    first_column, first_row, last_column, last_row = bounds
    rows_scanned = max(0, last_row - first_row)
    if rows_scanned > arguments["limits"]["max_source_rows"]:
        failed(
            "Summary source exceeds the configured row limit.",
            rows=rows_scanned,
            limit=arguments["limits"]["max_source_rows"],
        )
    source_columns = last_column - first_column + 1
    if source_columns > arguments["limits"]["max_source_columns"]:
        failed(
            "Summary source exceeds the configured column limit.",
            columns=source_columns,
            limit=arguments["limits"]["max_source_columns"],
        )

    formula_cells: set[str] = set()
    headers_list = headers(
        cells,
        bounds,
        sheet_name=source_sheet["name"],
        formula_policy=arguments["formula_policy"],
        formula_cells=formula_cells,
    )
    header_index = {name.casefold(): index for index, name in enumerate(headers_list)}
    group_columns = resolve_names(arguments["group_by"], header_index, "group_by")
    aggregate_columns = [
        None
        if item["function"] == "count"
        else resolve_name(item["column"], header_index, "aggregates.column")
        for item in arguments["aggregates"]
    ]
    output_headers = tuple(
        [headers_list[index] for index in group_columns]
        + [item["as"] for item in arguments["aggregates"]]
    )
    if len({name.casefold() for name in output_headers}) != len(output_headers):
        invalid("Resolved summary output headers are not unique.")
    sort_columns = [
        resolve_name(item["column"], {name.casefold(): index for index, name in enumerate(output_headers)}, "sort.column")
        for item in arguments["sort"]
    ]

    grouped: dict[tuple[tuple[str, str], ...], list[list[OutputCell]]] = {}
    rows_included = 0
    selected_columns = set(group_columns)
    selected_columns.update(index for index in aggregate_columns if index is not None)
    populated_rows = {
        row
        for (column, row), cell in cells.items()
        if first_column <= column <= last_column
        and first_row < row <= last_row
        and (cell.get("formula") or cell.get("value") is not None)
    }
    for row_number in range(first_row + 1, last_row + 1):
        if row_number not in populated_rows:
            continue
        selected = {
            index: scalar(
                cells.get((first_column + index, row_number)),
                formula_policy=arguments["formula_policy"],
                formula_cells=formula_cells,
                ref=f"{source_sheet['name']}!{num_to_col(first_column + index)}{row_number}",
            )
            for index in selected_columns
        }
        rows_included += 1
        key = tuple(
            (selected[index].kind, selected[index].value) for index in group_columns
        )
        if key not in grouped:
            if len(grouped) >= arguments["limits"]["max_groups"]:
                failed(
                    "Summary output exceeds the configured group limit.",
                    limit=arguments["limits"]["max_groups"],
                )
            grouped[key] = []
        grouped[key].append(
            [selected.get(index, OutputCell("", "empty")) for index in range(len(headers_list))]
        )

    rows = [
        tuple(
            [OutputCell(value, kind) for kind, value in key]
            + [
                _aggregate(
                    grouped_rows,
                    definition,
                    aggregate_columns[index],
                    numeric_policy=arguments["numeric_policy"],
                )
                for index, definition in enumerate(arguments["aggregates"])
            ]
        )
        for key, grouped_rows in grouped.items()
    ]
    rows = _sort_rows(rows, sort_columns, arguments["sort"])
    groups_before_top_n = len(rows)
    if arguments["top_n"] is not None:
        rows = rows[: arguments["top_n"]]
    output_cells = (len(rows) + 1) * len(output_headers)
    if output_cells > arguments["limits"]["max_output_cells"]:
        failed(
            "Summary output exceeds the configured cell limit.",
            cells=output_cells,
            limit=arguments["limits"]["max_output_cells"],
        )
    output_range = target_range(
        arguments["target"]["start_cell"],
        len(output_headers),
        len(rows) + 1,
    )
    return SummaryBuild(
        source_sheet=source_sheet["name"],
        source_range=format_range(bounds),
        rows_scanned=rows_scanned,
        rows_included=rows_included,
        groups_before_top_n=groups_before_top_n,
        headers=output_headers,
        rows=tuple(rows),
        formula_cells_used=tuple(sorted(formula_cells)),
        target_sheet=target_sheet,
        target_start_cell=arguments["target"]["start_cell"],
        target_range=output_range,
        table_name=arguments["target"]["table_name"],
        table_style=arguments["target"]["table_style"],
    )


def _aggregate(
    rows: list[list[OutputCell]],
    definition: dict[str, Any],
    column: int | None,
    *,
    numeric_policy: str,
) -> OutputCell:
    function = definition["function"]
    if function == "count":
        return OutputCell(str(len(rows)), "number")
    assert column is not None
    values = [row[column] for row in rows]
    if function == "count_nonblank":
        return OutputCell(str(sum(item.kind != "empty" for item in values)), "number")
    if function == "count_distinct":
        distinct = {(item.kind, item.value) for item in values if item.kind != "empty"}
        return OutputCell(str(len(distinct)), "number")
    numbers = [
        number
        for item in values
        for number in [numeric_value(item, definition["column"], numeric_policy)]
        if number is not None
    ]
    if function == "sum":
        return OutputCell(decimal_text(sum(numbers, Decimal(0))), "number")
    if not numbers:
        return OutputCell("", "empty")
    if function == "average":
        result = sum(numbers, Decimal(0)) / Decimal(len(numbers))
    elif function == "min":
        result = min(numbers)
    else:
        result = max(numbers)
    return OutputCell(decimal_text(result), "number")


def _sort_rows(
    rows: list[tuple[OutputCell, ...]],
    columns: list[int],
    definitions: list[dict[str, str]],
) -> list[tuple[OutputCell, ...]]:
    result = list(rows)
    for column, definition in reversed(list(zip(columns, definitions, strict=True))):
        populated = [row for row in result if row[column].kind != "empty"]
        empty = [row for row in result if row[column].kind == "empty"]
        populated.sort(
            key=lambda row: _sort_key(row[column]),
            reverse=definition["direction"] == "desc",
        )
        result = populated + empty
    return result


def _sort_key(cell: OutputCell) -> tuple[int, Any]:
    if cell.kind == "number":
        try:
            return 0, Decimal(cell.value)
        except InvalidOperation:
            pass
    if cell.kind == "boolean":
        return 1, int(cell.value)
    return 2, cell.value.casefold()
