"""Stable table selector and semantic projection helpers."""

from typing import Any
from xml.etree.ElementTree import Element

from .constants import qn
from .mapping import map_paragraph
from .projection import table_selector_sha256


def table_semantic_state(root: Element) -> list[dict[str, Any]]:
    body = root.find(qn("w", "body"))
    if body is None:
        return []
    tables = [child for child in body if child.tag == qn("w", "tbl")]
    return [
        {
            "selector_sha256": table_selector_sha256(table),
            "rows": [
                [
                    {
                        "text": cell_text(cell),
                        "grid_span": cell_property_value(cell, "gridSpan"),
                        "vertical_merge": cell_property_value(
                            cell, "vMerge", default="continue"
                        ),
                    }
                    for cell in row.findall(qn("w", "tc"))
                ]
                for row in table.findall(qn("w", "tr"))
            ],
        }
        for table in tables
    ]


def cell_text(cell: Element) -> str:
    return "\n".join(
        "".join(group.text for group in map_paragraph(paragraph).groups)
        for paragraph in cell.findall(qn("w", "p"))
    )


def cell_property_value(
    cell: Element,
    name: str,
    *,
    default: str | None = None,
) -> str | None:
    node = cell.find(f"./{qn('w', 'tcPr')}/{qn('w', name)}")
    return node.attrib.get(qn("w", "val"), default) if node is not None else None
