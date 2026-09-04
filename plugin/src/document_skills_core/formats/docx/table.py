"""Deterministic Word table construction helpers."""

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .xml_utils import paragraph, text_run


def table_element(value: dict[str, Any]) -> Element:
    width = value.get("width_twips", 9_360)
    column_widths = value.get("column_widths_twips") or _distributed_widths(
        width,
        len(value["rows"][0]),
    )
    table = Element(qn("w", "tbl"))
    properties = SubElement(table, qn("w", "tblPr"))
    SubElement(properties, qn("w", "tblStyle"), {qn("w", "val"): value["style"]})
    SubElement(
        properties,
        qn("w", "tblW"),
        {qn("w", "w"): str(width), qn("w", "type"): "dxa"},
    )
    SubElement(properties, qn("w", "tblLayout"), {qn("w", "type"): "fixed"})
    if not value.get("direct_header_bold", True):
        SubElement(
            properties,
            qn("w", "tblLook"),
            {qn("w", "val"): "0420"},
        )
    borders = value.get("borders")
    if borders:
        _append_table_borders(properties, borders)
    grid = SubElement(table, qn("w", "tblGrid"))
    for column_width in column_widths:
        SubElement(grid, qn("w", "gridCol"), {qn("w", "w"): str(column_width)})
    for row_index, row in enumerate(value["rows"]):
        table.append(
            table_row(
                row,
                widths=column_widths,
                bold=row_index == 0 and value.get("direct_header_bold", True),
                header=row_index == 0 and not value.get("direct_header_bold", True),
                header_border=(borders or {}).get("header_bottom") if row_index == 0 else None,
            )
        )
    return table


def table_row(
    cells: list[str],
    *,
    widths: list[int] | None = None,
    bold: bool = False,
    header: bool = False,
    header_border: dict[str, Any] | None = None,
) -> Element:
    row = Element(qn("w", "tr"))
    if header:
        properties = SubElement(row, qn("w", "trPr"))
        SubElement(properties, qn("w", "tblHeader"))
    effective_widths = widths or [1_440] * len(cells)
    for value, width in zip(cells, effective_widths, strict=True):
        cell = SubElement(row, qn("w", "tc"))
        cell_properties = SubElement(cell, qn("w", "tcPr"))
        SubElement(
            cell_properties,
            qn("w", "tcW"),
            {qn("w", "w"): str(width), qn("w", "type"): "dxa"},
        )
        if header_border is not None:
            cell_borders = SubElement(cell_properties, qn("w", "tcBorders"))
            _append_border(cell_borders, "bottom", header_border)
        paragraph_node = SubElement(cell, qn("w", "p"))
        text_run(paragraph_node, value, bold=bold)
    return row


def table_cell(text: str) -> Element:
    cell = Element(qn("w", "tc"))
    cell.append(paragraph(text))
    return cell


def _distributed_widths(total: int, count: int) -> list[int]:
    quotient, remainder = divmod(total, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def _append_table_borders(parent: Element, borders: dict[str, dict[str, Any]]) -> None:
    node = SubElement(parent, qn("w", "tblBorders"))
    mapping = {
        "top": "top",
        "left": "left",
        "bottom": "bottom",
        "right": "right",
        "inside_h": "insideH",
        "inside_v": "insideV",
    }
    for logical, ooxml in mapping.items():
        border = borders.get(logical)
        if border is None:
            SubElement(node, qn("w", ooxml), {qn("w", "val"): "nil"})
        else:
            _append_border(node, ooxml, border)


def _append_border(parent: Element, name: str, border: dict[str, Any]) -> None:
    SubElement(
        parent,
        qn("w", name),
        {
            qn("w", "val"): border["style"],
            qn("w", "sz"): str(border["size_eighth_points"]),
            qn("w", "color"): border["color"],
            qn("w", "space"): "0",
        },
    )
