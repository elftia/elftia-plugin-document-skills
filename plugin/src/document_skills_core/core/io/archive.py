"""Fail-closed OOXML ZIP/XML preflight without extracting document bodies."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
import stat
from typing import Any
import zipfile
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .ooxml_security import security_inventory


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int = 10_000
    max_uncompressed_bytes: int = 512 * 1024 * 1024
    max_expansion_ratio: float = 200.0
    max_xml_bytes: int = 32 * 1024 * 1024


class DangerousContentPolicy(StrEnum):
    REJECT = "reject"
    PRESERVE_DISABLED = "preserve-disabled"


def inspect_ooxml(
    path: str | Path,
    limits: ArchiveLimits | None = None,
    *,
    dangerous_policy: DangerousContentPolicy | str = DangerousContentPolicy.REJECT,
) -> dict[str, Any]:
    policy = limits or ArchiveLimits()
    content_policy = DangerousContentPolicy(dangerous_policy)
    members: list[str] = []
    unknown_parts: list[str] = []
    total_uncompressed = 0
    total_compressed = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > policy.max_entries:
                _unsafe("entry_count", len(infos), policy.max_entries)
            for info in infos:
                name = _safe_member_name(info)
                members.append(name)
                total_uncompressed += info.file_size
                total_compressed += info.compress_size
                if total_uncompressed > policy.max_uncompressed_bytes:
                    _unsafe(
                        "uncompressed_bytes",
                        total_uncompressed,
                        policy.max_uncompressed_bytes,
                    )
                if _is_symlink(info):
                    _unsafe("symlink_member", name, "not permitted")
                if name.endswith((".xml", ".rels")):
                    if info.file_size > policy.max_xml_bytes:
                        _unsafe("xml_bytes", info.file_size, policy.max_xml_bytes)
                    fromstring(archive.read(info))
                if not _known_part(name):
                    unknown_parts.append(name)
            ratio = total_uncompressed / max(total_compressed, 1)
            if ratio > policy.max_expansion_ratio:
                _unsafe("expansion_ratio", ratio, policy.max_expansion_ratio)
            bad_member = archive.testzip()
            if bad_member is not None:
                _unsafe("crc", bad_member, "valid CRC")
            security = security_inventory(archive, max_xml_bytes=policy.max_xml_bytes)
            if security["dangerous"] and content_policy == DangerousContentPolicy.REJECT:
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "OOXML active or externally linked content is rejected by policy.",
                    details={
                        "policy": content_policy.value,
                        "security_inventory": security,
                    },
                )
    except DocumentSkillsError:
        raise
    except (
        DefusedXmlException,
        ParseError,
        zipfile.BadZipFile,
        ValueError,
        OSError,
    ) as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "OOXML package failed ZIP/XML preflight.",
            details={"reason": type(error).__name__},
        ) from error
    return {
        "entries": len(members),
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": total_compressed,
        "expansion_ratio": ratio,
        "members": members,
        "unknown_parts": unknown_parts,
        "security": {
            **security,
            "policy": content_policy.value,
            "requires_disabled_preservation": security["dangerous"],
            "mutation_authorized": not security["dangerous"],
        },
    }


def _safe_member_name(info: zipfile.ZipInfo) -> str:
    raw = info.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if raw.startswith(("/", "\\")) or path.is_absolute() or ".." in path.parts:
        _unsafe("unsafe_member_path", raw, "relative contained path")
    if path.parts and ":" in path.parts[0]:
        _unsafe("absolute_member_path", raw, "relative contained path")
    return path.as_posix()


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _known_part(name: str) -> bool:
    roots = (
        "[Content_Types].xml",
        "_rels/",
        "docProps/",
        "word/",
        "xl/",
        "ppt/",
        "customXml/",
    )
    return name == roots[0] or name.startswith(roots[1:])


def _unsafe(budget: str, actual: object, ceiling: object) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        f"OOXML archive safety policy rejected {budget}.",
        details={"budget": budget, "actual": actual, "ceiling": ceiling},
    )
