"""Strict public contracts for DOCX template packs and reference import."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

from .contract_utils import _boolean, _exact_keys, _integer, _invalid, _text
from .create_contract import _table_borders
from .public_mutation_contract import _parse_template
from .style_profiles import parse_style_profile
from .story_contract import parse_story

_PACK_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_REGION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


def parse_pack_reference(value: Any, field: str = "pack") -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("DOCX template-pack reference must be an object.", field=field)
    kind = value.get("kind")
    if kind == "builtin":
        _exact_keys(value, {"kind", "id", "version"})
        pack_id = _pack_id(value.get("id"), f"{field}.id")
        version = _version(value.get("version"), f"{field}.version")
        return {"kind": "builtin", "id": pack_id, "version": version}
    if kind != "local":
        _invalid("Template-pack reference kind must be builtin or local.", field=f"{field}.kind")
    _exact_keys(value, {"kind", "path", "expected_manifest_sha256"})
    raw_path = _text(value.get("path"), f"{field}.path", allow_empty=False)
    if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
        _invalid("Local template-pack references require a local directory path.", field=f"{field}.path")
    digest = _digest(value.get("expected_manifest_sha256"), f"{field}.expected_manifest_sha256")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path(os.path.abspath(path))
    return {"kind": "local", "path": path, "expected_manifest_sha256": digest}


def parse_pack_list(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"local_packs"})
    local = value.get("local_packs", [])
    if type(local) is not list or len(local) > 32:
        _invalid("local_packs must be a bounded array.", field="local_packs")
    parsed = [parse_pack_reference(item, f"local_packs.{index}") for index, item in enumerate(local)]
    if any(item["kind"] != "local" for item in parsed):
        _invalid("local_packs accepts only explicit local pack references.")
    return {"local_packs": parsed}


def parse_pack_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"pack"})
    return {"pack": parse_pack_reference(value.get("pack"))}


def parse_import_inspect(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"expected_source_sha256"})
    return {
        "expected_source_sha256": _digest(
            value.get("expected_source_sha256"),
            "expected_source_sha256",
        )
    }


def parse_import_create(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"expected_source_sha256", "manifest", "provenance"})
    return {
        "expected_source_sha256": _digest(
            value.get("expected_source_sha256"),
            "expected_source_sha256",
        ),
        "manifest": _parse_import_manifest(value.get("manifest")),
        "provenance": _parse_provenance(value.get("provenance")),
    }


def parse_pack_instantiate(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "pack", "mode", "document_spec", "variables", "regions",
            "missing_policy", "verification",
        },
    )
    pack = parse_pack_reference(value.get("pack"))
    mode = value.get("mode")
    verification = value.get("verification", "core")
    if verification not in {"core", "enhanced"}:
        _invalid("Pack verification must be core or enhanced.", field="verification")
    if mode == "document-spec":
        if "document_spec" not in value or any(
            field in value for field in ("variables", "regions", "missing_policy")
        ):
            _invalid("Document-spec mode requires only document_spec content.")
        document_spec = value["document_spec"]
        if type(document_spec) is not dict:
            _invalid("document_spec must be an object.", field="document_spec")
        if "style_profile" in document_spec:
            _invalid(
                "Pack document-spec instantiation does not accept a caller style_profile.",
                field="document_spec.style_profile",
            )
        return {
            "pack": pack,
            "mode": mode,
            "document_spec": dict(document_spec),
            "verification": verification,
        }
    if mode != "template":
        _invalid("Pack mode must be template or document-spec.", field="mode")
    if "document_spec" in value:
        _invalid("Template mode does not accept document_spec.")
    template = _parse_template(
        {
            key: value[key]
            for key in ("variables", "regions", "missing_policy")
            if key in value
        }
    )
    return {"pack": pack, "mode": mode, "verification": verification, **template}


def _parse_import_manifest(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Import manifest metadata must be an object.", field="manifest")
    _exact_keys(
        value,
        {
            "id", "version", "display_name", "description", "modes",
            "variables", "regions", "role_styles", "compatibility",
            "language_policy", "authoring_format",
        },
    )
    modes = value.get("modes")
    if (
        type(modes) is not list
        or not 1 <= len(modes) <= 2
        or any(mode not in {"template", "document-spec"} for mode in modes)
        or len(set(modes)) != len(modes)
    ):
        _invalid("Import modes must be a unique non-empty bounded array.", field="manifest.modes")
    variables = _parse_variables(value.get("variables", []))
    regions = _parse_regions(value.get("regions", []))
    raw_roles = value.get("role_styles", {})
    if type(raw_roles) is not dict:
        _invalid("role_styles must be an object.", field="manifest.role_styles")
    roles = {}
    if raw_roles:
        profile = parse_style_profile(
            {
                "id": "template-mapped",
                "version": "1.0",
                "source": "contract.docx",
                "expected_source_sha256": "0" * 64,
                "role_styles": raw_roles,
            }
        )
        assert profile is not None
        roles = profile["role_styles"]
    if "document-spec" in modes and not roles:
        _invalid("Document-spec packs require explicit role_styles.", field="manifest.role_styles")
    if "document-spec" not in modes and roles:
        _invalid("role_styles require document-spec mode.", field="manifest.role_styles")
    authoring_format = _parse_authoring_format(
        value.get("authoring_format"),
        roles,
    )
    if "document-spec" not in modes and authoring_format is not None:
        _invalid(
            "authoring_format requires document-spec mode.",
            field="manifest.authoring_format",
        )
    compatibility = _parse_compatibility(value.get("compatibility"), modes)
    language_policy = _parse_language_policy(value.get("language_policy"))
    return {
        "id": _pack_id(value.get("id"), "manifest.id"),
        "version": _version(value.get("version"), "manifest.version"),
        "display_name": _bounded(value.get("display_name"), "manifest.display_name", 160),
        "description": _bounded(value.get("description"), "manifest.description", 2048),
        "modes": sorted(modes),
        "variables": variables,
        "regions": regions,
        "role_styles": dict(sorted(roles.items())),
        "authoring_format": authoring_format,
        "compatibility": compatibility,
        "language_policy": language_policy,
    }


def _parse_authoring_format(
    value: Any,
    role_styles: dict[str, str],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid(
            "authoring_format must be an object.",
            field="manifest.authoring_format",
        )
    _exact_keys(value, {"version", "role_formats", "default_footer", "table"})
    if value.get("version") != "1.0":
        _invalid(
            "Unsupported authoring_format version.",
            field="manifest.authoring_format.version",
        )
    raw_formats = value.get("role_formats")
    if type(raw_formats) is not dict or not 1 <= len(raw_formats) <= 32:
        _invalid(
            "authoring_format.role_formats must be a non-empty bounded object.",
            field="manifest.authoring_format.role_formats",
        )
    role_formats: dict[str, dict[str, Any]] = {}
    allowed = {
        "latin_font",
        "east_asia_font",
        "size_half_points",
        "bold",
        "alignment",
        "first_line_chars",
        "hanging_twips",
        "left_twips",
        "space_before_twips",
        "space_after_twips",
        "line_twips",
    }
    for role, raw_format in raw_formats.items():
        field = f"manifest.authoring_format.role_formats.{role}"
        if role not in role_styles:
            _invalid(
                "Authoring-format roles require an explicit semantic style mapping.",
                field=field,
            )
        if type(raw_format) is not dict:
            _invalid("Each role format must be an object.", field=field)
        _exact_keys(raw_format, allowed)
        parsed = {
            "latin_font": _bounded(raw_format.get("latin_font"), f"{field}.latin_font", 128),
            "east_asia_font": _bounded(
                raw_format.get("east_asia_font"),
                f"{field}.east_asia_font",
                128,
            ),
            "size_half_points": _integer(
                raw_format.get("size_half_points"),
                12,
                144,
            ),
        }
        if "bold" in raw_format:
            parsed["bold"] = _boolean(raw_format["bold"], f"{field}.bold")
        if "alignment" in raw_format:
            alignment = raw_format["alignment"]
            if alignment not in {"left", "center", "right", "both"}:
                _invalid(
                    "Role alignment must be left, center, right, or both.",
                    field=f"{field}.alignment",
                )
            parsed["alignment"] = alignment
        bounds = {
            "first_line_chars": (0, 1_000),
            "hanging_twips": (0, 5_760),
            "left_twips": (0, 5_760),
            "space_before_twips": (0, 5_760),
            "space_after_twips": (0, 5_760),
            "line_twips": (120, 2_880),
        }
        for name, (minimum, maximum) in bounds.items():
            if name in raw_format:
                parsed[name] = _integer(raw_format[name], minimum, maximum)
        if "first_line_chars" in parsed and "hanging_twips" in parsed:
            _invalid(
                "First-line and hanging indents are mutually exclusive.",
                field=field,
            )
        role_formats[role] = parsed
    raw_footer = value.get("default_footer")
    if type(raw_footer) is not dict:
        _invalid(
            "authoring_format.default_footer must be a structured story.",
            field="manifest.authoring_format.default_footer",
        )
    default_footer = parse_story(
        raw_footer,
        "manifest.authoring_format.default_footer",
    )
    assert type(default_footer) is dict
    raw_table = value.get("table")
    if type(raw_table) is not dict:
        _invalid(
            "authoring_format.table must be an object.",
            field="manifest.authoring_format.table",
        )
    _exact_keys(raw_table, {"width_twips", "borders"})
    borders = _table_borders(raw_table.get("borders"))
    assert borders is not None
    return {
        "version": "1.0",
        "role_formats": dict(sorted(role_formats.items())),
        "default_footer": default_footer,
        "table": {
            "width_twips": _integer(raw_table.get("width_twips"), 720, 31_680),
            "borders": borders,
        },
    }


def _parse_variables(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > 1024:
        _invalid("variables must be a bounded array.", field="manifest.variables")
    parsed = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if type(item) is not dict:
            _invalid("Each variable declaration must be an object.", field=f"manifest.variables.{index}")
        _exact_keys(item, {"name", "required"})
        name = _text(item.get("name"), f"manifest.variables.{index}.name", allow_empty=False)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name) or name in names:
            _invalid("Template variable declaration is invalid or duplicated.", field=f"manifest.variables.{index}.name")
        names.add(name)
        parsed.append({"name": name, "required": _boolean(item.get("required", True), "required")})
    return sorted(parsed, key=lambda item: item["name"])


def _parse_regions(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) > 256:
        _invalid("regions must be a bounded array.", field="manifest.regions")
    parsed = []
    ids: set[str] = set()
    targets: set[tuple[str, int]] = set()
    for index, item in enumerate(value):
        if type(item) is not dict:
            _invalid("Each region declaration must be an object.", field=f"manifest.regions.{index}")
        _exact_keys(item, {"id", "type", "paragraph_index", "expected_text"})
        region_id = _text(item.get("id"), f"manifest.regions.{index}.id", allow_empty=False)
        kind = item.get("type")
        paragraph_index = _integer(item.get("paragraph_index"), 0, 1_000_000)
        if _REGION_ID.fullmatch(region_id) is None or region_id in ids or kind not in {"paragraph_repeat", "paragraph_condition"}:
            _invalid("Template region declaration is invalid or duplicated.", field=f"manifest.regions.{index}")
        target = (kind, paragraph_index)
        if target in targets:
            _invalid("Template region target is duplicated.", field=f"manifest.regions.{index}")
        ids.add(region_id)
        targets.add(target)
        parsed.append(
            {
                "id": region_id,
                "type": kind,
                "paragraph_index": paragraph_index,
                "expected_text": _bounded(item.get("expected_text"), f"manifest.regions.{index}.expected_text", 32768, allow_empty=True),
            }
        )
    return sorted(parsed, key=lambda item: item["id"])


def _parse_compatibility(value: Any, modes: list[str]) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("compatibility must be an object.", field="manifest.compatibility")
    _exact_keys(value, {"document_spec_versions", "domain_profiles", "template_engine_versions", "style_profile_versions"})
    document_versions = _version_values(value.get("document_spec_versions", []), "document_spec_versions")
    engine_versions = _version_values(value.get("template_engine_versions", []), "template_engine_versions")
    style_versions = _string_values(value.get("style_profile_versions", []), "style_profile_versions")
    raw_domains = value.get("domain_profiles", [])
    if type(raw_domains) is not list or len(raw_domains) > 16:
        _invalid("domain_profiles must be a bounded array.")
    domains = []
    for index, domain in enumerate(raw_domains):
        if type(domain) is not dict:
            _invalid("Each domain profile declaration must be an object.")
        _exact_keys(domain, {"id", "version"})
        domains.append(
            {
                "id": _bounded(domain.get("id"), f"domain_profiles.{index}.id", 96),
                "version": _bounded(domain.get("version"), f"domain_profiles.{index}.version", 32),
            }
        )
    if "document-spec" in modes and ("1.0" not in document_versions or "template-mapped/1.0" not in style_versions):
        _invalid("Document-spec packs must declare document_spec 1.0 and template-mapped/1.0 compatibility.")
    if "template" in modes and "1.0" not in engine_versions:
        _invalid("Template packs must declare template engine version 1.0.")
    return {
        "document_spec_versions": document_versions,
        "domain_profiles": sorted(domains, key=lambda item: (item["id"], item["version"])),
        "template_engine_versions": engine_versions,
        "style_profile_versions": style_versions,
    }


def _parse_language_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return {"layout": "language-neutral", "content": "caller-owned", "translation": "none", "examples": []}
    if type(value) is not dict:
        _invalid("language_policy must be an object.")
    _exact_keys(value, {"layout", "content", "translation", "examples"})
    if value.get("layout") != "language-neutral" or value.get("content") != "caller-owned" or value.get("translation") != "none":
        _invalid("Template-pack language policy must preserve caller-owned content without translation.")
    examples = _string_values(value.get("examples", []), "language_policy.examples", maximum=32)
    return {"layout": "language-neutral", "content": "caller-owned", "translation": "none", "examples": examples}


def _parse_provenance(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Import provenance must be an object.", field="provenance")
    _exact_keys(value, {"source_kind", "imported_at", "license", "redistributable", "network"})
    source_kind = value.get("source_kind", "local")
    if source_kind not in {"local", "network"}:
        _invalid("Import source_kind must be local or network.", field="provenance.source_kind")
    imported_at = _timestamp(value.get("imported_at"), "provenance.imported_at")
    license_record = _parse_license(value.get("license"))
    redistributable = _boolean(value.get("redistributable", False), "provenance.redistributable")
    if license_record["status"] == "unknown" and redistributable:
        _invalid("Unknown-license imports cannot be marked redistributable.")
    result = {
        "source_kind": source_kind,
        "imported_at": imported_at,
        "license": license_record,
        "redistributable": redistributable,
    }
    if source_kind == "network":
        result["network"] = _parse_network(value.get("network"))
    elif "network" in value:
        _invalid("Network provenance is valid only for network-origin imports.")
    return result


def _parse_license(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "unknown", "identifier": None, "evidence": None}
    if type(value) is not dict:
        _invalid("license must be an object.")
    _exact_keys(value, {"status", "identifier", "evidence"})
    status = value.get("status")
    identifier = value.get("identifier")
    evidence = value.get("evidence")
    if status not in {"unknown", "declared", "reviewed"}:
        _invalid("License status is invalid.")
    if status == "unknown":
        if identifier is not None or evidence is not None:
            _invalid("Unknown license status cannot claim identifier or evidence.")
    elif type(identifier) is not str or not identifier or type(evidence) is not str or not evidence:
        _invalid("Declared/reviewed licenses require identifier and evidence.")
    return {"status": status, "identifier": identifier, "evidence": evidence}


def _parse_network(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Network-origin import requires complete network metadata.")
    _exact_keys(value, {"original_url", "retrieved_url", "retrieved_at", "downloader", "downloaded_sha256"})
    downloader = value.get("downloader")
    if type(downloader) is not dict:
        _invalid("Network downloader metadata must be an object.")
    _exact_keys(downloader, {"id", "version"})
    original_url = _bounded(value.get("original_url"), "network.original_url", 4096)
    retrieved_url = _bounded(value.get("retrieved_url"), "network.retrieved_url", 4096)
    if "://" not in original_url or "://" not in retrieved_url:
        _invalid("Network provenance URLs must be absolute acquisition records.")
    return {
        "original_url": original_url,
        "retrieved_url": retrieved_url,
        "retrieved_at": _timestamp(value.get("retrieved_at"), "network.retrieved_at"),
        "downloader": {
            "id": _bounded(downloader.get("id"), "network.downloader.id", 128),
            "version": _bounded(downloader.get("version"), "network.downloader.version", 64),
        },
        "downloaded_sha256": _digest(value.get("downloaded_sha256"), "network.downloaded_sha256"),
    }


def _version_values(value: Any, field: str) -> list[str]:
    values = _string_values(value, field, maximum=8)
    if any(not item for item in values):
        _invalid("Compatibility versions cannot be empty.", field=field)
    return values


def _string_values(value: Any, field: str, maximum: int = 8) -> list[str]:
    if type(value) is not list or len(value) > maximum or any(type(item) is not str or not item for item in value):
        _invalid("Value must be a bounded string array.", field=field)
    if len(set(value)) != len(value):
        _invalid("String array values must be unique.", field=field)
    return sorted(value)


def _timestamp(value: Any, field: str) -> str:
    rendered = _bounded(value, field, 64)
    try:
        datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except ValueError:
        _invalid("Timestamp must use ISO-8601 format.", field=field)
    return rendered


def _digest(value: Any, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid("SHA-256 must contain exactly 64 hexadecimal characters.", field=field)
    return value.casefold()


def _pack_id(value: Any, field: str) -> str:
    rendered = _bounded(value, field, 96)
    if _PACK_ID.fullmatch(rendered) is None:
        _invalid("Template-pack id is invalid.", field=field)
    return rendered


def _version(value: Any, field: str) -> str:
    rendered = _bounded(value, field, 32)
    if _VERSION.fullmatch(rendered) is None:
        _invalid("Template-pack version must be semantic x.y.z.", field=field)
    return rendered


def _bounded(value: Any, field: str, maximum: int, allow_empty: bool = False) -> str:
    rendered = _text(value, field, allow_empty=allow_empty)
    if len(rendered.encode("utf-8", errors="strict")) > maximum:
        _invalid("Text exceeds the field byte limit.", field=field, ceiling=maximum)
    return rendered


__all__ = [
    "parse_import_create",
    "parse_import_inspect",
    "parse_pack_instantiate",
    "parse_pack_list",
    "parse_pack_read",
    "parse_pack_reference",
]
