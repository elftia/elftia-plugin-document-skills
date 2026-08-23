"""Deterministic native SpreadsheetML chart and drawing builders."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement, register_namespace

from .constants import NS

CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAWING_MAIN_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
GRAPHIC_FRAME_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"

register_namespace("c", CHART_NS)
register_namespace("xdr", DRAWING_NS)
register_namespace("a", DRAWING_MAIN_NS)


def build_chart_root(chart: dict[str, Any], chart_id: int) -> Element:
    root = Element(f"{{{CHART_NS}}}chartSpace")
    SubElement(root, f"{{{CHART_NS}}}lang", {"val": "en-US"})
    chart_element = SubElement(root, f"{{{CHART_NS}}}chart")
    if chart["title"]:
        _append_title(chart_element, chart["title"])
    plot_area = SubElement(chart_element, f"{{{CHART_NS}}}plotArea")
    SubElement(plot_area, f"{{{CHART_NS}}}layout")
    axis_ids = (100_000 + chart_id * 10, 100_001 + chart_id * 10)
    chart_type = chart["type"]
    if chart_type in {"column", "bar"}:
        plot = SubElement(plot_area, f"{{{CHART_NS}}}barChart")
        SubElement(plot, f"{{{CHART_NS}}}barDir", {"val": "col" if chart_type == "column" else "bar"})
        SubElement(plot, f"{{{CHART_NS}}}grouping", {"val": "clustered"})
        SubElement(plot, f"{{{CHART_NS}}}varyColors", {"val": "0"})
        _append_series(plot, chart, scatter=False, line=False)
        _append_data_labels(plot, chart["data_labels"])
        for axis_id in axis_ids:
            SubElement(plot, f"{{{CHART_NS}}}axId", {"val": str(axis_id)})
        _append_category_axis(
            plot_area,
            axis_ids[0],
            axis_ids[1],
            position="b" if chart_type == "column" else "l",
            title=chart["x_axis_title"],
            number_format=chart["x_axis_number_format"],
        )
        _append_value_axis(
            plot_area,
            axis_ids[1],
            axis_ids[0],
            position="l" if chart_type == "column" else "b",
            title=chart["y_axis_title"],
            number_format=chart["y_axis_number_format"],
        )
    elif chart_type == "line":
        plot = SubElement(plot_area, f"{{{CHART_NS}}}lineChart")
        SubElement(plot, f"{{{CHART_NS}}}grouping", {"val": "standard"})
        SubElement(plot, f"{{{CHART_NS}}}varyColors", {"val": "0"})
        _append_series(plot, chart, scatter=False, line=True)
        _append_data_labels(plot, chart["data_labels"])
        for axis_id in axis_ids:
            SubElement(plot, f"{{{CHART_NS}}}axId", {"val": str(axis_id)})
        _append_category_axis(
            plot_area,
            axis_ids[0],
            axis_ids[1],
            position="b",
            title=chart["x_axis_title"],
            number_format=chart["x_axis_number_format"],
        )
        _append_value_axis(
            plot_area,
            axis_ids[1],
            axis_ids[0],
            position="l",
            title=chart["y_axis_title"],
            number_format=chart["y_axis_number_format"],
        )
    elif chart_type == "pie":
        plot = SubElement(plot_area, f"{{{CHART_NS}}}pieChart")
        SubElement(plot, f"{{{CHART_NS}}}varyColors", {"val": "1"})
        _append_series(plot, chart, scatter=False, line=False)
        _append_data_labels(plot, chart["data_labels"])
        SubElement(plot, f"{{{CHART_NS}}}firstSliceAng", {"val": "0"})
    else:
        plot = SubElement(plot_area, f"{{{CHART_NS}}}scatterChart")
        SubElement(plot, f"{{{CHART_NS}}}scatterStyle", {"val": "lineMarker"})
        SubElement(plot, f"{{{CHART_NS}}}varyColors", {"val": "0"})
        _append_series(plot, chart, scatter=True, line=True)
        _append_data_labels(plot, chart["data_labels"])
        for axis_id in axis_ids:
            SubElement(plot, f"{{{CHART_NS}}}axId", {"val": str(axis_id)})
        _append_value_axis(
            plot_area,
            axis_ids[0],
            axis_ids[1],
            position="b",
            title=chart["x_axis_title"],
            number_format=chart["x_axis_number_format"],
        )
        _append_value_axis(
            plot_area,
            axis_ids[1],
            axis_ids[0],
            position="l",
            title=chart["y_axis_title"],
            number_format=chart["y_axis_number_format"],
        )
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


def _append_series(plot: Element, chart: dict[str, Any], *, scatter: bool, line: bool) -> None:
    for index, series in enumerate(chart["series"]):
        item = SubElement(plot, f"{{{CHART_NS}}}ser")
        SubElement(item, f"{{{CHART_NS}}}idx", {"val": str(index)})
        SubElement(item, f"{{{CHART_NS}}}order", {"val": str(index)})
        text = SubElement(item, f"{{{CHART_NS}}}tx")
        SubElement(text, f"{{{CHART_NS}}}v").text = series["name"]
        _append_series_style(item, series["color"], line=line)
        if scatter:
            _append_num_reference(item, "xVal", series["x_values"])
            _append_num_reference(item, "yVal", series["y_values"])
        else:
            categories = SubElement(item, f"{{{CHART_NS}}}cat")
            category_reference = SubElement(categories, f"{{{CHART_NS}}}strRef")
            SubElement(category_reference, f"{{{CHART_NS}}}f").text = series["categories"]
            _append_num_reference(item, "val", series["values"])
        if line:
            marker = SubElement(item, f"{{{CHART_NS}}}marker")
            SubElement(marker, f"{{{CHART_NS}}}symbol", {"val": "circle"})
            SubElement(marker, f"{{{CHART_NS}}}size", {"val": "5"})
            SubElement(item, f"{{{CHART_NS}}}smooth", {"val": "0"})


def _append_series_style(parent: Element, color: str, *, line: bool) -> None:
    shape = SubElement(parent, f"{{{CHART_NS}}}spPr")
    if line:
        line_element = SubElement(shape, f"{{{DRAWING_MAIN_NS}}}ln")
        fill = SubElement(line_element, f"{{{DRAWING_MAIN_NS}}}solidFill")
    else:
        fill = SubElement(shape, f"{{{DRAWING_MAIN_NS}}}solidFill")
    SubElement(fill, f"{{{DRAWING_MAIN_NS}}}srgbClr", {"val": color[-6:]})


def _append_num_reference(parent: Element, name: str, formula: str) -> None:
    wrapper = SubElement(parent, f"{{{CHART_NS}}}{name}")
    reference = SubElement(wrapper, f"{{{CHART_NS}}}numRef")
    SubElement(reference, f"{{{CHART_NS}}}f").text = formula


def _append_data_labels(parent: Element, labels: dict[str, bool]) -> None:
    container = SubElement(parent, f"{{{CHART_NS}}}dLbls")
    for key, tag in (
        ("show_legend_key", "showLegendKey"),
        ("show_value", "showVal"),
        ("show_category_name", "showCatName"),
        ("show_series_name", "showSerName"),
        ("show_percentage", "showPercent"),
    ):
        SubElement(container, f"{{{CHART_NS}}}{tag}", {"val": "1" if labels[key] else "0"})


def _append_category_axis(
    plot_area: Element,
    axis_id: int,
    cross_axis_id: int,
    *,
    position: str,
    title: str | None,
    number_format: str | None,
) -> None:
    axis = SubElement(plot_area, f"{{{CHART_NS}}}catAx")
    _append_axis_common(axis, axis_id, cross_axis_id, position, title, number_format)
    SubElement(axis, f"{{{CHART_NS}}}auto", {"val": "1"})
    SubElement(axis, f"{{{CHART_NS}}}lblAlgn", {"val": "ctr"})
    SubElement(axis, f"{{{CHART_NS}}}lblOffset", {"val": "100"})


def _append_value_axis(
    plot_area: Element,
    axis_id: int,
    cross_axis_id: int,
    *,
    position: str,
    title: str | None,
    number_format: str | None,
) -> None:
    axis = SubElement(plot_area, f"{{{CHART_NS}}}valAx")
    _append_axis_common(axis, axis_id, cross_axis_id, position, title, number_format)
    SubElement(axis, f"{{{CHART_NS}}}majorGridlines")
    SubElement(axis, f"{{{CHART_NS}}}crossBetween", {"val": "between"})


def _append_axis_common(
    axis: Element,
    axis_id: int,
    cross_axis_id: int,
    position: str,
    title: str | None,
    number_format: str | None,
) -> None:
    SubElement(axis, f"{{{CHART_NS}}}axId", {"val": str(axis_id)})
    scaling = SubElement(axis, f"{{{CHART_NS}}}scaling")
    SubElement(scaling, f"{{{CHART_NS}}}orientation", {"val": "minMax"})
    SubElement(axis, f"{{{CHART_NS}}}delete", {"val": "0"})
    SubElement(axis, f"{{{CHART_NS}}}axPos", {"val": position})
    if title:
        _append_title(axis, title)
    if number_format:
        SubElement(
            axis,
            f"{{{CHART_NS}}}numFmt",
            {"formatCode": number_format, "sourceLinked": "0"},
        )
    SubElement(axis, f"{{{CHART_NS}}}tickLblPos", {"val": "nextTo"})
    SubElement(axis, f"{{{CHART_NS}}}crossAx", {"val": str(cross_axis_id)})
    SubElement(axis, f"{{{CHART_NS}}}crosses", {"val": "autoZero"})


def _append_title(parent: Element, text: str) -> None:
    title = SubElement(parent, f"{{{CHART_NS}}}title")
    tx = SubElement(title, f"{{{CHART_NS}}}tx")
    rich = SubElement(tx, f"{{{CHART_NS}}}rich")
    SubElement(rich, f"{{{DRAWING_MAIN_NS}}}bodyPr")
    SubElement(rich, f"{{{DRAWING_MAIN_NS}}}lstStyle")
    paragraph = SubElement(rich, f"{{{DRAWING_MAIN_NS}}}p")
    run = SubElement(paragraph, f"{{{DRAWING_MAIN_NS}}}r")
    SubElement(run, f"{{{DRAWING_MAIN_NS}}}rPr", {"lang": "en-US"})
    SubElement(run, f"{{{DRAWING_MAIN_NS}}}t").text = text
    SubElement(paragraph, f"{{{DRAWING_MAIN_NS}}}endParaRPr", {"lang": "en-US"})
    SubElement(title, f"{{{CHART_NS}}}layout")
    SubElement(title, f"{{{CHART_NS}}}overlay", {"val": "0"})


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
