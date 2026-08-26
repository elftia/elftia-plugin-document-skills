"""Bounded compatible DOCX body and relationship-graph merge planner."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES,
    WORD_MAIN,
    qn,
)
from .package import OpcPackage
from .merge_bookmarks import BookmarkMergePlanner
from .merge_comments import CommentMergePlanner
from .merge_content_controls import count_safe_merge_content_controls
from .merge_fields import count_safe_merge_fields
from .merge_notes import NoteMergePlanner
from .merge_parts import copy_relationship_target
from .merge_revisions import RevisionMergePlanner
from .merge_numbering import NUMBERING_PART, NumberingMergePlanner
from .merge_styles import STYLES_PART, StyleMergePlanner
from .relationships import relationship_map, relationship_xml_bytes
from .xml_utils import xml_bytes

DOCUMENT_RELS = "word/_rels/document.xml.rels"
_COMPATIBILITY_PARTS = (
    "word/fontTable.xml",
    "word/numbering.xml",
    "word/styles.xml",
    "word/theme/theme1.xml",
)
_RELATIONSHIP_ATTRIBUTES = {
    qn("r", "embed"),
    qn("r", "id"),
    qn("r", "link"),
}


@dataclass(frozen=True)
class MergeGraphPlan:
    changed_parts: dict[str, bytes]
    added_parts: dict[str, bytes]
    copied_body_blocks: int
    part_mappings: tuple[dict[str, str], ...]
    style_mappings: tuple[dict[str, Any], ...]
    styles_status: str
    abstract_num_mappings: tuple[dict[str, Any], ...]
    num_mappings: tuple[dict[str, Any], ...]
    numbering_status: str
    bookmark_mappings: tuple[dict[str, Any], ...]
    expected_field_count: int
    expected_content_control_count: int
    note_mappings: tuple[dict[str, Any], ...]
    expected_note_count: int
    comment_mappings: tuple[dict[str, Any], ...]
    expected_comment_count: int
    revision_mappings: tuple[dict[str, Any], ...]
    expected_revision_count: int
    move_range_mappings: tuple[dict[str, Any], ...]
    move_name_mappings: tuple[dict[str, Any], ...]
    expected_move_range_count: int
    expected_main_sha256: str
    expected_changed_hashes: dict[str, str]


def build_compatible_merge(
    base: OpcPackage,
    sources: list[OpcPackage],
    *,
    style_conflict_policy: str,
    numbering_conflict_policy: str,
) -> MergeGraphPlan:
    document = base.xml(WORD_MAIN)
    body = document.find(qn("w", "body"))
    if body is None:
        _unsafe("Base document body is missing.")
    relationship_root, relationship_is_added = _relationship_root(base)
    content_types = base.xml(CONTENT_TYPES)
    used_parts = set(base.parts)
    used_ids = {
        node.attrib.get("Id", "")
        for node in relationship_root.findall(qn("rels", "Relationship"))
    }
    drawing_id = _maximum_drawing_id(body)
    added_parts: dict[str, bytes] = {}
    mappings: list[dict[str, str]] = []
    copied_blocks = 0
    style_planner = StyleMergePlanner(base)
    numbering_planner = NumberingMergePlanner(base)
    bookmark_planner = BookmarkMergePlanner(body)
    note_planner = NoteMergePlanner(
        base,
        relationship_root,
        content_types,
        used_ids,
    )
    comment_planner = CommentMergePlanner(
        base,
        relationship_root,
        content_types,
        used_ids,
    )
    revision_planner = RevisionMergePlanner(body)
    expected_field_count = count_safe_merge_fields(body, source_index=None)
    expected_content_control_count = count_safe_merge_content_controls(
        body,
        source_index=None,
    )
    for source_index, source in enumerate(sources, start=1):
        _assert_compatible_semantic_parts(
            base,
            source,
            style_conflict_policy=style_conflict_policy,
            numbering_conflict_policy=numbering_conflict_policy,
        )
        source_document = source.xml(WORD_MAIN)
        source_body = source_document.find(qn("w", "body"))
        if source_body is None:
            _unsafe("Merge source document body is missing.")
        expected_field_count += count_safe_merge_fields(
            source_body,
            source_index=source_index,
        )
        expected_content_control_count += count_safe_merge_content_controls(
            source_body,
            source_index=source_index,
        )
        source_children, source_final = _body_parts(source_body, "source")
        _move_final_section_to_boundary(body)
        source_relationships = relationship_map(source.relationships, WORD_MAIN)
        relationship_ids: dict[str, str] = {}
        part_cache: dict[str, str] = {}
        copied = [deepcopy(child) for child in source_children]
        copied_final = deepcopy(source_final)
        note_planner.merge_source(
            source,
            source_index,
            [*copied, copied_final],
        )
        comment_planner.merge_source(
            source,
            source_index,
            [*copied, copied_final],
        )
        revision_planner.merge_source(
            source_index,
            [*copied, copied_final],
        )
        bookmark_planner.merge_source(
            source_index,
            [*copied, copied_final],
        )
        if style_conflict_policy == "rename-source":
            style_planner.merge_source(
                source,
                source_index,
                [*copied, copied_final],
            )
        if numbering_conflict_policy == "remap-source":
            numbering_planner.merge_source(
                source,
                source_index,
                [*copied, copied_final],
            )
        for node in [*copied, copied_final]:
            drawing_id = _remap_drawing_ids(node, drawing_id)
            for element in node.iter():
                for attribute in sorted(set(element.attrib) & _RELATIONSHIP_ATTRIBUTES):
                    old_id = element.attrib[attribute]
                    new_id = relationship_ids.get(old_id)
                    if new_id is None:
                        new_id, relationship_mappings = copy_relationship_target(
                            source,
                            source_relationships,
                            old_id,
                            relationship_root,
                            content_types,
                            used_ids,
                            used_parts,
                            added_parts,
                            part_cache,
                        )
                        relationship_ids[old_id] = new_id
                        mappings.extend(
                            {
                                "source_index": str(source_index),
                                **mapping,
                            }
                            for mapping in relationship_mappings
                        )
                    element.attrib[attribute] = new_id
        for child in copied:
            body.append(child)
        body.append(copied_final)
        copied_blocks += len(copied)
    document_payload = xml_bytes(document)
    changed_parts = {WORD_MAIN: document_payload}
    style_result = style_planner.finish()
    if style_result.payload is not None:
        changed_parts[STYLES_PART] = style_result.payload
    numbering_result = numbering_planner.finish()
    if numbering_result.payload is not None:
        changed_parts[NUMBERING_PART] = numbering_result.payload
    bookmark_result = bookmark_planner.finish()
    note_result = note_planner.finish()
    comment_result = comment_planner.finish()
    revision_result = revision_planner.finish()
    changed_parts.update(note_result.changed_parts)
    changed_parts.update(comment_result.changed_parts)
    added_parts.update(note_result.added_parts)
    added_parts.update(comment_result.added_parts)
    relationship_payload = relationship_xml_bytes(relationship_root)
    if relationship_is_added:
        added_parts[DOCUMENT_RELS] = relationship_payload
    elif relationship_payload != base.parts[DOCUMENT_RELS]:
        changed_parts[DOCUMENT_RELS] = relationship_payload
    content_types_payload = xml_bytes(content_types)
    if content_types_payload != base.parts[CONTENT_TYPES]:
        changed_parts[CONTENT_TYPES] = content_types_payload
    expected_changed_hashes = {
        name: sha256(payload).hexdigest()
        for name, payload in changed_parts.items()
    }
    return MergeGraphPlan(
        changed_parts,
        added_parts,
        copied_blocks,
        tuple(mappings),
        style_result.mappings,
        "remapped" if style_result.mappings else "identical",
        numbering_result.abstract_mappings,
        numbering_result.num_mappings,
        (
            "remapped"
            if numbering_result.abstract_mappings or numbering_result.num_mappings
            else "identical"
        ),
        bookmark_result.mappings,
        expected_field_count,
        expected_content_control_count,
        note_result.mappings,
        note_result.expected_count,
        comment_result.mappings,
        comment_result.expected_count,
        revision_result.mappings,
        revision_result.expected_count,
        revision_result.move_range_mappings,
        revision_result.move_name_mappings,
        revision_result.expected_move_range_count,
        sha256(document_payload).hexdigest(),
        expected_changed_hashes,
    )


def _assert_compatible_semantic_parts(
    base: OpcPackage,
    source: OpcPackage,
    *,
    style_conflict_policy: str,
    numbering_conflict_policy: str,
) -> None:
    checked = ["word/fontTable.xml", "word/theme/theme1.xml"]
    if style_conflict_policy == "require-identical":
        checked.append("word/styles.xml")
    if numbering_conflict_policy == "require-identical":
        checked.append("word/numbering.xml")
    mismatches = [
        name
        for name in checked
        if base.parts.get(name) != source.parts.get(name)
    ]
    if mismatches:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX merge requires graph-aware style or numbering conflict resolution.",
            status="enhancement_required",
            details={"mismatched_parts": mismatches},
        )


def _body_parts(body: Element, label: str) -> tuple[list[Element], Element]:
    children = list(body)
    direct_sections = [child for child in children if child.tag == qn("w", "sectPr")]
    if len(direct_sections) != 1 or children[-1] is not direct_sections[0]:
        _unsafe(f"{label.capitalize()} document final section is ambiguous.")
    return children[:-1], direct_sections[0]


def _move_final_section_to_boundary(body: Element) -> None:
    _children, final = _body_parts(body, "base")
    body.remove(final)
    boundary = Element(qn("w", "p"))
    properties = SubElement(boundary, qn("w", "pPr"))
    properties.append(final)
    body.append(boundary)


def _relationship_root(base: OpcPackage) -> tuple[Element, bool]:
    if DOCUMENT_RELS in base.parts:
        return base.xml(DOCUMENT_RELS), False
    return Element(qn("rels", "Relationships")), True


def _maximum_drawing_id(root: Element) -> int:
    return max(
        (
            int(value)
            for tag in (qn("wp", "docPr"), qn("pic", "cNvPr"))
            for node in root.iter(tag)
            if (value := node.attrib.get("id", "")).isdigit()
        ),
        default=0,
    )


def _remap_drawing_ids(root: Element, current: int) -> int:
    for tag in (qn("wp", "docPr"), qn("pic", "cNvPr")):
        for node in root.iter(tag):
            current += 1
            node.attrib["id"] = str(current)
    return current


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
