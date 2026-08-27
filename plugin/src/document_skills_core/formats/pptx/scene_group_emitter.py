"""Hierarchical group traversal shared by HTML and SVG scene emission."""

import hashlib
from typing import Any, Callable
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS

_P = NS["p"]
_A = NS["a"]


def emit_scene_objects(
    tree: Element,
    items: tuple[dict[str, Any], ...],
    *,
    slide_index: int,
    emit_leaf: Callable[[Element, dict[str, Any], int, str | None], None],
    geometry: Callable[[dict[str, Any]], dict[str, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    by_id = {item["source_id"]: item for item in items}
    if len(by_id) != len(items):
        _invalid("Scene group identities are duplicated.")
    for item in items:
        parent_id = item.get("parent_source_id")
        if parent_id is not None:
            parent = by_id.get(parent_id)
            if parent is None or parent.get("kind") != "group":
                _invalid("Scene child references a missing non-group parent.")
        by_parent.setdefault(parent_id, []).append(item)
    manifest: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    next_shape_id = 2
    active: set[str] = set()

    def walk(parent: Element, item: dict[str, Any]) -> None:
        nonlocal next_shape_id
        source_id = item["source_id"]
        if source_id in active:
            _invalid("Scene group hierarchy contains a cycle.")
        active.add(source_id)
        shape_id = next_shape_id
        next_shape_id += 1
        if item["kind"] == "group":
            target = _group(parent, item, shape_id, geometry(item))
            relationship_id = None
        else:
            relationship_id = None
            if item.get("outcome") == "rasterized" or item["kind"] == "image":
                index = 1 + sum(record["kind"] == "image" for record in relationships)
                relationship_id = f"rIdImage{index}"
                relationships.append({
                    "asset_id": item["asset_id"],
                    "id": relationship_id,
                    "kind": "image",
                })
            elif item["kind"] == "chart":
                index = 1 + sum(record["kind"] == "chart" for record in relationships)
                relationship_id = f"rIdChart{index}"
                relationships.append({
                    "id": relationship_id,
                    "kind": "chart",
                    "source_id": source_id,
                })
            emit_leaf(parent, item, shape_id, relationship_id)
            target = parent
        emitted_kind = (
            "image"
            if item.get("outcome") == "rasterized" or item["kind"] == "image"
            else item["kind"]
        )
        manifest.append({
            "slide": slide_index,
            "source_id": source_id,
            "shape_id": shape_id,
            "z_order": len(manifest),
            "kind": emitted_kind,
            "outcome": item["outcome"],
            "asset_sha256": item.get("asset_id"),
            "text_sha256": hashlib.sha256(item.get("text", "").encode("utf-8")).hexdigest(),
            "geometry": geometry(item),
            "parent_source_id": item.get("parent_source_id"),
        })
        for child in by_parent.get(source_id, []):
            walk(target, child)
        active.remove(source_id)

    for root in by_parent.get(None, []):
        walk(tree, root)
    if len(manifest) != len(items):
        _invalid("Scene group hierarchy contains unreachable objects.")
    return manifest, relationships


def _group(
    parent: Element,
    item: dict[str, Any],
    shape_id: int,
    geometry: dict[str, int],
) -> Element:
    group = SubElement(parent, f"{{{_P}}}grpSp")
    non_visual = SubElement(group, f"{{{_P}}}nvGrpSpPr")
    SubElement(
        non_visual,
        f"{{{_P}}}cNvPr",
        {"id": str(shape_id), "name": item["source_id"][:80]},
    )
    SubElement(non_visual, f"{{{_P}}}cNvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    properties = SubElement(group, f"{{{_P}}}grpSpPr")
    transform = SubElement(properties, f"{{{_A}}}xfrm")
    for tag, attributes in (
        ("off", {"x": str(geometry["x"]), "y": str(geometry["y"])}),
        ("ext", {"cx": str(geometry["cx"]), "cy": str(geometry["cy"])}),
        ("chOff", {"x": str(geometry["x"]), "y": str(geometry["y"])}),
        ("chExt", {"cx": str(geometry["cx"]), "cy": str(geometry["cy"])}),
    ):
        SubElement(transform, f"{{{_A}}}{tag}", attributes)
    return group


def _invalid(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message)


__all__ = ["emit_scene_objects"]
