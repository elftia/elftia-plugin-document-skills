"""Pinned A-Contract descriptor loading for semantic PPTX templates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .presentation_contracts import (
    PresentationContractConsumer,
    PresentationContractConsumerError,
)

_MAX_CONTRACT_BYTES = 4_194_304


@dataclass(frozen=True)
class TemplateDescriptor:
    template_contract: dict[str, Any]
    semantic_slots: dict[str, Any]
    deck_ir: dict[str, Any]
    contract_consumer: dict[str, Any]
    source_files: tuple[dict[str, Any], ...]

    @property
    def slots_by_id(self) -> dict[str, dict[str, Any]]:
        return {item["slotId"]: item for item in self.semantic_slots["slots"]}

    @property
    def slides_by_id(self) -> dict[str, dict[str, Any]]:
        return {item["slideId"]: item for item in self.deck_ir["slides"]}

    @property
    def objects_by_id(self) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        return {
            item["objectId"]: (slide, item)
            for slide in self.deck_ir["slides"]
            for item in slide["objects"]
        }


def load_template_descriptor(value: dict[str, Any]) -> TemplateDescriptor:
    """Load bounded JSON refs and validate them against the pinned owner package."""

    records: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for key in ("template_contract", "semantic_slots", "deck_ir"):
        payload, record = _read_json_ref(value[key], key)
        payloads[key] = payload
        records.append(record)
    try:
        consumer = PresentationContractConsumer.open(value["contract_root"])
        consumer.validate("template-contract", payloads["template_contract"])
        consumer.validate("semantic-slots", payloads["semantic_slots"])
        consumer.validate("deck-ir", payloads["deck_ir"])
        _validate_cross_contracts(payloads)
    except PresentationContractConsumerError as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The semantic template descriptor failed A-Contract validation.",
            status="failed",
            details={"consumer_code": error.code, "issues": list(error.issues)},
        ) from error
    return TemplateDescriptor(
        template_contract=payloads["template_contract"],
        semantic_slots=payloads["semantic_slots"],
        deck_ir=payloads["deck_ir"],
        contract_consumer={
            "manifest_sha256": consumer.pin.manifest_sha256,
            "package": consumer.pin.package,
            "package_version": consumer.pin.package_version,
            "status": "passed",
        },
        source_files=tuple(records),
    )


def validate_catalog_binding(
    descriptor: TemplateDescriptor,
    catalog_ref: dict[str, str] | None,
    *,
    input_sha256: str,
    delivery_profile: str | None = None,
) -> dict[str, Any]:
    """Bind caller catalog identity to the template contract without inventing a decision."""

    contract = descriptor.template_contract
    asset_ref = contract.get("assetRef")
    license_status = contract["licenseStatus"]
    asset_sha256 = asset_ref.get("sha256") if type(asset_ref) is dict else None
    if asset_sha256 is not None and asset_sha256 != f"sha256:{input_sha256}":
        _stale(
            "Template contract asset hash does not match the inert package.",
            actual=f"sha256:{input_sha256}",
            expected=asset_sha256,
        )
    if catalog_ref is None:
        result = {
            "catalog_ref": "not_provided",
            "hash_verification": "passed" if asset_sha256 is not None else "not_run",
            "license_status": license_status,
            "signature_verification": "not_provided",
        }
    else:
        expected = {
            "assetId": catalog_ref["assetId"],
            "catalogId": catalog_ref["catalogId"],
            "sha256": catalog_ref["sha256"],
            "version": catalog_ref["version"],
        }
        if asset_ref != expected:
            _stale(
                "Catalog identity does not match the A-Contract template asset reference.",
                actual=asset_ref,
                expected=expected,
            )
        if catalog_ref["sha256"] != f"sha256:{input_sha256}":
            _stale(
                "Catalog template hash does not match the inert package.",
                actual=f"sha256:{input_sha256}",
                expected=catalog_ref["sha256"],
            )
        result = {
            "catalog_ref": expected,
            "hash_verification": "passed",
            "license_status": license_status,
            "signature_verification": (
                "not_available_without_governance"
                if contract.get("decisionRef") is not None
                else "not_provided"
            ),
        }
    if delivery_profile is not None:
        _enforce_delivery_profile(contract, delivery_profile)
        result["delivery_profile"] = delivery_profile
    return result


def _read_json_ref(
    reference: dict[str, Any],
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = reference["path"]
    try:
        stat = path.stat()
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "A referenced presentation contract file does not exist.",
            status="invalid_request",
            details={"contract": label, "path": str(path)},
        ) from error
    if not path.is_file() or stat.st_size > _MAX_CONTRACT_BYTES:
        raise DocumentSkillsError(
            ErrorCode.RESOURCE_LIMIT,
            "A referenced presentation contract file is not a bounded regular file.",
            status="invalid_request",
            details={"bytes": stat.st_size, "contract": label},
        )
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != reference["sha256"]:
        _stale(
            "A referenced presentation contract hash no longer matches.",
            actual=actual,
            contract=label,
            expected=reference["sha256"],
        )
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "A referenced presentation contract is not valid UTF-8 JSON.",
            status="invalid_request",
            details={"contract": label},
        ) from error
    if type(value) is not dict:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "A referenced presentation contract must be an object.",
            status="invalid_request",
            details={"contract": label},
        )
    return value, {
        "bytes": len(data),
        "path": str(path),
        "sha256": actual,
        "type": label,
    }


def _validate_cross_contracts(payloads: dict[str, dict[str, Any]]) -> None:
    contract = payloads["template_contract"]
    slots = payloads["semantic_slots"]
    deck = payloads["deck_ir"]
    template_id = contract["templateId"]
    if slots["templateId"] != template_id:
        _invalid("Semantic slots target a different template id.")
    object_ids: set[str] = set()
    bound_slots: dict[str, str] = {}
    for slide in deck["slides"]:
        for item in slide["objects"]:
            object_ids.add(item["objectId"])
            binding = item.get("slotBinding")
            if binding is None:
                continue
            if binding["templateId"] != template_id:
                _invalid("Deck IR slot binding targets a different template id.")
            bound_slots[binding["slotId"]] = item["objectId"]
    declared = {item["slotId"]: item["sourceObjectId"] for item in slots["slots"]}
    if set(declared.values()) - object_ids:
        _invalid("Semantic slots reference objects missing from Deck IR.")
    if any(bound_slots.get(slot_id) != object_id for slot_id, object_id in declared.items()):
        _invalid("Deck IR slot bindings do not match semantic slot source objects.")


def _enforce_delivery_profile(contract: dict[str, Any], profile: str) -> None:
    status = contract["licenseStatus"]
    decision = contract.get("decisionRef")
    # A-Contract carries the decision identity but not its signature evidence.
    # Until A-Governance supplies a verifier, commercial delivery must remain
    # blocked even when an untrusted descriptor claims an allowed decision.
    blocked = status == "blocked" or profile == "commercial"
    if blocked:
        raise DocumentSkillsError(
            ErrorCode.LICENSE_BLOCKED,
            "The template license decision does not allow this delivery profile.",
            status="failed",
            details={
                "decision_profile": (
                    decision.get("profile") if type(decision) is dict else None
                ),
                "governance_verification": "not_available",
                "license_status": status,
                "profile": profile,
            },
        )


def _stale(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.STALE_PRECONDITION,
        message,
        status="invalid_request",
        details=details,
    )


def _invalid(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        status="failed",
    )
