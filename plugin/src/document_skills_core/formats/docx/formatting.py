"""Schema-ordered WordprocessingML paragraph and run formatting helpers."""

from typing import Any
from xml.etree.ElementTree import Element

from .constants import qn
from .package import OpcPackage

_RUN_PROPERTY_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "rStyle",
            "rFonts",
            "b",
            "bCs",
            "i",
            "iCs",
            "caps",
            "smallCaps",
            "strike",
            "dstrike",
            "outline",
            "shadow",
            "emboss",
            "imprint",
            "noProof",
            "snapToGrid",
            "vanish",
            "webHidden",
            "color",
            "spacing",
            "w",
            "kern",
            "position",
            "sz",
            "szCs",
            "highlight",
            "u",
            "effect",
            "bdr",
            "shd",
            "fitText",
            "vertAlign",
            "rtl",
            "cs",
            "em",
            "lang",
            "eastAsianLayout",
            "specVanish",
            "oMath",
        )
    )
}


def available_paragraph_styles(package: OpcPackage) -> set[str]:
    styles = package.xml("word/styles.xml")
    return {
        value
        for node in styles.findall(qn("w", "style"))
        if (value := node.attrib.get(qn("w", "styleId"))) is not None
    }


def set_paragraph_style(node: Element, style: str) -> None:
    properties = node.find(qn("w", "pPr"))
    if properties is None:
        properties = Element(qn("w", "pPr"))
        node.insert(0, properties)
    style_node = properties.find(qn("w", "pStyle"))
    if style_node is None:
        style_node = Element(qn("w", "pStyle"))
        properties.insert(0, style_node)
    style_node.set(qn("w", "val"), style)


def set_run_style(run: Element, style: dict[str, Any]) -> None:
    properties = run.find(qn("w", "rPr"))
    if properties is None:
        properties = Element(qn("w", "rPr"))
        run.insert(0, properties)
    if "font_family" in style:
        family = style["font_family"]
        _set_run_property(
            properties,
            "rFonts",
            {
                qn("w", "ascii"): family,
                qn("w", "hAnsi"): family,
                qn("w", "eastAsia"): family,
                qn("w", "cs"): family,
            },
        )
    if "bold" in style:
        _set_on_off(properties, "b", style["bold"])
    if "italic" in style:
        _set_on_off(properties, "i", style["italic"])
    if "color" in style:
        _set_run_property(properties, "color", {qn("w", "val"): style["color"]})
    if "font_size_pt" in style:
        half_points = str(int(float(style["font_size_pt"]) * 2))
        _set_run_property(properties, "sz", {qn("w", "val"): half_points})
        _set_run_property(properties, "szCs", {qn("w", "val"): half_points})
    if "highlight" in style:
        _set_run_property(
            properties,
            "highlight",
            {qn("w", "val"): style["highlight"]},
        )
    if "underline" in style:
        _set_run_property(
            properties,
            "u",
            {qn("w", "val"): "single" if style["underline"] else "none"},
        )


def _set_on_off(properties: Element, name: str, enabled: bool) -> None:
    attributes = {} if enabled else {qn("w", "val"): "0"}
    _set_run_property(properties, name, attributes)


def _set_run_property(
    properties: Element,
    name: str,
    attributes: dict[str, str],
) -> None:
    tag = qn("w", name)
    matches = [child for child in properties if child.tag == tag]
    node = matches[0] if matches else Element(tag)
    for duplicate in matches[1:]:
        properties.remove(duplicate)
    node.attrib.clear()
    node.attrib.update(attributes)
    if not matches:
        rank = _RUN_PROPERTY_ORDER[name]
        position = next(
            (
                index
                for index, child in enumerate(properties)
                if _RUN_PROPERTY_ORDER.get(_local_name(child.tag), 10_000) > rank
            ),
            len(properties),
        )
        properties.insert(position, node)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
