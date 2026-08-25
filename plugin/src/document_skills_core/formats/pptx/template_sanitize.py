"""Fail-closed inert template sanitization and physical package purge."""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    NS,
    PRESENTATION_MAIN,
    qn,
)
from .deep_validation import validate_deep_package
from .mutation import MutablePptxPackage
from .package import OpcPackage, PreservationManifest
from .relationships import source_for_relationship_part
from .slide_graph import _rewrite_content_types, relationship_part_for
from .template_sanitize_inventory import open_sanitizable_template

_PRESENTATION_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.presentation.main+xml"
)
_TEMPLATE_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.template.main+xml"
)
_RELATIONSHIP_ATTRIBUTES = {
    f"{{{NS['r']}}}embed",
    f"{{{NS['r']}}}id",
    f"{{{NS['r']}}}link",
}
_EMBEDDED_RELATIONSHIPS = {"oleobject", "package"}
_REFERENCE_CONTAINERS = {"graphicFrame", "pic"}
_REFERENCE_LEAVES = {
    "audioFile",
    "externalData",
    "hlinkClick",
    "hlinkHover",
    "oleObj",
    "videoFile",
}


@dataclass(frozen=True)
class TemplateSanitization:
    """Validated sanitizer evidence plus the copy-through preservation manifest."""

    operation_result: dict[str, Any]
    preservation: PreservationManifest


def build_template_sanitize_receipt(
    operation_result: dict[str, Any],
    *,
    source_sha256: str,
    candidate_path: Path,
) -> dict[str, Any]:
    """Build a content-addressed receipt that callers can recompute independently."""

    command = {
        "operation": "pptx.template.sanitize",
        "policy": operation_result["policy"],
    }
    payload = {
        "command_sha256": _canonical_hash(command),
        "consumer": operation_result["consumer"],
        "input_sha256": source_sha256,
        "license_status": operation_result["license_status"],
        "operation": "pptx.template.sanitize",
        "output_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "policy_sha256": _canonical_hash(operation_result["policy"]),
        "removed_part_sha256s": sorted(
            item["sha256"] for item in operation_result["removed_parts"]
        ),
        "removed_relationship_sha256s": sorted(
            item["relationship_sha256"]
            for item in operation_result["removed_relationships"]
        ),
        "schema": operation_result["schema"],
        "schema_version": "1.0",
        "source_mapping_sha256": _canonical_hash(operation_result["source_mapping"]),
        "visual": operation_result["visual"],
    }
    return {**payload, "receipt_sha256": _canonical_hash(payload)}


def sanitize_template(
    source_path: Path,
    candidate_path: Path,
    *,
    source_sha256: str,
    expected_sha256: str | None,
    policy: dict[str, str],
) -> TemplateSanitization:
    """Sanitize an inert template without opening external or active content."""

    if expected_sha256 is not None and expected_sha256 != source_sha256:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "The template input hash no longer matches the request precondition.",
            status="invalid_request",
            details={
                "expected_sha256": expected_sha256,
                "actual_sha256": source_sha256,
            },
        )
    admitted = open_sanitizable_template(source_path)
    source = admitted.package

    target = MutablePptxPackage(source)
    selected = _relationships_to_remove(source)
    _convert_embedded_chart_references(target, selected)
    removed_relationships = _remove_relationship_graph(target, source, selected)
    removed_parts = _purge_unreachable_parts(target, source)
    template_identity = _downgrade_template_identity(target, source)
    preservation = target.emit(candidate_path)
    postflight = validate_sanitized_template(
        candidate_path,
        removed_relationships=removed_relationships,
        removed_parts=removed_parts,
    )

    removed_part_records = [
        {
            "bytes": len(source.parts[part]),
            "part": part,
            "reason": "unreachable_after_sanitization",
            "sha256": source.part_hashes[part],
        }
        for part in sorted(removed_parts)
    ]
    return TemplateSanitization(
        operation_result={
            "changed_objects": [],
            "consumer": {
                "core_opc": {"status": "passed"},
                "libreoffice": {"status": "not_run"},
                "powerpoint": {"status": "not_run"},
            },
            "execution": {
                "cancellation": "not_applicable_bounded_core_transaction",
                "timeout": "not_applicable_bounded_core_transaction",
            },
            "license_status": "not_evaluated",
            "physical_purge": postflight,
            "policy": dict(sorted(policy.items())),
            "preservation": preservation.as_dict(),
            "preserved_objects": {
                "hidden_or_unselected_content": "kept",
                "status": "preserved_by_policy",
            },
            "removed_parts": removed_part_records,
            "removed_relationships": removed_relationships,
            "schema": {"status": "not_run"},
            "signature": {
                "invalidation_required": False,
                "source_status": "not_present",
            },
            "source_mapping": {
                "changed_parts": list(preservation.changed),
                "preserved_parts": list(preservation.preserved),
                "removed_parts": list(preservation.removed),
            },
            "template_identity": template_identity,
            "visual": {"status": "not_run"},
        },
        preservation=preservation,
    )


def validate_sanitized_template(
    candidate_path: Path,
    *,
    removed_relationships: list[dict[str, Any]],
    removed_parts: set[str],
) -> dict[str, Any]:
    """Reopen the candidate and independently prove the purge invariants."""

    candidate = OpcPackage.open(candidate_path)
    deep = validate_deep_package(candidate_path)
    remaining_embedded = [
        relationship
        for relationship in candidate.relationships
        if _terminal(relationship.relationship_type) in _EMBEDDED_RELATIONSHIPS
        or (relationship.resolved_target or "").startswith("ppt/embeddings/")
    ]
    if remaining_embedded:
        _validation_failed(
            "Sanitized template still contains embedded relationships.",
            relationships=len(remaining_embedded),
        )
    candidate_relationships = {
        (item.source_part, item.relationship_id)
        for item in candidate.relationships
    }
    relationship_residue = [
        (item["source_part"], item["id"])
        for item in removed_relationships
        if (item["source_part"], item["id"]) in candidate_relationships
    ]
    if relationship_residue:
        _validation_failed(
            "Removed relationships remain in the sanitized package.",
            relationships=relationship_residue[:64],
        )
    part_residue = sorted(removed_parts.intersection(candidate.parts))
    removed_hashes = {
        item["sha256"]
        for item in removed_relationships
        if item.get("target_part") in removed_parts and item.get("sha256")
    }
    recoverable_hashes = sorted(
        removed_hashes.intersection(candidate.part_hashes.values())
    )
    if part_residue or recoverable_hashes:
        _validation_failed(
            "Physically purged template bytes remain recoverable from the candidate ZIP.",
            part_residue=part_residue,
            recoverable_hashes=recoverable_hashes,
        )
    if candidate.content_type_for(PRESENTATION_MAIN) != _PRESENTATION_MAIN_TYPE:
        _validation_failed("Sanitized template was not downgraded to PPTX identity.")
    return {
        "active_content": "absent",
        "deep_graph": deep,
        "external_relationships": 0,
        "orphan_parts": 0,
        "purged_part_count": len(removed_parts),
        "purged_parts_absent": True,
        "removed_relationships_absent": True,
        "reopen": "passed",
    }


def _relationships_to_remove(package: OpcPackage) -> dict[tuple[str, str], str]:
    selected: dict[tuple[str, str], str] = {}
    for relationship in package.relationships:
        terminal = _terminal(relationship.relationship_type)
        if relationship.target_mode == "External":
            selected[(relationship.source_part, relationship.relationship_id)] = (
                "external_relationship"
            )
        elif (
            terminal in _EMBEDDED_RELATIONSHIPS
            or (relationship.resolved_target or "").startswith("ppt/embeddings/")
        ):
            selected[(relationship.source_part, relationship.relationship_id)] = (
                "ole_or_embedded_file"
            )
    return selected


def _convert_embedded_chart_references(
    target: MutablePptxPackage,
    selected: dict[tuple[str, str], str],
) -> None:
    chart_parts = {
        source_part
        for (source_part, _relationship_id), reason in selected.items()
        if reason == "ole_or_embedded_file"
        and source_part.startswith("ppt/charts/")
    }
    for part in sorted(chart_parts):
        root = target.xml(part)
        parent_map = {child: parent for parent in root.iter() for child in parent}
        replacements = 0
        for node in list(root.iter()):
            terminal = _local_name(node.tag)
            if terminal not in {"numRef", "strRef"}:
                continue
            cache_name = "numCache" if terminal == "numRef" else "strCache"
            cache = next(
                (child for child in node if _local_name(child.tag) == cache_name),
                None,
            )
            if cache is None:
                raise DocumentSkillsError(
                    ErrorCode.UNSUPPORTED_FEATURE,
                    "Embedded chart data cannot be removed without a complete literal cache.",
                    status="invalid_request",
                    details={"chart_part": part, "reference": terminal},
                )
            parent = parent_map.get(node)
            if parent is None:
                continue
            namespace = node.tag.split("}", 1)[0] + "}" if node.tag.startswith("{") else ""
            literal = Element(f"{namespace}{'numLit' if terminal == 'numRef' else 'strLit'}")
            for child in cache:
                literal.append(deepcopy(child))
            index = list(parent).index(node)
            parent.remove(node)
            parent.insert(index, literal)
            replacements += 1
        unsupported = [
            _local_name(node.tag)
            for node in root.iter()
            if _local_name(node.tag).endswith("Ref")
            and _local_name(node.tag) not in {"externalData"}
        ]
        if unsupported:
            raise DocumentSkillsError(
                ErrorCode.UNSUPPORTED_FEATURE,
                "Embedded chart data uses a reference shape without a safe literal form.",
                status="invalid_request",
                details={"chart_part": part, "references": sorted(set(unsupported))},
            )
        if replacements:
            target.set_part(part, _xml_bytes(root))


def _remove_relationship_graph(
    target: MutablePptxPackage,
    source: OpcPackage,
    selected: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    by_source: dict[str, set[str]] = defaultdict(set)
    reasons = dict(selected)
    for source_part, relationship_id in selected:
        by_source[source_part].add(relationship_id)
    source_maps = {
        source_part: {
            item.relationship_id: item
            for item in source.part_rels(source_part)
        }
        for source_part in by_source
    }
    for source_part in sorted(by_source):
        additional = _strip_source_references(target, source_part, by_source[source_part])
        for relationship_id in additional:
            if relationship_id not in source_maps[source_part]:
                continue
            by_source[source_part].add(relationship_id)
            reasons.setdefault((source_part, relationship_id), "dependent_relationship")
    removed: list[dict[str, Any]] = []
    for source_part, relationship_ids in sorted(by_source.items()):
        relationship_part = relationship_part_for(source_part)
        root = target.xml(relationship_part)
        for node in list(root):
            relationship_id = node.attrib.get("Id", "")
            if relationship_id in relationship_ids:
                root.remove(node)
        target.set_part(relationship_part, _xml_bytes(root))
        for relationship_id in sorted(relationship_ids):
            relationship = source_maps[source_part].get(relationship_id)
            if relationship is not None:
                removed.append(
                    _relationship_record(
                        relationship,
                        reason=reasons[(source_part, relationship_id)],
                        package=source,
                    )
                )
    return sorted(removed, key=lambda item: (item["source_part"], item["id"]))


def _strip_source_references(
    target: MutablePptxPackage,
    source_part: str,
    relationship_ids: set[str],
) -> set[str]:
    if not source_part or source_part not in target.parts:
        return set()
    content_type = (target.content_type_for(source_part) or "").casefold()
    if not (source_part.endswith(".xml") or content_type.endswith("+xml")):
        return set()
    root = target.xml(source_part)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    anchors: set[Element] = set()
    changed = False
    for node in list(root.iter()):
        matching = [
            name
            for name, value in node.attrib.items()
            if name in _RELATIONSHIP_ATTRIBUTES and value in relationship_ids
        ]
        if not matching:
            continue
        anchor = _reference_anchor(node, parent_map)
        if anchor is None:
            for name in matching:
                node.attrib.pop(name, None)
            changed = True
        else:
            anchors.add(anchor)
    additional: set[str] = set()
    for anchor in anchors:
        additional.update(
            value
            for node in anchor.iter()
            for name, value in node.attrib.items()
            if name in _RELATIONSHIP_ATTRIBUTES and value
        )
        parent = parent_map.get(anchor)
        if parent is None:
            raise DocumentSkillsError(
                ErrorCode.UNSUPPORTED_FEATURE,
                "A relationship-dependent root element cannot be removed safely.",
                status="invalid_request",
                details={"part": source_part, "element": _local_name(anchor.tag)},
            )
        parent.remove(anchor)
        changed = True
    if changed:
        target.set_part(source_part, _xml_bytes(root))
    return additional


def _reference_anchor(
    node: Element,
    parent_map: dict[Element, Element],
) -> Element | None:
    terminal = _local_name(node.tag)
    if terminal in {"hlinkClick", "hlinkHover", "externalData"}:
        return node
    if terminal in {"audioFile", "videoFile"}:
        return node
    current: Element | None = node
    container: Element | None = None
    while current is not None:
        local = _local_name(current.tag)
        if local in _REFERENCE_CONTAINERS:
            container = current
        current = parent_map.get(current)
    if container is not None:
        return container
    if terminal in _REFERENCE_LEAVES:
        return node
    return None


def _purge_unreachable_parts(
    target: MutablePptxPackage,
    source: OpcPackage,
) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for relationship in target.relationships:
        if relationship.target_mode == "Internal" and relationship.resolved_target:
            adjacency[relationship.source_part].add(relationship.resolved_target)
    reachable = _reachable(adjacency)
    content_parts = {
        part
        for part in target.parts
        if part != CONTENT_TYPES and not part.endswith(".rels")
    }
    removed = content_parts - reachable
    for part in sorted(removed):
        target.remove_part(part)
        target.remove_part(relationship_part_for(part))
    for part in sorted(list(target.parts)):
        if not part.endswith(".rels") or part == "_rels/.rels":
            continue
        source_part = source_for_relationship_part(part)
        if source_part not in target.parts:
            target.remove_part(part)
    _rewrite_content_types(target, removed=removed, additions={})
    missing_source_hashes = sorted(removed - set(source.part_hashes))
    if missing_source_hashes:
        _validation_failed(
            "Sanitizer removed parts that were not present in the locked source.",
            parts=missing_source_hashes,
        )
    return removed


def _downgrade_template_identity(
    target: MutablePptxPackage,
    source: OpcPackage,
) -> dict[str, Any]:
    before = source.content_type_for(PRESENTATION_MAIN)
    root = target.xml(CONTENT_TYPES)
    declaration = next(
        (
            node
            for node in root
            if node.tag == f"{{{CONTENT_TYPES_NS}}}Override"
            and node.attrib.get("PartName") == f"/{PRESENTATION_MAIN}"
        ),
        None,
    )
    if declaration is None:
        raise DocumentSkillsError(
            ErrorCode.UNSUPPORTED_FEATURE,
            "Presentation main content type is not declared by an exact override.",
            status="invalid_request",
        )
    declaration.set("ContentType", _PRESENTATION_MAIN_TYPE)
    target.set_part(CONTENT_TYPES, _xml_bytes(root))
    return {
        "input_content_type": before,
        "output_content_type": _PRESENTATION_MAIN_TYPE,
        "template_downgraded": before == _TEMPLATE_MAIN_TYPE,
    }


def _relationship_record(
    relationship: Any,
    *,
    reason: str,
    package: OpcPackage | None = None,
) -> dict[str, Any]:
    target_part = relationship.resolved_target
    target_payload_hash = (
        package.part_hashes.get(target_part)
        if package is not None and target_part is not None
        else None
    )
    canonical = {
        "id": relationship.relationship_id,
        "source_part": relationship.source_part,
        "target": relationship.target,
        "target_mode": relationship.target_mode,
        "type": relationship.relationship_type,
    }
    record: dict[str, Any] = {
        "id": relationship.relationship_id,
        "reason": reason,
        "relationship_sha256": hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "source_part": relationship.source_part,
        "target_mode": relationship.target_mode,
        "target_sha256": _text_hash(relationship.target),
        "type": _terminal(relationship.relationship_type),
    }
    if target_part is not None:
        record["target_part"] = target_part
    if target_payload_hash is not None:
        record["sha256"] = target_payload_hash
    return record


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


def _terminal(value: str) -> str:
    return value.rsplit("/", 1)[-1].casefold()


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _validation_failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        details=details,
    )


__all__ = [
    "TemplateSanitization",
    "build_template_sanitize_receipt",
    "sanitize_template",
    "validate_sanitized_template",
]
