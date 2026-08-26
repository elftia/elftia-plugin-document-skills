"""Immutable-input planning for bounded body image edits."""

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any
import unicodedata
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    REL_IMAGE,
    WORD_MAIN,
    qn,
)
from .image import load_image
from .mapping import Story
from .package import OpcPackage
from .relationships import relationship_map, relationship_xml_bytes
from .xml_utils import xml_bytes

_DOCUMENT_RELATIONSHIPS = "word/_rels/document.xml.rels"
_MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ImageEditPlan:
    kind: str
    image: dict[str, Any]
    relationship_id: str
    target_part: str
    anchor: Element | None = None
    parent: Element | None = None
    position: str | None = None
    drawing: Element | None = None
    document_properties_id: int | None = None
    picture_properties_id: int | None = None


@dataclass
class ImageMutationState:
    package: OpcPackage
    body: Story
    relationship_root: Element
    relationship_part_exists: bool
    content_types_root: Element
    relationship_nodes: dict[str, Element]
    relationship_identities: set[str]
    part_identities: set[tuple[str, ...]]
    document_property_ids: set[int]
    picture_property_ids: set[int]
    selected_relationships: set[str] = field(default_factory=set)
    added_parts: dict[str, bytes] = field(default_factory=dict)
    content_types_changed: bool = False
    total_image_bytes: int = 0

    @classmethod
    def open(cls, package: OpcPackage, body: Story) -> "ImageMutationState":
        relationship_part_exists = _DOCUMENT_RELATIONSHIPS in package.parts
        relationship_root = (
            package.xml(_DOCUMENT_RELATIONSHIPS)
            if relationship_part_exists
            else Element(qn("rels", "Relationships"))
        )
        relationship_nodes = {
            node.attrib["Id"]: node
            for node in relationship_root.findall(qn("rels", "Relationship"))
        }
        return cls(
            package=package,
            body=body,
            relationship_root=relationship_root,
            relationship_part_exists=relationship_part_exists,
            content_types_root=package.xml(CONTENT_TYPES),
            relationship_nodes=relationship_nodes,
            relationship_identities={
                _identifier_key(value) for value in relationship_nodes
            },
            part_identities={
                PORTABLE_PATH_POLICY.parse_relative(name).keys
                for name in package.parts
            },
            document_property_ids=_numeric_attributes(body.root, qn("wp", "docPr")),
            picture_property_ids=_numeric_attributes(body.root, qn("pic", "cNvPr")),
        )

    def plan_insert(
        self,
        edit: dict[str, Any],
        *,
        anchor: Element,
        parent: Element,
    ) -> ImageEditPlan:
        image = self._load(edit["image"])
        relationship_id = self._allocate_relationship_id()
        target_part = self._allocate_media_part(image["extension"])
        self._add_relationship(relationship_id, target_part)
        self._add_media(target_part, image)
        document_properties_id = _allocate_number(self.document_property_ids, start=1)
        picture_properties_id = _allocate_number(self.picture_property_ids, start=0)
        return ImageEditPlan(
            kind="image_insert",
            image=image,
            relationship_id=relationship_id,
            target_part=target_part,
            anchor=anchor,
            parent=parent,
            position=edit["position"],
            document_properties_id=document_properties_id,
            picture_properties_id=picture_properties_id,
        )

    def plan_replace(self, edit: dict[str, Any]) -> ImageEditPlan:
        target = edit["target"]
        relationship_id = target["relationship_id"]
        if relationship_id in self.selected_relationships:
            _request_conflict(relationship_id)
        relationship = relationship_map(
            self.package.relationships, WORD_MAIN
        ).get(relationship_id)
        node = self.relationship_nodes.get(relationship_id)
        if (
            relationship is None
            or node is None
            or relationship.relationship_type != REL_IMAGE
            or relationship.target_mode != "Internal"
            or relationship.resolved_target is None
        ):
            _precondition_failed(relationship_id, "image-relationship")
        media = self.package.parts.get(relationship.resolved_target)
        if media is None or sha256(media).hexdigest() != target["expected_media_sha256"]:
            _precondition_failed(relationship_id, "expected-media-sha256")
        drawings = drawings_for_relationship(self.body.root, relationship_id)
        if len(drawings) != 1:
            _precondition_failed(
                relationship_id,
                "drawing-reference-count",
                actual_matches=len(drawings),
            )
        drawing = drawings[0]
        properties = list(drawing.iter(qn("wp", "docPr")))
        actual_alt_text = properties[0].attrib.get("descr", "") if len(properties) == 1 else None
        if actual_alt_text != target["expected_alt_text"]:
            _precondition_failed(
                relationship_id,
                "expected-alt-text",
                expected_alt_text=target["expected_alt_text"],
                actual_alt_text=actual_alt_text,
            )
        image = self._load(edit["image"])
        target_part = self._allocate_media_part(image["extension"])
        node.attrib["Target"] = _relationship_target(target_part)
        node.attrib.pop("TargetMode", None)
        self.selected_relationships.add(relationship_id)
        self._add_media(target_part, image)
        return ImageEditPlan(
            kind="image_replace",
            image=image,
            relationship_id=relationship_id,
            target_part=target_part,
            drawing=drawing,
        )

    def package_parts(
        self,
        document_payload: bytes,
    ) -> tuple[dict[str, bytes], dict[str, bytes]]:
        changed = {WORD_MAIN: document_payload}
        relationships = relationship_xml_bytes(self.relationship_root)
        added = dict(self.added_parts)
        if self.relationship_part_exists:
            changed[_DOCUMENT_RELATIONSHIPS] = relationships
        else:
            added[_DOCUMENT_RELATIONSHIPS] = relationships
        if self.content_types_changed:
            changed[CONTENT_TYPES] = xml_bytes(self.content_types_root)
        return changed, added

    def _load(self, request: dict[str, Any]) -> dict[str, Any]:
        image = load_image(request)
        image["crop"] = request["crop"]
        self.total_image_bytes += len(image["bytes"])
        if self.total_image_bytes > _MAX_TOTAL_IMAGE_BYTES:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "DOCX edit images exceed the aggregate byte limit.",
                status="invalid_request",
                details={"ceiling": _MAX_TOTAL_IMAGE_BYTES},
            )
        return image

    def _allocate_relationship_id(self) -> str:
        counter = 1
        while True:
            candidate = f"rIdElftiaImage{counter}"
            identity = _identifier_key(candidate)
            if identity not in self.relationship_identities:
                self.relationship_identities.add(identity)
                return candidate
            counter += 1

    def _allocate_media_part(self, extension: str) -> str:
        counter = 1
        while True:
            candidate = f"word/media/elftia-image-{counter}.{extension}"
            identity = PORTABLE_PATH_POLICY.parse_relative(candidate).keys
            if identity not in self.part_identities:
                self.part_identities.add(identity)
                return candidate
            counter += 1

    def _add_relationship(self, relationship_id: str, target_part: str) -> None:
        node = SubElement(
            self.relationship_root,
            qn("rels", "Relationship"),
            {
                "Id": relationship_id,
                "Type": REL_IMAGE,
                "Target": _relationship_target(target_part),
            },
        )
        self.relationship_nodes[relationship_id] = node

    def _add_media(self, target_part: str, image: dict[str, Any]) -> None:
        self.added_parts[target_part] = image["bytes"]
        key = f"*.{image['extension']}"
        existing = self.package.content_types.get(key)
        if existing is not None and existing != image["content_type"]:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Existing image extension has a conflicting OPC content type.",
                details={"extension": image["extension"], "content_type": existing},
            )
        if existing is None:
            SubElement(
                self.content_types_root,
                f"{{{CONTENT_TYPES_NS}}}Default",
                {
                    "Extension": image["extension"],
                    "ContentType": image["content_type"],
                },
            )
            self.package.content_types[key] = image["content_type"]
            self.content_types_changed = True


def drawings_for_relationship(root: Element, relationship_id: str) -> list[Element]:
    matches = []
    for drawing in root.iter(qn("w", "drawing")):
        blips = [
            blip
            for blip in drawing.iter(qn("a", "blip"))
            if blip.attrib.get(qn("r", "embed")) == relationship_id
        ]
        if len(blips) > 1:
            return [drawing, drawing]
        if blips:
            matches.append(drawing)
    return matches


def _numeric_attributes(root: Element, tag: str) -> set[int]:
    values = set()
    for node in root.iter(tag):
        value = node.attrib.get("id", "")
        if value.isdigit():
            values.add(int(value))
    return values


def _allocate_number(values: set[int], *, start: int) -> int:
    candidate = start
    while candidate in values:
        candidate += 1
    values.add(candidate)
    return candidate


def _identifier_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _relationship_target(part: str) -> str:
    return PurePosixPath(part).relative_to("word").as_posix()


def _precondition_failed(
    relationship_id: str,
    reason: str,
    **details: Any,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX image selector precondition did not match the immutable input.",
        details={"relationship_id": relationship_id, "reason": reason, **details},
    )


def _request_conflict(relationship_id: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "DOCX edit transaction targets one image relationship more than once.",
        status="invalid_request",
        details={"relationship_id": relationship_id},
    )
