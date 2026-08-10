"""Standalone bounded OOXML checks implemented without producer readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import posixpath
import zipfile

from defusedxml.ElementTree import fromstring


_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 4096
_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": _DOC_REL,
}
_REQUIRED = {
    "docx": {"[Content_Types].xml", "_rels/.rels", "word/document.xml"},
    "xlsx": {
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
    },
    "pptx": {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
        "ppt/theme/theme1.xml",
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideLayouts/slideLayout1.xml",
    },
}


@dataclass(frozen=True)
class PackageSnapshot:
    names: frozenset[str]
    xml: dict[str, Any]
    total_bytes: int


def qualify_ooxml(
    format_id: str,
    artifact: Path,
    expectations: dict[str, Any],
) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    try:
        snapshot = _read_package(artifact)
        missing = sorted(_REQUIRED[format_id] - snapshot.names)
        _record(
            assertions,
            "ooxml.required-parts",
            not missing,
            {"missing": missing, "entries": len(snapshot.names)},
        )
        if missing:
            return _gate(assertions, {"total_uncompressed_bytes": snapshot.total_bytes})
        _validate_root_relationship(snapshot, format_id, assertions)
        _validate_content_types(snapshot, format_id, assertions)
        if format_id == "docx":
            _docx_assertions(snapshot, expectations, assertions)
        elif format_id == "xlsx":
            _xlsx_assertions(snapshot, expectations, assertions)
        else:
            _pptx_assertions(snapshot, expectations, assertions)
        return _gate(assertions, {"total_uncompressed_bytes": snapshot.total_bytes})
    except Exception as error:
        _record(
            assertions,
            "ooxml.package-open",
            False,
            {"category": type(error).__name__, "message": str(error)[:256]},
        )
        return _gate(assertions, {})


def _read_package(path: Path) -> PackageSnapshot:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("artifact-missing-or-empty")
    if path.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise ValueError("artifact-size-limit")
    xml: dict[str, Any] = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > _MAX_ENTRIES:
            raise ValueError("archive-entry-limit")
        total = 0
        names: set[str] = set()
        for info in infos:
            name = info.filename.replace("\\", "/")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or not name:
                raise ValueError("unsafe-archive-path")
            total += info.file_size
            if total > _MAX_ARCHIVE_BYTES:
                raise ValueError("archive-uncompressed-size-limit")
            names.add(name)
            if name.endswith((".xml", ".rels")):
                xml[name] = fromstring(archive.read(info))
    return PackageSnapshot(frozenset(names), xml, total)


def _validate_root_relationship(
    snapshot: PackageSnapshot,
    format_id: str,
    assertions: list[dict[str, Any]],
) -> None:
    expected = {
        "docx": "word/document.xml",
        "xlsx": "xl/workbook.xml",
        "pptx": "ppt/presentation.xml",
    }[format_id]
    relationships = _relationships(snapshot, "_rels/.rels", "")
    office_targets = [
        item["target"]
        for item in relationships.values()
        if item["type"].endswith("/officeDocument")
    ]
    _record(
        assertions,
        "ooxml.office-document-relationship",
        expected in office_targets,
        {"expected": expected, "actual": office_targets},
    )


def _validate_content_types(
    snapshot: PackageSnapshot,
    format_id: str,
    assertions: list[dict[str, Any]],
) -> None:
    root = snapshot.xml["[Content_Types].xml"]
    overrides = {
        child.attrib.get("PartName", "").lstrip("/"): child.attrib.get("ContentType", "")
        for child in root
        if child.tag.endswith("Override")
    }
    required = {
        "docx": ["word/document.xml"],
        "xlsx": ["xl/workbook.xml"],
        "pptx": [
            "ppt/presentation.xml",
            "ppt/theme/theme1.xml",
            "ppt/slideMasters/slideMaster1.xml",
            "ppt/slideLayouts/slideLayout1.xml",
        ],
    }[format_id]
    missing = [name for name in required if name not in overrides]
    _record(
        assertions,
        "ooxml.content-types",
        not missing,
        {"missing_overrides": missing},
    )


def _docx_assertions(
    snapshot: PackageSnapshot,
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    document = snapshot.xml["word/document.xml"]
    text = "".join(node.text or "" for node in document.findall(".//w:t", _NS))
    requested = [str(value) for value in expectations.get("text", [])]
    missing = [value for value in requested if value not in text]
    _record(assertions, "docx.requested-text", not missing, {"missing": missing})
    expected_tables = int(expectations.get("tables", 0))
    actual_tables = len(document.findall(".//w:tbl", _NS))
    _record(
        assertions,
        "docx.tables",
        actual_tables >= expected_tables,
        {"expected_minimum": expected_tables, "actual": actual_tables},
    )


def _xlsx_assertions(
    snapshot: PackageSnapshot,
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    workbook = snapshot.xml["xl/workbook.xml"]
    relationships = _relationships(snapshot, "xl/_rels/workbook.xml.rels", "xl")
    shared_strings = _shared_strings(snapshot)
    sheet_parts: dict[str, str] = {}
    for sheet in workbook.findall(".//s:sheet", _NS):
        name = sheet.attrib.get("name", "")
        rel_id = sheet.attrib.get(f"{{{_DOC_REL}}}id", "")
        relationship = relationships.get(rel_id)
        if relationship is not None:
            sheet_parts[name] = relationship["target"]
    expected_sheets = [str(value) for value in expectations.get("sheets", [])]
    missing_sheets = [name for name in expected_sheets if name not in sheet_parts]
    _record(
        assertions,
        "xlsx.sheets",
        not missing_sheets,
        {"missing": missing_sheets, "actual": sorted(sheet_parts)},
    )
    mismatches: list[dict[str, Any]] = []
    for qualified_ref, expected in expectations.get("cells", {}).items():
        sheet_name, cell_ref = str(qualified_ref).split("!", 1)
        part = sheet_parts.get(sheet_name)
        actual = _cell_value(snapshot, part, cell_ref, shared_strings) if part else None
        if str(actual) != str(expected):
            mismatches.append({"cell": qualified_ref, "expected": expected, "actual": actual})
    _record(assertions, "xlsx.cells", not mismatches, {"mismatches": mismatches})


def _pptx_assertions(
    snapshot: PackageSnapshot,
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    presentation = snapshot.xml["ppt/presentation.xml"]
    relationships = _relationships(snapshot, "ppt/_rels/presentation.xml.rels", "ppt")
    slide_ids = presentation.findall(".//p:sldIdLst/p:sldId", _NS)
    slide_parts: list[str] = []
    for slide_id in slide_ids:
        rel_id = slide_id.attrib.get(f"{{{_DOC_REL}}}id", "")
        relationship = relationships.get(rel_id)
        if relationship is not None and relationship["type"].endswith("/slide"):
            slide_parts.append(relationship["target"])
    missing_slide_parts = [name for name in slide_parts if name not in snapshot.names]
    _record(
        assertions,
        "pptx.slide-relationships",
        bool(slide_parts) and not missing_slide_parts,
        {"slides": slide_parts, "missing": missing_slide_parts},
    )
    expected_count = int(expectations.get("slide_count", 0))
    _record(
        assertions,
        "pptx.slide-count",
        len(slide_parts) == expected_count,
        {"expected": expected_count, "actual": len(slide_parts)},
    )
    text = "".join(
        node.text or ""
        for part in slide_parts
        for node in snapshot.xml[part].findall(".//a:t", _NS)
    )
    requested = [str(value) for value in expectations.get("text", [])]
    missing = [value for value in requested if value not in text]
    _record(assertions, "pptx.requested-text", not missing, {"missing": missing})


def _relationships(
    snapshot: PackageSnapshot,
    part: str,
    base: str,
) -> dict[str, dict[str, str]]:
    root = snapshot.xml[part]
    result: dict[str, dict[str, str]] = {}
    for relationship in root.findall(f"{{{_PACKAGE_REL}}}Relationship"):
        if relationship.attrib.get("TargetMode") == "External":
            continue
        target = relationship.attrib.get("Target", "")
        normalized = posixpath.normpath(posixpath.join(base, target)).lstrip("/")
        result[relationship.attrib.get("Id", "")] = {
            "target": normalized,
            "type": relationship.attrib.get("Type", ""),
        }
    return result


def _shared_strings(snapshot: PackageSnapshot) -> list[str]:
    part = "xl/sharedStrings.xml"
    if part not in snapshot.xml:
        return []
    return [
        "".join(node.text or "" for node in item.findall(".//s:t", _NS))
        for item in snapshot.xml[part].findall("s:si", _NS)
    ]


def _cell_value(
    snapshot: PackageSnapshot,
    part: str,
    reference: str,
    shared_strings: list[str],
) -> str | None:
    worksheet = snapshot.xml.get(part)
    if worksheet is None:
        return None
    for cell in worksheet.findall(".//s:c", _NS):
        if cell.attrib.get("r") != reference:
            continue
        if cell.attrib.get("t") == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//s:t", _NS))
        value = cell.find("s:v", _NS)
        if value is None:
            return None
        if cell.attrib.get("t") == "s":
            try:
                return shared_strings[int(value.text or "-1")]
            except (IndexError, ValueError):
                return None
        return value.text
    return None


def _record(
    assertions: list[dict[str, Any]],
    assertion_id: str,
    passed: bool,
    evidence: dict[str, Any],
) -> None:
    assertions.append(
        {
            "id": assertion_id,
            "outcome": "pass" if passed else "fail",
            "evidence": evidence,
            "message": "" if passed else f"Independent assertion failed: {assertion_id}",
        }
    )


def _gate(assertions: list[dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    failed = any(item["outcome"] == "fail" for item in assertions)
    return {
        "consumer": "stdlib-zip-defusedxml/1",
        "availability": "available",
        "outcome": "fail" if failed else "pass",
        "assertions": assertions,
        "warnings": [],
        "evidence": evidence,
    }
