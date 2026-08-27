"""OPC relationship and content-type helpers for legacy XLSX comments."""

from __future__ import annotations

import posixpath
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    NS,
    REL_VML_DRAWING,
)

_MAIN_NS = NS["main"]
_REL_NS = NS["rels"]
_COMMENTS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"
)
_VML_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.vmlDrawing"


def worksheet_relationships(context: Any, sheet_part: str) -> tuple[str, Element]:
    rels_part = relationship_part(sheet_part)
    if rels_part in context.package.parts or rels_part in context.added:
        return rels_part, context.root(rels_part)
    root = Element(f"{{{_REL_NS}}}Relationships")
    context.add_root(rels_part, root)
    return rels_part, root


def single_relationship(root: Element, relationship_type: str) -> Element | None:
    matches = [
        item
        for item in root.findall(f"{{{_REL_NS}}}Relationship")
        if item.attrib.get("Type") == relationship_type
    ]
    if len(matches) > 1:
        _invalid("Worksheet contains ambiguous comment relationships.")
    return matches[0] if matches else None


def legacy_vml_relationship(worksheet: Element, root: Element) -> Element | None:
    legacy = worksheet.find(f"{{{_MAIN_NS}}}legacyDrawing")
    if legacy is None:
        return None
    relationship_id = legacy.attrib.get(f"{{{NS['r']}}}id", "")
    relationship = next(
        (
            item
            for item in root.findall(f"{{{_REL_NS}}}Relationship")
            if item.attrib.get("Id") == relationship_id
        ),
        None,
    )
    if relationship is None or relationship.attrib.get("Type") != REL_VML_DRAWING:
        _invalid("Worksheet legacyDrawing relationship is invalid.")
    return relationship


def add_comment_content_types(context: Any, comment_part: str) -> None:
    root = context.root(CONTENT_TYPES)
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": f"/{comment_part}", "ContentType": _COMMENTS_CONTENT_TYPE},
    )
    if not any(
        item.attrib.get("Extension", "").casefold() == "vml"
        for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Default")
    ):
        root.insert(
            0,
            Element(
                f"{{{CONTENT_TYPES_NS}}}Default",
                {"Extension": "vml", "ContentType": _VML_CONTENT_TYPE},
            ),
        )
    context.mark_dirty(CONTENT_TYPES)


def remove_comment_content_types(
    context: Any,
    comment_part: str,
    vml_part: str,
    *,
    remove_vml: bool,
) -> None:
    root = context.root(CONTENT_TYPES)
    override = next(
        (
            item
            for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
            if item.attrib.get("PartName", "").lstrip("/") == comment_part
        ),
        None,
    )
    if override is None:
        _invalid("Comment content-type override is missing.", part=comment_part)
    root.remove(override)
    remaining_vml = not remove_vml or any(
        part.casefold().endswith(".vml")
        and part != vml_part
        and part not in context.removed
        for part in {*context.package.parts, *context.added}
    )
    if not remaining_vml:
        default = next(
            (
                item
                for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Default")
                if item.attrib.get("Extension", "").casefold() == "vml"
            ),
            None,
        )
        if default is not None:
            root.remove(default)
    context.mark_dirty(CONTENT_TYPES)


def insert_legacy_drawing(worksheet: Element, element: Element) -> None:
    table_parts = worksheet.find(f"{{{_MAIN_NS}}}tableParts")
    ext = worksheet.find(f"{{{_MAIN_NS}}}extLst")
    following = table_parts if table_parts is not None else ext
    index = list(worksheet).index(following) if following is not None else len(worksheet)
    worksheet.insert(index, element)


def next_comment_parts(context: Any) -> tuple[str, str]:
    used = {*context.package.parts, *context.added}
    index = 1
    while (
        f"xl/comments{index}.xml" in used
        or f"xl/drawings/commentsDrawing{index}.vml" in used
    ):
        index += 1
    return f"xl/comments{index}.xml", f"xl/drawings/commentsDrawing{index}.vml"


def next_relationship_id(root: Element) -> str:
    used = {
        item.attrib.get("Id", "")
        for item in root.findall(f"{{{_REL_NS}}}Relationship")
    }
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def next_vml_shape_id(root: Element) -> int:
    ids = []
    for child in root:
        value = child.attrib.get("id", "")
        suffix = value.removeprefix("_x0000_s")
        if suffix.isdigit():
            ids.append(int(suffix))
    return max(ids, default=1024) + 1


def resolve_target(source_part: str, target: str) -> str:
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(source_part), target)
    ).lstrip("/")


def relationship_part(part: str) -> str:
    directory, filename = part.rsplit("/", 1)
    return f"{directory}/_rels/{filename}.rels"


def relative_target(source_part: str, target_part: str) -> str:
    return posixpath.relpath(target_part, posixpath.dirname(source_part))


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
