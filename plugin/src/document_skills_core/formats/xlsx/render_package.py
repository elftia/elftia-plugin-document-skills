"""Bounded ZIP/OPC index used before an XLSX reaches a render provider."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any, BinaryIO, Iterator
import zipfile

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.archive import DangerousContentPolicy
from document_skills_core.core.io.ooxml_security import (
    spreadsheet_security_inventory,
)
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    MAX_PARTS,
    MAX_XLSX_BYTES,
    MAX_XML_BYTES,
    NS,
    PACKAGE_RELS,
    WORKBOOK_MAIN,
    WORKBOOK_RELS,
)
from .content_types import (
    content_type_for,
    validate_package_content_types,
)
from .relationships import (
    Relationship,
    resolve_internal_target,
    source_for_relationship_part,
)

_CRC_CHUNK_BYTES = 64 * 1024
_MAX_RELATIONSHIPS = MAX_PARTS * 2
_RELATIONSHIPS_TAG = f"{{{NS['rels']}}}Relationships"
_RELATIONSHIP_TAG = f"{{{NS['rels']}}}Relationship"
_CONTENT_TYPES_TAG = f"{{{CONTENT_TYPES_NS}}}Types"
_CONTENT_TYPE_DEFAULT_TAG = f"{{{CONTENT_TYPES_NS}}}Default"
_CONTENT_TYPE_OVERRIDE_TAG = f"{{{CONTENT_TYPES_NS}}}Override"


@dataclass(frozen=True)
class RenderMember:
    """Central-directory metadata for one canonical non-directory member."""

    archive_name: str
    file_size: int
    compress_size: int
    crc: int


@dataclass(frozen=True)
class RenderPackageIndex:
    """OPC metadata index that never retains decompressed package bodies."""

    path: Path
    members: dict[str, RenderMember]
    content_types: dict[str, str]
    workbook_format: str
    root_relationships: tuple[Relationship, ...]
    workbook_relationships: tuple[Relationship, ...]
    relationship_parts: dict[str, str]
    relationship_count: int
    security: dict[str, Any]

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        allowed_inert_categories: frozenset[str] | None = None,
    ) -> "RenderPackageIndex":
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise DocumentSkillsError(
                ErrorCode.INPUT_NOT_FOUND,
                "XLSX input does not exist.",
                details={"path": str(resolved)},
            )
        size = resolved.stat().st_size
        if size > MAX_XLSX_BYTES:
            _unsafe("XLSX exceeds the Core byte ceiling.", bytes=size)
        try:
            with zipfile.ZipFile(resolved) as archive:
                members = _index_members(archive)
                _require_members(members)
                with archive.open(members[CONTENT_TYPES].archive_name) as source_stream:
                    content_types = _parse_content_types_stream(source_stream)
                inventory = spreadsheet_security_inventory(
                    archive,
                    max_xml_bytes=MAX_XML_BYTES,
                    max_relationships=_MAX_RELATIONSHIPS,
                )
                security = _apply_security_policy(
                    inventory,
                    allowed_inert_categories=allowed_inert_categories,
                )
                _verify_crc(archive, members)
                (
                    relationship_parts,
                    root_relationships,
                    workbook_relationships,
                    relationship_count,
                ) = _index_relationships(archive, members)
                workbook_format = validate_package_content_types(
                    content_types,
                    list(root_relationships),
                )
        except DocumentSkillsError:
            raise
        except Exception as error:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "XLSX render package failed bounded ZIP/OPC preflight.",
                details={"reason": type(error).__name__},
            ) from error
        return cls(
            path=resolved,
            members=members,
            content_types=content_types,
            workbook_format=workbook_format,
            root_relationships=root_relationships,
            workbook_relationships=workbook_relationships,
            relationship_parts=relationship_parts,
            relationship_count=relationship_count,
            security=security,
        )

    def has_part(self, name: str) -> bool:
        return name in self.members

    def content_type_for(self, name: str) -> str | None:
        return content_type_for(name, self.content_types)

    def xml(self, name: str) -> Any:
        from defusedxml.ElementTree import fromstring

        member = self.members.get(name)
        if member is None:
            _unsafe("Required XML part is missing.", part=name)
        try:
            with self.open_part(name) as stream:
                return fromstring(_read_stream(stream, member.file_size))
        except DocumentSkillsError:
            raise
        except Exception as error:
            _unsafe(
                "XLSX XML part could not be parsed safely.",
                part=name,
                reason=type(error).__name__,
            )

    @contextmanager
    def open_part(self, name: str) -> Iterator[BinaryIO]:
        member = self.members.get(name)
        if member is None:
            _unsafe("Required part is missing.", part=name)
        try:
            with zipfile.ZipFile(self.path) as archive:
                info = archive.getinfo(member.archive_name)
                if (info.file_size, info.compress_size, info.CRC) != (
                    member.file_size,
                    member.compress_size,
                    member.crc,
                ):
                    _unsafe("XLSX package changed after render preflight.", part=name)
                with archive.open(info) as stream:
                    yield stream
        except DocumentSkillsError:
            raise
        except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as error:
            _unsafe(
                "XLSX part could not be streamed safely.",
                part=name,
                reason=type(error).__name__,
            )

    def spreadsheet_xml_parts(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in self.members
            if name.casefold().startswith("xl/") and name.casefold().endswith(".xml")
        )

    def relationships_for(self, source_part: str) -> tuple[Relationship, ...]:
        relationship_part = self.relationship_parts.get(source_part)
        if relationship_part is None:
            return ()
        try:
            with self.open_part(relationship_part) as source_stream:
                _source, relationships, _count = _parse_relationship_stream(
                    relationship_part,
                    source_stream,
                    set(self.members),
                    retain=True,
                    base_count=0,
                )
                return relationships
        except DocumentSkillsError:
            raise
        except Exception as error:
            _unsafe(
                "XLSX relationships could not be streamed safely.",
                part=relationship_part,
                reason=type(error).__name__,
            )


def _index_members(archive: zipfile.ZipFile) -> dict[str, RenderMember]:
    infos = archive.infolist()
    if len(infos) > MAX_PARTS:
        _unsafe("XLSX exceeds the package entry ceiling.", entries=len(infos))
    members: dict[str, RenderMember] = {}
    identities: dict[tuple[str, ...], str] = {}
    total_uncompressed = 0
    total_compressed = 0
    for info in infos:
        total_uncompressed += info.file_size
        total_compressed += info.compress_size
        if total_uncompressed > MAX_XLSX_BYTES:
            _unsafe(
                "XLSX exceeds the total uncompressed byte ceiling.",
                bytes=total_uncompressed,
            )
        raw = info.filename.replace("\\", "/")
        identity_source = raw.rstrip("/") if info.is_dir() else raw
        try:
            identity = PORTABLE_PATH_POLICY.parse_relative(identity_source)
        except (TypeError, UnicodeError, ValueError) as error:
            _unsafe(
                "XLSX contains a non-portable package member.",
                member=raw,
                reason=type(error).__name__,
            )
        canonical = "/".join(identity.components)
        if identity.keys in identities:
            _unsafe(
                "XLSX contains duplicate or normalized-alias package members.",
                member=raw,
                alias_of=identities[identity.keys],
            )
        identities[identity.keys] = canonical
        if _is_symlink(info):
            _unsafe("XLSX contains a symbolic-link package member.", member=raw)
        if info.flag_bits & 0x1:
            _unsafe("XLSX contains an encrypted package member.", member=raw)
        if info.is_dir():
            continue
        lowered = canonical.casefold()
        if lowered.endswith((".xml", ".rels")) and info.file_size > MAX_XML_BYTES:
            _unsafe(
                "XLSX XML part exceeds the Core byte ceiling.",
                part=canonical,
                bytes=info.file_size,
            )
        members[canonical] = RenderMember(
            archive_name=info.filename,
            file_size=info.file_size,
            compress_size=info.compress_size,
            crc=info.CRC,
        )
    ratio = total_uncompressed / max(total_compressed, 1)
    if ratio > 200.0:
        _unsafe("XLSX exceeds the package expansion-ratio ceiling.", ratio=ratio)
    return dict(sorted(members.items()))


def _require_members(members: dict[str, RenderMember]) -> None:
    missing = sorted({CONTENT_TYPES, PACKAGE_RELS, WORKBOOK_MAIN} - set(members))
    if missing:
        _unsafe("XLSX is missing a required package part.", missing_parts=missing)


def _verify_crc(
    archive: zipfile.ZipFile,
    members: dict[str, RenderMember],
) -> None:
    for member in members.values():
        with archive.open(member.archive_name) as stream:
            while stream.read(_CRC_CHUNK_BYTES):
                pass


def _read_stream(stream: BinaryIO, expected_size: int) -> bytes:
    payload = stream.read(expected_size + 1)
    if len(payload) != expected_size:
        _unsafe(
            "XLSX package member size changed while streaming.",
            expected_bytes=expected_size,
            actual_bytes=len(payload),
        )
    return payload


def _parse_content_types_stream(source_stream: BinaryIO) -> dict[str, str]:
    from defusedxml.ElementTree import iterparse

    result: dict[str, str] = {}
    override_identities: dict[tuple[str, ...], str] = {}
    declaration_count = 0
    depth = 0
    root_seen = False
    for event, element in iterparse(
        source_stream,
        events=("start", "end"),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    ):
        if event == "start":
            depth += 1
            if depth == 1:
                root_seen = True
                if element.tag != _CONTENT_TYPES_TAG:
                    _unsafe("Invalid OPC content-types root.")
            elif depth == 2:
                declaration_count += 1
                if declaration_count > MAX_PARTS:
                    _unsafe(
                        "XLSX exceeds the OPC content-type declaration ceiling.",
                        content_type_count=declaration_count,
                        content_type_limit=MAX_PARTS,
                    )
            else:
                _unsafe("OPC content-type declarations must be empty.")
            continue
        if depth == 2:
            if (
                len(element)
                or (element.text and element.text.strip())
                or (element.tail and element.tail.strip())
            ):
                _unsafe("OPC content-type declarations must be empty.")
            content_type = element.attrib.get("ContentType", "")
            if element.tag == _CONTENT_TYPE_OVERRIDE_TAG:
                key = _content_type_override_key(
                    element.attrib.get("PartName", ""),
                    override_identities,
                )
            elif element.tag == _CONTENT_TYPE_DEFAULT_TAG:
                key = _content_type_default_key(element.attrib.get("Extension", ""))
            else:
                _unsafe("Unknown OPC content-type declaration.")
            if not key or not content_type or key in result:
                _unsafe("Invalid or duplicate OPC content-type entry.")
            result[key] = content_type
        elif depth == 1 and element.text and element.text.strip():
            _unsafe("OPC content-types root may contain only declarations.")
        element.clear()
        depth -= 1
    if not root_seen:
        _unsafe("OPC content-types part is empty.")
    return dict(sorted(result.items()))


def _content_type_override_key(
    raw: str,
    identities: dict[tuple[str, ...], str],
) -> str:
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        _unsafe("Invalid OPC content-type override path.")
    try:
        identity = PORTABLE_PATH_POLICY.parse_relative(raw[1:])
    except (TypeError, UnicodeError, ValueError) as error:
        _unsafe(
            "OPC content-type override path is not portable.",
            reason=type(error).__name__,
        )
    if identity.keys in identities:
        _unsafe("Duplicate or normalized-alias OPC content-type override.")
    key = f"/{'/'.join(identity.components)}"
    identities[identity.keys] = key
    return key


def _content_type_default_key(extension: str) -> str:
    if not extension or any(marker in extension for marker in ("/", "\\", ".")):
        _unsafe("Invalid OPC content-type extension.")
    try:
        normalized = PORTABLE_PATH_POLICY.component_key(extension)
    except (TypeError, UnicodeError, ValueError) as error:
        _unsafe(
            "OPC content-type extension is not portable.",
            reason=type(error).__name__,
        )
    return f"*.{normalized}"


def _index_relationships(
    archive: zipfile.ZipFile,
    members: dict[str, RenderMember],
) -> tuple[
    dict[str, str],
    tuple[Relationship, ...],
    tuple[Relationship, ...],
    int,
]:
    member_names = set(members)
    relationship_parts: dict[str, str] = {}
    root_relationships: tuple[Relationship, ...] = ()
    workbook_relationships: tuple[Relationship, ...] = ()
    relationship_count = 0
    for name, member in members.items():
        if not name.casefold().endswith(".rels"):
            continue
        source_part = source_for_relationship_part(name)
        if source_part in relationship_parts:
            _unsafe(
                "XLSX contains multiple relationship parts for one source.",
                source_part=source_part,
            )
        relationship_parts[source_part] = name
        retain = name in {PACKAGE_RELS, WORKBOOK_RELS}
        with archive.open(member.archive_name) as source_stream:
            parsed_source, relationships, count = _parse_relationship_stream(
                name,
                source_stream,
                member_names,
                retain=retain,
                base_count=relationship_count,
            )
        if parsed_source != source_part:
            _unsafe("Relationship source metadata is inconsistent.", part=name)
        relationship_count += count
        if name == PACKAGE_RELS:
            root_relationships = relationships
        elif name == WORKBOOK_RELS:
            workbook_relationships = relationships
    return (
        dict(sorted(relationship_parts.items())),
        root_relationships,
        workbook_relationships,
        relationship_count,
    )


def _parse_relationship_stream(
    name: str,
    source_stream: BinaryIO,
    members: set[str],
    *,
    retain: bool,
    base_count: int,
) -> tuple[str, tuple[Relationship, ...], int]:
    from defusedxml.ElementTree import iterparse

    source_part = source_for_relationship_part(name)
    retained: list[Relationship] = []
    seen_ids: set[str] = set()
    count = 0
    root_seen = False
    for event, element in iterparse(
        source_stream,
        events=("start", "end"),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    ):
        if event == "start":
            if not root_seen:
                root_seen = True
                if element.tag != _RELATIONSHIPS_TAG:
                    _unsafe("Invalid relationship root.", part=name)
            continue
        if element.tag == _RELATIONSHIP_TAG:
            count += 1
            if base_count + count > _MAX_RELATIONSHIPS:
                _unsafe(
                    "XLSX exceeds the render relationship ceiling.",
                    relationship_count=base_count + count,
                    relationship_limit=_MAX_RELATIONSHIPS,
                )
            relationship = _relationship_from_element(
                element,
                source_part=source_part,
                relationship_part=name,
                members=members,
                seen_ids=seen_ids,
            )
            if retain:
                retained.append(relationship)
        element.clear()
    if not root_seen:
        _unsafe("Relationship part is empty.", part=name)
    return source_part, tuple(retained), count


def _relationship_from_element(
    element: Any,
    *,
    source_part: str,
    relationship_part: str,
    members: set[str],
    seen_ids: set[str],
) -> Relationship:
    relationship_id = element.attrib.get("Id", "")
    relationship_type = element.attrib.get("Type", "")
    target = element.attrib.get("Target", "")
    target_mode = element.attrib.get("TargetMode", "Internal")
    if not relationship_id or relationship_id in seen_ids:
        _unsafe(
            "Relationship ids must be unique and non-empty.",
            part=relationship_part,
        )
    if not relationship_type or not target:
        _unsafe(
            "Relationship type and target are required.",
            part=relationship_part,
        )
    seen_ids.add(relationship_id)
    if target_mode not in {"Internal", "External"}:
        _unsafe("Relationship target mode is invalid.", part=relationship_part)
    resolved_target = (
        None
        if target_mode == "External"
        else resolve_internal_target(source_part, target)
    )
    if resolved_target is not None and resolved_target not in members:
        _unsafe(
            "Relationship points to a missing internal part.",
            source=source_part,
            target=target,
            resolved_target=resolved_target,
        )
    return Relationship(
        source_part=source_part,
        relationship_part=relationship_part,
        relationship_id=relationship_id,
        relationship_type=relationship_type,
        target=target,
        target_mode=target_mode,
        resolved_target=resolved_target,
    )


def _apply_security_policy(
    inventory: dict[str, Any],
    *,
    allowed_inert_categories: frozenset[str] | None,
) -> dict[str, Any]:
    policy = (
        DangerousContentPolicy.PRESERVE_DISABLED
        if allowed_inert_categories is not None
        else DangerousContentPolicy.REJECT
    )
    categories = inventory.get("categories", {})
    if allowed_inert_categories is not None:
        unknown_allowed = sorted(set(allowed_inert_categories) - set(categories))
        if unknown_allowed:
            raise ValueError("Unknown inert OOXML security category.")
        disallowed = {
            name: records
            for name, records in categories.items()
            if records and name not in allowed_inert_categories
        }
        if disallowed:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "OOXML content exceeds the operation's narrow inert allowance.",
                details={
                    "allowed_inert_categories": sorted(allowed_inert_categories),
                    "disallowed_categories": disallowed,
                    "security_inventory": inventory,
                },
            )
    elif inventory.get("dangerous"):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "OOXML active or externally linked content is rejected by policy.",
            details={
                "policy": policy.value,
                "security_inventory": inventory,
            },
        )
    return {
        **inventory,
        "policy": policy.value,
        "requires_disabled_preservation": bool(inventory.get("dangerous")),
        "mutation_authorized": (
            allowed_inert_categories is not None or not inventory.get("dangerous")
        ),
        **(
            {
                "allowed_inert_categories": sorted(allowed_inert_categories),
            }
            if allowed_inert_categories is not None
            else {}
        ),
    }


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
