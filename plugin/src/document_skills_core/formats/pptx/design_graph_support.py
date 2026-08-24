"""Registry, selector, and bounded-frame helpers for PPTX design graph edits."""

import posixpath
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, PRESENTATION_MAIN
from .design_graph_xml import xml_bytes
from .mutation import MutablePptxPackage
from .projection import project_slide_size
from .slide_graph import (
    _next_relationship_id,
    relationship_part_for,
)

_P = NS["p"]
_R = NS["r"]
_RELS = NS["rels"]


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def R(tag: str) -> str:
    return f"{{{_R}}}{tag}"


def RELS(tag: str) -> str:
    return f"{{{_RELS}}}{tag}"


def attach_layout(target: MutablePptxPackage, master: str, layout: str) -> None:
    rels_part = relationship_part_for(master)
    rels = target.xml(rels_part)
    relationship_id = _next_relationship_id(rels, "rIdLayout")
    SubElement(rels, RELS("Relationship"), {
        "Id": relationship_id,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
        "Target": posixpath.relpath(layout, posixpath.dirname(master)),
    })
    target.set_part(rels_part, xml_bytes(rels))
    root = target.xml(master)
    identifiers = root.find(P("sldLayoutIdLst"))
    if identifiers is None:
        identifiers = SubElement(root, P("sldLayoutIdLst"))
    numeric = [int(node.attrib["id"]) for node in identifiers if node.attrib.get("id", "").isdigit()]
    SubElement(
        identifiers,
        P("sldLayoutId"),
        {"id": str(max(numeric, default=2_147_483_648) + 1), R("id"): relationship_id},
    )
    target.set_part(master, xml_bytes(root))


def detach_layout(target: MutablePptxPackage, master: str, relationship_id: str) -> None:
    rels_part = relationship_part_for(master)
    rels = target.xml(rels_part)
    for node in list(rels):
        if node.attrib.get("Id") == relationship_id:
            rels.remove(node)
    target.set_part(rels_part, xml_bytes(rels))
    root = target.xml(master)
    identifiers = root.find(P("sldLayoutIdLst"))
    if identifiers is not None:
        for node in list(identifiers):
            if node.attrib.get(R("id")) == relationship_id:
                identifiers.remove(node)
    target.set_part(master, xml_bytes(root))


def register_master(target: MutablePptxPackage, master: str) -> None:
    rels = target.xml("ppt/_rels/presentation.xml.rels")
    relationship_id = _next_relationship_id(rels, "rIdMaster")
    SubElement(rels, RELS("Relationship"), {
        "Id": relationship_id,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
        "Target": posixpath.relpath(master, "ppt"),
    })
    target.set_part("ppt/_rels/presentation.xml.rels", xml_bytes(rels))
    presentation = target.xml(PRESENTATION_MAIN)
    identifiers = presentation.find(P("sldMasterIdLst"))
    if identifiers is None:
        identifiers = Element(P("sldMasterIdLst"))
        presentation.insert(0, identifiers)
    numeric = [int(node.attrib["id"]) for node in identifiers if node.attrib.get("id", "").isdigit()]
    SubElement(
        identifiers,
        P("sldMasterId"),
        {"id": str(max(numeric, default=2_147_483_647) + 1), R("id"): relationship_id},
    )
    target.set_part(PRESENTATION_MAIN, xml_bytes(presentation))


def remove_master_registration(target: MutablePptxPackage, relationship_id: str) -> None:
    rels = target.xml("ppt/_rels/presentation.xml.rels")
    for node in list(rels):
        if node.attrib.get("Id") == relationship_id:
            rels.remove(node)
    target.set_part("ppt/_rels/presentation.xml.rels", xml_bytes(rels))
    presentation = target.xml(PRESENTATION_MAIN)
    identifiers = presentation.find(P("sldMasterIdLst"))
    if identifiers is not None:
        for node in list(identifiers):
            if node.attrib.get(R("id")) == relationship_id:
                identifiers.remove(node)
    target.set_part(PRESENTATION_MAIN, xml_bytes(presentation))


def validate_layout_frames(value: dict[str, Any], width: int, height: int) -> None:
    items = list(value["placeholders"])
    items.extend(value[key] for key in ("date", "footer", "slide_number") if value[key]["enabled"])
    failures = []
    for index, item in enumerate(items):
        frame = item["frame"]
        if frame["x"] + frame["cx"] > width or frame["y"] + frame["cy"] > height:
            failures.append({"frame": frame, "index": index})
    if failures:
        invalid("Layout placeholder frame exceeds the deck slide size.", failures=failures)


def slide_dimensions(target: MutablePptxPackage) -> tuple[int, int]:
    size = project_slide_size(target)
    if size is None:
        invalid("Presentation has no deck slide size.")
    try:
        return int(size["cx"]), int(size["cy"])
    except (KeyError, ValueError) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Presentation slide size is malformed.",
        ) from error


def remove_parts(target: MutablePptxPackage, parts: set[str]) -> set[str]:
    removed = set()
    for part in sorted(parts):
        if part in target.parts:
            target.remove_part(part)
            removed.add(part)
        rels = relationship_part_for(part)
        if rels in target.parts:
            target.remove_part(rels)
            removed.add(rels)
    return removed


def require_part(target: MutablePptxPackage, part: str, content_type: str) -> None:
    if part not in target.parts or target.content_type_for(part) != content_type:
        invalid("Selected design part does not exist with the required type.", part=part)


def invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
