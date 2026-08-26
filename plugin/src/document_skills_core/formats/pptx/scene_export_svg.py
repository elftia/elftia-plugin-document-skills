"""Constrained SVG serialization helpers for PPTX scene export."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import NS, local_name
from .scene_export_models import SceneProjectionUnsupported
from .svg_semantics import encode_semantic_model

_P = NS["p"]
_A = NS["a"]
_SVG = "http://www.w3.org/2000/svg"


def _p(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def text_svg(
    element: Element,
    object_id: str,
    pixel: dict[str, float],
    text: str,
) -> Element:
    size = 24.0
    run = next((node for node in element.iter(_a("rPr"))), None)
    if run is not None:
        try:
            size = max(
                1.0,
                min(400.0, float(run.attrib.get("sz", "1800")) / 100 * 96 / 72),
            )
        except ValueError:
            pass
    node = Element(
        f"{{{_SVG}}}text",
        {
            "fill": _text_color(element),
            "font-family": "Arial",
            "font-size": number(size),
            "id": object_id,
            "textLength": number(pixel["width"]),
            "x": number(pixel["x"]),
            "y": number(pixel["y"] + min(pixel["height"], size)),
        },
    )
    node.text = text
    return node


def shape_svg(
    element: Element,
    object_id: str,
    pixel: dict[str, float],
) -> tuple[str, Element]:
    properties = element.find(_p("spPr"))
    if properties is None:
        raise SceneProjectionUnsupported("missing-shape-properties")
    preset = properties.find(_a("prstGeom"))
    custom = properties.find(_a("custGeom"))
    attributes = {
        "fill": _solid_color(properties, default="#FFFFFF"),
        "id": object_id,
        "stroke": _line_color(properties),
        "stroke-width": "1",
    }
    if preset is not None:
        kind = preset.attrib.get("prst", "")
        if kind in {"rect", "roundRect"}:
            attributes.update({
                "height": number(pixel["height"]),
                "width": number(pixel["width"]),
                "x": number(pixel["x"]),
                "y": number(pixel["y"]),
            })
            if kind == "roundRect":
                attributes["rx"] = number(
                    min(pixel["width"], pixel["height"]) * 0.1
                )
            output_kind = "rounded-rectangle" if kind == "roundRect" else "rectangle"
            return output_kind, Element(f"{{{_SVG}}}rect", attributes)
        if kind == "ellipse":
            attributes.update({
                "cx": number(pixel["x"] + pixel["width"] / 2),
                "cy": number(pixel["y"] + pixel["height"] / 2),
                "rx": number(pixel["width"] / 2),
                "ry": number(pixel["height"] / 2),
            })
            return "ellipse", Element(f"{{{_SVG}}}ellipse", attributes)
        if kind == "line":
            return "line", _line_element(object_id, pixel, attributes)
        raise SceneProjectionUnsupported(
            f"unsupported-preset-{kind.casefold() or 'unknown'}"
        )
    if custom is not None:
        attributes["d"] = _custom_path(custom, pixel)
        return "path", Element(f"{{{_SVG}}}path", attributes)
    raise SceneProjectionUnsupported("unsupported-shape-geometry")


def line_svg(element: Element, object_id: str, pixel: dict[str, float]) -> Element:
    properties = element.find(_p("spPr"))
    attributes = {
        "fill": "none",
        "id": object_id,
        "stroke": _line_color(properties),
        "stroke-width": "1",
    }
    return _line_element(object_id, pixel, attributes)


def _line_element(
    object_id: str,
    pixel: dict[str, float],
    attributes: dict[str, str],
) -> Element:
    return Element(
        f"{{{_SVG}}}line",
        {
            **attributes,
            "id": object_id,
            "x1": number(pixel["x"]),
            "x2": number(pixel["x"] + pixel["width"]),
            "y1": number(pixel["y"]),
            "y2": number(pixel["y"] + pixel["height"]),
        },
    )


def _custom_path(custom: Element, pixel: dict[str, float]) -> str:
    path = custom.find(f"{_a('pathLst')}/{_a('path')}")
    if path is None:
        raise SceneProjectionUnsupported("empty-custom-geometry")
    try:
        local_width = float(path.attrib.get("w", "0"))
        local_height = float(path.attrib.get("h", "0"))
    except ValueError as error:
        raise SceneProjectionUnsupported("invalid-custom-geometry") from error
    if local_width <= 0 or local_height <= 0:
        raise SceneProjectionUnsupported("invalid-custom-geometry")
    commands = []
    command_map = {
        "moveTo": "M",
        "lnTo": "L",
        "quadBezTo": "Q",
        "cubicBezTo": "C",
    }
    for command in path:
        name = local_name(command.tag)
        if name == "close":
            commands.append("Z")
            continue
        operator = command_map.get(name)
        if operator is None:
            raise SceneProjectionUnsupported("unsupported-custom-path-command")
        points = []
        for point in command.findall(_a("pt")):
            try:
                x = pixel["x"] + float(point.attrib["x"]) / local_width * pixel["width"]
                y = pixel["y"] + float(point.attrib["y"]) / local_height * pixel["height"]
            except (KeyError, ValueError) as error:
                raise SceneProjectionUnsupported("invalid-custom-path-point") from error
            points.extend((number(x), number(y)))
        expected = {"M": 2, "L": 2, "Q": 4, "C": 6}[operator]
        if len(points) != expected:
            raise SceneProjectionUnsupported("invalid-custom-path-arity")
        commands.append(f"{operator} {' '.join(points)}")
    if not commands:
        raise SceneProjectionUnsupported("empty-custom-geometry")
    return " ".join(commands)


def table_model(table: Element) -> dict[str, Any]:
    rows = []
    for row in table.findall(_a("tr")):
        values = []
        for cell in row.findall(_a("tc")):
            values.append("".join(node.text or "" for node in cell.iter(_a("t"))))
        rows.append(values)
    if not rows or not rows[0]:
        raise SceneProjectionUnsupported("empty-table")
    if any(len(row) != len(rows[0]) for row in rows):
        raise SceneProjectionUnsupported("irregular-table")
    return {"header_rows": 1, "rows": rows}


def semantic_svg(
    object_id: str,
    kind: str,
    model: dict[str, Any],
    pixel: dict[str, float],
) -> Element:
    bounds = ",".join(
        number(pixel[key]) for key in ("x", "y", "width", "height")
    )
    group = Element(
        f"{{{_SVG}}}g",
        {
            "data-elftia-bounds": bounds,
            "data-elftia-kind": kind,
            "data-elftia-model": encode_semantic_model(kind, model),
            "id": object_id,
        },
    )
    SubElement(
        group,
        f"{{{_SVG}}}rect",
        {
            "fill": "#FFFFFF",
            "height": number(pixel["height"]),
            "stroke": "#666666",
            "stroke-width": "1",
            "width": number(pixel["width"]),
            "x": number(pixel["x"]),
            "y": number(pixel["y"]),
        },
    )
    label = SubElement(
        group,
        f"{{{_SVG}}}text",
        {
            "fill": "#222222",
            "font-size": "18",
            "textLength": number(max(1.0, pixel["width"] - 16)),
            "x": number(pixel["x"] + 8),
            "y": number(pixel["y"] + min(28.0, pixel["height"])),
        },
    )
    label.text = "Table" if kind == "table" else "Chart"
    return group


def _solid_color(properties: Element, *, default: str) -> str:
    if properties.find(_a("noFill")) is not None:
        return "none"
    solid = properties.find(_a("solidFill"))
    if solid is None:
        return default
    color = solid.find(_a("srgbClr"))
    if color is None or len(color.attrib.get("val", "")) != 6:
        raise SceneProjectionUnsupported("theme-or-complex-fill")
    return "#" + color.attrib["val"].upper()


def _line_color(properties: Element | None) -> str:
    if properties is None:
        return "#000000"
    line = properties.find(_a("ln"))
    if line is None or line.find(_a("noFill")) is not None:
        return "transparent"
    solid = line.find(_a("solidFill"))
    color = None if solid is None else solid.find(_a("srgbClr"))
    return "#000000" if color is None else "#" + color.attrib.get("val", "000000").upper()


def _text_color(element: Element) -> str:
    properties = next((node for node in element.iter(_a("rPr"))), None)
    if properties is None:
        return "#000000"
    solid = properties.find(_a("solidFill"))
    color = None if solid is None else solid.find(_a("srgbClr"))
    return "#000000" if color is None else "#" + color.attrib.get("val", "000000").upper()


def asset_extension(content_type: str, part: str) -> str:
    mapping = {"image/jpeg": "jpg", "image/png": "png"}
    if content_type in mapping:
        return mapping[content_type]
    suffix = part.rsplit(".", 1)[-1].casefold() if "." in part else ""
    if suffix in {"jpg", "jpeg", "png"}:
        return "jpg" if suffix == "jpeg" else suffix
    raise SceneProjectionUnsupported("unsupported-image-format")


def number(value: float) -> str:
    return str(round(value, 6)).rstrip("0").rstrip(".") or "0"


__all__ = [
    "asset_extension",
    "line_svg",
    "number",
    "semantic_svg",
    "shape_svg",
    "table_model",
    "text_svg",
]
