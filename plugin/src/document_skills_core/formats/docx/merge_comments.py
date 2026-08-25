"""Deterministic classic comment graph merge and id remapping."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import CONTENT_TYPES_NS, CT_COMMENTS, REL_COMMENTS, WORD_MAIN, local_name, qn
from .package import OpcPackage
from .relationships import relationship_map
from .xml_utils import xml_bytes

COMMENTS_PART = "word/comments.xml"
_EXTENDED_PARTS = {
    "word/commentsExtensible.xml",
    "word/commentsExtended.xml",
    "word/commentsIds.xml",
    "word/people.xml",
}
_UNSUPPORTED_NAMES = {
    "commentRangeEnd", "commentRangeStart", "commentReference", "del", "drawing",
    "fldChar", "fldSimple", "hyperlink", "ins", "instrText", "moveFrom", "moveTo",
    "numId", "object", "pStyle", "rStyle", "sdt",
}
_RELATIONSHIP_ATTRIBUTES = {qn("r", "embed"), qn("r", "id"), qn("r", "link")}


@dataclass(frozen=True)
class CommentMergeResult:
    changed_parts: dict[str, bytes]
    added_parts: dict[str, bytes]
    mappings: tuple[dict[str, Any], ...]
    expected_count: int


class CommentMergePlanner:
    def __init__(
        self,
        base: OpcPackage,
        relationship_root: Element,
        content_types: Element,
        used_relationship_ids: set[str],
    ) -> None:
        self.base = base
        self.relationship_root = relationship_root
        self.content_types = content_types
        self.used_relationship_ids = used_relationship_ids
        self.root = base.xml(COMMENTS_PART) if COMMENTS_PART in base.parts else None
        self.used_ids = _comment_ids(self.root, document="base")
        self.mappings: list[dict[str, Any]] = []
        self.touched = False

    def merge_source(
        self,
        source: OpcPackage,
        source_index: int,
        copied_nodes: list[Element],
    ) -> None:
        anchors = _source_anchor_nodes(copied_nodes, source_index)
        if not anchors:
            return
        extended = sorted(_EXTENDED_PARTS.intersection(source.parts))
        if extended:
            _unsupported(
                "DOCX merge does not support threaded or extended comment parts.",
                source_index=source_index,
                parts=extended,
            )
        if COMMENTS_PART not in source.parts or not _has_comment_relationship(source):
            _unsafe(
                "DOCX merge comment anchor has no bound comments part.",
                source_index=source_index,
            )
        if any(item.source_part == COMMENTS_PART for item in source.relationships):
            _unsupported(
                "DOCX merge comments part has a relationship graph.",
                source_index=source_index,
            )
        comments = _comment_map(source.xml(COMMENTS_PART), source_index)
        target_root = self._ensure_root()
        for source_id, nodes in anchors.items():
            comment = comments.get(source_id)
            if comment is None:
                _unsafe(
                    "DOCX merge comment anchor target is missing.",
                    source_index=source_index,
                    source_id=source_id,
                )
            _assert_supported_comment(comment, source_index, source_id)
            target_id = _allocate_comment_id(self.used_ids, int(source_id))
            copied = deepcopy(comment)
            copied.attrib[qn("w", "id")] = target_id
            target_root.append(copied)
            for node in nodes:
                node.attrib[qn("w", "id")] = target_id
            self.mappings.append(
                {
                    "source_id": source_id,
                    "source_index": source_index,
                    "target_id": target_id,
                }
            )
        self.touched = True

    def finish(self) -> CommentMergeResult:
        changed: dict[str, bytes] = {}
        added: dict[str, bytes] = {}
        if self.touched:
            assert self.root is not None
            payload = xml_bytes(self.root)
            if COMMENTS_PART in self.base.parts:
                changed[COMMENTS_PART] = payload
            else:
                added[COMMENTS_PART] = payload
        return CommentMergeResult(changed, added, tuple(self.mappings), len(self.used_ids))

    def _ensure_root(self) -> Element:
        if self.root is None:
            self.root = Element(qn("w", "comments"))
        if not any(
            node.attrib.get("Type") == REL_COMMENTS
            for node in self.relationship_root.findall(qn("rels", "Relationship"))
        ):
            SubElement(
                self.relationship_root,
                qn("rels", "Relationship"),
                {
                    "Id": _allocate_relationship_id(self.used_relationship_ids),
                    "Type": REL_COMMENTS,
                    "Target": "comments.xml",
                },
            )
        if not any(
            node.attrib.get("PartName") == f"/{COMMENTS_PART}"
            for node in self.content_types.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        ):
            SubElement(
                self.content_types,
                f"{{{CONTENT_TYPES_NS}}}Override",
                {"PartName": f"/{COMMENTS_PART}", "ContentType": CT_COMMENTS},
            )
        return self.root


def count_comment_definitions(package: OpcPackage) -> int:
    root = package.xml(COMMENTS_PART) if COMMENTS_PART in package.parts else None
    return len(_comment_ids(root, document="candidate"))


def _source_anchor_nodes(
    copied_nodes: list[Element],
    source_index: int,
) -> dict[str, list[Element]]:
    names = ("commentRangeStart", "commentRangeEnd", "commentReference")
    by_kind: dict[str, dict[str, list[Element]]] = {name: {} for name in names}
    for name, records in by_kind.items():
        for parent in copied_nodes:
            for node in parent.iter(qn("w", name)):
                value = node.attrib.get(qn("w", "id"), "")
                if not value.isdigit():
                    _unsafe(
                        "DOCX merge comment anchor id is invalid.",
                        source_index=source_index,
                        source_id=value,
                    )
                records.setdefault(value, []).append(node)
    ids = set().union(*(set(records) for records in by_kind.values()))
    for source_id in sorted(ids, key=int):
        counts = {name: len(records.get(source_id, [])) for name, records in by_kind.items()}
        if counts != {
            "commentRangeStart": 1,
            "commentRangeEnd": 1,
            "commentReference": 1,
        }:
            _unsupported(
                "DOCX merge requires one classic range/reference triple per comment.",
                source_index=source_index,
                source_id=source_id,
                counts=counts,
            )
    return {
        source_id: [by_kind[name][source_id][0] for name in names]
        for source_id in sorted(ids, key=int)
    }


def _comment_ids(root: Element | None, *, document: str) -> set[int]:
    if root is None:
        return set()
    result: set[int] = set()
    for comment in root.findall(qn("w", "comment")):
        value = comment.attrib.get(qn("w", "id"), "")
        if not value.isdigit() or int(value) in result:
            _unsafe("DOCX comment id is invalid or duplicated.", document=document, comment_id=value)
        result.add(int(value))
    return result


def _comment_map(root: Element, source_index: int) -> dict[str, Element]:
    result: dict[str, Element] = {}
    for comment in root.findall(qn("w", "comment")):
        value = comment.attrib.get(qn("w", "id"), "")
        if not value.isdigit() or value in result:
            _unsafe(
                "DOCX merge source comment id is invalid or duplicated.",
                source_index=source_index,
                source_id=value,
            )
        result[value] = comment
    return result


def _assert_supported_comment(comment: Element, source_index: int, source_id: str) -> None:
    structures = sorted(
        {
            local_name(node.tag)
            for node in comment.iter()
            if local_name(node.tag) in _UNSUPPORTED_NAMES
        }
    )
    relationship_bound = any(
        set(node.attrib).intersection(_RELATIONSHIP_ATTRIBUTES)
        for node in comment.iter()
    )
    if structures or relationship_bound:
        _unsupported(
            "DOCX merge supports only self-contained classic comment XML.",
            source_index=source_index,
            source_id=source_id,
            structures=structures,
            relationship_bound=relationship_bound,
        )


def _has_comment_relationship(source: OpcPackage) -> bool:
    return any(
        relationship.relationship_type == REL_COMMENTS
        and relationship.resolved_target == COMMENTS_PART
        for relationship in relationship_map(source.relationships, WORD_MAIN).values()
    )


def _allocate_comment_id(used: set[int], preferred: int) -> str:
    candidate = preferred
    if candidate in used:
        candidate = 0
        while candidate in used:
            candidate += 1
    used.add(candidate)
    return str(candidate)


def _allocate_relationship_id(used: set[str]) -> str:
    for index in range(1, 10_001):
        candidate = f"rIdMergeComment{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "Comment relationship id space is exhausted.")


def _unsupported(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
