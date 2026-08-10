"""Standalone bounded OOXML checks implemented without producer readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import posixpath
from typing import Any
from urllib.parse import unquote, urlsplit
import zipfile

from defusedxml.ElementTree import fromstring


_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 4096
_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RELATIONSHIP_ATTRIBUTES = {
    f"{{{_DOC_REL}}}embed",
    f"{{{_DOC_REL}}}id",
    f"{{{_DOC_REL}}}link",
}
_ACTIVE_RELATIONSHIP_MARKERS = (
    "/activex",
    "/attachedtemplate",
    "/control",
    "/externallink",
    "/oleobject",
    "/vbaproject",
)
_ACTIVE_CONTENT_TYPE_MARKERS = (
    "activex",
    "externallink",
    "macroenabled",
    "oleobject",
    "vbaproject",
)
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
class Relationship:
    relationship_id: str
    relationship_type: str
    target: str
    owner: str
    relationship_part: str


@dataclass(frozen=True)
class PackageSnapshot:
    names: frozenset[str]
    xml: dict[str, Any]
    total_bytes: int


RelationshipGraph = dict[str, dict[str, Relationship]]


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
        graph, _ = _validate_relationship_graph(snapshot, assertions)
        _validate_content_types(snapshot, format_id, assertions)
        _validate_root_relationship(graph, format_id, assertions)
        _validate_relationship_references(snapshot, graph, assertions)
        _validate_critical_relationships(snapshot, graph, format_id, assertions)
        if format_id == "docx":
            _docx_assertions(snapshot, expectations, assertions)
        elif format_id == "xlsx":
            _xlsx_assertions(snapshot, graph, expectations, assertions)
        else:
            _pptx_assertions(snapshot, graph, expectations, assertions)
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
            if name in names:
                raise ValueError(f"duplicate-archive-entry:{name}")
            total += info.file_size
            if total > _MAX_ARCHIVE_BYTES:
                raise ValueError("archive-uncompressed-size-limit")
            names.add(name)
            if name.endswith((".xml", ".rels")):
                xml[name] = fromstring(archive.read(info))
    return PackageSnapshot(frozenset(names), xml, total)


def _validate_relationship_graph(
    snapshot: PackageSnapshot,
    assertions: list[dict[str, Any]],
) -> tuple[RelationshipGraph, bool]:
    graph: RelationshipGraph = {}
    issues: list[dict[str, str]] = []
    relationship_count = 0
    relationship_parts = sorted(name for name in snapshot.names if name.endswith(".rels"))
    for part in relationship_parts:
        try:
            owner = _relationship_owner(part)
        except ValueError as error:
            issues.append({"part": part, "category": str(error)})
            continue
        if owner and owner not in snapshot.names:
            issues.append({"part": part, "category": "missing-relationship-owner", "owner": owner})
        root = snapshot.xml.get(part)
        if root is None:
            issues.append({"part": part, "category": "unparsed-relationships"})
            continue
        elements = root.findall(f"{{{_PACKAGE_REL}}}Relationship")
        if not elements:
            issues.append({"part": part, "category": "empty-relationships"})
        relationships: dict[str, Relationship] = {}
        for element in elements:
            relationship_count += 1
            relationship_id = element.attrib.get("Id", "").strip()
            relationship_type = element.attrib.get("Type", "").strip()
            target = element.attrib.get("Target", "").strip()
            target_mode = element.attrib.get("TargetMode", "").strip()
            if not relationship_id or not relationship_type or not target:
                issues.append(
                    {
                        "part": part,
                        "category": "empty-relationship-field",
                        "id": relationship_id,
                    }
                )
                continue
            if relationship_id in relationships:
                issues.append(
                    {
                        "part": part,
                        "category": "duplicate-relationship-id",
                        "id": relationship_id,
                    }
                )
                continue
            if target_mode:
                issues.append(
                    {
                        "part": part,
                        "category": "external-relationship",
                        "id": relationship_id,
                        "target_mode": target_mode,
                    }
                )
                continue
            if any(marker in relationship_type.casefold() for marker in _ACTIVE_RELATIONSHIP_MARKERS):
                issues.append(
                    {
                        "part": part,
                        "category": "active-or-updateable-relationship",
                        "id": relationship_id,
                    }
                )
                continue
            try:
                normalized = _resolve_relationship_target(owner, target)
            except ValueError as error:
                issues.append(
                    {
                        "part": part,
                        "category": str(error),
                        "id": relationship_id,
                    }
                )
                continue
            if normalized not in snapshot.names:
                issues.append(
                    {
                        "part": part,
                        "category": "dangling-relationship-target",
                        "id": relationship_id,
                        "target": normalized,
                    }
                )
                continue
            relationships[relationship_id] = Relationship(
                relationship_id=relationship_id,
                relationship_type=relationship_type,
                target=normalized,
                owner=owner,
                relationship_part=part,
            )
        graph[owner] = relationships
    _record(
        assertions,
        "ooxml.relationship-graph",
        not issues,
        {
            "relationship_parts": len(relationship_parts),
            "relationships": relationship_count,
            "issues": issues[:64],
            "issues_truncated": max(0, len(issues) - 64),
        },
    )
    return graph, not issues


def _relationship_owner(part: str) -> str:
    if part == "_rels/.rels":
        return ""
    pieces = list(PurePosixPath(part).parts)
    if len(pieces) < 2 or pieces[-2] != "_rels" or not pieces[-1].endswith(".rels"):
        raise ValueError("invalid-relationship-part")
    owner_name = pieces[-1][: -len(".rels")]
    if not owner_name:
        raise ValueError("empty-relationship-owner")
    return PurePosixPath(*pieces[:-2], owner_name).as_posix()


def _resolve_relationship_target(owner: str, target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("unsafe-relationship-target")
    decoded = unquote(parsed.path)
    if not decoded or "\\" in decoded or "\x00" in decoded:
        raise ValueError("unsafe-relationship-target")
    normalized = posixpath.normpath(
        decoded.lstrip("/")
        if decoded.startswith("/")
        else posixpath.join(posixpath.dirname(owner), decoded)
    )
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ValueError("unsafe-relationship-target")
    return normalized


def _validate_root_relationship(
    graph: RelationshipGraph,
    format_id: str,
    assertions: list[dict[str, Any]],
) -> None:
    expected = {
        "docx": "word/document.xml",
        "xlsx": "xl/workbook.xml",
        "pptx": "ppt/presentation.xml",
    }[format_id]
    office_targets = [
        item.target
        for item in graph.get("", {}).values()
        if item.relationship_type.endswith("/officeDocument")
    ]
    _record(
        assertions,
        "ooxml.office-document-relationship",
        office_targets == [expected],
        {"expected": expected, "actual": office_targets},
    )


def _validate_relationship_references(
    snapshot: PackageSnapshot,
    graph: RelationshipGraph,
    assertions: list[dict[str, Any]],
) -> None:
    missing: list[dict[str, str]] = []
    checked = 0
    for part, root in snapshot.xml.items():
        if part.endswith(".rels") or part == "[Content_Types].xml":
            continue
        relationships = graph.get(part, {})
        for element in root.iter():
            for attribute, relationship_id in element.attrib.items():
                if attribute not in _RELATIONSHIP_ATTRIBUTES:
                    continue
                checked += 1
                if not relationship_id or relationship_id not in relationships:
                    missing.append({"part": part, "id": relationship_id})
    _record(
        assertions,
        "ooxml.relationship-references",
        not missing,
        {"checked": checked, "missing": missing[:64]},
    )


def _validate_critical_relationships(
    snapshot: PackageSnapshot,
    graph: RelationshipGraph,
    format_id: str,
    assertions: list[dict[str, Any]],
) -> None:
    issues: list[dict[str, Any]] = []
    if format_id == "docx":
        relationships = graph.get("word/document.xml", {})
        if not _targets_by_type(relationships, "/styles"):
            issues.append({"owner": "word/document.xml", "missing_type": "/styles"})
    elif format_id == "xlsx":
        relationships = graph.get("xl/workbook.xml", {})
        if not _targets_by_type(relationships, "/styles"):
            issues.append({"owner": "xl/workbook.xml", "missing_type": "/styles"})
        workbook = snapshot.xml["xl/workbook.xml"]
        for sheet in workbook.findall(".//s:sheet", _NS):
            relationship_id = sheet.attrib.get(f"{{{_DOC_REL}}}id", "")
            relationship = relationships.get(relationship_id)
            if relationship is None or not relationship.relationship_type.endswith("/worksheet"):
                issues.append(
                    {
                        "owner": "xl/workbook.xml",
                        "id": relationship_id,
                        "expected_type": "/worksheet",
                    }
                )
    else:
        presentation_relationships = graph.get("ppt/presentation.xml", {})
        slide_parts = _targets_by_type(presentation_relationships, "/slide")
        master_parts = _targets_by_type(presentation_relationships, "/slideMaster")
        if not slide_parts:
            issues.append({"owner": "ppt/presentation.xml", "missing_type": "/slide"})
        if not master_parts:
            issues.append({"owner": "ppt/presentation.xml", "missing_type": "/slideMaster"})
        for slide_part in slide_parts:
            layouts = _targets_by_type(graph.get(slide_part, {}), "/slideLayout")
            if len(layouts) != 1:
                issues.append(
                    {"owner": slide_part, "expected_type": "/slideLayout", "actual": layouts}
                )
        layout_parts = {
            layout
            for master_part in master_parts
            for layout in _targets_by_type(graph.get(master_part, {}), "/slideLayout")
        }
        for slide_part in slide_parts:
            layout_parts.update(_targets_by_type(graph.get(slide_part, {}), "/slideLayout"))
        for layout_part in sorted(layout_parts):
            masters = _targets_by_type(graph.get(layout_part, {}), "/slideMaster")
            if len(masters) != 1:
                issues.append(
                    {"owner": layout_part, "expected_type": "/slideMaster", "actual": masters}
                )
            elif masters[0] not in master_parts:
                issues.append(
                    {"owner": layout_part, "unexpected_master": masters[0]}
                )
            elif layout_part not in _targets_by_type(graph.get(masters[0], {}), "/slideLayout"):
                issues.append(
                    {"owner": layout_part, "missing_master_back_reference": masters[0]}
                )
        for master_part in master_parts:
            themes = _targets_by_type(graph.get(master_part, {}), "/theme")
            layouts = _targets_by_type(graph.get(master_part, {}), "/slideLayout")
            if len(themes) != 1:
                issues.append(
                    {"owner": master_part, "expected_type": "/theme", "actual": themes}
                )
            if not layouts:
                issues.append({"owner": master_part, "missing_type": "/slideLayout"})
    _record(
        assertions,
        "ooxml.critical-relationship-closure",
        not issues,
        {"format": format_id, "issues": issues[:64]},
    )


def _targets_by_type(
    relationships: dict[str, Relationship],
    relationship_type_suffix: str,
) -> list[str]:
    return [
        relationship.target
        for relationship in relationships.values()
        if relationship.relationship_type.endswith(relationship_type_suffix)
    ]


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
    defaults = [
        child.attrib.get("ContentType", "")
        for child in root
        if child.tag.endswith("Default")
    ]
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
    active = sorted(
        content_type
        for content_type in [*overrides.values(), *defaults]
        if any(marker in content_type.casefold() for marker in _ACTIVE_CONTENT_TYPE_MARKERS)
    )
    _record(
        assertions,
        "ooxml.content-types",
        not missing and not active,
        {"missing_overrides": missing, "active_or_external": active},
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
    graph: RelationshipGraph,
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    workbook = snapshot.xml["xl/workbook.xml"]
    relationships = graph.get("xl/workbook.xml", {})
    shared_strings = _shared_strings(snapshot)
    sheet_parts: dict[str, str] = {}
    for sheet in workbook.findall(".//s:sheet", _NS):
        name = sheet.attrib.get("name", "")
        relationship_id = sheet.attrib.get(f"{{{_DOC_REL}}}id", "")
        relationship = relationships.get(relationship_id)
        if relationship is not None and relationship.relationship_type.endswith("/worksheet"):
            sheet_parts[name] = relationship.target
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
    graph: RelationshipGraph,
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    presentation = snapshot.xml["ppt/presentation.xml"]
    relationships = graph.get("ppt/presentation.xml", {})
    slide_ids = presentation.findall(".//p:sldIdLst/p:sldId", _NS)
    slide_parts: list[str] = []
    for slide_id in slide_ids:
        relationship_id = slide_id.attrib.get(f"{{{_DOC_REL}}}id", "")
        relationship = relationships.get(relationship_id)
        if relationship is not None and relationship.relationship_type.endswith("/slide"):
            slide_parts.append(relationship.target)
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
        "consumer": "stdlib-zip-defusedxml/2",
        "availability": "available",
        "outcome": "fail" if failed else "pass",
        "assertions": assertions,
        "warnings": [],
        "evidence": evidence,
    }
