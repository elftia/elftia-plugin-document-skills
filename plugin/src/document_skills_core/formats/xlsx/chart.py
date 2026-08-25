"""Deterministic native SpreadsheetML chart and drawing builders."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement, register_namespace

from .chart_components import (
    CHART_NS,
    DRAWING_MAIN_NS,
    DRAWING_NS,
    append_plots,
    append_title,
)
from .constants import NS

GRAPHIC_FRAME_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"

register_namespace("c", CHART_NS)
register_namespace("xdr", DRAWING_NS)
register_namespace("a", DRAWING_MAIN_NS)


def build_chart_root(chart: dict[str, Any], chart_id: int) -> Element:
    root = Element(f"{{{CHART_NS}}}chartSpace")
    SubElement(root, f"{{{CHART_NS}}}lang", {"val": "en-US"})
    SubElement(root, f"{{{CHART_NS}}}style", {"val": str(chart["style"])})
    chart_element = SubElement(root, f"{{{CHART_NS}}}chart")
    if chart["title"]:
        append_title(chart_element, chart["title"])
    plot_area = SubElement(chart_element, f"{{{CHART_NS}}}plotArea")
    SubElement(plot_area, f"{{{CHART_NS}}}layout")
    append_plots(plot_area, chart, chart_id)
    if chart["show_legend"]:
        legend = SubElement(chart_element, f"{{{CHART_NS}}}legend")
        SubElement(legend, f"{{{CHART_NS}}}legendPos", {"val": chart["legend_position"]})
        SubElement(legend, f"{{{CHART_NS}}}layout")
        SubElement(legend, f"{{{CHART_NS}}}overlay", {"val": "0"})
    SubElement(chart_element, f"{{{CHART_NS}}}plotVisOnly", {"val": "1"})
    SubElement(chart_element, f"{{{CHART_NS}}}dispBlanksAs", {"val": "gap"})
    return root


def append_chart_anchor(
    drawing: Element,
    chart: dict[str, Any],
    *,
    relationship_id: str,
    object_id: int,
) -> Element:
    first, last = chart["anchor"].split(":", 1)
    anchor = SubElement(drawing, f"{{{DRAWING_NS}}}twoCellAnchor")
    _append_marker(anchor, "from", first)
    _append_marker(anchor, "to", last)
    frame = SubElement(anchor, f"{{{DRAWING_NS}}}graphicFrame", {"macro": ""})
    non_visual = SubElement(frame, f"{{{DRAWING_NS}}}nvGraphicFramePr")
    SubElement(
        non_visual,
        f"{{{DRAWING_NS}}}cNvPr",
        {"id": str(object_id), "name": chart["name"]},
    )
    SubElement(non_visual, f"{{{DRAWING_NS}}}cNvGraphicFramePr")
    transform = SubElement(frame, f"{{{DRAWING_NS}}}xfrm")
    SubElement(transform, f"{{{DRAWING_MAIN_NS}}}off", {"x": "0", "y": "0"})
    SubElement(transform, f"{{{DRAWING_MAIN_NS}}}ext", {"cx": "0", "cy": "0"})
    graphic = SubElement(frame, f"{{{DRAWING_MAIN_NS}}}graphic")
    graphic_data = SubElement(
        graphic,
        f"{{{DRAWING_MAIN_NS}}}graphicData",
        {"uri": GRAPHIC_FRAME_URI},
    )
    SubElement(
        graphic_data,
        f"{{{CHART_NS}}}chart",
        {f"{{{NS['r']}}}id": relationship_id},
    )
    SubElement(anchor, f"{{{DRAWING_NS}}}clientData")
    return anchor


def _append_marker(parent: Element, name: str, ref: str) -> None:
    column, row = _cell_ref(ref)
    marker = SubElement(parent, f"{{{DRAWING_NS}}}{name}")
    SubElement(marker, f"{{{DRAWING_NS}}}col").text = str(column - 1)
    SubElement(marker, f"{{{DRAWING_NS}}}colOff").text = "0"
    SubElement(marker, f"{{{DRAWING_NS}}}row").text = str(row - 1)
    SubElement(marker, f"{{{DRAWING_NS}}}rowOff").text = "0"


def _cell_ref(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    assert match is not None
    column = 0
    for char in match.group(1).upper():
        column = column * 26 + ord(char) - ord("A") + 1
    return column, int(match.group(2))
