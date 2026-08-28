"""Contracts for PDF document table, image, and vector blocks."""

from pathlib import Path
from typing import Any

from .constants import MAX_TABLE_COLS, MAX_TABLE_ROWS
from .contract_utils import (
    bounded_number as _bounded_number,
    exact_keys as _exact_keys,
    integer as _integer,
    invalid as _invalid,
    number as _number,
    optional_text as _optional_text,
    text as _text,
)
from .create_contracts import parse_color, parse_dash
from .font_contracts import parse_sha256, require_unicode_font


def parse_block_table(
    table: Any,
    field_prefix: str,
    *,
    style: dict[str, Any] | None,
    palette: dict[str, list[float]],
) -> dict[str, Any] | None:
    if table is None:
        return None
    if type(table) is not dict:
        _invalid("table must be an object.", field=f"{field_prefix}.table")
    _exact_keys(
        table,
        {
            "rows",
            "column_widths",
            "padding",
            "border",
            "fill",
            "header_fill",
            "alignment",
            "header_rows",
            "repeat_header",
        },
    )
    rows = table.get("rows", [])
    if type(rows) is not list or not rows or len(rows) > MAX_TABLE_ROWS:
        _invalid("table.rows must be a non-empty bounded array.", field=f"{field_prefix}.table.rows")
    parsed_rows = []
    for r_idx, row in enumerate(rows):
        if type(row) is not dict:
            _invalid("table row must be an object.", field=f"{field_prefix}.table.rows.{r_idx}")
        _exact_keys(row, {"cells", "height", "fill"})
        cells = row.get("cells", [])
        if type(cells) is not list or len(cells) > MAX_TABLE_COLS:
            _invalid("row.cells must be a bounded array.", field=f"{field_prefix}.table.rows.{r_idx}.cells")
        parsed_cells = [
            _parse_table_cell(
                cell,
                f"{field_prefix}.table.rows.{r_idx}.cells.{c_idx}",
                palette=palette,
            )
            for c_idx, cell in enumerate(cells)
        ]
        for c_idx, cell in enumerate(parsed_cells):
            cell_text = cell.get("text") if isinstance(cell, dict) else cell
            if cell_text is not None:
                require_unicode_font(
                    cell_text,
                    style,
                    f"{field_prefix}.table.rows.{r_idx}.cells.{c_idx}",
                )
        height = row.get("height")
        if height is not None:
            height = _number(height, f"{field_prefix}.table.rows.{r_idx}.height")
            if not 8.0 <= height <= 1_000.0:
                _invalid("row.height must be between 8 and 1000 points.", field=f"{field_prefix}.table.rows.{r_idx}.height")
        row_fill = row.get("fill")
        if row_fill is not None:
            row_fill = parse_color(
                row_fill,
                f"{field_prefix}.table.rows.{r_idx}.fill",
                palette=palette,
            )
        parsed_rows.append({"cells": parsed_cells, "height": height, "fill": row_fill})

    column_count = max(len(row["cells"]) for row in parsed_rows)
    column_widths = table.get("column_widths")
    if column_widths is not None:
        if type(column_widths) is not list or len(column_widths) != column_count:
            _invalid("column_widths must match the maximum cell count.", field=f"{field_prefix}.table.column_widths")
        column_widths = [
            _positive_number(width, f"{field_prefix}.table.column_widths.{index}", 10.0, 2_000.0)
            for index, width in enumerate(column_widths)
        ]
    border = table.get("border")
    if border is None:
        parsed_border = {"width": 1.0, "color": [0.0, 0.0, 0.0]}
    else:
        if type(border) is not dict:
            _invalid("table.border must be an object.", field=f"{field_prefix}.table.border")
        _exact_keys(border, {"width", "color"})
        parsed_border = {
            "width": _positive_number(border.get("width", 1.0), f"{field_prefix}.table.border.width", 0.1, 20.0),
            "color": parse_color(
                border.get("color", [0.0, 0.0, 0.0]),
                f"{field_prefix}.table.border.color",
                palette=palette,
            ),
        }
    alignment = table.get("alignment", "left")
    if alignment not in {"left", "center", "right"}:
        _invalid("table.alignment must be left, center, or right.", field=f"{field_prefix}.table.alignment")
    header_rows = _integer(table.get("header_rows", 0), 0, len(parsed_rows))
    repeat_header = table.get("repeat_header", False)
    if type(repeat_header) is not bool:
        _invalid("table.repeat_header must be boolean.", field=f"{field_prefix}.table.repeat_header")
    if repeat_header and header_rows == 0:
        _invalid("repeat_header requires header_rows.", field=f"{field_prefix}.table.repeat_header")
    return {
        "rows": parsed_rows,
        "column_widths": column_widths,
        "padding": _positive_number(table.get("padding", 4.0), f"{field_prefix}.table.padding", 0.0, 100.0),
        "border": parsed_border,
        "fill": parse_color(
            table["fill"],
            f"{field_prefix}.table.fill",
            palette=palette,
        ) if table.get("fill") is not None else None,
        "header_fill": parse_color(
            table["header_fill"],
            f"{field_prefix}.table.header_fill",
            palette=palette,
        ) if table.get("header_fill") is not None else None,
        "alignment": alignment,
        "header_rows": header_rows,
        "repeat_header": repeat_header,
    }


def _parse_table_cell(
    value: Any,
    field: str,
    *,
    palette: dict[str, list[float]],
) -> str | dict[str, Any] | None:
    if value is None or isinstance(value, str):
        return _optional_text(value, field) if value is not None else None
    if type(value) is not dict:
        _invalid("table cell must be text, null, or an object.", field=field)
    _exact_keys(value, {"text", "alignment", "fill"})
    alignment = value.get("alignment")
    if alignment is not None and alignment not in {"left", "center", "right"}:
        _invalid("cell.alignment must be left, center, or right.", field=f"{field}.alignment")
    fill = value.get("fill")
    return {
        "text": _optional_text(value.get("text"), f"{field}.text"),
        "alignment": alignment,
        "fill": parse_color(
            fill,
            f"{field}.fill",
            palette=palette,
        ) if fill is not None else None,
    }


def _positive_number(value: Any, field: str, minimum: float, maximum: float) -> float:
    parsed = _number(value, field)
    if not minimum <= parsed <= maximum:
        _invalid(f"number must be between {minimum} and {maximum}.", field=field)
    return parsed


def parse_block_image(image: Any, field_prefix: str) -> dict[str, Any] | None:
    if image is None:
        _invalid("image must be an object.", field=f"{field_prefix}.image")
    if type(image) is not dict:
        _invalid("image must be an object.", field=f"{field_prefix}.image")
    if not image:
        _invalid(
            "image must be a non-empty bounded request.",
            field=f"{field_prefix}.image",
        )
    _exact_keys(
        image,
        {"filename", "sha256", "content_type", "fit", "width", "height", "alt"},
    )
    if not {"filename", "sha256", "content_type"}.issubset(image):
        _invalid(
            "image must include filename, sha256, and content_type.",
            field=f"{field_prefix}.image",
        )
    filename = _text(
        image.get("filename"),
        f"{field_prefix}.image.filename",
        allow_empty=False,
    )
    if "://" in filename or filename.casefold().startswith(("data:", "file:")):
        _invalid(
            "image.filename must be a local filesystem path, not a URL.",
            field=f"{field_prefix}.image.filename",
        )
    sha256 = parse_sha256(
        image.get("sha256"),
        f"{field_prefix}.image.sha256",
    )
    if sha256 is None:
        _invalid(
            "image.sha256 is required.",
            field=f"{field_prefix}.image.sha256",
        )
    content_type = _text(
        image.get("content_type"),
        f"{field_prefix}.image.content_type",
        allow_empty=False,
    )
    if content_type not in {"image/png", "image/jpeg"}:
        _invalid(
            "image.content_type must be image/png or image/jpeg.",
            field=f"{field_prefix}.image.content_type",
        )
    fit = image.get("fit", "contain")
    if fit not in {"contain", "cover", "stretch"}:
        _invalid(
            "image.fit must be contain, cover, or stretch.",
            field=f"{field_prefix}.image.fit",
        )
    return {
        "filename": str(Path(filename).expanduser().resolve(strict=False)),
        "sha256": sha256,
        "content_type": content_type,
        "fit": fit,
        "width": _bounded_number(
            image.get("width", 200.0),
            f"{field_prefix}.image.width",
            1.0,
            2_000.0,
        ),
        "height": _bounded_number(
            image.get("height", 100.0),
            f"{field_prefix}.image.height",
            1.0,
            2_000.0,
        ),
        "alt": _optional_text(
            image.get("alt"),
            f"{field_prefix}.image.alt",
        ),
    }


def parse_block_shape(
    shape: Any,
    field_prefix: str,
    *,
    palette: dict[str, list[float]],
) -> dict[str, Any] | None:
    if shape is None:
        return None
    if type(shape) is not dict:
        _invalid("shape must be an object.", field=f"{field_prefix}.shape")
    _exact_keys(
        shape,
        {
            "kind", "x", "y", "width", "height", "stroke", "fill",
            "opacity", "dash", "corner_radius",
        },
    )
    kind = shape.get("kind")
    if kind not in {"line", "rectangle", "rounded_rectangle", "ellipse"}:
        _invalid("shape.kind must be line, rectangle, rounded_rectangle, or ellipse.", field=f"{field_prefix}.shape.kind")
    corner_radius = shape.get("corner_radius", 0.0)
    if kind == "rounded_rectangle":
        corner_radius = _bounded_number(
            corner_radius,
            f"{field_prefix}.shape.corner_radius",
            0.01,
            1_000.0,
        )
    elif corner_radius not in {0, 0.0, None}:
        _invalid("corner_radius is only valid for rounded_rectangle.", field=f"{field_prefix}.shape.corner_radius")
    return {
        "kind": kind,
        "x": _number(shape.get("x", 0.0), f"{field_prefix}.shape.x"),
        "y": _number(shape.get("y", 0.0), f"{field_prefix}.shape.y"),
        "width": _bounded_number(shape.get("width", 100.0), f"{field_prefix}.shape.width", 0.01, 2_000.0),
        "height": _bounded_number(shape.get("height", 100.0), f"{field_prefix}.shape.height", 0.01, 2_000.0),
        "stroke": parse_color(
            shape.get("stroke"),
            f"{field_prefix}.shape.stroke",
            palette=palette,
        ),
        "fill": parse_color(
            shape.get("fill"),
            f"{field_prefix}.shape.fill",
            palette=palette,
        ),
        "opacity": _bounded_number(shape.get("opacity", 1.0), f"{field_prefix}.shape.opacity", 0.0, 1.0),
        "dash": parse_dash(shape.get("dash"), f"{field_prefix}.shape.dash"),
        "corner_radius": float(corner_radius or 0.0),
    }
