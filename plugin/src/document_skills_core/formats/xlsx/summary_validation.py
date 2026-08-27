"""Independent reopen assertions for ordinary summary-sheet output."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .format_policy import allowed_inert_categories, assert_package_matches_path, format_id
from .mapping import col_to_num, map_workbook, num_to_col, parse_ref
from .package import OpcPackage
from .projection import project_tables
from .summary_model import SummaryBuild
from .summary_support import OutputCell


def assert_summary_written(path: Path, expected: SummaryBuild) -> dict[str, Any]:
    package = OpcPackage.open(
        path,
        allowed_inert_categories=allowed_inert_categories(format_id(path)),
    )
    assert_package_matches_path(path, package.workbook_format)
    workbook = map_workbook(package)
    sheet = next(
        (item for item in workbook["sheets"] if item["name"] == expected.target_sheet),
        None,
    )
    if sheet is None or not sheet.get("part"):
        _failed("Summary target worksheet was not found after reopen.")
    actual = {
        cell["ref"].upper(): cell
        for row in sheet.get("rows", [])
        for cell in row.get("cells", [])
    }
    start = parse_ref(expected.target_start_cell)
    assert start is not None
    first_column = col_to_num(start[0])
    expected_rows = [
        tuple(OutputCell(value, "string") for value in expected.headers),
        *expected.rows,
    ]
    mismatches: list[str] = []
    for row_offset, row in enumerate(expected_rows):
        for column_offset, cell in enumerate(row):
            ref = f"{num_to_col(first_column + column_offset)}{start[1] + row_offset}"
            if not _matches(actual.get(ref), cell):
                mismatches.append(ref)
    if mismatches:
        _failed(
            "Summary cells did not match the computed aggregation after reopen.",
            cells=mismatches[:100],
        )
    table = next(
        (
            item
            for item in project_tables(package)
            if item["name"].casefold() == expected.table_name.casefold()
            and item.get("sheet") == expected.target_sheet
        ),
        None,
    )
    if table is None or any(
        (
            table.get("ref") != expected.target_range,
            table.get("style") != expected.table_style,
            table.get("columns") != list(expected.headers),
        )
    ):
        _failed("Summary native table did not match the requested output.")
    pivot_relationships = [
        relationship.relationship_id
        for relationship in package.relationships
        if relationship.source_part == sheet["part"]
        and relationship.relationship_type.rsplit("/", 1)[-1] == "pivotTable"
    ]
    if pivot_relationships:
        _failed(
            "Ordinary summary output unexpectedly owns a native pivot relationship.",
            relationships=pivot_relationships,
        )
    return {
        "summary_kind": "ordinary_table",
        "native_pivot": False,
        "sheet": expected.target_sheet,
        "range": expected.target_range,
        "table_name": expected.table_name,
        "groups": expected.groups_written,
    }


def _matches(actual: dict[str, Any] | None, expected: OutputCell) -> bool:
    if expected.kind == "empty":
        return actual is None or actual.get("value") is None
    if actual is None or actual.get("value") is None:
        return False
    value = str(actual["value"])
    if expected.kind == "number":
        try:
            return Decimal(value) == Decimal(expected.value)
        except InvalidOperation:
            return False
    if expected.kind == "boolean":
        return actual.get("type") == "b" and value == expected.value
    return value == expected.value and actual.get("type") in {"s", "str", "inlineStr"}


def _failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)
