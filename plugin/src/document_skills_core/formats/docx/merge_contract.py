"""Closed public contract for bounded high-fidelity DOCX merge."""

from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")


def parse_merge(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "numbering_conflict_policy",
            "sources",
            "style_conflict_policy",
        },
    )
    sources = value.get("sources")
    if type(sources) is not list or not sources or len(sources) > 16:
        _invalid("sources must be a non-empty bounded array.", field="sources")
    parsed_sources = []
    identities: set[tuple[str, ...]] = set()
    for index, source in enumerate(sources):
        if type(source) is not dict:
            _invalid("Merge source must be an object.", field=f"sources.{index}")
        _exact_keys(source, {"expected_sha256", "path"})
        raw_path = source.get("path")
        if (
            type(raw_path) is not str
            or not raw_path
            or len(raw_path.encode("utf-8", errors="strict")) > 32_768
            or "://" in raw_path
            or raw_path.startswith(("\\\\", "//"))
        ):
            _invalid("Merge source must be a bounded local path.", field=f"sources.{index}.path")
        path = Path(raw_path).expanduser().resolve(strict=False)
        if path.suffix.casefold() != ".docx":
            _invalid("Merge source must use .docx.", field=f"sources.{index}.path")
        identity = tuple(
            PORTABLE_PATH_POLICY.component_key(component)
            for component in path.parts
        )
        if identity in identities:
            _invalid("Merge sources must be unique.", field=f"sources.{index}.path")
        identities.add(identity)
        digest = source.get("expected_sha256")
        if type(digest) is not str or _SHA256.fullmatch(digest) is None:
            _invalid("Merge source SHA-256 is invalid.", field=f"sources.{index}.expected_sha256")
        parsed_sources.append(
            {"path": path, "expected_sha256": digest.casefold()}
        )
    if value.get("style_conflict_policy") not in {
        "rename-source",
        "require-identical",
    }:
        _invalid(
            "Style conflict policy must be rename-source or require-identical.",
            field="style_conflict_policy",
        )
    if value.get("numbering_conflict_policy") not in {
        "remap-source",
        "require-identical",
    }:
        _invalid(
            "Numbering conflict policy must be remap-source or require-identical.",
            field="numbering_conflict_policy",
        )
    return {
        "sources": parsed_sources,
        "style_conflict_policy": value["style_conflict_policy"],
        "numbering_conflict_policy": value["numbering_conflict_policy"],
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    extras = sorted(set(value) - allowed)
    if extras:
        _invalid("Unexpected DOCX merge keys.", fields=extras)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
