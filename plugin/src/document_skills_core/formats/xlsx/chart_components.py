"""Plot, series, axis, trendline, and error-bar XML for native charts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from xml.etree.ElementTree import Element, SubElement

CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAWING_MAIN_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def append_plots(plot_area: Element, chart: dict[str, Any], chart_id: int) -> None:
    """Emit one or more plot groups plus their primary/secondary axes."""

    groups: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, series in enumerate(chart["series"]):
        series_type = series.get("chart_type", chart["type"])
        groups[(series_type, series.get("axis", "primary"))].append((index, series))
    axis_ids = {
        "primary": (100_000 + chart_id * 10, 100_001 + chart_id * 10),
        "secondary": (100_002 + chart_id * 10, 100_003 + chart_id * 10),
    }
    used_axes: dict[str, str] = {}
    for (plot_type, axis), series in groups.items():
        plot = _append_plot(plot_area, plot_type, chart, series)
        if plot_type != "pie":
            first_axis, second_axis = axis_ids[axis]
            SubElement(plot, f"{{{CHART_NS}}}axId", {"val": str(first_axis)})
            SubElement(plot, f"{{{CHART_NS}}}axId", {"val": str(second_axis)})
            used_axes[axis] = (
                "numeric"
                if plot_type in {"scatter", "bubble"}
                else "bar"
                if plot_type == "bar"
                else "category"
            )
    for axis, kind in used_axes.items():
        _append_axis_pair(plot_area, chart, axis_ids[axis], axis=axis, kind=kind)


def append_title(parent: Element, text: str) -> None:
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


def _append_plot(
    plot_area: Element,
    plot_type: str,
    chart: dict[str, Any],
    series: list[tuple[int, dict[str, Any]]],
) -> Element:
    tag = {
        "column": "barChart",
        "bar": "barChart",
        "line": "lineChart",
        "pie": "pieChart",
        "scatter": "scatterChart",
        "area": "areaChart",
        "radar": "radarChart",
        "bubble": "bubbleChart",
    }[plot_type]
    plot = SubElement(plot_area, f"{{{CHART_NS}}}{tag}")
    if plot_type in {"column", "bar"}:
        SubElement(plot, f"{{{CHART_NS}}}barDir", {"val": "col" if plot_type == "column" else "bar"})
        SubElement(plot, f"{{{CHART_NS}}}grouping", {"val": "clustered"})
    elif plot_type in {"line", "area"}:
        SubElement(plot, f"{{{CHART_NS}}}grouping", {"val": "standard"})
    elif plot_type == "scatter":
        SubElement(plot, f"{{{CHART_NS}}}scatterStyle", {"val": "lineMarker"})
    elif plot_type == "radar":
        style = {"standard": "standard", "marker": "marker", "filled": "filled"}[
            chart["radar_style"]
        ]
        SubElement(plot, f"{{{CHART_NS}}}radarStyle", {"val": style})
    SubElement(plot, f"{{{CHART_NS}}}varyColors", {"val": "1" if plot_type == "pie" else "0"})
    for index, item in series:
        _append_series(plot, item, plot_type=plot_type, index=index)
    _append_data_labels(plot, chart["data_labels"])
    if plot_type == "pie":
        SubElement(plot, f"{{{CHART_NS}}}firstSliceAng", {"val": "0"})
    elif plot_type == "bubble":
        SubElement(plot, f"{{{CHART_NS}}}bubbleScale", {"val": str(chart["bubble_scale"])})
        SubElement(plot, f"{{{CHART_NS}}}showNegBubbles", {"val": "0"})
        SubElement(plot, f"{{{CHART_NS}}}sizeRepresents", {"val": "area"})
    return plot


def _append_series(
    plot: Element,
    series: dict[str, Any],
    *,
    plot_type: str,
    index: int,
) -> None:
    item = SubElement(plot, f"{{{CHART_NS}}}ser")
    SubElement(item, f"{{{CHART_NS}}}idx", {"val": str(index)})
    SubElement(item, f"{{{CHART_NS}}}order", {"val": str(index)})
    text = SubElement(item, f"{{{CHART_NS}}}tx")
    SubElement(text, f"{{{CHART_NS}}}v").text = series["name"]
    line = plot_type in {"line", "scatter", "radar"}
    _append_series_style(item, series["color"], line=line)
    if line:
        marker = SubElement(item, f"{{{CHART_NS}}}marker")
        SubElement(marker, f"{{{CHART_NS}}}symbol", {"val": "circle"})
        SubElement(marker, f"{{{CHART_NS}}}size", {"val": "5"})
    if series.get("trendline") is not None:
        _append_trendline(item, series["trendline"])
    for error_bars in series.get("error_bars", []):
        _append_error_bars(item, error_bars)
    if plot_type in {"scatter", "bubble"}:
        _append_num_reference(item, "xVal", series["x_values"])
        _append_num_reference(item, "yVal", series["y_values"])
        if plot_type == "bubble":
            _append_num_reference(item, "bubbleSize", series["bubble_sizes"])
            SubElement(item, f"{{{CHART_NS}}}bubble3D", {"val": "0"})
    else:
        categories = SubElement(item, f"{{{CHART_NS}}}cat")
        category_reference = SubElement(categories, f"{{{CHART_NS}}}strRef")
        SubElement(category_reference, f"{{{CHART_NS}}}f").text = series["categories"]
        _append_num_reference(item, "val", series["values"])
    if line:
        SubElement(item, f"{{{CHART_NS}}}smooth", {"val": "0"})


def _append_trendline(parent: Element, trendline: dict[str, Any]) -> None:
    container = SubElement(parent, f"{{{CHART_NS}}}trendline")
    kind = {
        "linear": "linear",
        "exponential": "exp",
        "logarithmic": "log",
        "polynomial": "poly",
        "power": "power",
        "moving_average": "movingAvg",
    }[trendline["type"]]
    SubElement(container, f"{{{CHART_NS}}}trendlineType", {"val": kind})
    for field, tag in (("order", "order"), ("period", "period")):
        if trendline[field] is not None:
            SubElement(container, f"{{{CHART_NS}}}{tag}", {"val": str(trendline[field])})
    for field, tag in (("forward", "forward"), ("backward", "backward"), ("intercept", "intercept")):
        if trendline[field] is not None and (field == "intercept" or trendline[field] != 0):
            SubElement(container, f"{{{CHART_NS}}}{tag}", {"val": str(trendline[field])})
    SubElement(
        container,
        f"{{{CHART_NS}}}dispRSqr",
        {"val": "1" if trendline["display_r_squared"] else "0"},
    )
    SubElement(
        container,
        f"{{{CHART_NS}}}dispEq",
        {"val": "1" if trendline["display_equation"] else "0"},
    )


def _append_error_bars(parent: Element, error_bars: dict[str, Any]) -> None:
    container = SubElement(parent, f"{{{CHART_NS}}}errBars")
    SubElement(container, f"{{{CHART_NS}}}errDir", {"val": error_bars["direction"]})
    SubElement(container, f"{{{CHART_NS}}}errBarType", {"val": "both"})
    kind = {
        "fixed": "fixedVal",
        "percentage": "percentage",
        "standard_deviation": "stdDev",
        "standard_error": "stdErr",
        "custom": "cust",
    }[error_bars["type"]]
    SubElement(container, f"{{{CHART_NS}}}errValType", {"val": kind})
    SubElement(
        container,
        f"{{{CHART_NS}}}noEndCap",
        {"val": "0" if error_bars["end_style"] else "1"},
    )
    if error_bars["type"] == "custom":
        _append_num_reference(container, "plus", error_bars["plus"])
        _append_num_reference(container, "minus", error_bars["minus"])
    elif error_bars["value"] is not None:
        SubElement(container, f"{{{CHART_NS}}}val", {"val": str(error_bars["value"])})


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


def _append_axis_pair(
    plot_area: Element,
    chart: dict[str, Any],
    axis_ids: tuple[int, int],
    *,
    axis: str,
    kind: str,
) -> None:
    secondary = axis == "secondary"
    prefix = "secondary_" if secondary else ""
    x_title = chart[f"{prefix}x_axis_title"]
    y_title = chart[f"{prefix}y_axis_title"]
    x_format = chart[f"{prefix}x_axis_number_format"]
    y_format = chart[f"{prefix}y_axis_number_format"]
    x_tag = "valAx" if kind == "numeric" else "catAx"
    x_position = "t" if secondary else "l" if kind == "bar" else "b"
    y_position = "r" if secondary else "b" if kind == "bar" else "l"
    x_axis = SubElement(plot_area, f"{{{CHART_NS}}}{x_tag}")
    _append_axis_common(
        x_axis,
        axis_ids[0],
        axis_ids[1],
        x_position,
        x_title,
        x_format,
        secondary=secondary,
        hidden=secondary and not x_title,
    )
    if kind == "category":
        SubElement(x_axis, f"{{{CHART_NS}}}auto", {"val": "1"})
        SubElement(x_axis, f"{{{CHART_NS}}}lblAlgn", {"val": "ctr"})
        SubElement(x_axis, f"{{{CHART_NS}}}lblOffset", {"val": "100"})
    y_axis = SubElement(plot_area, f"{{{CHART_NS}}}valAx")
    _append_axis_common(
        y_axis,
        axis_ids[1],
        axis_ids[0],
        y_position,
        y_title,
        y_format,
        secondary=secondary,
        hidden=False,
    )
    SubElement(y_axis, f"{{{CHART_NS}}}majorGridlines")
    SubElement(y_axis, f"{{{CHART_NS}}}crossBetween", {"val": "between"})


def _append_axis_common(
    axis: Element,
    axis_id: int,
    cross_axis_id: int,
    position: str,
    title: str | None,
    number_format: str | None,
    *,
    secondary: bool,
    hidden: bool,
) -> None:
    SubElement(axis, f"{{{CHART_NS}}}axId", {"val": str(axis_id)})
    scaling = SubElement(axis, f"{{{CHART_NS}}}scaling")
    SubElement(scaling, f"{{{CHART_NS}}}orientation", {"val": "minMax"})
    SubElement(axis, f"{{{CHART_NS}}}delete", {"val": "1" if hidden else "0"})
    SubElement(axis, f"{{{CHART_NS}}}axPos", {"val": position})
    if title:
        append_title(axis, title)
    if number_format:
        SubElement(axis, f"{{{CHART_NS}}}numFmt", {"formatCode": number_format, "sourceLinked": "0"})
    SubElement(axis, f"{{{CHART_NS}}}tickLblPos", {"val": "nextTo"})
    SubElement(axis, f"{{{CHART_NS}}}crossAx", {"val": str(cross_axis_id)})
    SubElement(axis, f"{{{CHART_NS}}}crosses", {"val": "max" if secondary else "autoZero"})
