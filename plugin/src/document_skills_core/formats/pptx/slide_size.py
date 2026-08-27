"""Deck-level slide-size mutation and fail-closed object-boundary validation."""

import math
from typing import Any
from xml.etree.ElementTree import Element, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, PRESENTATION_MAIN, local_name
from .mapping import map_slides
from .object_xml import drawable_elements, slide_shape_tree

_P = f"{{{NS['p']}}}"


def apply_slide_size(
    package: Any,
    size: dict[str, Any],
) -> dict[str, Any]:
    """Apply one explicit deck-level size and validate final slide objects later."""

    presentation = package.xml(PRESENTATION_MAIN)
    node = next(
        (child for child in presentation if local_name(child.tag) == "sldSz"),
        None,
    )
    before = _size_record(node)
    if node is None:
        node = Element(f"{_P}sldSz")
        _insert_slide_size(presentation, node)
    node.attrib.clear()
    node.attrib.update({
        "cx": str(size["cx"]),
        "cy": str(size["cy"]),
        "type": size["type"],
    })
    package.set_part(
        PRESENTATION_MAIN,
        tostring(presentation, encoding="UTF-8", xml_declaration=True),
    )
    return {
        "after": dict(size),
        "before": before,
        "scope": "deck",
    }


def validate_slide_object_bounds(
    package: Any,
    size: dict[str, Any],
) -> dict[str, Any]:
    """Require every top-level slide object to resolve inside the new canvas."""

    width = int(size["cx"])
    height = int(size["cy"])
    failures: list[dict[str, Any]] = []
    checked = 0
    inherited = 0
    for slide in map_slides(package):
        part = slide.get("part")
        if not part:
            failures.append({"code": "missing-slide-part", "slide": slide["number"]})
            continue
        roots = _inheritance_roots(package, slide)
        for element in drawable_elements(slide_shape_tree(package.xml(part))):
            checked += 1
            bounds = _element_bounds(element)
            if bounds is None:
                bounds = _inherited_bounds(element, roots)
                inherited += int(bounds is not None)
            identity = _object_identity(element, slide["number"])
            if bounds is None:
                failures.append({"code": "unresolved-bounds", **identity})
                continue
            x, y, cx, cy = bounds
            if cx < 0 or cy < 0:
                failures.append({"bounds": list(bounds), "code": "invalid-bounds", **identity})
            elif x < 0 or y < 0 or x + cx > width or y + cy > height:
                failures.append({"bounds": list(bounds), "code": "out-of-bounds", **identity})
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX slide-size change would leave objects outside the deck canvas.",
            details={
                "failures": failures[:64],
                "failures_truncated": max(0, len(failures) - 64),
                "slide_size": dict(size),
            },
        )
    return {
        "inherited_bounds": inherited,
        "objects_checked": checked,
        "object_bounds_valid": True,
        "slides_checked": len(map_slides(package)),
    }


def _size_record(node: Element | None) -> dict[str, Any] | None:
    if node is None:
        return None
    try:
        return {
            "cx": int(node.attrib["cx"]),
            "cy": int(node.attrib["cy"]),
            "type": node.attrib.get("type", "custom"),
        }
    except (KeyError, ValueError) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Existing PPTX slide size is malformed.",
        ) from error


def _insert_slide_size(presentation: Element, node: Element) -> None:
    following = {
        "custDataLst",
        "custShowLst",
        "defaultTextStyle",
        "embeddedFontLst",
        "extLst",
        "kinsoku",
        "modifyVerifier",
        "notesSz",
        "photoAlbum",
    }
    for index, child in enumerate(presentation):
        if local_name(child.tag) in following:
            presentation.insert(index, node)
            return
    presentation.append(node)


def _inheritance_roots(package: Any, slide: dict[str, Any]) -> list[Element]:
    roots = []
    for key in ("layout", "master"):
        part = (slide.get(key) or {}).get("part")
        if part in package.parts:
            roots.append(package.xml(part))
    return roots


def _inherited_bounds(
    element: Element,
    roots: list[Element],
) -> tuple[int, int, int, int] | None:
    key = _placeholder_key(element)
    if key is None:
        return None
    for root in roots:
        try:
            candidates = drawable_elements(slide_shape_tree(root))
        except DocumentSkillsError:
            continue
        for candidate in candidates:
            if _placeholder_key(candidate) != key:
                continue
            bounds = _element_bounds(candidate)
            if bounds is not None:
                return bounds
    return None


def _placeholder_key(element: Element) -> tuple[str, str] | None:
    placeholder = next(
        (node for node in element.iter() if local_name(node.tag) == "ph"),
        None,
    )
    if placeholder is None:
        return None
    return (
        placeholder.attrib.get("type", "body"),
        placeholder.attrib.get("idx", "0"),
    )


def _element_bounds(element: Element) -> tuple[int, int, int, int] | None:
    transform = next(
        (node for node in element.iter() if local_name(node.tag) == "xfrm"),
        None,
    )
    if transform is None:
        return None
    offset = next(
        (node for node in list(transform) if local_name(node.tag) == "off"),
        None,
    )
    extent = next(
        (node for node in list(transform) if local_name(node.tag) == "ext"),
        None,
    )
    if offset is None or extent is None:
        return None
    try:
        x = int(offset.attrib["x"])
        y = int(offset.attrib["y"])
        cx = int(extent.attrib["cx"])
        cy = int(extent.attrib["cy"])
        rotation = int(transform.attrib.get("rot", "0")) / 60_000
    except (KeyError, ValueError):
        return None
    if rotation % 180 == 0:
        return x, y, cx, cy
    radians = math.radians(rotation)
    rotated_cx = abs(cx * math.cos(radians)) + abs(cy * math.sin(radians))
    rotated_cy = abs(cx * math.sin(radians)) + abs(cy * math.cos(radians))
    center_x = x + cx / 2
    center_y = y + cy / 2
    left = math.floor(center_x - rotated_cx / 2)
    top = math.floor(center_y - rotated_cy / 2)
    return left, top, math.ceil(rotated_cx), math.ceil(rotated_cy)


def _object_identity(element: Element, slide: int) -> dict[str, Any]:
    properties = next(
        (node for node in element.iter() if local_name(node.tag) == "cNvPr"),
        None,
    )
    return {
        "name": "" if properties is None else properties.attrib.get("name", ""),
        "shape_id": "" if properties is None else properties.attrib.get("id", ""),
        "slide": slide,
    }
