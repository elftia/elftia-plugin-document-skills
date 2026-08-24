"""Detailed readback projection for native basic and advanced charts."""

from __future__ import annotations

from typing import Any

from .chart import CHART_NS, DRAWING_MAIN_NS, DRAWING_NS
from .constants import NS
from .relationships import relationship_map
from .xml_numeric import (
    MAX_UNSIGNED_INT,
    parse_optional_xml_int,
    parse_optional_xml_number,
    parse_xml_int,
    parse_xml_number,
)

_MAIN_NS = NS["main"]
_PLOT_TAGS = (
    ("barChart", "column"),
    ("lineChart", "line"),
    ("pieChart", "pie"),
    ("scatterChart", "scatter"),
    ("areaChart", "area"),
    ("radarChart", "radar"),
    ("bubbleChart", "bubble"),
)


def project_charts(package: Any) -> list[dict[str, Any]]:
    """Project chart plots, axes, advanced series details, anchors, and colors."""

    drawing_records = _drawing_records(package)
    charts: list[dict[str, Any]] = []
    for part in sorted(package.parts):
        if not part.startswith("xl/charts/") or not part.endswith(".xml"):
            continue
        root = package.xml(part)
        plots = _plots(root)
        plot_types = {item[0] for item in plots}
        chart_type = "combo" if len(plot_types) > 1 else next(iter(plot_types), "unknown")
        if chart_type == "column" and plots:
            direction = plots[0][1].find(f"{{{CHART_NS}}}barDir")
            if _value(direction, "col") == "bar":
                chart_type = "bar"
                plots[0] = ("bar", plots[0][1])
        axes = _axes(root)
        projected_series: list[tuple[int, dict[str, Any]]] = []
        for plot_type, plot in plots:
            axis = _plot_axis(plot, axes)
            for item in plot.findall(f"{{{CHART_NS}}}ser"):
                index = parse_xml_int(
                    _value(item.find(f"{{{CHART_NS}}}idx"), "0"),
                    attribute="chart.series.idx",
                    minimum=0,
                    maximum=MAX_UNSIGNED_INT,
                )
                projected_series.append(
                    (index, _project_series(item, plot_type, axis, combo=chart_type == "combo"))
                )
        projected_series.sort(key=lambda item: item[0])
        drawing = drawing_records.get(part, {})
        primary_x, primary_y = _axis_pair(axes, secondary=False, chart_type=chart_type)
        secondary_x, secondary_y = _axis_pair(axes, secondary=True, chart_type=chart_type)
        first_plot = plots[0][1] if plots else None
        style = root.find(f"{{{CHART_NS}}}style")
        radar = next((plot for kind, plot in plots if kind == "radar"), None)
        bubble = next((plot for kind, plot in plots if kind == "bubble"), None)
        charts.append(
            {
                "part": part,
                "content_type": package.content_type_for(part) or "",
                "chart_type": chart_type,
                "type": chart_type,
                "name": drawing.get("name", ""),
                "sheet": drawing.get("sheet", ""),
                "anchor": drawing.get("anchor", ""),
                "drawing_part": drawing.get("drawing_part", ""),
                "title": _project_title(root),
                "series": [item[1] for item in projected_series],
                "show_legend": root.find(f".//{{{CHART_NS}}}chart/{{{CHART_NS}}}legend") is not None,
                "legend_position": _value(
                    root.find(f".//{{{CHART_NS}}}legend/{{{CHART_NS}}}legendPos"),
                    "r",
                ),
                "x_axis_title": primary_x["title"],
                "y_axis_title": primary_y["title"],
                "x_axis_number_format": primary_x["number_format"],
                "y_axis_number_format": primary_y["number_format"],
                "secondary_x_axis_title": secondary_x["title"],
                "secondary_y_axis_title": secondary_y["title"],
                "secondary_x_axis_number_format": secondary_x["number_format"],
                "secondary_y_axis_number_format": secondary_y["number_format"],
                "data_labels": _project_data_labels(first_plot),
                "style": parse_xml_int(
                    _value(style, "2"),
                    attribute="chart.style",
                    minimum=1,
                    maximum=48,
                ),
                "radar_style": _value(
                    None if radar is None else radar.find(f"{{{CHART_NS}}}radarStyle"),
                    "standard",
                ),
                "bubble_scale": parse_xml_int(
                    _value(
                        None if bubble is None else bubble.find(f"{{{CHART_NS}}}bubbleScale"),
                        "100",
                    ),
                    attribute="chart.bubbleScale",
                    minimum=0,
                    maximum=300,
                ),
            }
        )
    return charts


def _drawing_records(package: Any) -> dict[str, dict[str, Any]]:
    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    sheet_names: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is not None and relationship.resolved_target:
            sheet_names[relationship.resolved_target] = sheet.attrib.get("name", "")
    drawings = {
        relationship.resolved_target: sheet_names.get(relationship.source_part, "")
        for relationship in package.relationships
        if relationship.relationship_type.rsplit("/", 1)[-1] == "drawing"
        and relationship.resolved_target
    }
    result: dict[str, dict[str, Any]] = {}
    for drawing_part, sheet_name in drawings.items():
        root = package.xml(drawing_part)
        relationships = relationship_map(package.relationships, drawing_part)
        for anchor in root.findall(f"{{{DRAWING_NS}}}twoCellAnchor"):
            reference = anchor.find(f".//{{{CHART_NS}}}chart")
            if reference is None:
                continue
            relationship = relationships.get(reference.attrib.get(f"{{{NS['r']}}}id", ""))
            if relationship is None or not relationship.resolved_target:
                continue
            non_visual = anchor.find(f".//{{{DRAWING_NS}}}cNvPr")
            result[relationship.resolved_target] = {
                "name": "" if non_visual is None else non_visual.attrib.get("name", ""),
                "sheet": sheet_name,
                "anchor": _project_anchor(anchor),
                "drawing_part": drawing_part,
            }
    return result


def _plots(root: Any) -> list[tuple[str, Any]]:
    plot_area = root.find(f".//{{{CHART_NS}}}plotArea")
    if plot_area is None:
        return []
    tags = {f"{{{CHART_NS}}}{tag}": kind for tag, kind in _PLOT_TAGS}
    return [(tags[child.tag], child) for child in plot_area if child.tag in tags]


def _axes(root: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    plot_area = root.find(f".//{{{CHART_NS}}}plotArea")
    if plot_area is None:
        return result
    for axis in plot_area:
        kind = axis.tag.rsplit("}", 1)[-1]
        if kind not in {"catAx", "valAx"}:
            continue
        identifier = _value(axis.find(f"{{{CHART_NS}}}axId"), "")
        result[identifier] = {
            "element": axis,
            "kind": "category" if kind == "catAx" else "value",
            "position": _value(axis.find(f"{{{CHART_NS}}}axPos"), ""),
            **_project_axis(axis),
        }
    return result


def _plot_axis(plot: Any, axes: dict[str, dict[str, Any]]) -> str:
    identifiers = [_value(item, "") for item in plot.findall(f"{{{CHART_NS}}}axId")]
    positions = {axes[item]["position"] for item in identifiers if item in axes}
    return "secondary" if positions & {"t", "r"} else "primary"


def _axis_pair(
    axes: dict[str, dict[str, Any]],
    *,
    secondary: bool,
    chart_type: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    empty = {"title": None, "number_format": None}
    positions = {"t", "r"} if secondary else {"b", "l"}
    candidates = [item for item in axes.values() if item["position"] in positions]
    if chart_type not in {"scatter", "bubble"}:
        x_axis = next((item for item in candidates if item["kind"] == "category"), empty)
        y_axis = next((item for item in candidates if item["kind"] == "value"), empty)
        return x_axis, y_axis
    x_position = "t" if secondary else "b"
    y_position = "r" if secondary else "l"
    x_axis = next((item for item in candidates if item["position"] == x_position), empty)
    y_axis = next((item for item in candidates if item["position"] == y_position), empty)
    return x_axis, y_axis


def _project_series(item: Any, plot_type: str, axis: str, *, combo: bool) -> dict[str, Any]:
    color_element = item.find(f".//{{{DRAWING_MAIN_NS}}}srgbClr")
    color = None if color_element is None else color_element.attrib.get("val")
    result: dict[str, Any] = {
        "name": _text(item.find(f"{{{CHART_NS}}}tx/{{{CHART_NS}}}v")),
        "categories": None,
        "values": None,
        "x_values": None,
        "y_values": None,
        "bubble_sizes": None,
        "color": None if color is None else f"FF{color}" if len(color) == 6 else color,
    }
    if plot_type in {"scatter", "bubble"}:
        result["x_values"] = _reference(item, "xVal")
        result["y_values"] = _reference(item, "yVal")
        if plot_type == "bubble":
            result["bubble_sizes"] = _reference(item, "bubbleSize")
    else:
        result["categories"] = _text(item.find(f"{{{CHART_NS}}}cat/*/{{{CHART_NS}}}f"))
        result["values"] = _reference(item, "val")
    if combo:
        result["chart_type"] = plot_type
    if axis == "secondary":
        result["axis"] = axis
    trendline = item.find(f"{{{CHART_NS}}}trendline")
    if trendline is not None:
        result["trendline"] = _project_trendline(trendline)
    error_bars = item.findall(f"{{{CHART_NS}}}errBars")
    if error_bars:
        result["error_bars"] = [_project_error_bars(entry) for entry in error_bars]
    return result


def _project_trendline(item: Any) -> dict[str, Any]:
    kind = {
        "linear": "linear",
        "exp": "exponential",
        "log": "logarithmic",
        "poly": "polynomial",
        "power": "power",
        "movingAvg": "moving_average",
    }[_value(item.find(f"{{{CHART_NS}}}trendlineType"), "linear")]
    return {
        "type": kind,
        "order": _optional_int(
            item.find(f"{{{CHART_NS}}}order"),
            attribute="chart.trendline.order",
            minimum=2,
            maximum=6,
        ),
        "period": _optional_int(
            item.find(f"{{{CHART_NS}}}period"),
            attribute="chart.trendline.period",
            minimum=2,
            maximum=255,
        ),
        "display_equation": _bool_value(item.find(f"{{{CHART_NS}}}dispEq")),
        "display_r_squared": _bool_value(item.find(f"{{{CHART_NS}}}dispRSqr")),
        "forward": _number_value(
            item.find(f"{{{CHART_NS}}}forward"),
            0,
            attribute="chart.trendline.forward",
            minimum=0,
            maximum=100_000,
        ),
        "backward": _number_value(
            item.find(f"{{{CHART_NS}}}backward"),
            0,
            attribute="chart.trendline.backward",
            minimum=0,
            maximum=100_000,
        ),
        "intercept": _optional_number(
            item.find(f"{{{CHART_NS}}}intercept"),
            attribute="chart.trendline.intercept",
            minimum=-1e100,
            maximum=1e100,
        ),
    }


def _project_error_bars(item: Any) -> dict[str, Any]:
    kind = {
        "fixedVal": "fixed",
        "percentage": "percentage",
        "stdDev": "standard_deviation",
        "stdErr": "standard_error",
        "cust": "custom",
    }[_value(item.find(f"{{{CHART_NS}}}errValType"), "fixedVal")]
    return {
        "direction": _value(item.find(f"{{{CHART_NS}}}errDir"), "y"),
        "type": kind,
        "value": _optional_number(
            item.find(f"{{{CHART_NS}}}val"),
            attribute="chart.errorBars.value",
            minimum=0,
            maximum=1e100,
        ),
        "plus": _reference(item, "plus") or None,
        "minus": _reference(item, "minus") or None,
        "end_style": not _bool_value(item.find(f"{{{CHART_NS}}}noEndCap")),
    }


def _project_axis(axis: Any) -> dict[str, Any]:
    number_format = axis.find(f"{{{CHART_NS}}}numFmt")
    return {
        "title": _rich_text(axis.find(f"{{{CHART_NS}}}title")) or None,
        "number_format": None if number_format is None else number_format.attrib.get("formatCode"),
    }


def _project_title(root: Any) -> str:
    return _rich_text(root.find(f".//{{{CHART_NS}}}chart/{{{CHART_NS}}}title"))


def _project_data_labels(plot: Any) -> dict[str, bool]:
    labels = None if plot is None else plot.find(f"{{{CHART_NS}}}dLbls")
    return {
        key: _bool_value(None if labels is None else labels.find(f"{{{CHART_NS}}}{tag}"))
        for key, tag in (
            ("show_value", "showVal"),
            ("show_category_name", "showCatName"),
            ("show_series_name", "showSerName"),
            ("show_legend_key", "showLegendKey"),
            ("show_percentage", "showPercent"),
        )
    }


def _project_anchor(anchor: Any) -> str:
    first = anchor.find(f"{{{DRAWING_NS}}}from")
    last = anchor.find(f"{{{DRAWING_NS}}}to")
    if first is None or last is None:
        return ""
    return f"{_marker_ref(first)}:{_marker_ref(last)}"


def _marker_ref(marker: Any) -> str:
    column = parse_xml_int(
        _text(marker.find(f"{{{DRAWING_NS}}}col")) or "0",
        attribute="drawing.marker.col",
        minimum=0,
        maximum=16_383,
    ) + 1
    row = parse_xml_int(
        _text(marker.find(f"{{{DRAWING_NS}}}row")) or "0",
        attribute="drawing.marker.row",
        minimum=0,
        maximum=1_048_575,
    ) + 1
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(ord("A") + remainder) + result
    return f"{result}{row}"


def _reference(parent: Any, name: str) -> str:
    return _text(parent.find(f"{{{CHART_NS}}}{name}/{{{CHART_NS}}}numRef/{{{CHART_NS}}}f"))


def _rich_text(element: Any) -> str:
    if element is None:
        return ""
    return "".join(item.text or "" for item in element.findall(f".//{{{DRAWING_MAIN_NS}}}t"))


def _text(element: Any) -> str:
    return "" if element is None else element.text or ""


def _value(element: Any, default: str) -> str:
    return default if element is None else element.attrib.get("val", default)


def _bool_value(element: Any) -> bool:
    return _value(element, "0") in {"1", "true", "on"}


def _optional_int(
    element: Any,
    *,
    attribute: str,
    minimum: int,
    maximum: int,
) -> int | None:
    return parse_optional_xml_int(
        None if element is None else _value(element, "0"),
        attribute=attribute,
        minimum=minimum,
        maximum=maximum,
    )


def _optional_number(
    element: Any,
    *,
    attribute: str,
    minimum: float,
    maximum: float,
) -> int | float | None:
    return parse_optional_xml_number(
        None if element is None else _value(element, "0"),
        attribute=attribute,
        minimum=minimum,
        maximum=maximum,
    )


def _number_value(
    element: Any,
    default: int | float,
    *,
    attribute: str,
    minimum: float,
    maximum: float,
) -> int | float:
    return (
        default
        if element is None
        else parse_xml_number(
            _value(element, str(default)),
            attribute=attribute,
            minimum=minimum,
            maximum=maximum,
        )
    )
