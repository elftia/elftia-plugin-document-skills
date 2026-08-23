"""Inert VBA/signature inventory and copy-through preservation proof."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record

from .package import OpcPackage
from .relationships import Relationship


@dataclass(frozen=True)
class MacroInventory:
    workbook_format: str
    workbook_main_content_type: str
    vba_parts: tuple[dict[str, str], ...]
    vba_relationships: tuple[dict[str, str | None], ...]
    signature_parts: tuple[dict[str, str], ...]
    signature_relationships: tuple[dict[str, str | None], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "workbook_format": self.workbook_format,
            "workbook_main_content_type": self.workbook_main_content_type,
            "vba_parts": list(self.vba_parts),
            "vba_relationships": list(self.vba_relationships),
            "signature_parts": list(self.signature_parts),
            "signature_relationships": list(self.signature_relationships),
        }


def inventory_macro_content(package: OpcPackage) -> MacroInventory:
    """Inventory macro payload and signature material without interpreting either."""

    signature_names = {
        name for name in package.parts if _is_signature_part(package, name)
    }
    vba_names = {
        name
        for name in package.parts
        if name not in signature_names and _is_vba_part(package, name)
    }
    signature_relationships = tuple(
        _relationship_record(item)
        for item in package.relationships
        if _is_signature_relationship(item)
    )
    vba_relationships = tuple(
        _relationship_record(item)
        for item in package.relationships
        if not _is_signature_relationship(item) and _is_vba_relationship(item)
    )
    return MacroInventory(
        workbook_format=package.workbook_format,
        workbook_main_content_type=package.content_type_for("xl/workbook.xml") or "",
        vba_parts=tuple(_part_record(package, name) for name in sorted(vba_names)),
        vba_relationships=tuple(sorted(vba_relationships, key=_relationship_sort_key)),
        signature_parts=tuple(
            _part_record(package, name) for name in sorted(signature_names)
        ),
        signature_relationships=tuple(
            sorted(signature_relationships, key=_relationship_sort_key)
        ),
    )


def macro_read_evidence(package: OpcPackage) -> dict[str, Any]:
    inventory = inventory_macro_content(package)
    return {
        "vba_execution": "not_executed",
        "vba_payload": "present" if inventory.vba_parts else "absent",
        "signature_state": (
            "present_not_cryptographically_verified"
            if inventory.signature_parts or inventory.signature_relationships
            else "absent"
        ),
        "cryptographic_verification": "not_performed",
        "inventory": inventory.as_dict(),
    }


def validate_macro_preservation(
    source: OpcPackage,
    output: OpcPackage,
    *,
    package_mutated: bool,
) -> dict[str, Any]:
    """Prove VBA/signature bytes and their exact relationships survived mutation."""

    before = inventory_macro_content(source)
    after = inventory_macro_content(output)
    mismatches: list[str] = []
    for field in (
        "vba_parts",
        "vba_relationships",
        "signature_parts",
        "signature_relationships",
    ):
        if getattr(before, field) != getattr(after, field):
            mismatches.append(field)
    if mismatches:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Macro or signature copy-through preservation failed.",
            details={"mismatched_inventory": mismatches},
        )
    signature_present = bool(
        before.signature_parts or before.signature_relationships
    )
    return {
        "vba_execution": "not_executed",
        "vba_payload": "preserved" if before.vba_parts else "absent",
        "signature_state": (
            "invalidated_by_package_mutation"
            if signature_present and package_mutated
            else (
                "present_not_cryptographically_verified"
                if signature_present
                else "absent"
            )
        ),
        "cryptographic_verification": "not_performed",
        "vba_parts_preserved": len(before.vba_parts),
        "vba_relationships_preserved": len(before.vba_relationships),
        "signature_parts_preserved": len(before.signature_parts),
        "signature_relationships_preserved": len(before.signature_relationships),
        "source_inventory": before.as_dict(),
        "output_inventory": after.as_dict(),
    }


def with_macro_preservation_gate(
    validation: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    gates = list(validation.get("gates", []))
    gates.append(
        gate_record(
            "operation.macro-copy-through-preservation",
            "pass",
            evidence={
                key: evidence[key]
                for key in (
                    "vba_execution",
                    "vba_payload",
                    "signature_state",
                    "cryptographic_verification",
                    "vba_parts_preserved",
                    "vba_relationships_preserved",
                    "signature_parts_preserved",
                    "signature_relationships_preserved",
                )
            },
        )
    )
    return {
        "schema_version": validation.get("schema_version", "1.0"),
        "status": validation.get("status", "pass"),
        "gates": gates,
    }


def signature_invalidated(evidence: dict[str, Any] | None) -> bool:
    return bool(
        evidence
        and evidence.get("signature_state") == "invalidated_by_package_mutation"
    )


def signature_warnings(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not signature_invalidated(evidence):
        return []
    return [
        {
            "code": "DS_MACRO_SIGNATURE_INVALIDATED",
            "message": "The preserved macro signature is invalid after package mutation.",
            "details": {"signature_state": evidence["signature_state"]},
        }
    ]


def signature_degradation() -> dict[str, Any]:
    return {
        "code": "macro-signature-invalidated",
        "semantic_difference": "The original macro signature no longer authenticates the mutated package.",
        "missing_capabilities": [],
        "recommended_providers": [],
    }


def _part_record(package: OpcPackage, name: str) -> dict[str, str]:
    return {
        "part": name,
        "content_type": package.content_type_for(name) or "",
        "sha256": package.part_hashes[name],
    }


def _relationship_record(item: Relationship) -> dict[str, str | None]:
    return {
        "source_part": item.source_part,
        "relationship_part": item.relationship_part,
        "id": item.relationship_id,
        "type": item.relationship_type,
        "target": item.target,
        "target_mode": item.target_mode,
        "resolved_target": item.resolved_target,
    }


def _relationship_sort_key(item: dict[str, str | None]) -> tuple[str, str, str]:
    return (
        item["source_part"] or "",
        item["id"] or "",
        item["target"] or "",
    )


def _is_vba_part(package: OpcPackage, name: str) -> bool:
    lowered_name = name.casefold()
    lowered_type = (package.content_type_for(name) or "").casefold()
    return "vba" in lowered_name or "vbaproject" in lowered_type


def _is_signature_part(package: OpcPackage, name: str) -> bool:
    lowered_name = name.casefold()
    lowered_type = (package.content_type_for(name) or "").casefold()
    return (
        "signature" in lowered_name
        or "digital-signature" in lowered_type
        or "signature" in lowered_type
    )


def _is_vba_relationship(item: Relationship) -> bool:
    return "vba" in item.relationship_type.casefold() or "vba" in item.target.casefold()


def _is_signature_relationship(item: Relationship) -> bool:
    return (
        "signature" in item.relationship_type.casefold()
        or "signature" in item.target.casefold()
    )
