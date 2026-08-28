"""Deterministic styled table layout for PDF creation."""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import bbox_within, PageLayout, pdf_number
from .font_embedding import EmbeddedFontSet
from .font_shaping import resolved_style, ShapedLine, TextShaper
from .unicode_text import emit_shaped_line


@dataclass(frozen=True)
class _CellLayout:
    text: str
    alignment: str
    fill: list[float] | None
    lines: tuple[ShapedLine, ...]


@dataclass(frozen=True)
class _RowLayout:
    cells: tuple[_CellLayout, ...]
    height: float
    fill: list[float] | None


def build_table_block(
    block: dict[str, Any],
    layout: PageLayout,
    top: float,
    *,
    page_number: int,
    block_index: int,
    shaper: TextShaper,
    fonts: EmbeddedFontSet,
    spacing_after: float = 10.0,
) -> tuple[list[str], float, dict[str, Any]]:
    """Build a bounded styled table and its creation evidence."""
    table, style, widths, rows = _resolved_table_layout(
        block,
        layout,
        shaper,
    )
    column_count = len(widths)
    total_height = sum(row.height for row in rows)
    if top - total_height < layout.bottom:
        capability = "pdf.table-pagination" if table["repeat_header"] else "pdf.table-overflow"
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED if table["repeat_header"] else ErrorCode.REQUEST_INVALID,
            "Table content exceeds the current page content box.",
            status="enhancement_required" if table["repeat_header"] else "invalid_request",
            details={
                "field": f"pages.{page_number - 1}.blocks.{block_index}",
                "capability": capability,
                "required_height": round(total_height, 4),
                "available_height": round(top - layout.bottom, 4),
            },
        )

    operators = ["%DS-BLOCK:table"]
    cell_evidence: list[dict[str, Any]] = []
    text_evidence: list[dict[str, Any]] = []
    row_top = top
    for row_index, row in enumerate(rows):
        row_bottom = row_top - row.height
        cell_left = layout.left
        for column_index, width in enumerate(widths):
            cell = row.cells[column_index]
            fill = _cell_fill(cell, row, table, row_index)
            if fill is not None:
                operators.extend([
                    "q",
                    _color_operator(fill, "rg"),
                    f"{pdf_number(cell_left)} {pdf_number(row_bottom)} "
                    f"{pdf_number(width)} {pdf_number(row.height)} re f",
                    "Q",
                ])
            border = table["border"]
            operators.extend([
                "q",
                f"{pdf_number(border['width'])} w",
                _color_operator(border["color"], "RG"),
                f"{pdf_number(cell_left)} {pdf_number(row_bottom)} "
                f"{pdf_number(width)} {pdf_number(row.height)} re S",
                "Q",
            ])
            baseline = row_top - table["padding"] - style["font_size"] * 0.8
            cell_bbox = [cell_left, row_bottom, cell_left + width, row_top]
            content_bbox = [
                cell_left + table["padding"],
                row_bottom + table["padding"],
                cell_left + width - table["padding"],
                row_top - table["padding"],
            ]
            line_bboxes: list[list[float]] = []
            for line in cell.lines:
                text_x = _cell_text_x(
                    cell_left,
                    width,
                    line.width,
                    table["padding"],
                    cell.alignment,
                )
                line_bbox = [
                    round(text_x, 4),
                    round(baseline - style["font_size"] * 0.2, 4),
                    round(text_x + line.width, 4),
                    round(baseline + style["font_size"] * 0.8, 4),
                ]
                if not bbox_within(line_bbox, content_bbox):
                    raise DocumentSkillsError(
                        ErrorCode.REQUEST_INVALID,
                        "Table cell text exceeds its content box.",
                        status="invalid_request",
                        details={
                            "row": row_index,
                            "column": column_index,
                            "bbox": line_bbox,
                            "content_bbox": content_bbox,
                        },
                    )
                line_ops, resources = emit_shaped_line(
                    line,
                    style,
                    x=text_x,
                    baseline=baseline,
                    fonts=fonts,
                )
                operators.extend(line_ops)
                line_bboxes.append(line_bbox)
                text_evidence.append({
                    "page": page_number,
                    "block_index": block_index,
                    "source_text": cell.text,
                    "text": line.text,
                    "bbox": line_bbox,
                    "font": f"/{resources[0]}" if resources else None,
                    "fonts": [f"/{resource}" for resource in resources],
                    "size": style["font_size"],
                    "color": style["color"],
                    "line_height": style["line_height"],
                    "alignment": cell.alignment,
                    "direction": line.direction,
                    "language": style.get("language"),
                })
                baseline -= style["line_height"]
            cell_evidence.append({
                "row": row_index,
                "column": column_index,
                "bbox": [round(value, 4) for value in cell_bbox],
                "content_bbox": [round(value, 4) for value in content_bbox],
                "line_bboxes": line_bboxes,
                "text": cell.text,
            })
            cell_left += width
        row_top = row_bottom
    return operators, row_top - spacing_after, {
        "page": page_number,
        "block_index": block_index,
        "bbox": [layout.left, row_top, layout.left + sum(widths), top],
        "row_count": len(rows),
        "column_count": column_count,
        "column_widths": [round(width, 4) for width in widths],
        "row_heights": [round(row.height, 4) for row in rows],
        "header_rows": table["header_rows"],
        "repeat_header": table["repeat_header"],
        "padding": table["padding"],
        "border": table["border"],
        "cells": cell_evidence,
        "text_lines": text_evidence,
    }


def paginate_table_block(
    block: dict[str, Any],
    layout: PageLayout,
    shaper: TextShaper,
) -> list[dict[str, Any]]:
    """Split a sole repeat-header table into page-sized block copies."""
    table, _style, _widths, row_layouts = _resolved_table_layout(
        block,
        layout,
        shaper,
    )
    if not table["repeat_header"]:
        return [block]
    available = layout.height - layout.top - layout.bottom
    if sum(row.height for row in row_layouts) <= available:
        return [block]
    header_count = table["header_rows"]
    header_height = sum(row.height for row in row_layouts[:header_count])
    if header_count == 0 or header_height >= available:
        raise _table_pagination_error("Repeated table headers do not fit on a page.")

    source_rows = table["rows"]
    chunks: list[list[dict[str, Any]]] = []
    body_index = header_count
    while body_index < len(source_rows):
        chunk = list(source_rows[:header_count])
        used = header_height
        start = body_index
        while body_index < len(source_rows):
            row_height = row_layouts[body_index].height
            if used + row_height > available:
                break
            chunk.append(source_rows[body_index])
            used += row_height
            body_index += 1
        if body_index == start:
            raise _table_pagination_error("A table body row does not fit below its repeated header.")
        chunks.append(chunk)
    if len(chunks) < 2:
        return [block]
    return [
        {
            **block,
            "table": {
                **block["table"],
                "rows": rows,
            },
        }
        for rows in chunks
    ]


def table_block_height(
    block: dict[str, Any],
    layout: PageLayout,
    shaper: TextShaper,
) -> float:
    """Measure a validated table using the same row layout as the emitter."""
    _table, _style, _widths, rows = _resolved_table_layout(
        block,
        layout,
        shaper,
    )
    return sum(row.height for row in rows)


def _resolved_table_layout(
    block: dict[str, Any],
    layout: PageLayout,
    shaper: TextShaper,
) -> tuple[dict[str, Any], dict[str, Any], list[float], list[_RowLayout]]:
    table = _table_defaults(block["table"])
    style = _table_text_style(block.get("style"))
    column_count = max(len(row["cells"]) for row in table["rows"])
    widths = _column_widths(
        table.get("column_widths"),
        column_count,
        layout.content_width,
    )
    return table, style, widths, _layout_rows(table, style, widths, shaper)


def _layout_rows(
    table: dict[str, Any],
    style: dict[str, Any],
    widths: list[float],
    shaper: TextShaper,
) -> list[_RowLayout]:
    rows: list[_RowLayout] = []
    for source_row in table["rows"]:
        cells: list[_CellLayout] = []
        content_height = 0.0
        for column_index, width in enumerate(widths):
            source_cell = (
                source_row["cells"][column_index]
                if column_index < len(source_row["cells"])
                else None
            )
            text, alignment, fill = _cell_values(source_cell, table["alignment"])
            lines = tuple(
                shaper.wrap_and_shape(
                    text,
                    style,
                    max(width - 2.0 * table["padding"], 1.0),
                )
            )
            cells.append(_CellLayout(text, alignment, fill, lines))
            content_height = max(content_height, len(lines) * style["line_height"])
        minimum_height = content_height + 2.0 * table["padding"]
        requested_height = source_row.get("height")
        if requested_height is not None and requested_height < minimum_height:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Table row height is too small for its wrapped cell content.",
                status="invalid_request",
                details={
                    "requested_height": requested_height,
                    "minimum_height": round(minimum_height, 4),
                },
            )
        rows.append(_RowLayout(
            cells=tuple(cells),
            height=float(requested_height or max(20.0, minimum_height)),
            fill=source_row.get("fill"),
        ))
    return rows


def _table_defaults(table: dict[str, Any]) -> dict[str, Any]:
    return {
        "rows": table["rows"],
        "column_widths": table.get("column_widths"),
        "padding": float(table.get("padding", 4.0)),
        "border": table.get("border") or {"width": 1.0, "color": [0.0, 0.0, 0.0]},
        "fill": table.get("fill"),
        "header_fill": table.get("header_fill"),
        "alignment": table.get("alignment", "left"),
        "header_rows": int(table.get("header_rows", 0)),
        "repeat_header": bool(table.get("repeat_header", False)),
    }


def _table_text_style(style: dict[str, Any] | None) -> dict[str, Any]:
    if style is not None:
        return style
    return {
        **resolved_style("paragraph", None),
        "font_size": 10.0,
        "line_height": 12.0,
    }


def _column_widths(
    requested: list[float] | None,
    count: int,
    available: float,
) -> list[float]:
    if requested is None:
        return [available / count] * count
    total = sum(float(width) for width in requested)
    if total > available + 0.01:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Table column widths exceed the page content width.",
            status="invalid_request",
            details={"requested_width": total, "available_width": available},
        )
    return [float(width) for width in requested]


def _cell_values(
    cell: Any,
    default_alignment: str,
) -> tuple[str, str, list[float] | None]:
    if isinstance(cell, dict):
        return (
            cell.get("text") or "",
            cell.get("alignment") or default_alignment,
            cell.get("fill"),
        )
    return ("" if cell is None else str(cell), default_alignment, None)


def _cell_fill(
    cell: _CellLayout,
    row: _RowLayout,
    table: dict[str, Any],
    row_index: int,
) -> list[float] | None:
    if cell.fill is not None:
        return cell.fill
    if row.fill is not None:
        return row.fill
    if row_index < table["header_rows"] and table["header_fill"] is not None:
        return table["header_fill"]
    return table["fill"]


def _cell_text_x(
    left: float,
    width: float,
    text_width: float,
    padding: float,
    alignment: str,
) -> float:
    if alignment == "right":
        return left + width - padding - text_width
    if alignment == "center":
        return left + (width - text_width) / 2.0
    return left + padding


def _color_operator(color: list[float], operator: str) -> str:
    return " ".join(pdf_number(value) for value in color) + f" {operator}"


def _table_pagination_error(message: str) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details={"capability": "pdf.table-pagination"},
    )
