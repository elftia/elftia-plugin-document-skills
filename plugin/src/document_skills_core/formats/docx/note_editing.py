"""Footnote/endnote inventory and full package-graph mutation."""

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    CT_ENDNOTES,
    CT_FOOTNOTES,
    REL_ENDNOTES,
    REL_FOOTNOTES,
    WORD_MAIN,
    qn,
)
from .mapping import Story
from .package import OpcPackage
from .relationships import relationship_map, relationship_xml_bytes
from .xml_utils import text_run, xml_bytes

DOCUMENT_RELS = "word/_rels/document.xml.rels"
_CONFIG = {
    "footnote": ("word/footnotes.xml", REL_FOOTNOTES, CT_FOOTNOTES),
    "endnote": ("word/endnotes.xml", REL_ENDNOTES, CT_ENDNOTES),
}


@dataclass(frozen=True)
class NoteEditPlan:
    value: dict[str, Any]
    state: "NoteMutationState"
    paragraph: Element | None = None
    note_id: str | None = None


class NoteMutationState:
    def __init__(self, package: OpcPackage, body: Story) -> None:
        self.package = package
        self.body = body
        self.relationship_root = (
            package.xml(DOCUMENT_RELS)
            if DOCUMENT_RELS in package.parts
            else Element(qn("rels", "Relationships"))
        )
        self.content_types = package.xml(CONTENT_TYPES)
        self.roots: dict[str, Element | None] = {
            kind: package.xml(config[0]) if config[0] in package.parts else None
            for kind, config in _CONFIG.items()
        }
        self.used_ids = {
            kind: {
                int(value)
                for node in root.findall(qn("w", kind))
                if (value := node.attrib.get(qn("w", "id"), "")).lstrip("-").isdigit()
                and int(value) > 0
            }
            if root is not None
            else set()
            for kind, root in self.roots.items()
        }
        self.selected: set[tuple[str, str]] = set()
        self.touched: set[str] = set()

    def plan_insert(self, edit: dict[str, Any], paragraph: Element) -> NoteEditPlan:
        note_id = str(_allocate_id(self.used_ids[edit["kind"]]))
        return NoteEditPlan(edit, self, paragraph=paragraph, note_id=note_id)

    def plan_delete(self, edit: dict[str, Any]) -> NoteEditPlan:
        selector = edit["selector"]
        key = (selector["kind"], selector["id"])
        if key in self.selected:
            _precondition("note-selected-twice", kind=key[0], note_id=key[1])
        record = _note_record(self.roots[selector["kind"]], key[0], key[1], self.body.root)
        if record is None:
            _precondition("note-id", kind=key[0], note_id=key[1])
        if record["text"] != selector["expected_text"]:
            _precondition(
                "expected-text",
                kind=key[0],
                note_id=key[1],
                actual_text=record["text"],
            )
        self.selected.add(key)
        return NoteEditPlan(edit, self, note_id=key[1])

    def ensure_root(self, kind: str) -> Element:
        root = self.roots[kind]
        if root is not None:
            return root
        root = _new_notes_root(kind)
        self.roots[kind] = root
        part, relationship_type, content_type = _CONFIG[kind]
        relationships = relationship_map(self.package.relationships, WORD_MAIN)
        if not any(
            relationship.relationship_type == relationship_type
            for relationship in relationships.values()
        ):
            used = {
                node.attrib.get("Id", "")
                for node in self.relationship_root.findall(qn("rels", "Relationship"))
            }
            relationship_id = _allocate_relationship_id(used, kind)
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

    def package_parts(self, _document_payload: bytes) -> tuple[dict[str, bytes], dict[str, bytes]]:
        changed: dict[str, bytes] = {}
        added: dict[str, bytes] = {}
        for kind in sorted(self.touched):
            part = _CONFIG[kind][0]
            root = self.roots[kind]
            assert root is not None
            _record_part(self.package, part, xml_bytes(root), changed, added)
        relationships_payload = relationship_xml_bytes(self.relationship_root)
        if relationships_payload != self.package.parts.get(DOCUMENT_RELS):
            _record_part(self.package, DOCUMENT_RELS, relationships_payload, changed, added)
        content_types_payload = xml_bytes(self.content_types)
        if content_types_payload != self.package.parts[CONTENT_TYPES]:
            changed[CONTENT_TYPES] = content_types_payload
        return changed, added

    def inventory(self) -> list[dict[str, Any]]:
        return _project_note_roots(self.roots, self.body.root, 10_000)[0]


def apply_note_plan(plan: NoteEditPlan) -> None:
    edit = plan.value
    kind = edit.get("kind") or edit["selector"]["kind"]
    plan.state.touched.add(kind)
    root = plan.state.ensure_root(kind)
    if edit["type"] == "note_insert":
        assert plan.paragraph is not None
        assert plan.note_id is not None
        reference_run = Element(qn("w", "r"))
        SubElement(reference_run, qn("w", f"{kind}Reference"), {qn("w", "id"): plan.note_id})
        if edit["placement"] == "append":
            plan.paragraph.append(reference_run)
        else:
            position = 1 if plan.paragraph.find(qn("w", "pPr")) is not None else 0
            plan.paragraph.insert(position, reference_run)
        note = SubElement(root, qn("w", kind), {qn("w", "id"): plan.note_id})
        paragraph = SubElement(note, qn("w", "p"))
        marker_run = SubElement(paragraph, qn("w", "r"))
        SubElement(marker_run, qn("w", f"{kind}Ref"))
        text_run(paragraph, edit["text"])
        return
    assert plan.note_id is not None
    note = next(
        node
        for node in root.findall(qn("w", kind))
        if node.attrib.get(qn("w", "id")) == plan.note_id
    )
    root.remove(note)
    reference_tag = qn("w", f"{kind}Reference")
    parents = {id(child): parent for parent in plan.state.body.root.iter() for child in parent}
    for reference in list(plan.state.body.root.iter(reference_tag)):
        if reference.attrib.get(qn("w", "id")) == plan.note_id:
            parent = parents[id(reference)]
            parent.remove(reference)


def project_notes(package: OpcPackage, maximum: int = 2_000) -> tuple[list[dict[str, Any]], bool]:
    roots = {
        kind: package.xml(config[0]) if config[0] in package.parts else None
        for kind, config in _CONFIG.items()
    }
    return _project_note_roots(roots, package.xml(WORD_MAIN), maximum)


def assert_note_inventory(package: OpcPackage, expected: list[dict[str, Any]]) -> dict[str, Any]:
    actual, truncated = project_notes(package, max(len(expected) + 1, 1))
    if truncated or actual != expected:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited notes do not match the immutable package graph plan.",
        )
    return {"verified_notes": len(actual)}


def _project_note_roots(
    roots: dict[str, Element | None],
    document: Element,
    maximum: int,
) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    for kind in ("footnote", "endnote"):
        root = roots[kind]
        if root is None:
            continue
        for note in root.findall(qn("w", kind)):
            note_id = note.attrib.get(qn("w", "id"), "")
            if not note_id.isdigit() or int(note_id) <= 0:
                continue
            if len(result) >= maximum:
                return result, True
            result.append(
                {
                    "kind": kind,
                    "id": note_id,
                    "text": "".join(node.text or "" for node in note.iter(qn("w", "t"))),
                    "reference_count": sum(
                        1
                        for reference in document.iter(qn("w", f"{kind}Reference"))
                        if reference.attrib.get(qn("w", "id")) == note_id
                    ),
                }
            )
    return result, False


def _note_record(root: Element | None, kind: str, note_id: str, document: Element) -> dict[str, Any] | None:
    if root is None:
        return None
    for note in root.findall(qn("w", kind)):
        if note.attrib.get(qn("w", "id")) == note_id:
            return {
                "text": "".join(node.text or "" for node in note.iter(qn("w", "t")))
            }
    return None


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


def _allocate_id(used: set[int]) -> int:
    candidate = 1
    while candidate in used:
        candidate += 1
    used.add(candidate)
    return candidate


def _allocate_relationship_id(used: set[str], kind: str) -> str:
    for index in range(1, 10_001):
        candidate = f"rId{kind.title()}{index}"
        if candidate not in used:
            return candidate
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "Note relationship id space is exhausted.")


def _record_part(
    package: OpcPackage,
    part: str,
    payload: bytes,
    changed: dict[str, bytes],
    added: dict[str, bytes],
) -> None:
    if part in package.parts:
        changed[part] = payload
    else:
        added[part] = payload


def _precondition(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX note selector did not match the immutable input.",
        details={"reason": reason, **details},
    )
