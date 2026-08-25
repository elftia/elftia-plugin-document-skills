"""Deterministic relationship target and part allocation for DOCX merge."""

import posixpath
from pathlib import PurePosixPath
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES_NS,
    REL_FOOTER,
    REL_HEADER,
    REL_IMAGE,
    WORD_MAIN,
    qn,
)
from .package import OpcPackage
from .relationships import relationship_xml_bytes
from .xml_utils import xml_bytes

_COPIED_RELATIONSHIP_TYPES = {REL_FOOTER, REL_HEADER, REL_IMAGE}


def copy_relationship_target(
    source: OpcPackage,
    relationships: dict[str, Any],
    old_id: str,
    relationship_root: Element,
    content_types: Element,
    used_ids: set[str],
    used_parts: set[str],
    added_parts: dict[str, bytes],
    part_cache: dict[str, str],
) -> tuple[str, tuple[dict[str, str], ...]]:
    relationship = relationships.get(old_id)
    if (
        relationship is None
        or relationship.target_mode != "Internal"
        or relationship.relationship_type not in _COPIED_RELATIONSHIP_TYPES
        or relationship.resolved_target is None
    ):
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX merge encountered an unsupported body relationship.",
            status="enhancement_required",
            details={"relationship_id": old_id},
        )
    mappings: list[dict[str, str]] = []
    target = relationship.resolved_target
    new_target = _copy_part_graph(
        source,
        target,
        content_types,
        used_parts,
        added_parts,
        part_cache,
        mappings,
        trail=(),
    )
    new_id = _allocate_relationship_id(used_ids)
    SubElement(
        relationship_root,
        qn("rels", "Relationship"),
        {
            "Id": new_id,
            "Type": relationship.relationship_type,
            "Target": posixpath.relpath(new_target, posixpath.dirname(WORD_MAIN)),
        },
    )
    mappings.insert(
        0,
        {
            "relationship_id": old_id,
            "new_relationship_id": new_id,
            "source_part": target,
            "target_part": new_target,
        },
    )
    return new_id, tuple(mappings)


def _copy_part_graph(
    source: OpcPackage,
    target: str,
    content_types: Element,
    used_parts: set[str],
    added_parts: dict[str, bytes],
    part_cache: dict[str, str],
    mappings: list[dict[str, str]],
    *,
    trail: tuple[str, ...],
) -> str:
    cached = part_cache.get(target)
    if cached is not None:
        return cached
    if target in trail or len(trail) >= 16:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX merge relationship graph is cyclic or too deep.",
            status="enhancement_required",
            details={"target_part": target},
        )
    nested = sorted(
        (item for item in source.relationships if item.source_part == target),
        key=lambda item: item.relationship_id,
    )
    new_target = _allocate_part_name(target, used_parts)
    part_cache[target] = new_target
    payload = source.parts[target]
    if nested:
        root = source.xml(target)
        relationship_root = Element(qn("rels", "Relationships"))
        nested_used_ids: set[str] = set()
        nested_ids: dict[str, str] = {}
        for relationship in nested:
            if (
                relationship.target_mode != "Internal"
                or relationship.relationship_type != REL_IMAGE
                or relationship.resolved_target is None
            ):
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "DOCX merge nested graph supports only internal image relationships.",
                    status="enhancement_required",
                    details={
                        "source_part": target,
                        "relationship_id": relationship.relationship_id,
                    },
                )
            copied_target = _copy_part_graph(
                source,
                relationship.resolved_target,
                content_types,
                used_parts,
                added_parts,
                part_cache,
                mappings,
                trail=(*trail, target),
            )
            new_id = _allocate_relationship_id(nested_used_ids)
            nested_ids[relationship.relationship_id] = new_id
            SubElement(
                relationship_root,
                qn("rels", "Relationship"),
                {
                    "Id": new_id,
                    "Type": relationship.relationship_type,
                    "Target": posixpath.relpath(
                        copied_target,
                        posixpath.dirname(new_target),
                    ),
                },
            )
            mappings.append(
                {
                    "relationship_id": relationship.relationship_id,
                    "new_relationship_id": new_id,
                    "source_part": relationship.resolved_target,
                    "target_part": copied_target,
                }
            )
        _rewrite_relationship_attributes(root, nested_ids, target)
        payload = xml_bytes(root)
        relationship_part = _relationship_part_name(new_target)
        if relationship_part in used_parts:
            _unsafe(
                "DOCX merge relationship part collides.",
                part=relationship_part,
            )
        used_parts.add(relationship_part)
        added_parts[relationship_part] = relationship_xml_bytes(relationship_root)
    content_type = source.content_type_for(target)
    if content_type is None:
        _unsafe("Merge relationship target has no content type.", part=target)
    added_parts[new_target] = payload
    _add_content_type(content_types, new_target, content_type)
    return new_target


def _rewrite_relationship_attributes(
    root: Element,
    relationship_ids: dict[str, str],
    source_part: str,
) -> None:
    relationship_attributes = {
        qn("r", "embed"),
        qn("r", "id"),
        qn("r", "link"),
    }
    for element in root.iter():
        for attribute in sorted(set(element.attrib) & relationship_attributes):
            old_id = element.attrib[attribute]
            if old_id not in relationship_ids:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "DOCX merge XML contains an unbound nested relationship id.",
                    status="enhancement_required",
                    details={"source_part": source_part, "relationship_id": old_id},
                )
            element.attrib[attribute] = relationship_ids[old_id]


def _relationship_part_name(source_part: str) -> str:
    path = PurePosixPath(source_part)
    return (path.parent / "_rels" / f"{path.name}.rels").as_posix()


def _allocate_part_name(source: str, used: set[str]) -> str:
    path = PurePosixPath(source)
    stem = re.sub(r"\d+$", "", path.stem) or "part"
    for index in range(1, 10_001):
        candidate = (path.parent / f"{stem}Merge{index}{path.suffix}").as_posix()
        if candidate not in used and _relationship_part_name(candidate) not in used:
            used.add(candidate)
            return candidate
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX merge part id space is exhausted.",
    )


def _allocate_relationship_id(used: set[str]) -> str:
    for index in range(1, 10_001):
        candidate = f"rIdMerge{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX merge relationship id space is exhausted.",
    )


def _add_content_type(root: Element, part: str, content_type: str) -> None:
    part_name = f"/{part}"
    if any(
        node.attrib.get("PartName") == part_name
        for node in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
    ):
        _unsafe("DOCX merge content-type target collides.", part=part)
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": part_name, "ContentType": content_type},
    )


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
