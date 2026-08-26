"""Closed public payloads for typed DOCX table edits."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_MAX_CELL_BYTES = 32_768
_MAX_TABLE_CELLS = 8_192


def parse_table_target(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.target"
    if type(value) is not dict:
        _invalid("Table target must be an object.", field=field)
    _exact_keys(value, {"expected_table_sha256", "story", "table_index"})
    if value.get("story") != "body":
        _invalid("Table edits currently target only the body story.", field=f"{field}.story")
    digest = value.get("expected_table_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid(
            "Expected table SHA-256 must be a 64-digit hexadecimal value.",
            field=f"{field}.expected_table_sha256",
        )
    return {
        "story": "body",
        "table_index": _integer(value.get("table_index"), 0, 10_000, f"{field}.table_index"),
        "expected_table_sha256": digest.casefold(),
    }


def parse_table_payload(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Table payload must be an object.", field=field)
    _exact_keys(value, {"rows", "style"})
    style = value.get("style", "TableGrid")
    if style != "TableGrid":
        _invalid("Core DOCX supports only the TableGrid table style.", field=f"{field}.style")
    rows = _text_matrix(value.get("rows"), f"{field}.rows", minimum_rows=1)
    if sum(len(row) for row in rows) > _MAX_TABLE_CELLS:
        _invalid("Table payload exceeds the aggregate cell limit.", field=f"{field}.rows")
    return {"style": style, "rows": rows}


def parse_cell_selector(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.cell"
    if type(value) is not dict:
        _invalid("Table cell selector must be an object.", field=field)
    _exact_keys(value, {"cell_index", "expected_text", "row_index"})
    return {
        "row_index": _integer(value.get("row_index"), 0, 10_000, f"{field}.row_index"),
        "cell_index": _integer(value.get("cell_index"), 0, 1_000, f"{field}.cell_index"),
        "expected_text": _text(value.get("expected_text"), f"{field}.expected_text"),
    }


def parse_row_selector(value: Any, edit_index: int, name: str) -> dict[str, Any]:
    field = f"edits.{edit_index}.{name}"
    if type(value) is not dict:
        _invalid("Table row selector must be an object.", field=field)
    _exact_keys(value, {"expected_cells", "row_index"})
    cells = value.get("expected_cells")
    if type(cells) is not list or not 1 <= len(cells) <= 64:
        _invalid("Expected row cells must be a non-empty bounded array.", field=f"{field}.expected_cells")
    return {
        "row_index": _integer(value.get("row_index"), 0, 10_000, f"{field}.row_index"),
        "expected_cells": [
            _text(cell, f"{field}.expected_cells.{index}")
            for index, cell in enumerate(cells)
        ],
    }


def parse_cells(value: Any, field: str, *, minimum: int = 1) -> list[str]:
    if type(value) is not list or not minimum <= len(value) <= 64:
        _invalid("Table cells must be a bounded text array.", field=field)
    return [_text(cell, f"{field}.{index}") for index, cell in enumerate(value)]


def parse_merge_range(value: Any, edit_index: int) -> dict[str, Any]:
    field = f"edits.{edit_index}.range"
    if type(value) is not dict:
        _invalid("Table merge range must be an object.", field=field)
    _exact_keys(
        value,
        {"end_column", "end_row", "expected_texts", "start_column", "start_row"},
    )
    start_row = _integer(value.get("start_row"), 0, 10_000, f"{field}.start_row")
    end_row = _integer(value.get("end_row"), start_row, 10_000, f"{field}.end_row")
    start_column = _integer(
        value.get("start_column"), 0, 1_000, f"{field}.start_column"
    )
    end_column = _integer(
        value.get("end_column"), start_column, 1_000, f"{field}.end_column"
    )
    if start_row == end_row and start_column == end_column:
        _invalid("Table merge range must contain at least two cells.", field=field)
    expected = _text_matrix(
        value.get("expected_texts"),
        f"{field}.expected_texts",
        minimum_rows=1,
    )
    expected_height = end_row - start_row + 1
    expected_width = end_column - start_column + 1
    if len(expected) != expected_height or any(
        len(row) != expected_width for row in expected
    ):
        _invalid("Merge expected_texts must exactly match the selected rectangle.", field=f"{field}.expected_texts")
    if expected_height * expected_width > _MAX_TABLE_CELLS:
        _invalid("Table merge range exceeds the cell limit.", field=field)
    return {
        "start_row": start_row,
        "end_row": end_row,
        "start_column": start_column,
        "end_column": end_column,
        "expected_texts": expected,
    }


def parse_table_text(value: Any, field: str) -> str:
    return _text(value, field)


def _text_matrix(value: Any, field: str, *, minimum_rows: int) -> list[list[str]]:
    if type(value) is not list or not minimum_rows <= len(value) <= 1_000:
        _invalid("Table rows must be a non-empty bounded array.", field=field)
    rows: list[list[str]] = []
    width = None
    for row_index, row in enumerate(value):
        if type(row) is not list or not 1 <= len(row) <= 64:
            _invalid("Each table row must be a non-empty bounded array.", field=f"{field}.{row_index}")
        parsed = [
            _text(cell, f"{field}.{row_index}.{cell_index}")
            for cell_index, cell in enumerate(row)
        ]
        width = len(parsed) if width is None else width
        if len(parsed) != width:
            _invalid("All table rows must have the same cell count.", field=field)
        rows.append(parsed)
    return rows


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(
            f"Integer must be between {minimum} and {maximum}.",
            field=field,
        )
    return value


def _text(value: Any, field: str) -> str:
    if type(value) is not str:
        _invalid("Expected a text value.", field=field)
    if len(value.encode("utf-8", errors="strict")) > _MAX_CELL_BYTES:
        _invalid("Table cell text exceeds the byte limit.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected DOCX table argument keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
