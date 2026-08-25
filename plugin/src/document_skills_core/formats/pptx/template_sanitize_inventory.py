"""Bounded raw-graph and dangerous-content admission for template sanitization."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any
import zipfile

from defusedxml.ElementTree import fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.archive import (
    ArchiveLimits,
    DangerousContentPolicy,
    inspect_ooxml,
)

from .constants import CONTENT_TYPES, MAX_PARTS, MAX_PPTX_BYTES, MAX_XML_BYTES, PRESENTATION_MAIN, qn
from .package import OpcPackage
from .relationships import resolve_internal_target, source_for_relationship_part

_ACTIVE_CATEGORIES = {
    "activex",
    "dde",
    "executable_parts",
    "vba",
    "xlm",
}
_TEMPLATE_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.template.main+xml"
)


@dataclass(frozen=True)
class SanitizableTemplateSource:
    package: OpcPackage
    relationship_inventory: dict[str, Any]


def open_sanitizable_template(path: Path) -> SanitizableTemplateSource:
    relationship_inventory = _scan_relationship_anomalies(path)
    if (
        relationship_inventory["duplicate_relationship_ids"]
        or relationship_inventory["dangling_relationships"]
    ):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Template relationships are ambiguous or dangling and cannot be rewritten safely.",
            status="invalid_request",
            details=relationship_inventory,
        )
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    signatures = _signature_inventory(package)
    if signatures:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Signed presentation templates are rejected instead of silently invalidated.",
            status="invalid_request",
            details={"signature_inventory": signatures[:64]},
        )
    active = _active_inventory(package)
    if active:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Active template content cannot be sanitized by removal.",
            status="invalid_request",
            details={"active_inventory": active},
        )
    return SanitizableTemplateSource(package, relationship_inventory)


def _scan_relationship_anomalies(path: Path) -> dict[str, Any]:
    limits = ArchiveLimits(
        max_entries=MAX_PARTS,
        max_uncompressed_bytes=MAX_PPTX_BYTES,
        max_expansion_ratio=200.0,
        max_xml_bytes=MAX_XML_BYTES,
    )
    try:
        inspect_ooxml(
            path,
            limits,
            dangerous_policy=DangerousContentPolicy.PRESERVE_DISABLED,
        )
    except DocumentSkillsError as error:
        if error.code == ErrorCode.ARCHIVE_UNSAFE and error.details.get("budget"):
            raise DocumentSkillsError(
                ErrorCode.RESOURCE_LIMIT,
                "Template exceeds the bounded sanitizer resource policy.",
                status="invalid_request",
                details=error.details,
            ) from error
        raise
    duplicate_ids: list[dict[str, Any]] = []
    dangling: list[dict[str, Any]] = []
    adjacency: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(path) as archive:
        infos = {
            item.filename.replace("\\", "/"): item
            for item in archive.infolist()
            if not item.is_dir()
        }
        members = set(infos)
        for relationship_part in sorted(
            name for name in members if name.endswith(".rels")
        ):
            source_part = source_for_relationship_part(relationship_part)
            root = fromstring(archive.read(infos[relationship_part]))
            seen: set[str] = set()
            for node in root.findall(qn("rels", "Relationship")):
                relationship_id = node.attrib.get("Id", "")
                target = node.attrib.get("Target", "")
                target_mode = node.attrib.get("TargetMode", "Internal")
                record = _raw_relationship_record(
                    source_part,
                    relationship_part,
                    relationship_id,
                    node.attrib.get("Type", ""),
                    target,
                    target_mode,
                )
                if relationship_id in seen:
                    duplicate_ids.append(record)
                seen.add(relationship_id)
                if target_mode == "External":
                    continue
                resolved = resolve_internal_target(source_part, target)
                if resolved not in members:
                    dangling.append({**record, "resolved_target_sha256": _text_hash(resolved)})
                    continue
                adjacency[source_part].add(resolved)
        reachable = _reachable(adjacency)
        content_parts = {
            name
            for name in members
            if name != CONTENT_TYPES and not name.endswith(".rels")
        }
        orphan_parts = sorted(content_parts - reachable)
        orphan_records = [
            {
                "bytes": infos[name].file_size,
                "part": name,
                "sha256": hashlib.sha256(archive.read(infos[name])).hexdigest(),
            }
            for name in orphan_parts
        ]
    return {
        "dangling_relationships": dangling[:128],
        "duplicate_relationship_ids": duplicate_ids[:128],
        "orphan_parts": orphan_records[:128],
    }


def _active_inventory(package: OpcPackage) -> dict[str, list[dict[str, Any]]]:
    categories = package.security.get("categories", {})
    active = {
        category: _redact_records(records)
        for category, records in categories.items()
        if category in _ACTIVE_CATEGORIES and records
    }
    unsafe_templates = [
        record
        for record in categories.get("templates", [])
        if not _benign_template_identity(record)
        and str(record.get("target_mode", "")).casefold() != "external"
    ]
    if unsafe_templates:
        active["templates"] = _redact_records(unsafe_templates)
    return active


def _benign_template_identity(record: dict[str, Any]) -> bool:
    return (
        record.get("kind") == "content-type"
        and record.get("part") == f"/{PRESENTATION_MAIN}"
        and str(record.get("type", "")).casefold() == _TEMPLATE_MAIN_TYPE.casefold()
    )


def _signature_inventory(package: OpcPackage) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for part in sorted(package.parts):
        lowered = part.casefold()
        if (
            lowered.startswith("_xmlsignatures/")
            or lowered.endswith("origin.sigs")
            or "vbaprojectsignature" in lowered
        ):
            inventory.append({"kind": "part", "part": part, "sha256": package.part_hashes[part]})
    for relationship in package.relationships:
        marker = f"{relationship.relationship_type} {relationship.target}".casefold()
        if (
            "digital-signature" in marker
            or "_xmlsignatures" in marker
            or "vbaprojectsignature" in marker
        ):
            inventory.append({
                "id": relationship.relationship_id,
                "kind": "relationship",
                "source_part": relationship.source_part,
                "target_sha256": _text_hash(relationship.target),
                "type": relationship.relationship_type.rsplit("/", 1)[-1],
            })
    for declaration, content_type in package.content_types.items():
        if (
            "digital-signature" in content_type.casefold()
            or "vbaprojectsignature" in content_type.casefold()
        ):
            inventory.append({
                "kind": "content-type",
                "part": declaration,
                "type": content_type,
            })
    return inventory


def _raw_relationship_record(
    source_part: str,
    relationship_part: str,
    relationship_id: str,
    relationship_type: str,
    target: str,
    target_mode: str,
) -> dict[str, Any]:
    return {
        "id": relationship_id,
        "relationship_part": relationship_part,
        "source_part": source_part,
        "target_mode": target_mode,
        "target_sha256": _text_hash(target),
        "type": relationship_type.rsplit("/", 1)[-1].casefold(),
    }


def _redact_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted: list[dict[str, Any]] = []
    for record in records[:64]:
        item = {key: value for key, value in record.items() if key != "target"}
        if record.get("target") is not None:
            item["target_sha256"] = _text_hash(str(record["target"]))
        redacted.append(item)
    return redacted


def _reachable(adjacency: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    pending = deque(sorted(adjacency.get("", set())))
    while pending:
        part = pending.popleft()
        if part in reachable:
            continue
        reachable.add(part)
        pending.extend(sorted(adjacency.get(part, set()) - reachable))
    return reachable


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


__all__ = ["SanitizableTemplateSource", "open_sanitizable_template"]
