"""Copy-through package registration for native pivot/cache OOXML parts."""

from __future__ import annotations

from dataclasses import dataclass
import posixpath
import re
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    NS,
    REL_PIVOT_CACHE,
    REL_PIVOT_TABLE,
    WORKBOOK_MAIN,
    WORKBOOK_RELS,
)
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest
from .pivot_model import PivotBuild
from .pivot_xml import (
    build_cache_definition,
    build_cache_records,
    build_relationships,
    build_table_definition,
)

_CACHE_RECORDS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheRecords"
)
_PIVOT_TABLE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotTable+xml"
)
_CACHE_DEFINITION_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"
)
_CACHE_RECORDS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheRecords+xml"
)
_PART_INDEX = re.compile(r"(\d+)\.xml$")


@dataclass(frozen=True)
class PivotPackageParts:
    cache_id: int
    pivot_table: str
    cache_definition: str
    cache_records: str
    target_sheet_part: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "cache_id": self.cache_id,
            "pivot_table_part": self.pivot_table,
            "cache_definition_part": self.cache_definition,
            "cache_records_part": self.cache_records,
            "target_sheet_part": self.target_sheet_part,
        }


def append_pivot_parts(
    package: OpcPackage,
    destination: str | Path,
    pivot: PivotBuild,
) -> tuple[PreservationManifest, PivotPackageParts]:
    """Attach one real pivot table, cache definition, and cache record set."""

    _assert_unique_pivot_name(package, pivot.name)
    target_sheet_part = _sheet_part(package, pivot.target_sheet)
    part_index = _next_part_index(package.parts)
    pivot_table_part = f"xl/pivotTables/pivotTable{part_index}.xml"
    cache_definition_part = f"xl/pivotCache/pivotCacheDefinition{part_index}.xml"
    cache_records_part = f"xl/pivotCache/pivotCacheRecords{part_index}.xml"
    cache_id = _next_cache_id(package)

    workbook = package.xml(WORKBOOK_MAIN)
    workbook_rels = package.xml(WORKBOOK_RELS)
    worksheet = package.xml(target_sheet_part)
    content_types = package.xml(CONTENT_TYPES)
    workbook_rel_id = _append_relationship(
        workbook_rels,
        REL_PIVOT_CACHE,
        posixpath.relpath(cache_definition_part, posixpath.dirname(WORKBOOK_MAIN)),
    )
    _append_workbook_cache(workbook, cache_id, workbook_rel_id)

    sheet_rels_part = _relationship_part(target_sheet_part)
    sheet_rels_exists = sheet_rels_part in package.parts
    sheet_rels = package.xml(sheet_rels_part) if sheet_rels_exists else _relationships_root()
    _append_relationship(
        sheet_rels,
        REL_PIVOT_TABLE,
        posixpath.relpath(pivot_table_part, posixpath.dirname(target_sheet_part)),
    )

    _append_override(content_types, pivot_table_part, _PIVOT_TABLE_CONTENT_TYPE)
    _append_override(content_types, cache_definition_part, _CACHE_DEFINITION_CONTENT_TYPE)
    _append_override(content_types, cache_records_part, _CACHE_RECORDS_CONTENT_TYPE)

    pivot_rels_part = _relationship_part(pivot_table_part)
    cache_rels_part = _relationship_part(cache_definition_part)
    additions = {
        pivot_table_part: build_table_definition(pivot, cache_id),
        pivot_rels_part: build_relationships(
            [
                (
                    "rId1",
                    REL_PIVOT_CACHE,
                    posixpath.relpath(cache_definition_part, posixpath.dirname(pivot_table_part)),
                )
            ]
        ),
        cache_definition_part: build_cache_definition(pivot, "rId1"),
        cache_rels_part: build_relationships(
            [
                (
                    "rId1",
                    _CACHE_RECORDS_REL,
                    posixpath.relpath(cache_records_part, posixpath.dirname(cache_definition_part)),
                )
            ]
        ),
        cache_records_part: build_cache_records(pivot),
    }
    changed = {
        WORKBOOK_MAIN: _xml(workbook),
        WORKBOOK_RELS: _xml(workbook_rels),
        target_sheet_part: _xml(worksheet),
        CONTENT_TYPES: _xml(content_types),
    }
    if sheet_rels_exists:
        changed[sheet_rels_part] = _xml(sheet_rels)
    else:
        additions[sheet_rels_part] = _xml(sheet_rels)
    manifest = package.write_copy(
        destination,
        changed_parts=changed,
        added_parts=additions,
    )
    return manifest, PivotPackageParts(
        cache_id,
        pivot_table_part,
        cache_definition_part,
        cache_records_part,
        target_sheet_part,
    )


def _append_workbook_cache(root: Element, cache_id: int, relationship_id: str) -> None:
    container = root.find(f"{{{NS['main']}}}pivotCaches")
    if container is None:
        container = Element(f"{{{NS['main']}}}pivotCaches")
        _insert_before(root, container, {"extLst"})
    SubElement(
        container,
        f"{{{NS['main']}}}pivotCache",
        {"cacheId": str(cache_id), f"{{{NS['r']}}}id": relationship_id},
    )


def _append_relationship(root: Element, relationship_type: str, target: str) -> str:
    relationship_id = _next_relationship_id(root)
    SubElement(
        root,
        f"{{{NS['rels']}}}Relationship",
        {"Id": relationship_id, "Type": relationship_type, "Target": target},
    )
    return relationship_id


def _append_override(root: Element, part: str, content_type: str) -> None:
    part_name = f"/{part}"
    if any(
        child.attrib.get("PartName") == part_name
        for child in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
    ):
        _invalid("Pivot package part content type already exists.", part=part)
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": part_name, "ContentType": content_type},
    )


def _sheet_part(package: OpcPackage, sheet_name: str) -> str:
    workbook = map_workbook(package)
    sheet = next((item for item in workbook["sheets"] if item["name"] == sheet_name), None)
    if sheet is None or not sheet.get("part"):
        _invalid("Pivot target worksheet relationship was not found.", sheet=sheet_name)
    return sheet["part"]


def _assert_unique_pivot_name(package: OpcPackage, name: str) -> None:
    for part in package.parts:
        if part.startswith("xl/pivotTables/") and part.endswith(".xml"):
            root = package.xml(part)
            if root.attrib.get("name", "").casefold() == name.casefold():
                _invalid("Pivot table name already exists.", name=name)


def _next_cache_id(package: OpcPackage) -> int:
    root = package.xml(WORKBOOK_MAIN)
    values = [
        int(item.attrib["cacheId"])
        for item in root.findall(f".//{{{NS['main']}}}pivotCache")
        if item.attrib.get("cacheId", "").isdigit()
    ]
    return max(values, default=0) + 1


def _next_part_index(parts: dict[str, bytes]) -> int:
    used: set[int] = set()
    for name in parts:
        if name.startswith(("xl/pivotTables/pivotTable", "xl/pivotCache/pivotCache")):
            match = _PART_INDEX.search(name)
            if match is not None:
                used.add(int(match.group(1)))
    result = 1
    while result in used:
        result += 1
    return result


def _next_relationship_id(root: Element) -> str:
    used = {item.attrib.get("Id", "") for item in root}
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def _relationship_part(source_part: str) -> str:
    directory, name = posixpath.split(source_part)
    return posixpath.join(directory, "_rels", f"{name}.rels")


def _relationships_root() -> Element:
    return Element(f"{{{NS['rels']}}}Relationships")


def _insert_before(root: Element, child: Element, terminal_names: set[str]) -> None:
    for index, existing in enumerate(root):
        if existing.tag.rsplit("}", 1)[-1] in terminal_names:
            root.insert(index, child)
            return
    root.append(child)


def _xml(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
