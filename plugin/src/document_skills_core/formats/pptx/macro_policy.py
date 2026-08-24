"""Narrow inert keep-VBA admission and copy-through verification for PPTM."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import PRESENTATION_MAIN
from .package import OpcPackage

MACRO_MAIN_TYPE = "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"
VBA_CONTENT_TYPE = "application/vnd.ms-office.vbaProject"
VBA_PART = "ppt/vbaProject.bin"


def open_presentation_package(
    path: str | Path,
    *,
    allow_vba: bool,
    candidate: bool = False,
) -> OpcPackage:
    if not allow_vba:
        return OpcPackage.open(path)
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    validate_vba_package(package, candidate=candidate)
    return package


def validate_vba_package(
    package: OpcPackage,
    *,
    candidate: bool,
) -> dict[str, Any]:
    signatures = _signature_inventory(package)
    if signatures:
        _reject(
            "Signed PPTM packages require explicit signature invalidation handling.",
            candidate=candidate,
            signature_invalidation_required=True,
            signature_inventory=signatures[:32],
        )
    if (package.content_type_for(PRESENTATION_MAIN) or "").casefold() != MACRO_MAIN_TYPE.casefold():
        _reject(
            "PPTM must declare the macro-enabled presentation main content type.",
            candidate=candidate,
        )
    if VBA_PART not in package.parts or not package.parts[VBA_PART]:
        _reject("PPTM must contain one non-empty VBA project part.", candidate=candidate)
    if (package.content_type_for(VBA_PART) or "").casefold() != VBA_CONTENT_TYPE.casefold():
        _reject(
            "PPTM VBA project content type is missing or invalid.",
            candidate=candidate,
        )
    relationships = [
        relationship
        for relationship in package.part_rels(PRESENTATION_MAIN)
        if relationship.relationship_type.rsplit("/", 1)[-1] == "vbaProject"
    ]
    if (
        len(relationships) != 1
        or relationships[0].target_mode != "Internal"
        or relationships[0].resolved_target != VBA_PART
    ):
        _reject(
            "PPTM must contain one internal presentation-to-VBA relationship.",
            candidate=candidate,
        )
    categories = package.security.get("categories", {})
    unexpected_categories = {
        name: records
        for name, records in categories.items()
        if name not in {"ole", "vba"} and records
    }
    invalid_vba = [
        record
        for record in categories.get("vba", [])
        if not _allowed_vba_record(record)
    ]
    invalid_embedded = _invalid_embedded_workbook_records(package, categories.get("ole", []))
    if unexpected_categories or invalid_vba or invalid_embedded:
        _reject(
            "PPTM contains active or external inventory outside the exact VBA project graph.",
            candidate=candidate,
            unexpected_categories=sorted(unexpected_categories),
            invalid_vba_records=invalid_vba[:32],
            invalid_embedded_items=invalid_embedded[:32],
        )
    relationship = relationships[0]
    return {
        "bytes": len(package.parts[VBA_PART]),
        "content_type": VBA_CONTENT_TYPE,
        "main_content_type": MACRO_MAIN_TYPE,
        "part": VBA_PART,
        "relationship": {
            "id": relationship.relationship_id,
            "source_part": relationship.source_part,
            "target": relationship.resolved_target,
            "type": relationship.relationship_type,
        },
        "sha256": package.part_hashes[VBA_PART],
        "signature_invalidation_required": False,
    }


def validate_vba_copy_through(
    source: OpcPackage,
    candidate_path: Path,
    source_evidence: dict[str, Any],
) -> dict[str, Any]:
    candidate = open_presentation_package(
        candidate_path,
        allow_vba=True,
        candidate=True,
    )
    candidate_evidence = validate_vba_package(candidate, candidate=True)
    unchanged = (
        source.parts[VBA_PART] == candidate.parts[VBA_PART]
        and source_evidence["sha256"] == candidate_evidence["sha256"]
    )
    if not unchanged:
        _reject(
            "PPTM VBA project bytes changed during keep-VBA editing.",
            candidate=True,
            source_sha256=source_evidence["sha256"],
            candidate_sha256=candidate_evidence["sha256"],
        )
    return {
        **candidate_evidence,
        "copy_through": "exact-bytes",
        "source_sha256": source_evidence["sha256"],
        "unchanged": True,
    }


def _allowed_vba_record(record: dict[str, str]) -> bool:
    kind = record.get("kind")
    part = record.get("part", "")
    content_type = record.get("type", "")
    if kind == "package-part":
        return part == VBA_PART
    if kind == "content-type":
        return (
            part == f"/{PRESENTATION_MAIN}"
            and content_type.casefold() == MACRO_MAIN_TYPE.casefold()
        ) or (
            part in {"bin", f"/{VBA_PART}"}
            and content_type.casefold() == VBA_CONTENT_TYPE.casefold()
        )
    if record.get("source") == "ppt/_rels/presentation.xml.rels":
        return (
            record.get("target") == "vbaProject.bin"
            and record.get("target_mode", "").casefold() in {"", "internal"}
            and record.get("type", "").rsplit("/", 1)[-1] == "vbaProject"
        )
    return False


def _invalid_embedded_workbook_records(
    package: OpcPackage,
    records: list[dict[str, str]],
) -> list[dict[str, str]]:
    allowed_relationships = {
        (relationship.relationship_part, relationship.relationship_id): relationship.resolved_target
        for relationship in package.relationships
        if relationship.source_part.startswith("ppt/charts/chart")
        and relationship.target_mode == "Internal"
        and relationship.relationship_type.rsplit("/", 1)[-1] == "package"
        and relationship.resolved_target is not None
        and relationship.resolved_target.startswith("ppt/embeddings/")
        and relationship.resolved_target.casefold().endswith(".xlsx")
    }
    allowed_parts = set(allowed_relationships.values())
    return [
        record
        for record in records
        if record.get("part") not in allowed_parts
        and (record.get("source"), record.get("id")) not in allowed_relationships
    ]


def _signature_inventory(package: OpcPackage) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    for part in sorted(package.parts):
        lowered = part.casefold()
        if (
            lowered.startswith("_xmlsignatures/")
            or lowered.endswith("origin.sigs")
            or "vbaprojectsignature" in lowered
        ):
            inventory.append({"kind": "part", "part": part})
    for relationship in package.relationships:
        marker = f"{relationship.relationship_type} {relationship.target}".casefold()
        if (
            "digital-signature" in marker
            or "_xmlsignatures" in marker
            or "vbaprojectsignature" in marker
        ):
            inventory.append({
                "kind": "relationship",
                "part": relationship.relationship_part,
                "id": relationship.relationship_id,
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


def _reject(message: str, *, candidate: bool, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED if candidate else ErrorCode.ARCHIVE_UNSAFE,
        message,
        status="failed" if candidate else "invalid_request",
        details=details,
    )
