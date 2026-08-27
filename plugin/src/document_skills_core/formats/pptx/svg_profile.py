"""Closed SVG style, attribute, definition, and gradient profile."""

import re
from typing import Any
from xml.etree.ElementTree import Element

from .svg_values import (
    MAX_GRADIENTS,
    SOURCE_ID,
    XLINK_NAMESPACE,
    color,
    invalid,
    local,
    namespace,
    number,
    offset,
    unit_interval,
    unsafe,
)

_COMMON_ATTRIBUTES = {
    "data-pptx-fallback-image", "fill", "fill-opacity", "filter", "id", "opacity",
    "stroke", "stroke-opacity", "stroke-width", "style", "transform",
}
_TAG_ATTRIBUTES = {
    "ellipse": {"cx", "cy", "rx", "ry"},
    "image": {"height", "href", "width", "x", "y"},
    "line": {"x1", "x2", "y1", "y2"},
    "path": {"d"},
    "polygon": {"points"},
    "rect": {"height", "rx", "ry", "width", "x", "y"},
    "text": {
        "font-family", "font-size", "font-style", "font-weight", "text-anchor",
        "text-decoration", "textLength", "x", "y",
    },
    "tspan": {
        "fill", "font-family", "font-size", "font-style", "font-weight", "id",
        "style", "text-decoration",
    },
    "g": {"data-elftia-bounds", "data-elftia-kind", "data-elftia-model"},
}
_STYLE_PROPERTIES = {
    "fill", "fill-opacity", "font-family", "font-size", "font-style", "font-weight",
    "opacity", "stop-color", "stop-opacity", "stroke", "stroke-opacity", "stroke-width",
    "text-anchor", "text-decoration",
}


class SvgProfile:
    def __init__(self) -> None:
        self.gradients: dict[str, dict[str, Any]] = {}
        self.filter_ids: set[str] = set()

    def definitions(self, root: Element) -> None:
        for child in root:
            if local(child.tag) != "defs":
                continue
            for definition in child:
                tag = local(definition.tag)
                if tag == "linearGradient":
                    self._linear_gradient(definition)
                elif tag == "filter":
                    identifier = definition.attrib.get("id")
                    if (
                        not identifier
                        or SOURCE_ID.fullmatch(identifier) is None
                        or set(definition.attrib) != {"id"}
                        or list(definition)
                    ):
                        unsafe("SVG filter definitions must be empty bounded markers.")
                    self.filter_ids.add(identifier)
                else:
                    unsafe("SVG definition is outside the closed profile.", element=tag)

    def gradient(self, value: str) -> dict[str, Any] | None:
        match = re.fullmatch(r"url\(#([A-Za-z][A-Za-z0-9_.:-]{0,79})\)", value)
        if match is None:
            if value.startswith("url("):
                unsafe("SVG paint references must be local approved gradients.")
            return None
        gradient = self.gradients.get(match.group(1))
        if gradient is None:
            invalid("SVG references an unknown gradient.")
        return gradient

    def style(self, element: Element, inherited: dict[str, str]) -> dict[str, str]:
        style = dict(inherited)
        raw = element.attrib.get("style")
        if raw:
            for declaration in raw.split(";"):
                if not declaration.strip():
                    continue
                if declaration.count(":") != 1:
                    invalid("SVG style declaration is malformed.")
                name, value = (part.strip() for part in declaration.split(":", 1))
                if name not in _STYLE_PROPERTIES or not value:
                    invalid("SVG style property is outside the closed profile.", property=name)
                style[name] = value
        for name in _STYLE_PROPERTIES:
            if name in element.attrib:
                style[name] = element.attrib[name]
        return style

    def validate_attributes(self, element: Element, tag: str) -> None:
        allowed = _COMMON_ATTRIBUTES | _TAG_ATTRIBUTES[tag]
        for raw_name in element.attrib:
            attribute_namespace = namespace(raw_name)
            name = local(raw_name)
            if name.casefold().startswith("on"):
                unsafe("SVG event-handler attributes are forbidden.", attribute=name)
            if attribute_namespace not in {"", XLINK_NAMESPACE} or name not in allowed:
                invalid("SVG attribute is outside the closed profile.", attribute=name, element=tag)

    def _linear_gradient(self, element: Element) -> None:
        allowed = {"id", "x1", "x2", "y1", "y2"}
        if set(element.attrib) - allowed:
            invalid("SVG gradient attributes are unsupported.")
        identifier = element.attrib.get("id")
        if not identifier or SOURCE_ID.fullmatch(identifier) is None or identifier in self.gradients:
            invalid("SVG gradient identity is invalid or duplicated.")
        stops = []
        for stop in element:
            if local(stop.tag) != "stop":
                invalid("SVG gradients accept only stop children.")
            allowed_stop = {"offset", "stop-color", "stop-opacity", "style"}
            if set(stop.attrib) - allowed_stop:
                invalid("SVG gradient stop attributes are unsupported.")
            style = self.style(stop, {})
            stops.append({
                "color": color(style.get("stop-color", "#000000"), "stop-color"),
                "offset": offset(stop.attrib.get("offset")),
                "opacity": unit_interval(style.get("stop-opacity", "1"), "stop-opacity"),
            })
        if not 2 <= len(stops) <= 8 or stops != sorted(stops, key=lambda item: item["offset"]):
            invalid("SVG gradient stops are unsorted or exceed policy.")
        self.gradients[identifier] = {
            "kind": "linear",
            "stops": stops,
            "x1": number(element.attrib.get("x1", "0"), "x1"),
            "x2": number(element.attrib.get("x2", "1"), "x2"),
            "y1": number(element.attrib.get("y1", "0"), "y1"),
            "y2": number(element.attrib.get("y2", "0"), "y2"),
        }
        if len(self.gradients) > MAX_GRADIENTS:
            invalid("SVG gradient count exceeds policy.")


__all__ = ["SvgProfile"]
