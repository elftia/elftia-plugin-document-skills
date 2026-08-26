"""Strict public contracts for semantic template inspection and creation."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_SLIDES

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^(?:slide|object)_[0-9a-f]{32}$")


def parse_template_inspect_arguments(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {"catalog_ref", "contact_sheet", "descriptor", "expected_input_sha256", "mode"},
        "arguments",
    )
    mode = _choice(value.get("mode", "strict"), {"strict", "tolerant"}, "mode")
    contact_sheet = _boolean(value.get("contact_sheet", False), "contact_sheet")
    return {
        "catalog_ref": _catalog_ref(value.get("catalog_ref"), "catalog_ref"),
        "contact_sheet": contact_sheet,
        "descriptor": _descriptor(value.get("descriptor"), "descriptor"),
        "expected_input_sha256": _digest(
            value.get("expected_input_sha256"),
            "expected_input_sha256",
            required=False,
        ),
        "mode": mode,
    }


def parse_template_create_arguments(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "catalog_ref",
            "delivery_profile",
            "descriptor",
            "expected_input_sha256",
            "pages",
            "unbound_required_slot",
            "unselected_content",
        },
        "arguments",
    )
    pages = value.get("pages")
    if type(pages) is not list or not pages or len(pages) > MAX_SLIDES:
        _invalid("pages must be a non-empty bounded array.", field="pages")
    parsed_pages = [_page(item, index) for index, item in enumerate(pages)]
    output_ids = [item["output_slide_id"] for item in parsed_pages]
    if len(output_ids) != len(set(output_ids)):
        _invalid("output_slide_id values must be unique.", field="pages")
    descriptor = _descriptor(value.get("descriptor"), "descriptor")
    if descriptor is None:
        _invalid("Template creation requires an A-Contract descriptor.", field="descriptor")
    expected = _digest(
        value.get("expected_input_sha256"),
        "expected_input_sha256",
        required=True,
    )
    return {
        "catalog_ref": _catalog_ref(value.get("catalog_ref"), "catalog_ref"),
        "delivery_profile": _choice(
            value.get("delivery_profile", "development"),
            {"commercial", "development", "research"},
            "delivery_profile",
        ),
        "descriptor": descriptor,
        "expected_input_sha256": expected,
        "pages": parsed_pages,
        "unbound_required_slot": _literal(
            value.get("unbound_required_slot", "reject"),
            "reject",
            "unbound_required_slot",
        ),
        "unselected_content": _literal(
            value.get("unselected_content", "physical_purge"),
            "physical_purge",
            "unselected_content",
        ),
    }


def _descriptor(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("descriptor must be an object.", field=field)
    _exact_keys(
        value,
        {"contract_root", "deck_ir", "semantic_slots", "template_contract"},
        field,
    )
    contract_root = _path(value.get("contract_root"), f"{field}.contract_root")
    return {
        "contract_root": contract_root,
        "deck_ir": _json_ref(value.get("deck_ir"), f"{field}.deck_ir"),
        "semantic_slots": _json_ref(
            value.get("semantic_slots"),
            f"{field}.semantic_slots",
        ),
        "template_contract": _json_ref(
            value.get("template_contract"),
            f"{field}.template_contract",
        ),
    }


def _json_ref(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Contract reference must be an object.", field=field)
    _exact_keys(value, {"path", "sha256"}, field)
    return {
        "path": _path(value.get("path"), f"{field}.path"),
        "sha256": _digest(value.get("sha256"), f"{field}.sha256", required=True),
    }


def _catalog_ref(value: Any, field: str) -> dict[str, str] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("catalog_ref must be an object.", field=field)
    _exact_keys(value, {"assetId", "catalogId", "sha256", "version"}, field)
    result = {
        "assetId": _text(value.get("assetId"), f"{field}.assetId", False),
        "catalogId": _text(value.get("catalogId"), f"{field}.catalogId", False),
        "sha256": "sha256:" + _digest_prefixed(
            value.get("sha256"),
            f"{field}.sha256",
        ),
        "version": _text(value.get("version"), f"{field}.version", False),
    }
    return result


def _page(value: Any, index: int) -> dict[str, Any]:
    field = f"pages.{index}"
    if type(value) is not dict:
        _invalid("Each page must be an object.", field=field)
    _exact_keys(value, {"bindings", "output_slide_id", "source_slide_id"}, field)
    bindings = value.get("bindings", [])
    if type(bindings) is not list or len(bindings) > 512:
        _invalid("bindings must be a bounded array.", field=f"{field}.bindings")
    parsed = [_binding(item, field, item_index) for item_index, item in enumerate(bindings)]
    slot_ids = [item["slot_id"] for item in parsed]
    if len(slot_ids) != len(set(slot_ids)):
        _invalid("A page may bind each slot at most once.", field=f"{field}.bindings")
    return {
        "bindings": parsed,
        "output_slide_id": _stable_id(
            value.get("output_slide_id"),
            "slide",
            f"{field}.output_slide_id",
        ),
        "source_slide_id": _stable_id(
            value.get("source_slide_id"),
            "slide",
            f"{field}.source_slide_id",
        ),
    }


def _binding(value: Any, page_field: str, index: int) -> dict[str, Any]:
    field = f"{page_field}.bindings.{index}"
    if type(value) is not dict:
        _invalid("Each binding must be an object.", field=field)
    _exact_keys(value, {"expected_hash", "slot_id", "value"}, field)
    payload = value.get("value")
    if type(payload) is not dict:
        _invalid("Binding value must be an object.", field=f"{field}.value")
    if "type" not in payload:
        _invalid("Binding value requires a type.", field=f"{field}.value.type")
    return {
        "expected_hash": _digest(
            value.get("expected_hash"),
            f"{field}.expected_hash",
            required=True,
        ),
        "slot_id": _text(value.get("slot_id"), f"{field}.slot_id", False),
        "value": dict(payload),
    }


def _stable_id(value: Any, kind: str, field: str) -> str:
    result = _text(value, field, False)
    if not _STABLE_ID.fullmatch(result) or not result.startswith(f"{kind}_"):
        _invalid(f"{field} must be an A-Contract {kind} id.", field=field)
    return result


def _digest_prefixed(value: Any, field: str) -> str:
    text = _text(value, field, False)
    digest = text[7:] if text.startswith("sha256:") else text
    if not _SHA256.fullmatch(digest):
        _invalid("Value must be a lowercase SHA-256 digest.", field=field)
    return digest


def _digest(value: Any, field: str, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    return _digest_prefixed(value, field)


def _path(value: Any, field: str) -> Path:
    return Path(_text(value, field, False)).expanduser().resolve(strict=False)


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _literal(value: Any, expected: str, field: str) -> str:
    if value != expected:
        _invalid(f"{field} must be {expected}.", field=field)
    return expected


def _choice(value: Any, choices: set[str], field: str) -> str:
    result = _text(value, field, False)
    if result not in choices:
        _invalid("Value is not an allowed choice.", field=field, choices=sorted(choices))
    return result


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Template contract contains unknown fields.", field=field, unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
