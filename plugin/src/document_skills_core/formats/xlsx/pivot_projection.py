"""Relationship-aware native pivot table and cache readback projection."""

from __future__ import annotations

from typing import Any

from .constants import NS, REL_PIVOT_CACHE, REL_PIVOT_TABLE, WORKBOOK_MAIN

_MAIN_NS = NS["main"]
_CACHE_RECORDS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheRecords"
)


def project_pivot_tables(package: Any) -> list[dict[str, Any]]:
    """Project each worksheet-owned pivot through its complete relationship chain."""

    sheet_names = _sheet_names(package)
    workbook_caches = _workbook_caches(package)
    result: list[dict[str, Any]] = []
    for relationship in package.relationships:
        if relationship.relationship_type != REL_PIVOT_TABLE or not relationship.resolved_target:
            continue
        table_part = relationship.resolved_target
        table = package.xml(table_part)
        cache_id = _integer(table.attrib.get("cacheId"), -1)
        cache_part = _related_part(package, table_part, REL_PIVOT_CACHE)
        workbook_cache_part = workbook_caches.get(cache_id)
        cache = package.xml(cache_part) if cache_part else None
        records_part = (
            _related_part(package, cache_part, _CACHE_RECORDS_REL) if cache_part else None
        )
        records = package.xml(records_part) if records_part else None
        fields = _cache_fields(cache)
        pivot_fields = table.find(f"{{{_MAIN_NS}}}pivotFields")
        location = table.find(f"{{{_MAIN_NS}}}location")
        style = table.find(f"{{{_MAIN_NS}}}pivotTableStyleInfo")
        result.append(
            {
                "native": True,
                "name": table.attrib.get("name", ""),
                "sheet": sheet_names.get(relationship.source_part, ""),
                "location": "" if location is None else location.attrib.get("ref", ""),
                "style": "" if style is None else style.attrib.get("name", ""),
                "cache_id": cache_id,
                "source": _cache_source(cache),
                "rows": _axis_fields(table, pivot_fields, fields, "rowFields"),
                "columns": _axis_fields(table, pivot_fields, fields, "colFields"),
                "filters": _page_fields(table, pivot_fields, fields),
                "values": _data_fields(table, fields),
                "cache": {
                    "record_count": _integer(cache.attrib.get("recordCount") if cache is not None else None, 0),
                    "records_written": (
                        len(records.findall(f"{{{_MAIN_NS}}}r")) if records is not None else 0
                    ),
                    "fields": [field["name"] for field in fields],
                    "workbook_relationship_matches": workbook_cache_part == cache_part,
                },
                "parts": {
                    "worksheet": relationship.source_part,
                    "pivot_table": table_part,
                    "cache_definition": cache_part,
                    "cache_records": records_part,
                },
                "content_types": {
                    "pivot_table": package.content_type_for(table_part) or "",
                    "cache_definition": package.content_type_for(cache_part) if cache_part else "",
                    "cache_records": package.content_type_for(records_part) if records_part else "",
                },
            }
        )
    return sorted(result, key=lambda item: (item["sheet"], item["name"]))


def _sheet_names(package: Any) -> dict[str, str]:
    workbook = package.xml(WORKBOOK_MAIN)
    relationships = {
        item.relationship_id: item
        for item in package.relationships
        if item.source_part == WORKBOOK_MAIN
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = relationships.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is not None and relationship.resolved_target:
            result[relationship.resolved_target] = sheet.attrib.get("name", "")
    return result


def _workbook_caches(package: Any) -> dict[int, str]:
    workbook = package.xml(WORKBOOK_MAIN)
    relationships = {
        item.relationship_id: item
        for item in package.relationships
        if item.source_part == WORKBOOK_MAIN and item.relationship_type == REL_PIVOT_CACHE
    }
    result: dict[int, str] = {}
    for cache in workbook.findall(f".//{{{_MAIN_NS}}}pivotCache"):
        cache_id = _integer(cache.attrib.get("cacheId"), -1)
        relationship = relationships.get(cache.attrib.get(f"{{{NS['r']}}}id", ""))
        if cache_id >= 0 and relationship is not None and relationship.resolved_target:
            result[cache_id] = relationship.resolved_target
    return result


def _related_part(package: Any, source: str, relationship_type: str) -> str | None:
    matches = [
        item.resolved_target
        for item in package.relationships
        if item.source_part == source
        and item.relationship_type == relationship_type
        and item.resolved_target
    ]
    return matches[0] if len(matches) == 1 else None


def _cache_source(cache: Any | None) -> dict[str, str]:
    if cache is None:
        return {"sheet": "", "range": ""}
    source = cache.find(f".//{{{_MAIN_NS}}}worksheetSource")
    if source is None:
        return {"sheet": "", "range": ""}
    return {"sheet": source.attrib.get("sheet", ""), "range": source.attrib.get("ref", "")}


def _cache_fields(cache: Any | None) -> list[dict[str, Any]]:
    if cache is None:
        return []
    result: list[dict[str, Any]] = []
    for field in cache.findall(f".//{{{_MAIN_NS}}}cacheFields/{{{_MAIN_NS}}}cacheField"):
        shared = field.find(f"{{{_MAIN_NS}}}sharedItems")
        result.append(
            {
                "name": field.attrib.get("name", ""),
                "items": [] if shared is None else [_shared_item(item) for item in shared],
            }
        )
    return result


def _axis_fields(
    table: Any,
    pivot_fields: Any | None,
    cache_fields: list[dict[str, Any]],
    container_name: str,
) -> list[dict[str, Any]]:
    container = table.find(f"{{{_MAIN_NS}}}{container_name}")
    if container is None:
        return []
    result: list[dict[str, Any]] = []
    for field in container.findall(f"{{{_MAIN_NS}}}field"):
        index = _integer(field.attrib.get("x"), -1)
        pivot_field = _child(pivot_fields, index)
        result.append(
            {
                "column": _field_name(cache_fields, index),
                "field_index": index,
                "sort": _sort_value(pivot_field),
            }
        )
    return result


def _page_fields(
    table: Any,
    pivot_fields: Any | None,
    cache_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    container = table.find(f"{{{_MAIN_NS}}}pageFields")
    if container is None:
        return []
    result: list[dict[str, Any]] = []
    for field in container.findall(f"{{{_MAIN_NS}}}pageField"):
        index = _integer(field.attrib.get("fld"), -1)
        item_position = _optional_integer(field.attrib.get("item"))
        selected = _selected_page_item(pivot_fields, cache_fields, index, item_position)
        result.append(
            {
                "column": _field_name(cache_fields, index),
                "field_index": index,
                "selected": selected,
            }
        )
    return result


def _data_fields(table: Any, cache_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for field in table.findall(f".//{{{_MAIN_NS}}}dataFields/{{{_MAIN_NS}}}dataField"):
        index = _integer(field.attrib.get("fld"), -1)
        result.append(
            {
                "column": _field_name(cache_fields, index),
                "field_index": index,
                "function": field.attrib.get("subtotal", "sum"),
                "as": field.attrib.get("name", ""),
            }
        )
    return result


def _selected_page_item(
    pivot_fields: Any | None,
    cache_fields: list[dict[str, Any]],
    field_index: int,
    item_position: int | None,
) -> dict[str, str] | None:
    if item_position is None:
        return None
    pivot_field = _child(pivot_fields, field_index)
    items = None if pivot_field is None else pivot_field.find(f"{{{_MAIN_NS}}}items")
    item = _child(items, item_position)
    cache_index = _integer(item.attrib.get("x") if item is not None else None, -1)
    if not 0 <= field_index < len(cache_fields):
        return None
    shared = cache_fields[field_index]["items"]
    return shared[cache_index] if 0 <= cache_index < len(shared) else None


def _shared_item(item: Any) -> dict[str, str]:
    kind = item.tag.rsplit("}", 1)[-1]
    kinds = {"m": "empty", "s": "string", "n": "number", "b": "boolean", "d": "date", "e": "error"}
    return {"kind": kinds.get(kind, kind), "value": item.attrib.get("v", "")}


def _sort_value(pivot_field: Any | None) -> str:
    value = "manual" if pivot_field is None else pivot_field.attrib.get("sortType", "manual")
    return {"ascending": "asc", "descending": "desc"}.get(value, value)


def _field_name(fields: list[dict[str, Any]], index: int) -> str:
    return fields[index]["name"] if 0 <= index < len(fields) else ""


def _child(parent: Any | None, index: int) -> Any | None:
    if parent is None or not 0 <= index < len(parent):
        return None
    return list(parent)[index]


def _optional_integer(value: str | None) -> int | None:
    return int(value) if value is not None and value.lstrip("-").isdigit() else None


def _integer(value: str | None, default: int) -> int:
    parsed = _optional_integer(value)
    return default if parsed is None else parsed
