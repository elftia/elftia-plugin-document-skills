"""Deterministic bounded inline-picture emission and updates."""

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn

EMU_PER_INCH = 914_400


def image_dimensions_emu(image: dict[str, Any]) -> tuple[int, int]:
    width = int(image["width_inches"] * EMU_PER_INCH)
    height = int(width * image["height_px"] / image["width_px"])
    return width, height


def image_paragraph(
    image: dict[str, Any],
    *,
    document_properties_id: int,
    document_name: str,
    picture_properties_id: int,
    picture_name: str,
) -> Element:
    width, height = image_dimensions_emu(image)
    paragraph_node = Element(qn("w", "p"))
    run = SubElement(paragraph_node, qn("w", "r"))
    drawing = SubElement(run, qn("w", "drawing"))
    inline = SubElement(drawing, qn("wp", "inline"))
    SubElement(inline, qn("wp", "extent"), {"cx": str(width), "cy": str(height)})
    SubElement(
        inline,
        qn("wp", "docPr"),
        {
            "id": str(document_properties_id),
            "name": document_name,
            "descr": image["alt_text"],
        },
    )
    graphic = SubElement(inline, qn("a", "graphic"))
    graphic_data = SubElement(
        graphic,
        qn("a", "graphicData"),
        {"uri": "http://schemas.openxmlformats.org/drawingml/2006/picture"},
    )
    picture = SubElement(graphic_data, qn("pic", "pic"))
    non_visual = SubElement(picture, qn("pic", "nvPicPr"))
    SubElement(
        non_visual,
        qn("pic", "cNvPr"),
        {"id": str(picture_properties_id), "name": picture_name},
    )
    SubElement(non_visual, qn("pic", "cNvPicPr"))
    fill = SubElement(picture, qn("pic", "blipFill"))
    SubElement(fill, qn("a", "blip"), {qn("r", "embed"): image["relationship_id"]})
    _set_crop(fill, image.get("crop"))
    stretch = SubElement(fill, qn("a", "stretch"))
    SubElement(stretch, qn("a", "fillRect"))
    shape = SubElement(picture, qn("pic", "spPr"))
    transform = SubElement(shape, qn("a", "xfrm"))
    SubElement(transform, qn("a", "off"), {"x": "0", "y": "0"})
    SubElement(transform, qn("a", "ext"), {"cx": str(width), "cy": str(height)})
    geometry = SubElement(shape, qn("a", "prstGeom"), {"prst": "rect"})
    SubElement(geometry, qn("a", "avLst"))
    return paragraph_node


def update_image_drawing(drawing: Element, image: dict[str, Any]) -> None:
    width, height = image_dimensions_emu(image)
    extent = _exact_descendant(drawing, qn("wp", "extent"), "picture extent")
    document_properties = _exact_descendant(
        drawing, qn("wp", "docPr"), "picture document properties"
    )
    fill = _exact_descendant(drawing, qn("pic", "blipFill"), "picture fill")
    transform_extent = _exact_descendant(
        drawing, qn("a", "ext"), "picture transform extent"
    )
    extent.attrib.update({"cx": str(width), "cy": str(height)})
    transform_extent.attrib.update({"cx": str(width), "cy": str(height)})
    document_properties.attrib["descr"] = image["alt_text"]
    _set_crop(fill, image.get("crop"))


def crop_attributes(crop: dict[str, float] | None) -> dict[str, str] | None:
    if crop is None:
        return None
    return {
        attribute: str(round(crop[side] * 1_000))
        for side, attribute in (
            ("left", "l"),
            ("top", "t"),
            ("right", "r"),
            ("bottom", "b"),
        )
    }


def _set_crop(fill: Element, crop: dict[str, float] | None) -> None:
    for existing in list(fill.findall(qn("a", "srcRect"))):
        fill.remove(existing)
    attributes = crop_attributes(crop)
    if attributes is None:
        return
    source_rectangle = Element(qn("a", "srcRect"), attributes)
    blip = fill.find(qn("a", "blip"))
    position = list(fill).index(blip) + 1 if blip is not None else 0
    fill.insert(position, source_rectangle)


def _exact_descendant(root: Element, tag: str, label: str) -> Element:
    matches = list(root.iter(tag))
    if len(matches) != 1:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            f"Image editing requires exactly one {label}.",
            status="enhancement_required",
        )
    return matches[0]
