"""Contained OPC relationship parsing and target resolution."""

from dataclasses import dataclass
import posixpath
from pathlib import PurePosixPath
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from defusedxml.ElementTree import fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .constants import NS, qn
from .xml_utils import xml_bytes

_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class Relationship:
    source_part: str
    relationship_part: str
    relationship_id: str
    relationship_type: str
    target: str
    target_mode: str
    resolved_target: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_part": self.source_part,
            "relationship_part": self.relationship_part,
            "id": self.relationship_id,
            "type": self.relationship_type,
            "target": self.target,
            "target_mode": self.target_mode,
            "resolved_target": self.resolved_target,
        }


def source_for_relationship_part(name: str) -> str:
    if name == "_rels/.rels":
        return ""
    path = PurePosixPath(name)
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        _unsafe("Invalid relationship part path.", part=name)
    source_name = path.name[: -len(".rels")]
    return (path.parent.parent / source_name).as_posix()


def parse_relationships(
    name: str,
    payload: bytes,
    members: set[str],
) -> list[Relationship]:
    root = fromstring(payload)
    if root.tag != qn("rels", "Relationships"):
        _unsafe("Invalid relationship root.", part=name)
    source = source_for_relationship_part(name)
    relationships: list[Relationship] = []
    seen_ids: set[str] = set()
    for node in root.findall(qn("rels", "Relationship")):
        relationship_id = node.attrib.get("Id", "")
        relationship_type = node.attrib.get("Type", "")
        target = node.attrib.get("Target", "")
        target_mode = node.attrib.get("TargetMode", "Internal")
        if not relationship_id or relationship_id in seen_ids:
            _unsafe("Relationship ids must be unique and non-empty.", part=name)
        if not relationship_type or not target:
            _unsafe("Relationship type and target are required.", part=name)
        seen_ids.add(relationship_id)
        external = target_mode.casefold() == "external"
        if target_mode not in {"Internal", "External"}:
            _unsafe("Relationship target mode is invalid.", part=name)
        resolved = None if external else resolve_internal_target(source, target)
        if resolved is not None and resolved not in members:
            _unsafe(
                "Relationship points to a missing internal part.",
                source=source,
                target=target,
                resolved_target=resolved,
            )
        relationships.append(
            Relationship(
                source,
                name,
                relationship_id,
                relationship_type,
                target,
                target_mode,
                resolved,
            )
        )
    return relationships


def resolve_internal_target(source_part: str, target: str) -> str:
    normalized = target.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("//")
        or _DRIVE.match(normalized)
        or "?" in normalized
        or "#" in normalized
    ):
        _unsafe("Relationship target is not a contained package path.", target=target)
    base = posixpath.dirname(source_part)
    resolved = posixpath.normpath(
        normalized.lstrip("/")
        if normalized.startswith("/")
        else posixpath.join(base, normalized)
    )
    try:
        identity = PORTABLE_PATH_POLICY.parse_relative(resolved)
    except (TypeError, UnicodeError, ValueError) as error:
        _unsafe(
            "Relationship target is not portable.",
            target=target,
            reason=type(error).__name__,
        )
    return "/".join(identity.components)


def relationship_map(
    relationships: list[Relationship], source_part: str
) -> dict[str, Relationship]:
    return {
        item.relationship_id: item
        for item in relationships
        if item.source_part == source_part
    }


def relationship_xml_bytes(root: Element) -> bytes:
    """Serialize a relationship part with its namespace as the default.

    Some consumers, including LibreOffice, reject the equivalent explicit
    ``rels:`` prefix form. Rebuild the small closed relationship vocabulary
    instead of applying a textual XML rewrite.
    """
    if root.tag != qn("rels", "Relationships"):
        _unsafe("Invalid relationship root.")
    normalized = Element("Relationships", {"xmlns": NS["rels"]})
    for node in root:
        if node.tag != qn("rels", "Relationship"):
            _unsafe("Invalid relationship child.")
        SubElement(normalized, "Relationship", dict(node.attrib))
    return xml_bytes(normalized)


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        message,
        details=details,
    )
