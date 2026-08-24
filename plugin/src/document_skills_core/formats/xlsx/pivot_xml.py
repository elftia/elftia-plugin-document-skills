"""OOXML part builders for a bounded worksheet-backed pivot table."""

from __future__ import annotations

from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS
from .pivot_model import PivotAxis, PivotBuild
from .summary_support import OutputCell

_MAIN_NS = NS["main"]


def build_cache_definition(pivot: PivotBuild, records_relationship_id: str) -> bytes:
    root = Element(
        _tag("pivotCacheDefinition"),
        {
            f"{{{NS['r']}}}id": records_relationship_id,
            "saveData": "1",
            "refreshOnLoad": "0",
            "enableRefresh": "1",
            "recordCount": str(pivot.record_count),
            "createdVersion": "3",
            "refreshedVersion": "3",
            "minRefreshableVersion": "3",
        },
    )
    source = SubElement(root, _tag("cacheSource"), {"type": "worksheet"})
    SubElement(
        source,
        _tag("worksheetSource"),
        {"ref": pivot.source_range, "sheet": pivot.source_sheet},
    )
    fields = SubElement(root, _tag("cacheFields"), {"count": str(len(pivot.cache_fields))})
    for field in pivot.cache_fields:
        cache_field = SubElement(fields, _tag("cacheField"), {"name": field.name, "numFmtId": "0"})
        shared = SubElement(cache_field, _tag("sharedItems"), _shared_attributes(field.items))
        for item in field.items:
            _append_value(shared, item)
    return _xml(root)


def build_cache_records(pivot: PivotBuild) -> bytes:
    root = Element(_tag("pivotCacheRecords"), {"count": str(pivot.record_count)})
    for record in pivot.cache_records:
        row = SubElement(root, _tag("r"))
        for index in record:
            SubElement(row, _tag("x"), {"v": str(index)})
    return _xml(root)


def build_table_definition(pivot: PivotBuild, cache_id: int) -> bytes:
    root = Element(
        _tag("pivotTableDefinition"),
        {
            "name": pivot.name,
            "cacheId": str(cache_id),
            "dataOnRows": "0",
            "dataCaption": "Values",
            "applyNumberFormats": "0",
            "applyBorderFormats": "0",
            "applyFontFormats": "0",
            "applyPatternFormats": "0",
            "applyAlignmentFormats": "0",
            "applyWidthHeightFormats": "0",
            "showDrill": "1",
            "useAutoFormatting": "0",
            "itemPrintTitles": "1",
            "indent": "0",
            "outline": "1",
            "outlineData": "1",
            "compact": "1",
            "compactData": "1",
            "createdVersion": "3",
            "updatedVersion": "3",
            "minRefreshableVersion": "3",
        },
    )
    location_attributes = {
        "ref": pivot.location_ref,
        "firstHeaderRow": "1" if pivot.column_axis is not None else "0",
        "firstDataRow": "2" if pivot.column_axis is not None else "1",
        "firstDataCol": "1",
    }
    if pivot.page_filter is not None:
        location_attributes.update({"rowPageCount": "1", "colPageCount": "1"})
    SubElement(root, _tag("location"), location_attributes)
    _append_pivot_fields(root, pivot)
    _append_axis(root, "row", pivot.row_axis)
    if pivot.column_axis is not None:
        _append_axis(root, "col", pivot.column_axis)
    if pivot.page_filter is not None:
        page_fields = SubElement(root, _tag("pageFields"), {"count": "1"})
        attributes = {"fld": str(pivot.page_filter.field_index), "hier": "-1"}
        if pivot.page_filter.selected_position is not None:
            attributes["item"] = str(pivot.page_filter.selected_position)
        SubElement(page_fields, _tag("pageField"), attributes)
    data_fields = SubElement(root, _tag("dataFields"), {"count": "1"})
    SubElement(
        data_fields,
        _tag("dataField"),
        {
            "name": pivot.value.alias,
            "fld": str(pivot.value.field_index),
            "subtotal": pivot.value.function,
            "numFmtId": "0",
        },
    )
    SubElement(
        root,
        _tag("pivotTableStyleInfo"),
        {
            "name": pivot.style,
            "showRowHeaders": "1",
            "showColHeaders": "1",
            "showRowStripes": "0",
            "showColStripes": "0",
            "showLastColumn": "1",
        },
    )
    return _xml(root)


def build_relationships(entries: list[tuple[str, str, str]]) -> bytes:
    root = Element(f"{{{NS['rels']}}}Relationships")
    for relationship_id, relationship_type, target in entries:
        SubElement(
            root,
            f"{{{NS['rels']}}}Relationship",
            {"Id": relationship_id, "Type": relationship_type, "Target": target},
        )
    return _xml(root)


def _append_pivot_fields(root: Element, pivot: PivotBuild) -> None:
    fields = SubElement(root, _tag("pivotFields"), {"count": str(len(pivot.cache_fields))})
    for index in range(len(pivot.cache_fields)):
        axis = _axis_for_field(pivot, index)
        attributes = {"compact": "0", "showAll": "0"}
        if axis is not None:
            axis_name, definition = axis
            attributes.update(
                {
                    "axis": axis_name,
                    "defaultSubtotal": "0",
                    "sortType": (
                        "ascending"
                        if getattr(definition, "sort", "asc") == "asc"
                        else "descending"
                    ),
                }
            )
        elif index == pivot.value.field_index:
            attributes["dataField"] = "1"
        field = SubElement(fields, _tag("pivotField"), attributes)
        item_indices = _field_item_indices(pivot, index)
        if item_indices is not None:
            items = SubElement(field, _tag("items"), {"count": str(len(item_indices))})
            for cache_index in item_indices:
                SubElement(items, _tag("item"), {"x": str(cache_index)})


def _append_axis(root: Element, prefix: str, axis: PivotAxis) -> None:
    fields = SubElement(root, _tag(f"{prefix}Fields"), {"count": "1"})
    SubElement(fields, _tag("field"), {"x": str(axis.field_index)})
    items = SubElement(
        root,
        _tag(f"{prefix}Items"),
        {"count": str(len(axis.visible_positions) + 1)},
    )
    for position in axis.visible_positions:
        item = SubElement(items, _tag("i"))
        SubElement(item, _tag("x"), {"v": str(position)})
    grand = SubElement(items, _tag("i"), {"t": "grand"})
    SubElement(grand, _tag("x"))


def _axis_for_field(pivot: PivotBuild, index: int) -> tuple[str, PivotAxis] | None:
    if pivot.row_axis.field_index == index:
        return "axisRow", pivot.row_axis
    if pivot.column_axis is not None and pivot.column_axis.field_index == index:
        return "axisCol", pivot.column_axis
    if pivot.page_filter is not None and pivot.page_filter.field_index == index:
        return "axisPage", pivot.page_filter  # type: ignore[return-value]
    return None


def _field_item_indices(pivot: PivotBuild, index: int) -> tuple[int, ...] | None:
    if pivot.row_axis.field_index == index:
        return pivot.row_axis.cache_indices
    if pivot.column_axis is not None and pivot.column_axis.field_index == index:
        return pivot.column_axis.cache_indices
    if pivot.page_filter is not None and pivot.page_filter.field_index == index:
        return pivot.page_filter.cache_indices
    return None


def _shared_attributes(items: tuple[OutputCell, ...]) -> dict[str, str]:
    kinds = {item.kind for item in items}
    attributes = {
        "count": str(len(items)),
        "containsBlank": _bool("empty" in kinds),
        "containsString": _bool("string" in kinds),
        "containsNumber": _bool("number" in kinds),
        "containsMixedTypes": _bool(len(kinds) > 1),
        "containsSemiMixedTypes": _bool(len(kinds) > 1),
    }
    numeric = [Decimal(item.value) for item in items if item.kind == "number"]
    if numeric:
        attributes["containsInteger"] = _bool(all(item == item.to_integral() for item in numeric))
        attributes["minValue"] = str(min(numeric))
        attributes["maxValue"] = str(max(numeric))
    return attributes


def _append_value(parent: Element, item: OutputCell) -> None:
    tags = {"empty": "m", "string": "s", "number": "n", "boolean": "b"}
    tag = tags[item.kind]
    attributes = {} if item.kind == "empty" else {"v": item.value}
    SubElement(parent, _tag(tag), attributes)


def _tag(local: str) -> str:
    return f"{{{_MAIN_NS}}}{local}"


def _bool(value: bool) -> str:
    return "1" if value else "0"


def _xml(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)
