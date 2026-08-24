"""Semantic and relationship-chain validation for native pivot creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, REL_PIVOT_TABLE
from .format_policy import allowed_inert_categories, assert_package_matches_path, format_id
from .package import OpcPackage
from .pivot_model import PivotBuild
from .pivot_package import PivotPackageParts
from .pivot_projection import project_pivot_tables

_PIVOT_TABLE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotTable+xml"
)
_CACHE_DEFINITION_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"
)
_CACHE_RECORDS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheRecords+xml"
)


def assert_pivot_written(
    path: Path,
    pivot: PivotBuild,
    parts: PivotPackageParts,
) -> dict[str, Any]:
    package = OpcPackage.open(
        path,
        allowed_inert_categories=allowed_inert_categories(format_id(path)),
    )
    assert_package_matches_path(path, package.workbook_format)
    matches = [item for item in project_pivot_tables(package) if item["name"] == pivot.name]
    if len(matches) != 1:
        _failed("Created native pivot table was not found exactly once.", name=pivot.name)
    actual = matches[0]
    expected_rows = [
        {
            "column": pivot.row_axis.column,
            "field_index": pivot.row_axis.field_index,
            "sort": pivot.row_axis.sort,
        }
    ]
    expected_columns = []
    if pivot.column_axis is not None:
        expected_columns.append(
            {
                "column": pivot.column_axis.column,
                "field_index": pivot.column_axis.field_index,
                "sort": pivot.column_axis.sort,
            }
        )
    expected_filters = []
    if pivot.page_filter is not None:
        selected = (
            None
            if pivot.page_filter.selected_position is None
            else _project_item(pivot.page_filter.items[pivot.page_filter.selected_position])
        )
        expected_filters.append(
            {
                "column": pivot.page_filter.column,
                "field_index": pivot.page_filter.field_index,
                "selected": selected,
            }
        )
    expected_values = [
        {
            "column": pivot.value.column,
            "field_index": pivot.value.field_index,
            "function": pivot.value.function,
            "as": pivot.value.alias,
        }
    ]
    expected_parts = parts.as_dict()
    failures: list[str] = []
    comparisons = {
        "native": actual["native"] is True,
        "sheet": actual["sheet"] == pivot.target_sheet,
        "location": actual["location"] == pivot.location_ref,
        "style": actual["style"] == pivot.style,
        "source": actual["source"]
        == {"sheet": pivot.source_sheet, "range": pivot.source_range},
        "rows": actual["rows"] == expected_rows,
        "columns": actual["columns"] == expected_columns,
        "filters": actual["filters"] == expected_filters,
        "values": actual["values"] == expected_values,
        "cache-id": actual["cache_id"] == parts.cache_id,
        "cache-record-count": actual["cache"]["record_count"] == pivot.record_count,
        "cache-records-written": actual["cache"]["records_written"] == pivot.record_count,
        "cache-fields": actual["cache"]["fields"] == list(pivot.source_headers),
        "workbook-cache-relationship": actual["cache"]["workbook_relationship_matches"],
        "pivot-table-part": actual["parts"]["pivot_table"] == expected_parts["pivot_table_part"],
        "cache-definition-part": actual["parts"]["cache_definition"]
        == expected_parts["cache_definition_part"],
        "cache-records-part": actual["parts"]["cache_records"]
        == expected_parts["cache_records_part"],
        "pivot-content-type": actual["content_types"]["pivot_table"]
        == _PIVOT_TABLE_CONTENT_TYPE,
        "cache-definition-content-type": actual["content_types"]["cache_definition"]
        == _CACHE_DEFINITION_CONTENT_TYPE,
        "cache-records-content-type": actual["content_types"]["cache_records"]
        == _CACHE_RECORDS_CONTENT_TYPE,
        "worksheet-pivot-reference": _worksheet_reference_matches(package, parts),
        "cache-records-reference": _cache_records_reference_matches(package, parts),
    }
    failures.extend(name for name, matched in comparisons.items() if not matched)
    if failures:
        _failed(
            "Created native pivot table failed semantic readback.",
            name=pivot.name,
            missing_or_mismatched=failures,
        )
    return {
        "native_pivot": True,
        "name": pivot.name,
        "cache_id": parts.cache_id,
        "record_count": pivot.record_count,
        "relationship_chain_complete": True,
        "parts": actual["parts"],
    }


def _worksheet_reference_matches(package: OpcPackage, parts: PivotPackageParts) -> bool:
    relationship = next(
        (
            item
            for item in package.relationships
            if item.source_part == parts.target_sheet_part
            and item.relationship_type == REL_PIVOT_TABLE
            and item.resolved_target == parts.pivot_table
        ),
        None,
    )
    if relationship is None:
        return False
    worksheet = package.xml(parts.target_sheet_part)
    return any(
        item.attrib.get(f"{{{NS['r']}}}id") == relationship.relationship_id
        for item in worksheet.findall(
            f".//{{{NS['main']}}}pivotTableParts/{{{NS['main']}}}pivotTablePart"
        )
    )


def _cache_records_reference_matches(package: OpcPackage, parts: PivotPackageParts) -> bool:
    relationship = next(
        (
            item
            for item in package.relationships
            if item.source_part == parts.cache_definition
            and item.resolved_target == parts.cache_records
            and item.relationship_type.rsplit("/", 1)[-1] == "pivotCacheRecords"
        ),
        None,
    )
    if relationship is None:
        return False
    root = package.xml(parts.cache_definition)
    return root.attrib.get(f"{{{NS['r']}}}id") == relationship.relationship_id


def _project_item(item: Any) -> dict[str, str]:
    return {"kind": item.kind, "value": item.value}


def _failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)
