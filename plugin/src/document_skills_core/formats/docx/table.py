"""Deterministic Word table construction helpers."""

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .xml_utils import paragraph, text_run


def table_element(value: dict[str, Any]) -> Element:
    table = Element(qn("w", "tbl"))
    properties = SubElement(table, qn("w", "tblPr"))
    SubElement(properties, qn("w", "tblStyle"), {qn("w", "val"): value["style"]})
    if not value.get("direct_header_bold", True):
        SubElement(
            properties,
            qn("w", "tblLook"),
            {qn("w", "val"): "0420"},
        )
    grid = SubElement(table, qn("w", "tblGrid"))
    for _cell in value["rows"][0]:
        SubElement(grid, qn("w", "gridCol"))
    for row_index, row in enumerate(value["rows"]):
        table.append(
            table_row(
                row,
                bold=row_index == 0 and value.get("direct_header_bold", True),
                header=row_index == 0 and not value.get("direct_header_bold", True),
            )
        )
    return table


def table_row(
    cells: list[str],
    *,
    bold: bool = False,
    header: bool = False,
) -> Element:
    row = Element(qn("w", "tr"))
    if header:
        properties = SubElement(row, qn("w", "trPr"))
        SubElement(properties, qn("w", "tblHeader"))
    for value in cells:
        cell = SubElement(row, qn("w", "tc"))
        paragraph_node = SubElement(cell, qn("w", "p"))
        text_run(paragraph_node, value, bold=bold)
    return row


def table_cell(text: str) -> Element:
    cell = Element(qn("w", "tc"))
    cell.append(paragraph(text))
    return cell
