"""Bounded inert OPC index and copy-through package rewrite for PPTX."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element
import zipfile

from defusedxml.ElementTree import fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.archive import (
    ArchiveLimits,
    DangerousContentPolicy,
    inspect_ooxml,
)
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .constants import (
    CONTENT_TYPES,
    MAX_PARTS,
    MAX_PPTX_BYTES,
    MAX_XML_BYTES,
    PACKAGE_RELS,
    PRESENTATION_MAIN,
)
from .content_types import (
    content_type_for,
    parse_content_types,
    validate_package_content_types,
)
from .relationships import Relationship, parse_relationships

_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_KNOWN_PREFIXES = ("_rels/", "customXml/", "docProps/", "ppt/")


@dataclass(frozen=True)
class PreservationManifest:
    changed: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    preserved: tuple[str, ...]
    input_hashes: dict[str, str]
    output_hashes: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed_parts": list(self.changed),
            "added_parts": list(self.added),
            "removed_parts": list(self.removed),
            "preserved_parts": list(self.preserved),
            "input_hashes": self.input_hashes,
            "output_hashes": self.output_hashes,
        }


@dataclass
class OpcPackage:
    path: Path
    parts: dict[str, bytes]
    part_hashes: dict[str, str]
    content_types: dict[str, str]
    relationships: list[Relationship]
    security: dict[str, Any]
    unknown_parts: list[str]

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        allow_dangerous_inventory: bool = False,
    ) -> "OpcPackage":
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise DocumentSkillsError(
                ErrorCode.INPUT_NOT_FOUND,
                "PPTX input does not exist.",
                details={"path": str(resolved)},
            )
        if resolved.stat().st_size > MAX_PPTX_BYTES:
            _unsafe("PPTX exceeds the Core byte ceiling.", bytes=resolved.stat().st_size)
        policy = (
            DangerousContentPolicy.PRESERVE_DISABLED
            if allow_dangerous_inventory
            else DangerousContentPolicy.REJECT
        )
        preflight = inspect_ooxml(
            resolved,
            ArchiveLimits(
                max_entries=MAX_PARTS,
                max_uncompressed_bytes=MAX_PPTX_BYTES,
                max_expansion_ratio=200.0,
                max_xml_bytes=MAX_XML_BYTES,
            ),
            dangerous_policy=policy,
        )
        parts = _read_parts(resolved)
        if CONTENT_TYPES not in parts or PACKAGE_RELS not in parts or PRESENTATION_MAIN not in parts:
            _unsafe("PPTX is missing a required package part.")
        content_types = parse_content_types(parts[CONTENT_TYPES])
        relationships = _parse_all_relationships(parts)
        validate_package_content_types(content_types, relationships)
        unknown = sorted(name for name in parts if not _known_part(name))
        return cls(
            resolved,
            parts,
            {name: _sha256(payload) for name, payload in parts.items()},
            content_types,
            relationships,
            preflight["security"],
            unknown,
        )

    def content_type_for(self, name: str) -> str | None:
        return content_type_for(name, self.content_types)

    def xml(self, name: str) -> Element:
        payload = self.parts.get(name)
        if payload is None:
            _unsafe("Required XML part is missing.", part=name)
        if len(payload) > MAX_XML_BYTES:
            _unsafe("XML part exceeds the Core byte ceiling.", part=name)
        try:
            return fromstring(payload)
        except Exception as error:
            _unsafe(
                "PPTX XML part could not be parsed safely.",
                part=name,
                reason=type(error).__name__,
            )

    def part_text(self, name: str) -> bytes:
        payload = self.parts.get(name)
        if payload is None:
            _unsafe("Required part is missing.", part=name)
        return payload

    def slide_parts(self) -> list[str]:
        """Return sorted slide part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/slides/slide")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def slide_master_parts(self) -> list[str]:
        """Return sorted slide master part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/slideMasters/slideMaster")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def slide_layout_parts(self) -> list[str]:
        """Return sorted slide layout part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/slideLayouts/slideLayout")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def notes_slide_parts(self) -> list[str]:
        """Return sorted notes slide part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/notesSlides/notesSlide")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def notes_master_parts(self) -> list[str]:
        """Return sorted notes master part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/notesMasters/notesMaster")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def theme_parts(self) -> list[str]:
        """Return sorted theme part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/theme/theme")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def media_parts(self) -> list[str]:
        """Return sorted media part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/media/")
        )

    def chart_parts(self) -> list[str]:
        """Return sorted chart part names."""
        return sorted(
            name for name in self.parts
            if name.startswith("ppt/charts/chart")
            and name.endswith(".xml")
            and "_rels" not in name
        )

    def part_rels(self, part_name: str) -> list[Relationship]:
        """Return relationships sourced from a specific part."""
        return [r for r in self.relationships if r.source_part == part_name]

    def write_copy(
        self,
        destination: str | Path,
        *,
        changed_parts: dict[str, bytes],
        added_parts: dict[str, bytes] | None = None,
        removed_parts: set[str] | None = None,
    ) -> PreservationManifest:
        additions = added_parts or {}
        removals = removed_parts or set()
        if (
            set(changed_parts).intersection(additions)
            or set(changed_parts).intersection(removals)
            or set(additions).intersection(removals)
        ):
            raise ValueError("A package part mutation must be declared exactly once.")
        missing = sorted(set(changed_parts) - set(self.parts))
        missing_removals = sorted(removals - set(self.parts))
        existing_additions = sorted(set(additions).intersection(self.parts))
        if missing or missing_removals or existing_additions:
            raise ValueError("Copy-through part declaration does not match the package.")
        output_parts = {
            **{name: payload for name, payload in self.parts.items() if name not in removals},
            **changed_parts,
            **additions,
        }
        write_deterministic_zip(Path(destination), output_parts)
        output_hashes = {
            name: _sha256(payload) for name, payload in sorted(output_parts.items())
        }
        preserved = sorted(set(self.parts) - set(changed_parts) - removals)
        if any(output_hashes[name] != self.part_hashes[name] for name in preserved):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "An untargeted PPTX part changed during copy-through mutation.",
            )
        return PreservationManifest(
            tuple(sorted(changed_parts)),
            tuple(sorted(additions)),
            tuple(sorted(removals)),
            tuple(preserved),
            dict(sorted(self.part_hashes.items())),
            output_hashes,
        )

    def compare_preservation(
        self,
        output: "OpcPackage",
        *,
        allowed_changed: set[str],
    ) -> PreservationManifest:
        input_names = set(self.parts)
        output_names = set(output.parts)
        added = sorted(output_names - input_names)
        removed = sorted(input_names - output_names)
        changed = sorted(
            name
            for name in input_names.intersection(output_names)
            if self.part_hashes[name] != output.part_hashes[name]
        )
        unexpected = sorted(set(changed) - allowed_changed)
        if added or removed or unexpected:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "PPTX output changed an undeclared package part.",
                details={
                    "added_parts": added,
                    "removed_parts": removed,
                    "unexpected_changed_parts": unexpected,
                },
            )
        preserved = sorted(input_names - set(changed))
        return PreservationManifest(
            tuple(changed),
            tuple(added),
            tuple(removed),
            tuple(preserved),
            dict(sorted(self.part_hashes.items())),
            dict(sorted(output.part_hashes.items())),
        )


def write_deterministic_zip(destination: Path, parts: dict[str, bytes]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, _FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, parts[name])


def _read_parts(path: Path) -> dict[str, bytes]:
    parts: dict[str, bytes] = {}
    identities: dict[tuple[str, ...], str] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace("\\", "/")
            try:
                identity = PORTABLE_PATH_POLICY.parse_relative(raw)
            except (TypeError, UnicodeError, ValueError) as error:
                _unsafe(
                    "PPTX contains a non-portable package member.",
                    member=raw,
                    reason=type(error).__name__,
                )
            canonical = "/".join(identity.components)
            if canonical in parts or identity.keys in identities:
                _unsafe(
                    "PPTX contains duplicate or normalized-alias package members.",
                    member=raw,
                    alias_of=identities.get(identity.keys),
                )
            identities[identity.keys] = canonical
            parts[canonical] = archive.read(info)
    return parts


def _parse_all_relationships(parts: dict[str, bytes]) -> list[Relationship]:
    member_names = set(parts)
    relationships: list[Relationship] = []
    for name in sorted(parts):
        if name.endswith(".rels"):
            relationships.extend(parse_relationships(name, parts[name], member_names))
    return relationships


def _known_part(name: str) -> bool:
    return name == CONTENT_TYPES or name.startswith(_KNOWN_PREFIXES)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
