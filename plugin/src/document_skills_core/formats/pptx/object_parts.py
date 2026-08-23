"""Contained relationship and part mutations for PPTX object edits."""

import posixpath
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .mutation import MutablePptxPackage
from .slide_graph import relationship_part_for, _rewrite_content_types

_RELS = NS["rels"]


def RELS(tag: str) -> str:
    return f"{{{_RELS}}}{tag}"


def add_part_relationship(
    target: MutablePptxPackage,
    source_part: str,
    target_part: str,
    relationship_kind: str,
    prefix: str,
) -> str:
    root = _relationship_root(target, source_part)
    relationship_id = _next_relationship_id(root, prefix)
    SubElement(root, RELS("Relationship"), {
        "Id": relationship_id,
        "Type": (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
            f"{relationship_kind}"
        ),
        "Target": posixpath.relpath(target_part, posixpath.dirname(source_part)),
    })
    target.set_part(relationship_part_for(source_part), _xml_bytes(root))
    return relationship_id


def replace_relationship_target(
    target: MutablePptxPackage,
    source_part: str,
    relationship_id: str,
    target_part: str,
    relationship_kind: str,
) -> str | None:
    root = _relationship_root(target, source_part)
    previous = None
    for node in root.findall(RELS("Relationship")):
        if node.attrib.get("Id") != relationship_id:
            continue
        previous_relationship = next(
            (
                item
                for item in target.part_rels(source_part)
                if item.relationship_id == relationship_id
            ),
            None,
        )
        previous = (
            None
            if previous_relationship is None
            else previous_relationship.resolved_target
        )
        node.set(
            "Type",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
            f"{relationship_kind}",
        )
        node.set(
            "Target",
            posixpath.relpath(target_part, posixpath.dirname(source_part)),
        )
        node.attrib.pop("TargetMode", None)
        target.set_part(relationship_part_for(source_part), _xml_bytes(root))
        return previous
    _invalid("Selected object relationship is missing.", relationship_id=relationship_id)


def remove_relationship(
    target: MutablePptxPackage,
    source_part: str,
    relationship_id: str,
) -> str | None:
    previous = next(
        (
            item.resolved_target
            for item in target.part_rels(source_part)
            if item.relationship_id == relationship_id
        ),
        None,
    )
    root = _relationship_root(target, source_part)
    removed = False
    for node in list(root):
        if node.attrib.get("Id") == relationship_id:
            root.remove(node)
            removed = True
            break
    if not removed:
        _invalid("Selected object relationship is missing.", relationship_id=relationship_id)
    target.set_part(relationship_part_for(source_part), _xml_bytes(root))
    return previous


def remove_unreachable_dependencies(
    target: MutablePptxPackage,
    candidate_root: str | None,
) -> list[str]:
    if candidate_root is None or candidate_root not in target.parts:
        return []
    relationships = target.relationships
    candidates = _forward_dependencies(relationships, candidate_root)
    reachable = _root_reachable(relationships)
    removable = candidates - reachable
    removed: set[str] = set()
    for part in sorted(removable):
        if part in target.parts:
            target.remove_part(part)
            removed.add(part)
        rels_part = relationship_part_for(part)
        if rels_part in target.parts:
            target.remove_part(rels_part)
            removed.add(rels_part)
    if removed:
        _rewrite_content_types(target, removed=removed, additions={})
    return sorted(removed)


def register_content_types(
    target: MutablePptxPackage,
    additions: dict[str, str],
) -> None:
    if additions:
        _rewrite_content_types(target, removed=set(), additions=additions)


def next_part_index(parts: dict[str, bytes], prefix: str) -> int:
    indices = []
    for name in parts:
        if not name.startswith(prefix):
            continue
        terminal = posixpath.basename(name)
        stem = posixpath.splitext(terminal)[0]
        suffix = stem[len(posixpath.basename(prefix)):]
        if suffix.isdigit():
            indices.append(int(suffix))
    return max(indices, default=0) + 1


def require_internal_relationship(
    target: Any,
    source_part: str,
    relationship_id: str,
    relationship_kind: str,
) -> str:
    relationship = next(
        (
            item
            for item in target.part_rels(source_part)
            if item.relationship_id == relationship_id
        ),
        None,
    )
    if (
        relationship is None
        or relationship.target_mode != "Internal"
        or relationship.resolved_target is None
        or not relationship.relationship_type.endswith(f"/{relationship_kind}")
    ):
        _invalid(
            "Selected object must use a contained package relationship.",
            relationship_id=relationship_id,
            relationship_kind=relationship_kind,
        )
    return relationship.resolved_target


def _relationship_root(
    target: MutablePptxPackage,
    source_part: str,
) -> Element:
    relationship_part = relationship_part_for(source_part)
    if relationship_part not in target.parts:
        return Element(RELS("Relationships"))
    return target.xml(relationship_part)


def _next_relationship_id(root: Element, prefix: str) -> str:
    used = {node.attrib.get("Id", "") for node in root}
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


def _forward_dependencies(relationships: list[Any], root_part: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for relationship in relationships:
        if relationship.resolved_target is not None:
            adjacency.setdefault(relationship.source_part, set()).add(
                relationship.resolved_target
            )
    seen: set[str] = set()
    pending = [root_part]
    while pending:
        part = pending.pop()
        if part in seen:
            continue
        seen.add(part)
        pending.extend(adjacency.get(part, ()))
    return seen


def _root_reachable(relationships: list[Any]) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for relationship in relationships:
        if relationship.resolved_target is not None:
            adjacency.setdefault(relationship.source_part, set()).add(
                relationship.resolved_target
            )
    seen: set[str] = set()
    pending = list(adjacency.get("", ()))
    while pending:
        part = pending.pop()
        if part in seen:
            continue
        seen.add(part)
        pending.extend(adjacency.get(part, ()))
    return seen


def _xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
