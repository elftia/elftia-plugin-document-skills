"""Bounded public contracts for constrained SVG and scene bundle operations."""

from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT
from .presentation_contracts import PRESENTATION_CONTRACT_V1_PIN

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_STABLE_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def parse_svg_create_arguments(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"fallback_policy", "metadata"})
    fallback = value.get("fallback_policy", "reject")
    if fallback not in {"element-rasterize", "reject"}:
        _invalid(
            "SVG fallback_policy must be reject or element-rasterize.",
            field="fallback_policy",
        )
    return {
        "fallback_policy": fallback,
        "metadata": _metadata(
            value.get("metadata"),
            default_title="Elftia SVG Presentation",
        ),
    }


def parse_scene_export_arguments(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"contract", "identity", "mode"})
    mode = value.get("mode")
    if mode not in {"strict", "tolerant"}:
        _invalid("Scene export mode must be strict or tolerant.", field="mode")
    contract = value.get("contract")
    if type(contract) is not dict:
        _invalid("Scene export requires an A-Contract binding.", field="contract")
    _exact_keys(contract, {"manifest_sha256", "root"}, prefix="contract")
    manifest_sha256 = _text(
        contract.get("manifest_sha256"),
        "contract.manifest_sha256",
        allow_empty=False,
    )
    if manifest_sha256 != PRESENTATION_CONTRACT_V1_PIN.manifest_sha256:
        _invalid(
            "Scene export A-Contract manifest hash does not match the pinned owner artifact.",
            field="contract.manifest_sha256",
        )
    contract_root = Path(
        _text(contract.get("root"), "contract.root", allow_empty=False)
    ).expanduser().resolve(strict=False)
    identity = value.get("identity")
    if type(identity) is not dict:
        _invalid("Scene export requires a stable identity seed.", field="identity")
    _exact_keys(
        identity,
        {"namespace", "source_template_id", "source_template_version"},
        prefix="identity",
    )
    namespace = _stable_slug(identity.get("namespace"), "identity.namespace")
    source_template_id = _stable_slug(
        identity.get("source_template_id"),
        "identity.source_template_id",
    )
    source_template_version = _text(
        identity.get("source_template_version"),
        "identity.source_template_version",
        allow_empty=False,
    )
    if _SEMVER.fullmatch(source_template_version) is None:
        _invalid(
            "source_template_version must be a semantic version.",
            field="identity.source_template_version",
        )
    return {
        "contract": {
            "manifest_sha256": manifest_sha256,
            "root": contract_root,
        },
        "identity": {
            "namespace": namespace,
            "source_template_id": source_template_id,
            "source_template_version": source_template_version,
        },
        "mode": mode,
    }


def _metadata(value: Any, *, default_title: str) -> dict[str, str]:
    if value is None:
        value = {}
    if type(value) is not dict:
        _invalid("SVG metadata must be an object.", field="metadata")
    _exact_keys(value, {"creator", "subject", "title"}, prefix="metadata")
    return {
        "creator": _text(
            value.get("creator", "Elftia Document Skills"),
            "metadata.creator",
        ),
        "subject": _text(value.get("subject", ""), "metadata.subject"),
        "title": _text(value.get("title", default_title), "metadata.title"),
    }


def _stable_slug(value: Any, field: str) -> str:
    text = _text(value, field, allow_empty=False)
    if _STABLE_SLUG.fullmatch(text) is None:
        _invalid("Value must be a stable lowercase slug.", field=field)
    return text


def _exact_keys(value: dict[str, Any], allowed: set[str], *, prefix: str = "arguments") -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown SVG/scene operation argument.", field=prefix, unknown=unknown)


def _text(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


__all__ = ["parse_scene_export_arguments", "parse_svg_create_arguments"]
