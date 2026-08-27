"""Stable identity and geometry projection for PPTX scene export."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element

from .constants import NS, local_name
from .scene_export_models import SceneProjectionUnsupported

_P = NS["p"]
_A = NS["a"]
_R = NS["r"]


def _p(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{_R}}}{tag}"


def ordered_slides(package: Any) -> list[dict[str, str]]:
    presentation = package.xml("ppt/presentation.xml")
    relationships = {
        item.relationship_id: item
        for item in package.part_rels("ppt/presentation.xml")
    }
    result = []
    slide_list = presentation.find(_p("sldIdLst"))
    if slide_list is None:
        return result
    for item in slide_list.findall(_p("sldId")):
        relationship = relationships.get(item.attrib.get(_r("id"), ""))
        if relationship is not None and relationship.resolved_target in package.parts:
            result.append({
                "numeric_id": item.attrib.get("id", "unknown"),
                "part": relationship.resolved_target,
            })
    return result


def source_identity(element: Element) -> tuple[str | None, str]:
    non_visual = next(
        (node for node in element.iter() if local_name(node.tag) == "cNvPr"),
        None,
    )
    if non_visual is None:
        return None, ""
    return non_visual.attrib.get("id"), non_visual.attrib.get("name", "")


def geometry(
    element: Element,
    transform: tuple[float, float, float, float],
) -> dict[str, float] | None:
    tag = local_name(element.tag)
    if tag == "grpSp":
        xfrm = element.find(f"{_p('grpSpPr')}/{_a('xfrm')}")
    elif tag == "graphicFrame":
        xfrm = element.find(_p("xfrm"))
    else:
        xfrm = element.find(f"{_p('spPr')}/{_a('xfrm')}")
    if xfrm is None:
        return None
    offset = xfrm.find(_a("off"))
    extent = xfrm.find(_a("ext"))
    if offset is None or extent is None:
        return None
    try:
        x = float(offset.attrib["x"])
        y = float(offset.attrib["y"])
        width = float(extent.attrib["cx"])
        height = float(extent.attrib["cy"])
    except (KeyError, ValueError):
        return None
    sx, sy, tx, ty = transform
    return {
        "height": max(1.0, height * sy),
        "width": max(1.0, width * sx),
        "x": x * sx + tx,
        "y": y * sy + ty,
    }


def group_transform(
    element: Element,
    parent: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    xfrm = element.find(f"{_p('grpSpPr')}/{_a('xfrm')}")
    if xfrm is None:
        raise SceneProjectionUnsupported("missing-group-transform")
    offset, extent = xfrm.find(_a("off")), xfrm.find(_a("ext"))
    child_offset, child_extent = xfrm.find(_a("chOff")), xfrm.find(_a("chExt"))
    if any(value is None for value in (offset, extent, child_offset, child_extent)):
        raise SceneProjectionUnsupported("incomplete-group-transform")
    try:
        ratio_x = float(extent.attrib["cx"]) / float(child_extent.attrib["cx"])
        ratio_y = float(extent.attrib["cy"]) / float(child_extent.attrib["cy"])
        parent_sx, parent_sy, parent_tx, parent_ty = parent
        return (
            parent_sx * ratio_x,
            parent_sy * ratio_y,
            parent_tx + parent_sx * (
                float(offset.attrib["x"])
                - float(child_offset.attrib["x"]) * ratio_x
            ),
            parent_ty + parent_sy * (
                float(offset.attrib["y"])
                - float(child_offset.attrib["y"]) * ratio_y
            ),
        )
    except (KeyError, ValueError, ZeroDivisionError) as error:
        raise SceneProjectionUnsupported("invalid-group-transform") from error


def object_base(
    object_id: str,
    value: dict[str, float],
    z_order: int,
    *,
    parent_id: str | None,
    group_id: str | None,
    editability: str = "native",
    unsupported: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bounds": {
            key: round(value[key], 6)
            for key in ("x", "y", "width", "height")
        },
        "degradationBudget": {"allowedFallbacks": [], "maximum": "none"},
        "editability": editability,
        "materializationDiagnostics": [],
        "nativeTarget": "both",
        "objectId": object_id,
        "refs": {"licenseStatus": "not_evaluated"},
        "unsupportedFeatures": unsupported or [],
        "zOrder": z_order,
    }
    if parent_id is not None:
        result["parentId"] = parent_id
    if group_id is not None:
        result["groupId"] = group_id
    return result


def pixels(
    value: dict[str, float],
    slide_cx: int,
    slide_cy: int,
) -> dict[str, float]:
    return {
        "height": value["height"] / slide_cy * 1080,
        "width": value["width"] / slide_cx * 1920,
        "x": value["x"] / slide_cx * 1920,
        "y": value["y"] / slide_cy * 1080,
    }


__all__ = [
    "geometry",
    "group_transform",
    "object_base",
    "ordered_slides",
    "pixels",
    "source_identity",
]
