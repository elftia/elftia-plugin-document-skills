"""SVG graphic, semantic, text, and fallback scene projection."""

from __future__ import annotations

import math
from typing import Any
from xml.etree.ElementTree import Element

from .svg_assets import load_svg_asset
from .svg_geometry import (
    Matrix,
    apply,
    bounds,
    parse_path,
    parse_polygon,
    transform_frame,
)
from .svg_semantics import decode_semantic_model
from .svg_values import (
    alignment as _alignment,
    assert_canvas_geometry as _assert_canvas_geometry,
    color as _color,
    href as _href,
    length as _length,
    length_value as _length_value,
    local as _local,
    number as _number,
    paint as _paint,
    positive_length as _positive_length,
    positive_number as _positive_number,
    text_style as _text_style,
    unit_interval as _unit_interval,
)


class SvgItemProjectionMixin:
    """Projection methods mixed into the state-owning SVG compiler."""

    def _semantic_group(
        self,
        element: Element,
        source_id: str,
        parent_id: str | None,
        matrix: Matrix,
        opacity: float,
    ) -> dict[str, Any]:
        kind = element.attrib.get("data-elftia-kind", "")
        model = decode_semantic_model(
            kind,
            element.attrib.get("data-elftia-model", ""),
        )
        raw_bounds = element.attrib.get("data-elftia-bounds", "")
        values = [item.strip() for item in raw_bounds.split(",")]
        if len(values) != 4:
            self._invalid(
                "SVG semantic bounds must contain x, y, width, and height."
            )
        x, y, width, height = (
            _number(value, "data-elftia-bounds") for value in values
        )
        if width <= 0 or height <= 0:
            self._invalid("SVG semantic bounds must be positive.")
        for child in element:
            child_tag = _local(child.tag)
            if child_tag not in {
                "ellipse",
                "line",
                "path",
                "polygon",
                "rect",
                "text",
            }:
                self._unsafe("SVG semantic preview contains an unsupported element.")
            self.profile.validate_attributes(child, child_tag)
            if child_tag == "text":
                for descendant in child:
                    if _local(descendant.tag) != "tspan":
                        self._unsafe(
                            "SVG semantic text preview accepts only tspan children."
                        )
                    self.profile.validate_attributes(descendant, "tspan")
        item = self._base_item(
            source_id,
            parent_id,
            kind,
            transform_frame(x, y, width, height, matrix),
            opacity=opacity,
            fill="transparent",
            stroke="transparent",
            stroke_width=0.0,
        )
        item["table"] = model if kind == "table" else None
        item["chart"] = model if kind == "chart" else None
        return item

    def _graphic(
        self,
        element: Element,
        tag: str,
        source_id: str,
        parent_id: str | None,
        matrix: Matrix,
        style: dict[str, str],
        opacity: float,
    ) -> dict[str, Any]:
        path_commands = None
        polygon_points = None
        if tag == "rect":
            x, y = _length(element, "x", 0), _length(element, "y", 0)
            width = _positive_length(element, "width")
            height = _positive_length(element, "height")
            geometry = transform_frame(x, y, width, height, matrix)
            radius = _length(element, "rx", 0) * math.hypot(
                matrix[0], matrix[1]
            )
            kind = "rounded-rectangle" if radius > 0 else "rectangle"
        elif tag == "ellipse":
            cx, cy = _length(element, "cx"), _length(element, "cy")
            rx = _positive_length(element, "rx")
            ry = _positive_length(element, "ry")
            geometry = transform_frame(cx - rx, cy - ry, rx * 2, ry * 2, matrix)
            radius, kind = 0.0, "ellipse"
        elif tag == "line":
            points = [
                apply(matrix, (_length(element, "x1"), _length(element, "y1"))),
                apply(matrix, (_length(element, "x2"), _length(element, "y2"))),
            ]
            geometry = bounds(points)
            path_commands = [
                {"op": "move", "points": [points[0]]},
                {"op": "line", "points": [points[1]]},
            ]
            radius, kind = 0.0, "path"
        elif tag == "polygon":
            polygon_points, geometry = parse_polygon(
                element.attrib.get("points", ""),
                matrix,
            )
            radius, kind = 0.0, "polygon"
        elif tag == "path":
            path_commands, geometry = parse_path(
                element.attrib.get("d", ""),
                matrix,
            )
            self.path_commands += len(path_commands)
            radius, kind = 0.0, "path"
        elif tag == "text":
            return self._text_item(
                element,
                source_id,
                parent_id,
                matrix,
                style,
                opacity,
            )
        elif tag == "image":
            geometry = transform_frame(
                _length(element, "x", 0),
                _length(element, "y", 0),
                _positive_length(element, "width"),
                _positive_length(element, "height"),
                matrix,
            )
            asset = load_svg_asset(
                self.source,
                _href(element),
                purpose="source-image",
                assets=self.assets,
            )
            item = self._base_item(
                source_id,
                parent_id,
                "image",
                geometry,
                opacity=opacity,
                fill="transparent",
                stroke=_paint(
                    style["stroke"],
                    style["stroke-opacity"],
                    "stroke",
                ),
                stroke_width=_length_value(style["stroke-width"]),
            )
            item.update(
                {
                    "asset_id": asset["id"],
                    "image_crop": {
                        "left": 0,
                        "top": 0,
                        "right": 0,
                        "bottom": 0,
                    },
                }
            )
            return item
        else:  # pragma: no cover - guarded by caller
            self._invalid("SVG graphic element is unsupported.")
        item = self._base_item(
            source_id,
            parent_id,
            kind,
            geometry,
            opacity=opacity,
            fill=(
                style["fill"]
                if style["fill"].startswith("url(")
                else _paint(style["fill"], style["fill-opacity"], "fill")
            ),
            stroke=_paint(
                style["stroke"],
                style["stroke-opacity"],
                "stroke",
            ),
            stroke_width=_length_value(style["stroke-width"]),
            radius=radius,
        )
        item["path_commands"] = path_commands
        item["points"] = polygon_points
        gradient = self.profile.gradient(style["fill"])
        if gradient is not None:
            fill_opacity = _unit_interval(style["fill-opacity"], "fill-opacity")
            gradient = {
                **gradient,
                "stops": [
                    {**stop, "opacity": stop["opacity"] * fill_opacity}
                    for stop in gradient["stops"]
                ],
            }
        item["gradient"] = gradient
        return item

    def _text_item(
        self,
        element: Element,
        source_id: str,
        parent_id: str | None,
        matrix: Matrix,
        style: dict[str, str],
        opacity: float,
    ) -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        if element.text:
            runs.append({"text": element.text, "style": _text_style(style)})
        for index, child in enumerate(element):
            if _local(child.tag) != "tspan":
                self._unsafe("SVG text accepts only bounded tspan children.")
            self.profile.validate_attributes(child, "tspan")
            self._source_id(child, f"{source_id}-tspan-{index + 1}")
            child_style = self.profile.style(child, style)
            if child.text:
                runs.append({"text": child.text, "style": _text_style(child_style)})
            if child.tail:
                runs.append({"text": child.tail, "style": _text_style(style)})
        runs = [run for run in runs if run["text"]]
        text = "".join(run["text"] for run in runs)
        if not text or len(text.encode("utf-8")) > 64_000:
            self._invalid("SVG text is empty or exceeds policy.", source_id=source_id)
        size = _positive_number(style["font-size"], "font-size")
        width_value = element.attrib.get("textLength")
        if width_value is None:
            width = max(size, len(text) * size * 0.6)
            outcome, reason = "approximated", "text_length_estimated"
            self.approximations += 1
        else:
            width = _positive_number(width_value, "textLength")
            outcome, reason = "native", None
        geometry = transform_frame(
            _length(element, "x", 0),
            _length(element, "y", 0) - size,
            width,
            size * 1.25,
            matrix,
        )
        item = self._base_item(
            source_id,
            parent_id,
            "text",
            geometry,
            opacity=opacity,
            fill="transparent",
            stroke="transparent",
            stroke_width=0.0,
        )
        item.update(
            {
                "outcome": outcome,
                "outcome_reason": reason,
                "paragraphs": [
                    {
                        "alignment": _alignment(style["text-anchor"]),
                        "line_height": "normal",
                        "runs": runs,
                    }
                ],
                "text": text,
                "text_style": _text_style(style),
            }
        )
        return item

    def _base_item(
        self,
        source_id: str,
        parent_id: str | None,
        kind: str,
        geometry: dict[str, float],
        *,
        opacity: float,
        fill: str,
        stroke: str,
        stroke_width: float,
        radius: float = 0.0,
    ) -> dict[str, Any]:
        _assert_canvas_geometry(geometry)
        return {
            "asset_id": None,
            "border_color": (
                stroke if stroke.startswith("rgba(") else _color(stroke, "stroke")
            ),
            "border_width": max(0.0, stroke_width),
            "fill": (
                "transparent"
                if fill.startswith("url(")
                else fill if fill.startswith("rgba(") else _color(fill, "fill")
            ),
            "gradient": None,
            "height": geometry["height"],
            "image_crop": None,
            "kind": kind,
            "opacity": opacity,
            "outcome": "native",
            "outcome_reason": None,
            "paragraphs": [],
            "parent_source_id": parent_id,
            "path_commands": None,
            "points": None,
            "radius": max(0.0, radius),
            "rotation": geometry.get("rotation", 0.0),
            "source_id": source_id,
            "text": "",
            "text_insets": {"bottom": 0, "left": 0, "right": 0, "top": 0},
            "text_style": _text_style({}),
            "table": None,
            "chart": None,
            "width": geometry["width"],
            "x": geometry["x"],
            "y": geometry["y"],
        }

    def _element_fallback(
        self,
        element: Element,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        relative = element.attrib.get("data-pptx-fallback-image")
        if self.fallback_policy != "element-rasterize" or not relative:
            self._invalid(
                "Unsupported SVG filter requires an explicit element fallback asset."
            )
        area = item["width"] * item["height"]
        if area >= 1920 * 1080 * 0.8:
            self._invalid("Whole-slide or near-whole-slide SVG fallback is forbidden.")
        asset = load_svg_asset(
            self.source,
            relative,
            purpose="element-fallback",
            assets=self.assets,
        )
        return {
            **item,
            "asset_id": asset["id"],
            "fill": "transparent",
            "gradient": None,
            "image_crop": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "kind": "image",
            "outcome": "rasterized",
            "outcome_reason": "unsupported_filter",
            "path_commands": None,
            "points": None,
        }


__all__ = ["SvgItemProjectionMixin"]
