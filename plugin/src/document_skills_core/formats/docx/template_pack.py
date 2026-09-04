"""Versioned, integrity-bound DOCX template-pack resolution."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_PACK_FILES = 128
_MAX_PACK_BYTES = 512 * 1024 * 1024
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class PackMember:
    path: str
    sha256: str
    bytes: int
    media_type: str
    role: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "role": self.role,
        }


@dataclass(frozen=True)
class ResolvedTemplatePack:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    manifest_bytes: int
    members: tuple[PackMember, ...]
    reference_kind: str

    @property
    def payload_path(self) -> Path:
        return self.root / Path(*self.manifest["payload"]["path"].split("/"))

    def summary(self) -> dict[str, Any]:
        capabilities = self.manifest["capabilities"]
        provenance = self.manifest["provenance"]
        return {
            "id": self.manifest["id"],
            "version": self.manifest["version"],
            "display_name": self.manifest["display_name"],
            "description": self.manifest["description"],
            "manifest_sha256": self.manifest_sha256,
            "supported_modes": list(capabilities["modes"]),
            "language_policy": dict(self.manifest["language_policy"]),
            "redistributable": provenance["redistributable"],
            "reference_kind": self.reference_kind,
        }


def canonical_json_bytes(value: Any) -> bytes:
    """Return the only accepted on-disk JSON representation for pack data."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8", errors="strict")


def member_record(path: Path, relative: str, media_type: str, role: str) -> PackMember:
    payload = path.read_bytes()
    return PackMember(
        relative,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        media_type,
        role,
    )


def load_builtin_catalog(project_root: Path) -> tuple[dict[str, Any], ...]:
    catalog_path = _catalog_root(project_root) / "catalog.json"
    try:
        raw = catalog_path.read_bytes()
        catalog = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _integrity("Built-in template-pack catalog is unavailable or invalid.", reason=type(error).__name__)
    if canonical_json_bytes(catalog) != raw:
        _integrity("Built-in template-pack catalog is not canonical UTF-8 JSON.")
    if type(catalog) is not dict or set(catalog) != {"schema_version", "packs"}:
        _integrity("Built-in template-pack catalog fields are invalid.")
    if catalog.get("schema_version") != "docx-template-pack-catalog/v1":
        _integrity("Built-in template-pack catalog version is unsupported.")
    packs = catalog.get("packs")
    if type(packs) is not list or len(packs) > 128:
        _integrity("Built-in template-pack catalog exceeds its bounded contract.")
    seen: set[tuple[str, str]] = set()
    parsed: list[dict[str, Any]] = []
    for index, entry in enumerate(packs):
        if type(entry) is not dict or set(entry) != {
            "id", "version", "path", "expected_manifest_sha256"
        }:
            _integrity("Built-in template-pack catalog entry is invalid.", index=index)
        digest = entry.get("expected_manifest_sha256")
        if type(digest) is not str or _SHA256.fullmatch(digest) is None:
            _integrity("Built-in template-pack catalog digest is invalid.", index=index)
        try:
            identity = PORTABLE_PATH_POLICY.require_release_safe(entry.get("path"))
        except (TypeError, UnicodeError, ValueError) as error:
            _path_error("Built-in template-pack catalog path is unsafe.", index=index, reason=type(error).__name__)
        key = (entry.get("id"), entry.get("version"))
        if not all(type(item) is str and item for item in key) or key in seen:
            _integrity("Built-in template-pack catalog identities are invalid.", index=index)
        seen.add(key)
        parsed.append({**entry, "path": "/".join(identity.components)})
    expected_order = sorted(parsed, key=lambda item: (item["id"], _version_key(item["version"])))
    if parsed != expected_order:
        _integrity("Built-in template-pack catalog order is not deterministic.")
    return tuple(parsed)


def resolve_pack_reference(
    project_root: Path,
    schemas: SchemaCatalog,
    reference: dict[str, Any],
) -> ResolvedTemplatePack:
    kind = reference["kind"]
    if kind == "builtin":
        matches = [
            entry
            for entry in load_builtin_catalog(project_root)
            if entry["id"] == reference["id"] and entry["version"] == reference["version"]
        ]
        if not matches:
            raise DocumentSkillsError(
                ErrorCode.INPUT_NOT_FOUND,
                "The requested built-in DOCX template pack id/version was not found.",
                status="invalid_request",
                details={"pack_id": reference["id"], "pack_version": reference["version"]},
            )
        entry = matches[0]
        identity = PORTABLE_PATH_POLICY.require_release_safe(entry["path"])
        root = _catalog_root(project_root) / Path(*identity.components)
        expected_digest = entry["expected_manifest_sha256"]
    else:
        root = reference["path"]
        expected_digest = reference["expected_manifest_sha256"]
    return resolve_pack_directory(
        root,
        schemas,
        expected_manifest_sha256=expected_digest,
        reference_kind=kind,
    )


def snapshot_pack_reference(
    project_root: Path,
    schemas: SchemaCatalog,
    reference: dict[str, Any],
    snapshot_root: Path,
) -> ResolvedTemplatePack:
    """Copy a resolved pack into operation-owned storage and re-verify it.

    Resolution intentionally remains useful to read/list callers. Authoring uses
    this stronger boundary: no path below the caller-controlled pack root escapes
    this function, and the returned pack points exclusively at the private copy.
    """

    source = resolve_pack_reference(project_root, schemas, reference)
    if snapshot_root.exists():
        _integrity("Template-pack snapshot destination must be absent.")
    snapshot_root.mkdir(parents=True)
    before = _inventory(source.root)
    for relative, metadata in before.items():
        source_path = source.root / Path(*relative.split("/"))
        destination = snapshot_root / Path(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = _read_stable_file(source_path, metadata)
        with destination.open("xb") as handle:
            handle.write(payload)
    after = _inventory(source.root)
    if before != after:
        _integrity(
            "Template pack changed while its operation-owned snapshot was copied.",
            reason="snapshot-source-mutation",
        )
    snapshot = resolve_pack_directory(
        snapshot_root,
        schemas,
        expected_manifest_sha256=source.manifest_sha256,
        reference_kind=source.reference_kind,
    )
    if snapshot.manifest != source.manifest or snapshot.members != source.members:
        _integrity(
            "Template-pack snapshot does not match the resolved source.",
            reason="snapshot-metadata-drift",
        )
    return snapshot


def resolve_pack_directory(
    root: str | Path,
    schemas: SchemaCatalog,
    *,
    expected_manifest_sha256: str,
    reference_kind: str = "local",
) -> ResolvedTemplatePack:
    if _SHA256.fullmatch(expected_manifest_sha256) is None:
        _integrity("Expected template-pack manifest SHA-256 is invalid.")
    root_path = _plain_absolute_directory(root)
    before = _inventory(root_path)
    by_path = before
    manifest_metadata = by_path.get("manifest.json")
    if manifest_metadata is None:
        _integrity("Template pack is missing manifest.json.")
    manifest_path = root_path / "manifest.json"
    manifest_bytes = _read_stable_file(manifest_path, manifest_metadata)
    actual_manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_digest != expected_manifest_sha256:
        _integrity(
            "Template-pack manifest digest does not match its external binding.",
            reason="manifest-sha256",
        )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        _integrity("Template-pack manifest is not valid UTF-8 JSON.", reason=type(error).__name__)
    if canonical_json_bytes(manifest) != manifest_bytes:
        _integrity("Template-pack manifest is not canonical UTF-8 JSON.")
    try:
        schemas.validate("docx-template-pack", manifest)
    except DocumentSkillsError as error:
        _integrity(
            "Template-pack manifest does not satisfy the supported schema.",
            reason="manifest-schema",
            schema_error_code=error.code.value,
            schema_details=error.details,
        )
    members = _validate_manifest_members(root_path, manifest, by_path)
    after = _inventory(root_path)
    if before != after or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != actual_manifest_digest:
        _integrity("Template pack changed while it was being resolved.", reason="mutation-race")
    return ResolvedTemplatePack(
        root_path,
        manifest,
        actual_manifest_digest,
        len(manifest_bytes),
        members,
        reference_kind,
    )


def public_pack_manifest(pack: ResolvedTemplatePack) -> dict[str, Any]:
    manifest = pack.manifest
    return {
        "schema_version": manifest["schema_version"],
        "id": manifest["id"],
        "version": manifest["version"],
        "display_name": manifest["display_name"],
        "description": manifest["description"],
        "manifest_sha256": pack.manifest_sha256,
        "payload": dict(manifest["payload"]),
        "members": [member.as_dict() for member in pack.members],
        "capabilities": manifest["capabilities"],
        "compatibility": manifest["compatibility"],
        "language_policy": manifest["language_policy"],
        "provenance": manifest["provenance"],
        "evidence": manifest["evidence"],
        "diagnostics": [],
    }


def _validate_manifest_members(
    root: Path,
    manifest: dict[str, Any],
    inventory: dict[str, tuple[int, int, int, int]],
) -> tuple[PackMember, ...]:
    declared: dict[str, PackMember] = {}
    portable_keys: set[tuple[str, ...]] = set()
    for index, raw in enumerate(manifest["members"]):
        try:
            identity = PORTABLE_PATH_POLICY.require_release_safe(raw["path"])
        except (TypeError, UnicodeError, ValueError) as error:
            _path_error("Template-pack member path is unsafe.", index=index, reason=type(error).__name__)
        relative = "/".join(identity.components)
        if relative == "manifest.json" or identity.keys in portable_keys or relative in declared:
            _path_error("Template-pack member paths collide or declare manifest.json.", member=relative)
        portable_keys.add(identity.keys)
        record = PackMember(
            relative,
            raw["sha256"],
            raw["bytes"],
            raw["media_type"],
            raw["role"],
        )
        declared[relative] = record
    actual = set(inventory) - {"manifest.json"}
    if set(declared) != actual:
        _integrity(
            "Template-pack declared member inventory does not match the directory.",
            missing_members=sorted(set(declared) - actual),
            undeclared_members=sorted(actual - set(declared)),
        )
    validated: list[PackMember] = []
    for relative in sorted(declared):
        record = declared[relative]
        metadata = inventory[relative]
        if metadata[2] != record.bytes:
            _integrity("Template-pack member byte count drifted.", member=relative)
        payload = _read_stable_file(root / Path(*relative.split("/")), metadata)
        if hashlib.sha256(payload).hexdigest() != record.sha256:
            _integrity("Template-pack member digest drifted.", member=relative)
        validated.append(record)
    payload = manifest["payload"]
    payload_path = payload["path"]
    if payload_path not in declared or declared[payload_path].as_dict() != payload:
        _integrity("Template-pack payload declaration does not match its member record.")
    if Path(payload_path).suffix.casefold() not in {".docx", ".dotx"}:
        _integrity("Template-pack payload must be an inert DOCX or DOTX.")
    evidence_paths = {item["path"] for item in manifest["evidence"]}
    if not evidence_paths.issubset(declared):
        _integrity("Template-pack evidence references an undeclared member.")
    return tuple(validated)


def _inventory(root: Path) -> dict[str, tuple[int, int, int, int]]:
    records: dict[str, tuple[int, int, int, int]] = {}
    identities: set[tuple[str, ...]] = set()
    total_bytes = 0
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in sorted(directory_names):
            directory = current_path / name
            _plain_entry(directory, directory=True)
            relative = directory.relative_to(root).as_posix()
            identity = _portable(relative)
            if identity.keys in identities:
                _path_error("Template-pack paths contain a portable collision.", member=relative)
            identities.add(identity.keys)
        for name in sorted(file_names):
            path = current_path / name
            metadata = _plain_entry(path, directory=False)
            relative = path.relative_to(root).as_posix()
            identity = _portable(relative)
            if identity.keys in identities:
                _path_error("Template-pack paths contain a portable collision.", member=relative)
            identities.add(identity.keys)
            canonical = "/".join(identity.components)
            records[canonical] = _identity(metadata)
            total_bytes += metadata.st_size
            if len(records) > _MAX_PACK_FILES or total_bytes > _MAX_PACK_BYTES:
                raise DocumentSkillsError(
                    ErrorCode.RESOURCE_LIMIT,
                    "Template pack exceeds its file or byte limit.",
                )
    return dict(sorted(records.items()))


def _read_stable_file(path: Path, expected: tuple[int, int, int, int]) -> bytes:
    before = _identity(_plain_entry(path, directory=False))
    if before != expected:
        _integrity("Template-pack member changed before it could be read.", member=path.name)
    with path.open("rb") as handle:
        payload = handle.read(_MAX_PACK_BYTES + 1)
    after = _identity(_plain_entry(path, directory=False))
    if before != after or len(payload) != before[2]:
        _integrity("Template-pack member changed while it was being read.", member=path.name)
    return payload


def _plain_absolute_directory(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    try:
        _assert_no_redirected_ancestors(path)
        metadata = _plain_entry(path, directory=True)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "Template-pack directory does not exist.",
            details={"reason": type(error).__name__},
        ) from error
    if not stat.S_ISDIR(metadata.st_mode):
        _path_error("Template-pack root must be a plain directory.")
    return path


def _assert_no_redirected_ancestors(path: Path) -> None:
    candidates = [path, *path.parents]
    for candidate in reversed(candidates):
        if not os.path.lexists(candidate):
            continue
        metadata = candidate.lstat()
        if candidate.is_symlink() or _redirected(metadata):
            _path_error("Template-pack path crosses a symlink, junction, or reparse point.")


def _plain_entry(path: Path, *, directory: bool) -> os.stat_result:
    metadata = path.lstat()
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected or path.is_symlink() or _redirected(metadata):
        _path_error("Template pack contains a redirected or non-regular entry.", member=path.name)
    return metadata


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


def _redirected(metadata: os.stat_result) -> bool:
    return bool(os.name == "nt" and metadata.st_file_attributes & _REPARSE_POINT)


def _portable(relative: str):
    try:
        return PORTABLE_PATH_POLICY.require_release_safe(relative)
    except (TypeError, UnicodeError, ValueError) as error:
        _path_error("Template-pack member path is not portable.", member=relative, reason=type(error).__name__)


def _catalog_root(project_root: Path) -> Path:
    return project_root.resolve() / "skills" / "document-docx" / "assets" / "template-packs"


def _version_key(version: str) -> tuple[int, int, int]:
    try:
        values = tuple(int(item) for item in version.split("."))
    except (AttributeError, ValueError):
        return (-1, -1, -1)
    return values if len(values) == 3 else (-1, -1, -1)


def _integrity(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        details={"diagnostic": "DS_DOCX_TEMPLATE_PACK_INTEGRITY", **details},
    )


def _path_error(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.PATH_UNSAFE,
        message,
        details={"diagnostic": "DS_DOCX_TEMPLATE_PACK_PATH_UNSAFE", **details},
    )


__all__ = [
    "PackMember",
    "ResolvedTemplatePack",
    "canonical_json_bytes",
    "load_builtin_catalog",
    "member_record",
    "public_pack_manifest",
    "resolve_pack_directory",
    "resolve_pack_reference",
    "snapshot_pack_reference",
]
