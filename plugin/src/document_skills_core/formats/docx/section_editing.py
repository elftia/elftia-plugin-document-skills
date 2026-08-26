"""Immutable-input planning for section and header/footer edits."""

from dataclasses import dataclass, field
from typing import Any
import unicodedata
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    CT_FOOTER,
    CT_HEADER,
    CT_SETTINGS,
    REL_FOOTER,
    REL_HEADER,
    REL_SETTINGS,
    WORD_MAIN,
    qn,
)
from .mapping import Story
from .package import OpcPackage
from .relationships import relationship_map, relationship_xml_bytes
from .story import story_bytes
from .xml_utils import selector_sha256, xml_bytes

_DOCUMENT_RELATIONSHIPS = "word/_rels/document.xml.rels"
_SETTINGS_PART = "word/settings.xml"


@dataclass(frozen=True)
class SectionEditPlan:
    kind: str
    section_index: int
    section: Element
    value: dict[str, Any]
    reference: Element | None = None
    relationship_id: str | None = None
    target_part: str | None = None


@dataclass
class SectionMutationState:
    package: OpcPackage
    body: Story
    sections: list[Element]
    relationship_root: Element
    content_types_root: Element
    relationship_nodes: dict[str, Element]
    relationship_identities: set[str]
    part_identities: set[tuple[str, ...]]
    selected_stories: set[tuple[int, str, str]] = field(default_factory=set)
    selected_sections: set[int] = field(default_factory=set)
    added_parts: dict[str, bytes] = field(default_factory=dict)
    changed_auxiliary_parts: dict[str, bytes] = field(default_factory=dict)
    relationships_changed: bool = False
    content_types_changed: bool = False

    @classmethod
    def open(cls, package: OpcPackage, body: Story) -> "SectionMutationState":
        relationship_root = package.xml(_DOCUMENT_RELATIONSHIPS)
        relationship_nodes = {
            node.attrib["Id"]: node
            for node in relationship_root.findall(qn("rels", "Relationship"))
        }
        return cls(
            package,
            body,
            list(body.root.iter(qn("w", "sectPr"))),
            relationship_root,
            package.xml(CONTENT_TYPES),
            relationship_nodes,
            {_identity(value) for value in relationship_nodes},
            {
                PORTABLE_PATH_POLICY.parse_relative(name).keys
                for name in package.parts
            },
        )

    def plan(self, edit: dict[str, Any]) -> SectionEditPlan:
        section, index = self._select_section(edit["target"])
        if edit["type"] == "section_update":
            if index in self.selected_sections:
                _conflict(index, "section-update")
            self.selected_sections.add(index)
            return SectionEditPlan("section_update", index, section, edit["updates"])

        identity = (index, edit["kind"], edit["variant"])
        if identity in self.selected_stories:
            _conflict(index, "header-footer-variant")
        self.selected_stories.add(identity)
        reference = _story_reference(section, edit["kind"], edit["variant"])
        relationship = None
        if reference is not None:
            relationship = relationship_map(
                self.package.relationships, WORD_MAIN
            ).get(reference.attrib.get(qn("r", "id"), ""))
        actual_hash = (
            self.package.part_hashes.get(relationship.resolved_target)
            if relationship is not None and relationship.resolved_target is not None
            else None
        )
        if actual_hash != edit["expected_story_sha256"]:
            _precondition_failed(
                index,
                "expected-story-sha256",
                expected_sha256=edit["expected_story_sha256"],
                actual_sha256=actual_hash,
            )
        if edit["link_to_previous"]:
            if index == 0:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "The first section cannot link a header/footer to a previous section.",
                    status="invalid_request",
                )
            return SectionEditPlan("header_footer_update", index, section, edit, reference)

        relationship_id = self._allocate_relationship_id()
        target_part = self._allocate_story_part(edit["kind"])
        self._add_story_relationship(
            relationship_id,
            target_part,
            edit["kind"],
        )
        self.added_parts[target_part] = story_bytes(edit["kind"], edit["text"])
        self._ensure_override(
            target_part,
            CT_HEADER if edit["kind"] == "header" else CT_FOOTER,
        )
        if edit["variant"] == "even":
            self._ensure_even_and_odd_settings()
        return SectionEditPlan(
            "header_footer_update",
            index,
            section,
            edit,
            reference,
            relationship_id,
            target_part,
        )

    def package_parts(
        self,
        document_payload: bytes,
    ) -> tuple[dict[str, bytes], dict[str, bytes]]:
        changed = {WORD_MAIN: document_payload, **self.changed_auxiliary_parts}
        if self.relationships_changed:
            changed[_DOCUMENT_RELATIONSHIPS] = relationship_xml_bytes(
                self.relationship_root
            )
        if self.content_types_changed:
            changed[CONTENT_TYPES] = xml_bytes(self.content_types_root)
        return changed, dict(self.added_parts)

    def _select_section(self, target: dict[str, Any]) -> tuple[Element, int]:
        index = target["section_index"]
        if index >= len(self.sections):
            _precondition_failed(index, "section-index")
        section = self.sections[index]
        actual = selector_sha256(section)
        if actual != target["expected_section_sha256"]:
            _precondition_failed(
                index,
                "expected-section-sha256",
                expected_sha256=target["expected_section_sha256"],
                actual_sha256=actual,
            )
        return section, index

    def _allocate_relationship_id(self) -> str:
        counter = 1
        while True:
            candidate = f"rIdElftiaStory{counter}"
            identity = _identity(candidate)
            if identity not in self.relationship_identities:
                self.relationship_identities.add(identity)
                return candidate
            counter += 1

    def _allocate_story_part(self, kind: str) -> str:
        counter = 1
        while True:
            candidate = f"word/{kind}-elftia-{counter}.xml"
            identity = PORTABLE_PATH_POLICY.parse_relative(candidate).keys
            if identity not in self.part_identities:
                self.part_identities.add(identity)
                return candidate
            counter += 1

    def _add_story_relationship(
        self,
        relationship_id: str,
        target_part: str,
        kind: str,
    ) -> None:
        node = SubElement(
            self.relationship_root,
            qn("rels", "Relationship"),
            {
                "Id": relationship_id,
                "Type": REL_HEADER if kind == "header" else REL_FOOTER,
                "Target": target_part.removeprefix("word/"),
            },
        )
        self.relationship_nodes[relationship_id] = node
        self.relationships_changed = True

    def _ensure_override(self, part: str, content_type: str) -> None:
        key = f"/{part}"
        existing = self.package.content_types.get(key)
        if existing is not None:
            if existing != content_type:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Existing story part has a conflicting content type.",
                )
            return
        SubElement(
            self.content_types_root,
            f"{{{CONTENT_TYPES_NS}}}Override",
            {"PartName": key, "ContentType": content_type},
        )
        self.package.content_types[key] = content_type
        self.content_types_changed = True

    def _ensure_even_and_odd_settings(self) -> None:
        if _SETTINGS_PART in self.added_parts:
            return
        if _SETTINGS_PART in self.package.parts:
            root = self.package.xml(_SETTINGS_PART)
            if root.find(qn("w", "evenAndOddHeaders")) is None:
                root.append(Element(qn("w", "evenAndOddHeaders")))
                self.changed_auxiliary_parts[_SETTINGS_PART] = xml_bytes(root)
            return
        root = Element(qn("w", "settings"))
        root.append(Element(qn("w", "evenAndOddHeaders")))
        self.added_parts[_SETTINGS_PART] = xml_bytes(root)
        self._ensure_override(_SETTINGS_PART, CT_SETTINGS)
        existing = next(
            (
                item
                for item in self.package.relationships
                if item.source_part == WORD_MAIN
                and item.relationship_type == REL_SETTINGS
            ),
            None,
        )
        if existing is None:
            relationship_id = self._allocate_relationship_id()
            SubElement(
                self.relationship_root,
                qn("rels", "Relationship"),
                {
                    "Id": relationship_id,
                    "Type": REL_SETTINGS,
                    "Target": "settings.xml",
                },
            )
            self.relationships_changed = True


def _story_reference(section: Element, kind: str, variant: str) -> Element | None:
    tag = qn("w", f"{kind}Reference")
    matches = [
        node
        for node in section.findall(tag)
        if node.attrib.get(qn("w", "type"), "default") == variant
    ]
    if len(matches) > 1:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Section contains duplicate header/footer reference variants.",
        )
    return matches[0] if matches else None


def _identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _precondition_failed(index: int, reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX section selector precondition did not match the immutable input.",
        details={"section_index": index, "reason": reason, **details},
    )


def _conflict(index: int, reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "DOCX edit transaction contains conflicting section edits.",
        status="invalid_request",
        details={"section_index": index, "reason": reason},
    )
