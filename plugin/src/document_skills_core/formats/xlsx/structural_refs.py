"""Bounded A1 reference migration for row and column structural edits."""

from __future__ import annotations

from dataclasses import dataclass
import re

_SHEET = r"(?:'(?:[^']|'')+'|[A-Za-z_\\][A-Za-z0-9_.\\]*)"
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_COLUMN_RANGE = r"\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}"
_ROW_RANGE = r"\$?\d+:\$?\d+"
_REFERENCE_RE = re.compile(
    rf"(?<![A-Za-z0-9_.])(?:(?P<sheet>{_SHEET})!)?"
    rf"(?P<ref>(?:{_CELL})(?::{_CELL})?|{_COLUMN_RANGE}|{_ROW_RANGE})"
    r"(?![A-Za-z0-9_])"
)
_CELL_RE = re.compile(r"(?P<col_abs>\$?)(?P<col>[A-Za-z]{1,3})(?P<row_abs>\$?)(?P<row>\d+)")
_COLUMN_RANGE_RE = re.compile(
    r"(?P<a_abs>\$?)(?P<a>[A-Za-z]{1,3}):(?P<b_abs>\$?)(?P<b>[A-Za-z]{1,3})"
)
_ROW_RANGE_RE = re.compile(r"(?P<a_abs>\$?)(?P<a>\d+):(?P<b_abs>\$?)(?P<b>\d+)")
_SHEET_REFERENCE_RE = re.compile(rf"(?<![A-Za-z0-9_.])(?P<sheet>{_SHEET})!")


@dataclass(frozen=True)
class AxisMutation:
    sheet: str
    axis: str
    index: int
    count: int
    delete: bool


def rewrite_formula(
    formula: str,
    *,
    current_sheet: str | None,
    mutation: AxisMutation,
) -> str:
    """Rewrite A1 references outside formula string literals."""

    fragments = formula.split('"')
    for index in range(0, len(fragments), 2):
        fragments[index] = _REFERENCE_RE.sub(
            lambda match: _rewrite_match(match, current_sheet, mutation),
            fragments[index],
        )
    return '"'.join(fragments)


def rewrite_reference(
    reference: str,
    *,
    current_sheet: str | None,
    mutation: AxisMutation,
) -> str:
    """Rewrite a single range, sqref list, defined name, or chart formula."""

    return _REFERENCE_RE.sub(
        lambda match: _rewrite_match(match, current_sheet, mutation),
        reference,
    )


def shift_coordinate(
    column: int,
    row: int,
    mutation: AxisMutation,
) -> tuple[int, int] | None:
    value = row if mutation.axis == "row" else column
    shifted = _shift_single(value, mutation)
    if shifted is None:
        return None
    return (column, shifted) if mutation.axis == "row" else (shifted, row)


def has_external_workbook_reference(formula: str) -> bool:
    return re.search(r"\[[^\]]+\][^!]*!", formula) is not None


def rename_sheet_references(value: str, old_name: str, new_name: str) -> str:
    """Rename explicit sheet tokens while preserving formula string literals."""

    fragments = value.split('"')
    for index in range(0, len(fragments), 2):
        fragments[index] = _SHEET_REFERENCE_RE.sub(
            lambda match: (
                f"{_encode_sheet(new_name)}!"
                if _decode_sheet(match.group("sheet")).casefold() == old_name.casefold()
                else match.group(0)
            ),
            fragments[index],
        )
    return '"'.join(fragments)


def references_sheet(value: str, sheet_name: str) -> bool:
    """Return whether a formula/reference contains an explicit target sheet token."""

    return any(
        _decode_sheet(match.group("sheet")).casefold() == sheet_name.casefold()
        for match in _SHEET_REFERENCE_RE.finditer(value)
    )


def _rewrite_match(
    match: re.Match[str],
    current_sheet: str | None,
    mutation: AxisMutation,
) -> str:
    sheet_token = match.group("sheet")
    referenced_sheet = _decode_sheet(sheet_token) if sheet_token else current_sheet
    if referenced_sheet is None or referenced_sheet.casefold() != mutation.sheet.casefold():
        return match.group(0)
    shifted = _shift_a1_reference(match.group("ref"), mutation)
    if shifted == "#REF!":
        return "#REF!"
    prefix = f"{sheet_token}!" if sheet_token else ""
    return f"{prefix}{shifted}"


def _shift_a1_reference(reference: str, mutation: AxisMutation) -> str:
    column_range = _COLUMN_RANGE_RE.fullmatch(reference)
    if column_range is not None:
        if mutation.axis != "column":
            return reference
        shifted = _shift_interval(
            _column_number(column_range.group("a")),
            _column_number(column_range.group("b")),
            mutation,
        )
        if shifted is None:
            return "#REF!"
        return (
            f"{column_range.group('a_abs')}{_column_name(shifted[0])}:"
            f"{column_range.group('b_abs')}{_column_name(shifted[1])}"
        )
    row_range = _ROW_RANGE_RE.fullmatch(reference)
    if row_range is not None:
        if mutation.axis != "row":
            return reference
        shifted = _shift_interval(
            int(row_range.group("a")),
            int(row_range.group("b")),
            mutation,
        )
        if shifted is None:
            return "#REF!"
        return (
            f"{row_range.group('a_abs')}{shifted[0]}:"
            f"{row_range.group('b_abs')}{shifted[1]}"
        )
    cells = reference.split(":", 1)
    parsed = [_CELL_RE.fullmatch(cell) for cell in cells]
    if any(item is None for item in parsed):
        return reference
    if len(parsed) == 1:
        return _shift_cell(parsed[0], mutation)
    start = parsed[0]
    end = parsed[1]
    if mutation.axis == "row":
        interval = _shift_interval(
            int(start.group("row")),
            int(end.group("row")),
            mutation,
        )
        if interval is None:
            return "#REF!"
        start_value, end_value = interval
        return f"{_render_cell(start, row=start_value)}:{_render_cell(end, row=end_value)}"
    interval = _shift_interval(
        _column_number(start.group("col")),
        _column_number(end.group("col")),
        mutation,
    )
    if interval is None:
        return "#REF!"
    return (
        f"{_render_cell(start, column=interval[0])}:"
        f"{_render_cell(end, column=interval[1])}"
    )


def _shift_cell(match: re.Match[str], mutation: AxisMutation) -> str:
    if mutation.axis == "row":
        shifted = _shift_single(int(match.group("row")), mutation)
        return "#REF!" if shifted is None else _render_cell(match, row=shifted)
    shifted = _shift_single(_column_number(match.group("col")), mutation)
    return "#REF!" if shifted is None else _render_cell(match, column=shifted)


def _shift_single(value: int, mutation: AxisMutation) -> int | None:
    if not mutation.delete:
        shifted = value + mutation.count if value >= mutation.index else value
        maximum = 1_048_576 if mutation.axis == "row" else 16_384
        return None if shifted > maximum else shifted
    deleted_last = mutation.index + mutation.count - 1
    if mutation.index <= value <= deleted_last:
        return None
    return value - mutation.count if value > deleted_last else value


def _shift_interval(
    start: int,
    end: int,
    mutation: AxisMutation,
) -> tuple[int, int] | None:
    if start > end:
        start, end = end, start
    if not mutation.delete:
        shifted_start = start + mutation.count if start >= mutation.index else start
        shifted_end = end + mutation.count if end >= mutation.index else end
        maximum = 1_048_576 if mutation.axis == "row" else 16_384
        if shifted_end > maximum:
            return None
        return shifted_start, shifted_end
    deleted_last = mutation.index + mutation.count - 1
    if end < mutation.index:
        return start, end
    if start > deleted_last:
        return start - mutation.count, end - mutation.count
    retained_before = start < mutation.index
    retained_after = end > deleted_last
    if not retained_before and not retained_after:
        return None
    shifted_start = start if retained_before else mutation.index
    shifted_end = end - mutation.count if retained_after else mutation.index - 1
    return (shifted_start, shifted_end) if shifted_start <= shifted_end else None


def _render_cell(
    match: re.Match[str],
    *,
    column: int | None = None,
    row: int | None = None,
) -> str:
    rendered_column = _column_name(column) if column is not None else match.group("col").upper()
    rendered_row = row if row is not None else int(match.group("row"))
    return (
        f"{match.group('col_abs')}{rendered_column}"
        f"{match.group('row_abs')}{rendered_row}"
    )


def _decode_sheet(value: str) -> str:
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _encode_sheet(value: str) -> str:
    if re.fullmatch(r"[A-Za-z_\\][A-Za-z0-9_.\\]*", value):
        return value
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
