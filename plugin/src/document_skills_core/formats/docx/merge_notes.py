"""Deterministic footnote/endnote part merge and reference-id remapping."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES_NS,
    CT_ENDNOTES,
    CT_FOOTNOTES,
    REL_ENDNOTES,
    REL_FOOTNOTES,
    WORD_MAIN,
    local_name,
    qn,
)
from .package import OpcPackage
from .relationships import relationship_map
from .xml_utils import xml_bytes

_CONFIG = {
    "footnote": ("word/footnotes.xml", REL_FOOTNOTES, CT_FOOTNOTES),
    "endnote": ("word/endnotes.xml", REL_ENDNOTES, CT_ENDNOTES),
}
_UNSUPPORTED_NAMES = {
    "commentRangeEnd",
    "commentRangeStart",
    "commentReference",
    "del",
    "drawing",
    "fldChar",
    "fldSimple",
    "hyperlink",
    "ins",
    "instrText",
    "moveFrom",
    "moveTo",
    "numId",
    "object",
    "pStyle",
    "rStyle",
    "sdt",
}
_RELATIONSHIP_ATTRIBUTES = {qn("r", "embed"), qn("r", "id"), qn("r", "link")}


@dataclass(frozen=True)
class NoteMergeResult:
    changed_parts: dict[str, bytes]
    added_parts: dict[str, bytes]
    mappings: tuple[dict[str, Any], ...]
    expected_count: int


class NoteMergePlanner:
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
        self.roots = {
            kind: base.xml(part) if part in base.parts else None
            for kind, (part, _relationship, _content_type) in _CONFIG.items()
        }
        self.used_note_ids = {
            kind: _positive_note_ids(root, kind)
            for kind, root in self.roots.items()
        }
        self.mappings: list[dict[str, Any]] = []
        self.touched: set[str] = set()

    def merge_source(
        self,
        source: OpcPackage,
        source_index: int,
        copied_nodes: list[Element],
    ) -> None:
        for kind, (part, relationship_type, _content_type) in _CONFIG.items():
            references = [
                reference
                for node in copied_nodes
                for reference in node.iter(qn("w", f"{kind}Reference"))
            ]
            if not references:
                continue
            source_root = source.xml(part) if part in source.parts else None
            if source_root is None or not _has_document_relationship(
                source,
                relationship_type,
                part,
            ):
                _unsafe(
                    "DOCX merge note reference has no bound note part.",
                    source_index=source_index,
                    kind=kind,
                )
            if any(item.source_part == part for item in source.relationships):
                _unsupported(
                    "DOCX merge note part has a relationship graph.",
                    source_index=source_index,
                    kind=kind,
                )
            notes = _note_map(source_root, kind, source_index)
            target_root = self._ensure_root(kind)
            remapped: dict[str, str] = {}
            for reference in references:
                source_id = reference.attrib.get(qn("w", "id"), "")
                if not source_id.isdigit() or int(source_id) <= 0:
                    _unsafe(
                        "DOCX merge note reference id is invalid.",
                        source_index=source_index,
                        kind=kind,
                        source_id=source_id,
                    )
                target_id = remapped.get(source_id)
                if target_id is None:
                    note = notes.get(source_id)
                    if note is None:
                        _unsafe(
                            "DOCX merge note reference target is missing.",
                            source_index=source_index,
                            kind=kind,
                            source_id=source_id,
                        )
                    _assert_supported_note(note, source_index, kind, source_id)
                    target_id = _allocate_note_id(
                        self.used_note_ids[kind],
                        int(source_id),
                    )
                    copied_note = deepcopy(note)
                    copied_note.attrib[qn("w", "id")] = target_id
                    target_root.append(copied_note)
                    remapped[source_id] = target_id
                    self.mappings.append(
                        {
                            "kind": kind,
                            "source_id": source_id,
                            "source_index": source_index,
                            "target_id": target_id,
                        }
                    )
                reference.attrib[qn("w", "id")] = target_id
            self.touched.add(kind)

    def finish(self) -> NoteMergeResult:
        changed: dict[str, bytes] = {}
        added: dict[str, bytes] = {}
        for kind in sorted(self.touched):
            part = _CONFIG[kind][0]
            root = self.roots[kind]
            assert root is not None
            payload = xml_bytes(root)
            if part in self.base.parts:
                changed[part] = payload
            else:
                added[part] = payload
        return NoteMergeResult(
            changed,
            added,
            tuple(self.mappings),
            sum(len(ids) for ids in self.used_note_ids.values()),
        )

    def _ensure_root(self, kind: str) -> Element:
        root = self.roots[kind]
        if root is None:
            root = _new_notes_root(kind)
            self.roots[kind] = root
        part, relationship_type, content_type = _CONFIG[kind]
        if not any(
            node.attrib.get("Type") == relationship_type
            for node in self.relationship_root.findall(qn("rels", "Relationship"))
        ):
            relationship_id = _allocate_relationship_id(self.used_relationship_ids)
            SubElement(
                self.relationship_root,
                qn("rels", "Relationship"),
                {
                    "Id": relationship_id,
                    "Type": relationship_type,
                    "Target": part.removeprefix("word/"),
                },
            )
        part_name = f"/{part}"
        if not any(
            node.attrib.get("PartName") == part_name
            for node in self.content_types.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        ):
            SubElement(
                self.content_types,
                f"{{{CONTENT_TYPES_NS}}}Override",
                {"PartName": part_name, "ContentType": content_type},
            )
        return root


def _positive_note_ids(root: Element | None, kind: str) -> set[int]:
    if root is None:
        return set()
    result: set[int] = set()
    for note in root.findall(qn("w", kind)):
        value = note.attrib.get(qn("w", "id"), "")
        if value.isdigit() and int(value) > 0:
            if int(value) in result:
                _unsafe("DOCX merge base contains duplicate note ids.", kind=kind)
            result.add(int(value))
    return result


def _note_map(root: Element, kind: str, source_index: int) -> dict[str, Element]:
    result: dict[str, Element] = {}
    for note in root.findall(qn("w", kind)):
        value = note.attrib.get(qn("w", "id"), "")
        if not value.isdigit() or int(value) <= 0:
            continue
        if value in result:
            _unsafe(
                "DOCX merge source contains duplicate note ids.",
                source_index=source_index,
                kind=kind,
                source_id=value,
            )
        result[value] = note
    return result


def _assert_supported_note(
    note: Element,
    source_index: int,
    kind: str,
    source_id: str,
) -> None:
    structures = sorted(
        {
            local_name(node.tag)
            for node in note.iter()
            if local_name(node.tag) in _UNSUPPORTED_NAMES
        }
    )
    relationship_bound = any(
        set(node.attrib).intersection(_RELATIONSHIP_ATTRIBUTES)
        for node in note.iter()
    )
    if structures or relationship_bound:
        _unsupported(
            "DOCX merge supports only self-contained note XML.",
            source_index=source_index,
            kind=kind,
            source_id=source_id,
            structures=structures,
            relationship_bound=relationship_bound,
        )


def _has_document_relationship(
    source: OpcPackage,
    relationship_type: str,
    part: str,
) -> bool:
    return any(
        relationship.relationship_type == relationship_type
        and relationship.resolved_target == part
        for relationship in relationship_map(source.relationships, WORD_MAIN).values()
    )


def _allocate_note_id(used: set[int], preferred: int) -> str:
    candidate = preferred
    if candidate in used:
        candidate = 1
        while candidate in used:
            candidate += 1
    used.add(candidate)
    return str(candidate)


def _allocate_relationship_id(used: set[str]) -> str:
    for index in range(1, 10_001):
        candidate = f"rIdMergeNote{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "Note relationship id space is exhausted.")


def _new_notes_root(kind: str) -> Element:
    root = Element(qn("w", f"{kind}s"))
    for note_id, note_type, marker in (
        ("-1", "separator", "separator"),
        ("0", "continuationSeparator", "continuationSeparator"),
    ):
        note = SubElement(
            root,
            qn("w", kind),
            {qn("w", "id"): note_id, qn("w", "type"): note_type},
        )
        paragraph = SubElement(note, qn("w", "p"))
        run = SubElement(paragraph, qn("w", "r"))
        SubElement(run, qn("w", marker))
    return root


def _unsupported(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
