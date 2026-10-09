"""Identity-bound LibreOffice inputs with byte-based format dispatch."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import struct
from typing import BinaryIO
import zipfile

from defusedxml.ElementTree import fromstring

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.archive import ArchiveLimits, inspect_ooxml
from ...core.io.temp_roots import OperationTempRoot
from ...formats.xlsx.constants import MAX_XLSX_BYTES, WORKBOOK_CONTENT_TYPES
from ...formats.xlsx.formula_security import assert_provider_formula_safe
from ...formats.xlsx.source_snapshot import (
    assert_bounded_source_preserved,
    bounded_source_record,
    merge_bounded_source_preservation_failure,
    stage_source_snapshot,
)

_CONTENT_TYPES = "[Content_Types].xml"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_CFB_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_MAX_CONTENT_TYPES_BYTES = 8 * 1024 * 1024
_OOXML_MAIN_TYPES = {
    **{
        content_type: (format_id, "/xl/workbook.xml")
        for format_id, content_type in WORKBOOK_CONTENT_TYPES.items()
    },
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": (
        "docx",
        "/word/document.xml",
    ),
    "application/vnd.ms-word.document.macroEnabled.main+xml": (
        "docm",
        "/word/document.xml",
    ),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml": (
        "dotx",
        "/word/document.xml",
    ),
    "application/vnd.ms-word.template.macroEnabledTemplate.main+xml": (
        "dotm",
        "/word/document.xml",
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": (
        "pptx",
        "/ppt/presentation.xml",
    ),
    "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml": (
        "pptm",
        "/ppt/presentation.xml",
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml": (
        "potx",
        "/ppt/presentation.xml",
    ),
    "application/vnd.ms-powerpoint.template.macroEnabled.main+xml": (
        "potm",
        "/ppt/presentation.xml",
    ),
}
_OPERATION_FORMATS = {
    "libreoffice.recalc-xlsx": frozenset({"xlsx"}),
    "libreoffice.convert-pdf": frozenset({"docx", "xlsx", "pptx"}),
    "libreoffice.render-image": frozenset({"docx", "pptx", "pdf"}),
    "libreoffice.read-legacy": frozenset({"doc", "xls", "ppt"}),
}
_LEGACY_STREAM_NAMES = {
    "doc": frozenset({"WordDocument"}),
    "xls": frozenset({"Workbook", "Book"}),
    "ppt": frozenset({"PowerPoint Document"}),
}
_LEGACY_STREAM_MARKERS = frozenset().union(*_LEGACY_STREAM_NAMES.values())
_CFB_FREE_SECTOR = 0xFFFFFFFF
_CFB_END_OF_CHAIN = 0xFFFFFFFE
_CFB_FAT_SECTOR = 0xFFFFFFFD
_CFB_DIFAT_SECTOR = 0xFFFFFFFC
_CFB_HEADER_DIFAT_ENTRIES = 109
_MAX_CFB_DIRECTORY_SECTORS = 4096


@dataclass(frozen=True)
class LibreOfficeInput:
    """One private input snapshot and its content-derived format."""

    path: Path
    actual_format: str


@contextmanager
def private_libreoffice_input(
    input_path: Path,
    *,
    operation: str,
    byte_limit: int = MAX_XLSX_BYTES,
) -> Iterator[LibreOfficeInput]:
    """Create one snapshot, classify it, preflight it, and preserve its source."""

    source = bounded_source_record(input_path, "input", byte_limit=byte_limit)
    try:
        with OperationTempRoot() as private_root:
            staged = stage_source_snapshot(
                source,
                private_root,
                byte_limit=byte_limit,
            )
            actual_format = _detect_format(staged)
            snapshot = private_root / f"provider-input.{actual_format}"
            staged.replace(snapshot)
            _assert_operation_accepts(operation, actual_format)
            if actual_format in {"xlsx", "xlsm", "xltx", "xltm"}:
                assert_provider_formula_safe(snapshot)
            if actual_format == "pdf":
                _assert_single_page_pdf_safe(snapshot)
            yield LibreOfficeInput(snapshot, actual_format)
        assert_bounded_source_preserved(source, byte_limit=byte_limit)
    except BaseException as error:
        merge_bounded_source_preservation_failure(
            error,
            source,
            byte_limit=byte_limit,
        )
        raise


def _detect_format(path: Path) -> str:
    if path.stat().st_size > MAX_XLSX_BYTES:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "LibreOffice input exceeds the provider byte ceiling.",
            details={"input_bytes": path.stat().st_size, "input_limit": MAX_XLSX_BYTES},
        )
    with path.open("rb") as handle:
        signature = handle.read(len(_CFB_SIGNATURE))
    if signature.startswith(b"PK"):
        return _detect_ooxml_format(path)
    if signature == _CFB_SIGNATURE:
        return _detect_legacy_format(path)
    if signature.startswith(b"%PDF-"):
        return "pdf"
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "LibreOffice input bytes are not an accepted Office document.",
        status="invalid_request",
    )


def _assert_single_page_pdf_safe(path: Path) -> None:
    from ...formats.pdf.actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
    from ...formats.pdf.object_model import parse_pdf
    from ...formats.pdf.page_tree import walk_pages

    model = parse_pdf(path)
    if model.trailer.encrypt is not None or has_dangerous_actions(classify_actions(model)) or has_executable_embedded_files(model):
        _unsafe("LibreOffice PDF raster input contains encryption or active content.")
    if len(walk_pages(model)) != 1:
        raise DocumentSkillsError(ErrorCode.REQUEST_INVALID,
                                  "LibreOffice PNG evidence requires one bounded PDF page.",
                                  status="invalid_request")


def _detect_ooxml_format(path: Path) -> str:
    inspect_ooxml(
        path,
        ArchiveLimits(
            max_entries=5_000,
            max_uncompressed_bytes=MAX_XLSX_BYTES,
            max_expansion_ratio=200.0,
            max_xml_bytes=_MAX_CONTENT_TYPES_BYTES,
        ),
    )
    try:
        with zipfile.ZipFile(path) as archive:
            declarations = [
                info
                for info in archive.infolist()
                if info.filename.replace("\\", "/") == _CONTENT_TYPES
            ]
            if len(declarations) != 1:
                _unsafe("OOXML requires one exact content-types declaration.")
            declaration = declarations[0]
            if declaration.file_size > _MAX_CONTENT_TYPES_BYTES:
                _unsafe("OOXML content-types declaration exceeds its byte ceiling.")
            with archive.open(declaration) as handle:
                root = fromstring(handle.read(_MAX_CONTENT_TYPES_BYTES + 1))
    except DocumentSkillsError:
        raise
    except Exception as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "LibreOffice OOXML format detection failed closed.",
            details={"reason": type(error).__name__},
        ) from error
    if root.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
        _unsafe("OOXML content-types root is invalid.")
    formats = {
        mapping[0]
        for node in root
        for content_type in [node.attrib.get("ContentType", "")]
        for mapping in [_OOXML_MAIN_TYPES.get(content_type)]
        if node.tag == f"{{{_CONTENT_TYPES_NS}}}Override"
        and mapping is not None
        and node.attrib.get("PartName", "") == mapping[1]
    }
    if len(formats) != 1:
        _unsafe("OOXML does not identify one supported Office main document type.")
    return formats.pop()


def _detect_legacy_format(path: Path) -> str:
    stream_names = _cfb_stream_names(path)
    found = {
        format_id
        for format_id, names in _LEGACY_STREAM_NAMES.items()
        if stream_names & names
    }
    if len(found) != 1:
        _unsafe("Legacy compound input does not identify one supported Office format.")
    return found.pop()


def _cfb_stream_names(path: Path) -> set[str]:
    """Read only the bounded FAT and directory chain of one MS-CFB file."""

    names: set[str] = set()
    try:
        with path.open("rb") as handle:
            header = handle.read(512)
            if len(header) != 512 or header[:8] != _CFB_SIGNATURE:
                _unsafe("Legacy compound input has an invalid CFB header.")
            major = _u16(header, 26)
            byte_order = _u16(header, 28)
            sector_shift = _u16(header, 30)
            if (
                byte_order != 0xFFFE
                or major not in {3, 4}
                or sector_shift != (9 if major == 3 else 12)
                or _u16(header, 32) != 6
            ):
                _unsafe("Legacy compound input uses an invalid CFB geometry.")
            sector_size = 1 << sector_shift
            file_bytes = path.stat().st_size
            if file_bytes > MAX_XLSX_BYTES:
                _unsafe("Legacy compound input exceeds its CFB byte ceiling.")
            if file_bytes < 512 + sector_size:
                _unsafe("Legacy compound input is truncated before its CFB sectors.")
            sector_count = file_bytes // sector_size - 1
            if file_bytes % sector_size or sector_count < 1:
                _unsafe("Legacy compound input is not aligned to its CFB sector size.")
            fat_count = _u32(header, 44)
            first_directory = _u32(header, 48)
            first_difat = _u32(header, 68)
            difat_count = _u32(header, 72)
            fat_entries_per_sector = sector_size // 4
            required_fat_count = (
                sector_count + fat_entries_per_sector - 1
            ) // fat_entries_per_sector
            required_difat_count = max(
                0,
                (
                    fat_count
                    - _CFB_HEADER_DIFAT_ENTRIES
                    + fat_entries_per_sector
                    - 2
                )
                // (fat_entries_per_sector - 1),
            )
            if (
                fat_count != required_fat_count
                or difat_count != required_difat_count
            ):
                _unsafe("Legacy compound input has invalid CFB allocation geometry.")
            fat_sector_ids = [
                value
                for value in struct.unpack_from(
                    f"<{_CFB_HEADER_DIFAT_ENTRIES}I",
                    header,
                    76,
                )
                if value != _CFB_FREE_SECTOR
            ]
            if len(fat_sector_ids) != min(
                fat_count,
                _CFB_HEADER_DIFAT_ENTRIES,
            ):
                _unsafe("Legacy compound input has an inconsistent FAT declaration.")
            current = first_difat
            seen_difat: set[int] = set()
            for _index in range(difat_count):
                _require_sector(current, sector_count, seen_difat, "DIFAT")
                seen_difat.add(current)
                payload = _read_cfb_sector(handle, current, sector_size)
                values = struct.unpack(f"<{sector_size // 4}I", payload)
                for value in values[:-1]:
                    if value == _CFB_FREE_SECTOR:
                        continue
                    if len(fat_sector_ids) >= fat_count:
                        _unsafe(
                            "Legacy compound input has an inconsistent FAT declaration."
                        )
                    fat_sector_ids.append(value)
                current = values[-1]
            if difat_count and current != _CFB_END_OF_CHAIN:
                _unsafe("Legacy compound input has an unterminated DIFAT chain.")
            if len(fat_sector_ids) != fat_count or len(set(fat_sector_ids)) != fat_count:
                _unsafe("Legacy compound input has an inconsistent FAT declaration.")
            for sector_id in fat_sector_ids:
                _require_sector(sector_id, sector_count, set(), "FAT")

            cached_fat_index = -1
            cached_fat_payload = b""

            def fat_entry(sector_id: int) -> int:
                nonlocal cached_fat_index, cached_fat_payload
                table_index, entry_index = divmod(
                    sector_id,
                    fat_entries_per_sector,
                )
                if table_index >= len(fat_sector_ids):
                    _unsafe("Legacy compound sector exceeds the FAT table.")
                if table_index != cached_fat_index:
                    cached_fat_payload = _read_cfb_sector(
                        handle,
                        fat_sector_ids[table_index],
                        sector_size,
                    )
                    cached_fat_index = table_index
                return _u32(cached_fat_payload, entry_index * 4)

            if any(
                fat_entry(sector_id) != _CFB_FAT_SECTOR
                for sector_id in fat_sector_ids
            ):
                _unsafe("Legacy compound input does not bind its FAT sectors.")
            if any(
                fat_entry(sector_id) != _CFB_DIFAT_SECTOR
                for sector_id in seen_difat
            ):
                _unsafe("Legacy compound input does not bind its DIFAT sectors.")
            current = first_directory
            seen_directory: set[int] = set()
            while current != _CFB_END_OF_CHAIN:
                if len(seen_directory) >= _MAX_CFB_DIRECTORY_SECTORS:
                    _unsafe(
                        "Legacy compound input exceeds its directory sector ceiling."
                    )
                _require_sector(current, sector_count, seen_directory, "directory")
                seen_directory.add(current)
                names.update(
                    _directory_stream_names(
                        _read_cfb_sector(handle, current, sector_size)
                    )
                )
                current = fat_entry(current)
                if current in {
                    _CFB_FREE_SECTOR,
                    _CFB_FAT_SECTOR,
                    _CFB_DIFAT_SECTOR,
                }:
                    _unsafe("Legacy compound directory has an invalid FAT chain.")
    except DocumentSkillsError:
        raise
    except (OSError, struct.error, UnicodeError) as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Legacy compound format detection failed closed.",
            details={"reason": type(error).__name__},
        ) from error
    return names


def _directory_stream_names(payload: bytes) -> set[str]:
    names: set[str] = set()
    for offset in range(0, len(payload), 128):
        entry = payload[offset : offset + 128]
        if len(entry) != 128 or entry[66] != 2:
            continue
        name_bytes = _u16(entry, 64)
        if name_bytes < 2 or name_bytes > 64 or name_bytes % 2:
            _unsafe("Legacy compound stream has an invalid directory name.")
        raw_name = bytes(entry[: name_bytes - 2])
        try:
            name = raw_name.decode("utf-16le", errors="strict")
        except UnicodeError as error:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Legacy compound stream name is not valid UTF-16LE.",
            ) from error
        if name in _LEGACY_STREAM_MARKERS:
            names.add(name)
    return names


def _read_cfb_sector(handle: BinaryIO, sector_id: int, sector_size: int) -> bytes:
    handle.seek(sector_size + sector_id * sector_size)
    payload = handle.read(sector_size)
    if len(payload) != sector_size:
        _unsafe("Legacy compound input has a truncated CFB sector.")
    return payload


def _require_sector(
    sector_id: int,
    sector_count: int,
    seen: set[int],
    chain: str,
) -> None:
    if sector_id >= sector_count or sector_id in seen:
        _unsafe(f"Legacy compound input has an invalid {chain} sector chain.")


def _u16(payload: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", payload, offset)[0]


def _u32(payload: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", payload, offset)[0]


def _assert_operation_accepts(operation: str, actual_format: str) -> None:
    accepted = _OPERATION_FORMATS.get(operation)
    if accepted is None or actual_format not in accepted:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "LibreOffice operation does not accept the detected input format.",
            status="invalid_request",
            details={
                "operation": operation,
                "actual_format": actual_format,
                "accepted_formats": sorted(accepted or ()),
            },
        )


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
