"""Native editable chart parts backed by bounded literal caches."""

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import NS
from .scaffold import _to_xml_bytes

_C = NS["c"]
_A = NS["a"]


def C(tag: str) -> str:
    return f"{{{_C}}}{tag}"


def A(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def prepare_chart(value: dict[str, Any], index: int) -> dict[str, Any]:
    """Attach deterministic package identity and backward-compatible defaults."""

    chart_type = value.get("chart_type", "bar")
    categories = list(value.get("categories") or ["Category 1"])
    series = value.get("series")
    if not series:
        if chart_type == "scatter":
            series = [{"name": value.get("title") or "Series 1", "x_values": [1.0], "y_values": [1.0]}]
        else:
            series = [{"name": value.get("title") or "Series 1", "values": [1.0]}]
    axes = value.get("axes") or {}
    default_axis = {"title": "", "number_format": "General"}
    return {
        **value,
        "axes": {
            name: {**default_axis, **(axes.get(name) or {})}
            for name in ("category", "value", "x", "y")
        },
        "categories": categories,
        "chart_type": chart_type,
        "colors": list(value.get("colors") or []),
        "data_labels": {
            "show_category_name": False,
            "show_series_name": False,
            "show_value": False,
            **(value.get("data_labels") or {}),
        },
        "index": index,
        "legend": {"show": True, "position": "right", **(value.get("legend") or {})},
        "part": f"ppt/charts/chart{index}.xml",
        "relationship_id": "rIdChart",
        "series": list(series),
        "target": f"../charts/chart{index}.xml",
        "title": value.get("title", ""),
    }


def build_chart_part(chart: dict[str, Any]) -> bytes:
    root = Element(C("chartSpace"))
    SubElement(root, C("date1904"), {"val": "0"})
    SubElement(root, C("lang"), {"val": "en-US"})
    SubElement(root, C("roundedCorners"), {"val": "0"})
    chart_node = SubElement(root, C("chart"))
    if chart["title"]:
        _text_title(chart_node, chart["title"])
    SubElement(chart_node, C("autoTitleDeleted"), {"val": "0" if chart["title"] else "1"})
    plot_area = SubElement(chart_node, C("plotArea"))
    SubElement(plot_area, C("layout"))
    axis_ids = (100_000_000 + chart["index"] * 10 + 1, 100_000_000 + chart["index"] * 10 + 2)
    chart_type = chart["chart_type"]
    if chart_type in {"bar", "column"}:
        _bar_chart(plot_area, chart, axis_ids)
        _category_axes(plot_area, chart, axis_ids)
    elif chart_type == "line":
        _line_chart(plot_area, chart, axis_ids)
        _category_axes(plot_area, chart, axis_ids)
    elif chart_type == "pie":
        _pie_chart(plot_area, chart)
    elif chart_type == "scatter":
        _scatter_chart(plot_area, chart, axis_ids)
        _scatter_axes(plot_area, chart, axis_ids)
    if chart["legend"]["show"]:
        legend = SubElement(chart_node, C("legend"))
        SubElement(legend, C("legendPos"), {"val": _legend_position(chart["legend"]["position"])})
        SubElement(legend, C("layout"))
        SubElement(legend, C("overlay"), {"val": "0"})
    SubElement(chart_node, C("plotVisOnly"), {"val": "1"})
    SubElement(chart_node, C("dispBlanksAs"), {"val": "gap"})
    SubElement(chart_node, C("showDLblsOverMax"), {"val": "0"})
    return _to_xml_bytes(root)


def public_chart_record(chart: dict[str, Any]) -> dict[str, Any]:
    return {
        "chart_part": chart["part"],
        "chart_type": chart["chart_type"],
        "data_storage": "literal-cache",
        "editable": True,
        "fallback": "native",
        "series": len(chart["series"]),
    }


def _bar_chart(parent: Element, chart: dict[str, Any], axis_ids: tuple[int, int]) -> None:
    node = SubElement(parent, C("barChart"))
    SubElement(node, C("barDir"), {"val": "bar" if chart["chart_type"] == "bar" else "col"})
    SubElement(node, C("grouping"), {"val": "clustered"})
    SubElement(node, C("varyColors"), {"val": "0"})
    for index, series in enumerate(chart["series"]):
        _category_series(node, chart, series, index)
    _data_labels(node, chart["data_labels"])
    SubElement(node, C("gapWidth"), {"val": "150"})
    for axis_id in axis_ids:
        SubElement(node, C("axId"), {"val": str(axis_id)})


def _line_chart(parent: Element, chart: dict[str, Any], axis_ids: tuple[int, int]) -> None:
    node = SubElement(parent, C("lineChart"))
    SubElement(node, C("grouping"), {"val": "standard"})
    SubElement(node, C("varyColors"), {"val": "0"})
    for index, series in enumerate(chart["series"]):
        series_node = _category_series(node, chart, series, index)
        marker = SubElement(series_node, C("marker"))
        SubElement(marker, C("symbol"), {"val": "circle"})
        SubElement(marker, C("size"), {"val": "5"})
        SubElement(series_node, C("smooth"), {"val": "0"})
    _data_labels(node, chart["data_labels"])
    for axis_id in axis_ids:
        SubElement(node, C("axId"), {"val": str(axis_id)})


def _pie_chart(parent: Element, chart: dict[str, Any]) -> None:
    node = SubElement(parent, C("pieChart"))
    SubElement(node, C("varyColors"), {"val": "1"})
    for index, series in enumerate(chart["series"]):
        _category_series(node, chart, series, index)
    _data_labels(node, chart["data_labels"])
    SubElement(node, C("firstSliceAng"), {"val": "0"})


def _scatter_chart(parent: Element, chart: dict[str, Any], axis_ids: tuple[int, int]) -> None:
    node = SubElement(parent, C("scatterChart"))
    SubElement(node, C("scatterStyle"), {"val": "lineMarker"})
    SubElement(node, C("varyColors"), {"val": "0"})
    for index, series in enumerate(chart["series"]):
        series_node = SubElement(node, C("ser"))
        SubElement(series_node, C("idx"), {"val": str(index)})
        SubElement(series_node, C("order"), {"val": str(index)})
        _series_name(series_node, series.get("name", f"Series {index + 1}"))
        _series_color(series_node, chart, index)
        marker = SubElement(series_node, C("marker"))
        SubElement(marker, C("symbol"), {"val": "circle"})
        SubElement(marker, C("size"), {"val": "5"})
        x_values = series.get("x_values") or [float(point + 1) for point in range(len(series.get("y_values") or [1.0]))]
        _numeric_literal(SubElement(series_node, C("xVal")), x_values, "General")
        _numeric_literal(SubElement(series_node, C("yVal")), series.get("y_values") or [1.0], "General")
        SubElement(series_node, C("smooth"), {"val": "0"})
    _data_labels(node, chart["data_labels"])
    for axis_id in axis_ids:
        SubElement(node, C("axId"), {"val": str(axis_id)})


def _category_series(
    parent: Element,
    chart: dict[str, Any],
    series: dict[str, Any],
    index: int,
) -> Element:
    node = SubElement(parent, C("ser"))
    SubElement(node, C("idx"), {"val": str(index)})
    SubElement(node, C("order"), {"val": str(index)})
    _series_name(node, series.get("name", f"Series {index + 1}"))
    _series_color(node, chart, index)
    _string_literal(SubElement(node, C("cat")), chart["categories"])
    _numeric_literal(SubElement(node, C("val")), series.get("values") or [1.0], "General")
    return node


def _series_name(parent: Element, name: str) -> None:
    tx = SubElement(parent, C("tx"))
    value = SubElement(tx, C("v"))
    value.text = name


def _series_color(parent: Element, chart: dict[str, Any], index: int) -> None:
    if index >= len(chart["colors"]):
        return
    sp_pr = SubElement(parent, C("spPr"))
    solid = SubElement(sp_pr, A("solidFill"))
    SubElement(solid, A("srgbClr"), {"val": chart["colors"][index]})


def _string_literal(parent: Element, values: list[str]) -> None:
    literal = SubElement(parent, C("strLit"))
    SubElement(literal, C("ptCount"), {"val": str(len(values))})
    for index, value in enumerate(values):
        point = SubElement(literal, C("pt"), {"idx": str(index)})
        node = SubElement(point, C("v"))
        node.text = value


def _numeric_literal(parent: Element, values: list[float], number_format: str) -> None:
    literal = SubElement(parent, C("numLit"))
    format_code = SubElement(literal, C("formatCode"))
    format_code.text = number_format
    SubElement(literal, C("ptCount"), {"val": str(len(values))})
    for index, value in enumerate(values):
        point = SubElement(literal, C("pt"), {"idx": str(index)})
        node = SubElement(point, C("v"))
        node.text = format(float(value), ".15g")


def _data_labels(parent: Element, labels: dict[str, bool]) -> None:
    node = SubElement(parent, C("dLbls"))
    SubElement(node, C("showLegendKey"), {"val": "0"})
    SubElement(node, C("showVal"), {"val": _bool(labels["show_value"])})
    SubElement(node, C("showCatName"), {"val": _bool(labels["show_category_name"])})
    SubElement(node, C("showSerName"), {"val": _bool(labels["show_series_name"])})
    SubElement(node, C("showPercent"), {"val": "0"})
    SubElement(node, C("showBubbleSize"), {"val": "0"})


def _category_axes(parent: Element, chart: dict[str, Any], axis_ids: tuple[int, int]) -> None:
    category, value = axis_ids
    _axis(parent, "catAx", category, value, chart["axes"]["category"], "b")
    _axis(parent, "valAx", value, category, chart["axes"]["value"], "l")


def _scatter_axes(parent: Element, chart: dict[str, Any], axis_ids: tuple[int, int]) -> None:
    x_axis, y_axis = axis_ids
    _axis(parent, "valAx", x_axis, y_axis, chart["axes"]["x"], "b")
    _axis(parent, "valAx", y_axis, x_axis, chart["axes"]["y"], "l")


def _axis(
    parent: Element,
    kind: str,
    axis_id: int,
    cross_axis: int,
    settings: dict[str, str],
    position: str,
) -> None:
    node = SubElement(parent, C(kind))
    SubElement(node, C("axId"), {"val": str(axis_id)})
    scaling = SubElement(node, C("scaling"))
    SubElement(scaling, C("orientation"), {"val": "minMax"})
    SubElement(node, C("delete"), {"val": "0"})
    SubElement(node, C("axPos"), {"val": position})
    if settings["title"]:
        _text_title(node, settings["title"])
    SubElement(node, C("numFmt"), {"formatCode": settings["number_format"], "sourceLinked": "0"})
    SubElement(node, C("majorTickMark"), {"val": "none"})
    SubElement(node, C("minorTickMark"), {"val": "none"})
    SubElement(node, C("tickLblPos"), {"val": "nextTo"})
    SubElement(node, C("crossAx"), {"val": str(cross_axis)})
    SubElement(node, C("crosses"), {"val": "autoZero"})
    if kind == "catAx":
        SubElement(node, C("auto"), {"val": "1"})
        SubElement(node, C("lblAlgn"), {"val": "ctr"})
        SubElement(node, C("lblOffset"), {"val": "100"})
    else:
        SubElement(node, C("crossBetween"), {"val": "between"})


def _text_title(parent: Element, text: str) -> None:
    title = SubElement(parent, C("title"))
    tx = SubElement(title, C("tx"))
    rich = SubElement(tx, C("rich"))
    SubElement(rich, A("bodyPr"))
    SubElement(rich, A("lstStyle"))
    paragraph = SubElement(rich, A("p"))
    run = SubElement(paragraph, A("r"))
    SubElement(run, A("rPr"), {"lang": "en-US"})
    value = SubElement(run, A("t"))
    value.text = text
    SubElement(paragraph, A("endParaRPr"), {"lang": "en-US"})
    SubElement(title, C("layout"))
    SubElement(title, C("overlay"), {"val": "0"})


def _legend_position(value: str) -> str:
    return {
        "bottom": "b",
        "left": "l",
        "right": "r",
        "top": "t",
        "top_right": "tr",
    }[value]


def _bool(value: bool) -> str:
    return "1" if value else "0"
