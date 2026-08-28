"""Bounded lattice-table inference from axis-aligned stroked ruling paths."""

from dataclasses import dataclass
from typing import Any

from .content_streams import TextBlock
from .table_rulings import (
    COORDINATE_TOLERANCE,
    extract_stroked_rulings,
    RulingLine,
)

_CONFIDENCE = 0.9
_MAX_GRID_ROWS = 1_000
_MAX_GRID_COLUMNS = 256
_MAX_GRID_SLOTS = 4_096


@dataclass(frozen=True)
class _Cell:
    row: int
    column: int
    row_span: int
    column_span: int
    bbox: tuple[float, float, float, float]


def extract_lattice_tables(
    content: bytes,
    page: int,
    blocks: list[TextBlock],
    *,
    min_rows: int,
    min_columns: int,
) -> tuple[list[dict[str, Any]], set[int]]:
    """Return ruled tables and identities of text blocks assigned to their cells."""
    lines = extract_stroked_rulings(content)
    tables: list[dict[str, Any]] = []
    used_blocks: set[int] = set()
    for component in _connected_components(lines):
        projected = _project_component(
            component,
            page,
            blocks,
            min_rows=min_rows,
            min_columns=min_columns,
        )
        if projected is None:
            continue
        table, assigned = projected
        tables.append(table)
        used_blocks.update(assigned)
    tables.sort(key=lambda table: (-float(table["bbox"][3]), float(table["bbox"][0])))
    return tables, used_blocks


def _connected_components(lines: list[RulingLine]) -> list[list[RulingLine]]:
    parents = list(range(len(lines)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(lines)):
        for right in range(left + 1, len(lines)):
            if _lines_touch(lines[left], lines[right]):
                union(left, right)
    grouped: dict[int, list[RulingLine]] = {}
    for index, line in enumerate(lines):
        grouped.setdefault(find(index), []).append(line)
    return list(grouped.values())


def _lines_touch(left: RulingLine, right: RulingLine) -> bool:
    tolerance = COORDINATE_TOLERANCE
    if left.orientation == right.orientation:
        return (
            abs(left.position - right.position) <= tolerance
            and left.start <= right.end + tolerance
            and right.start <= left.end + tolerance
        )
    horizontal, vertical = (
        (left, right) if left.orientation == "horizontal" else (right, left)
    )
    return (
        horizontal.start - tolerance <= vertical.position <= horizontal.end + tolerance
        and vertical.start - tolerance
        <= horizontal.position
        <= vertical.end + tolerance
    )


def _project_component(
    lines: list[RulingLine],
    page: int,
    blocks: list[TextBlock],
    *,
    min_rows: int,
    min_columns: int,
) -> tuple[dict[str, Any], set[int]] | None:
    horizontal = [line for line in lines if line.orientation == "horizontal"]
    vertical = [line for line in lines if line.orientation == "vertical"]
    xs = _coordinates(
        [
            *(line.position for line in vertical),
            *(value for line in horizontal for value in (line.start, line.end)),
        ]
    )
    ys = _coordinates(
        [
            *(line.position for line in horizontal),
            *(value for line in vertical for value in (line.start, line.end)),
        ]
    )
    if len(xs) - 1 < min_columns or len(ys) - 1 < min_rows:
        return None
    row_count = len(ys) - 1
    column_count = len(xs) - 1
    if (
        row_count > _MAX_GRID_ROWS
        or column_count > _MAX_GRID_COLUMNS
        or row_count * column_count > _MAX_GRID_SLOTS
    ):
        return None
    xmin, xmax = xs[0], xs[-1]
    ymin, ymax = ys[0], ys[-1]
    if not (
        _covered(horizontal, ymin, xmin, xmax)
        and _covered(horizontal, ymax, xmin, xmax)
        and _covered(vertical, xmin, ymin, ymax)
        and _covered(vertical, xmax, ymin, ymax)
    ):
        return None
    cells = _infer_cells(xs, ys, horizontal, vertical)
    if cells is None:
        return None
    rows: list[dict[str, Any]] = []
    assigned: set[int] = set()
    for row_index in range(len(ys) - 1):
        row_top = ys[-1 - row_index]
        row_bottom = ys[-2 - row_index]
        row_cells = []
        for cell in (item for item in cells if item.row == row_index):
            matching = _blocks_in_box(blocks, cell.bbox)
            assigned.update(id(block) for block in matching)
            row_cells.append(
                {
                    "text": "\n".join(block.text for block in matching),
                    "bbox": list(cell.bbox),
                    "row": cell.row + 1,
                    "column": cell.column + 1,
                    "row_span": cell.row_span,
                    "column_span": cell.column_span,
                    "confidence": _CONFIDENCE,
                }
            )
        rows.append(
            {
                "bbox": [xmin, row_bottom, xmax, row_top],
                "cells": row_cells,
            }
        )
    merged_count = sum(cell.row_span > 1 or cell.column_span > 1 for cell in cells)
    return (
        {
            "index": 0,
            "page": page,
            "pages": [page],
            "bbox": [xmin, ymin, xmax, ymax],
            "source": "core-lattice",
            "confidence": _CONFIDENCE,
            "cross_page": False,
            "grid": {
                "row_count": len(ys) - 1,
                "column_count": len(xs) - 1,
                "merged_cell_count": merged_count,
            },
            "rows": rows,
        },
        assigned,
    )


def _coordinates(values: list[float]) -> list[float]:
    clustered: list[list[float]] = []
    for value in sorted(values):
        if clustered and value - clustered[-1][-1] <= COORDINATE_TOLERANCE:
            clustered[-1].append(value)
        else:
            clustered.append([value])
    return [round(sum(cluster) / len(cluster), 4) for cluster in clustered]


def _covered(
    lines: list[RulingLine], position: float, start: float, end: float
) -> bool:
    intervals = sorted(
        (max(start, line.start), min(end, line.end))
        for line in lines
        if abs(line.position - position) <= COORDINATE_TOLERANCE
        and line.end >= start - COORDINATE_TOLERANCE
        and line.start <= end + COORDINATE_TOLERANCE
    )
    cursor = start
    for interval_start, interval_end in intervals:
        if interval_start > cursor + COORDINATE_TOLERANCE:
            return False
        cursor = max(cursor, interval_end)
        if cursor >= end - COORDINATE_TOLERANCE:
            return True
    return cursor >= end - COORDINATE_TOLERANCE


def _infer_cells(
    xs: list[float],
    ys: list[float],
    horizontal: list[RulingLine],
    vertical: list[RulingLine],
) -> list[_Cell] | None:
    row_count = len(ys) - 1
    column_count = len(xs) - 1
    remaining = {
        (row, column) for row in range(row_count) for column in range(column_count)
    }
    cells: list[_Cell] = []
    while remaining:
        seed = min(remaining)
        region = {seed}
        stack = [seed]
        while stack:
            row, column = stack.pop()
            for neighbor in _open_neighbors(
                row,
                column,
                xs,
                ys,
                horizontal,
                vertical,
            ):
                if neighbor in remaining and neighbor not in region:
                    region.add(neighbor)
                    stack.append(neighbor)
        remaining.difference_update(region)
        rows = [slot[0] for slot in region]
        columns = [slot[1] for slot in region]
        row_min, row_max = min(rows), max(rows)
        column_min, column_max = min(columns), max(columns)
        if len(region) != (row_max - row_min + 1) * (column_max - column_min + 1):
            return None
        x0, x1 = xs[column_min], xs[column_max + 1]
        y1 = ys[-1 - row_min]
        y0 = ys[-2 - row_max]
        if not (
            _covered(horizontal, y0, x0, x1)
            and _covered(horizontal, y1, x0, x1)
            and _covered(vertical, x0, y0, y1)
            and _covered(vertical, x1, y0, y1)
        ):
            return None
        cells.append(
            _Cell(
                row=row_min,
                column=column_min,
                row_span=row_max - row_min + 1,
                column_span=column_max - column_min + 1,
                bbox=(x0, y0, x1, y1),
            )
        )
    return sorted(cells, key=lambda cell: (cell.row, cell.column))


def _open_neighbors(
    row: int,
    column: int,
    xs: list[float],
    ys: list[float],
    horizontal: list[RulingLine],
    vertical: list[RulingLine],
) -> list[tuple[int, int]]:
    row_count = len(ys) - 1
    column_count = len(xs) - 1
    top = ys[-1 - row]
    bottom = ys[-2 - row]
    neighbors: list[tuple[int, int]] = []
    if column > 0 and not _covered(vertical, xs[column], bottom, top):
        neighbors.append((row, column - 1))
    if column + 1 < column_count and not _covered(
        vertical, xs[column + 1], bottom, top
    ):
        neighbors.append((row, column + 1))
    if row > 0 and not _covered(horizontal, top, xs[column], xs[column + 1]):
        neighbors.append((row - 1, column))
    if row + 1 < row_count and not _covered(
        horizontal, bottom, xs[column], xs[column + 1]
    ):
        neighbors.append((row + 1, column))
    return neighbors


def _blocks_in_box(
    blocks: list[TextBlock],
    bbox: tuple[float, float, float, float],
) -> list[TextBlock]:
    x0, y0, x1, y1 = bbox
    matching = [
        block
        for block in blocks
        if x0 - COORDINATE_TOLERANCE
        <= (block.bbox[0] + block.bbox[2]) / 2.0
        <= x1 + COORDINATE_TOLERANCE
        and y0 - COORDINATE_TOLERANCE
        <= (block.bbox[1] + block.bbox[3]) / 2.0
        <= y1 + COORDINATE_TOLERANCE
    ]
    return sorted(matching, key=lambda block: (-block.bbox[3], block.bbox[0]))
