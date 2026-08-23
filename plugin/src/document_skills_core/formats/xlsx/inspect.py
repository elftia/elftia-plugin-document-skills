"""Inert structural inspection of XLSX package features."""

from pathlib import Path
from typing import Any

from .annotations import project_comments
from .constants import CALC_CHAIN_PART, NS, SHARED_STRINGS_PART, STYLES_PART
from .package import OpcPackage
from .projection import (
    project_charts,
    project_conditional_formats,
    project_data_validations,
    project_drawings,
    project_external_links,
    project_hyperlinks,
    project_pivot_caches,
    project_tables,
)
from .worksheet_metadata import project_worksheet_metadata
from .workbook_properties import project_workbook_properties


def inspect_xlsx(
    path: str | Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inspect an XLSX package structure inertly.

    Uses ``allow_dangerous_inventory=True`` so that dangerous content is inventoried
    but never executed or followed.
    """
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    include_hashes = arguments.get("include_hashes", True)
    warnings: list[dict[str, Any]] = []

    # Sorted part inventory with content types and hashes
    parts_inventory: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        entry: dict[str, Any] = {
            "name": name,
            "content_type": package.content_type_for(name) or "",
            "bytes": len(package.parts[name]),
        }
        if include_hashes:
            entry["sha256"] = package.part_hashes[name]
        parts_inventory.append(entry)

    # Content types
    content_types_list = sorted(
        ({"part": k, "content_type": v} for k, v in package.content_types.items()),
        key=lambda item: item["part"],
    )

    # Relationships inventory
    rels_list = sorted(
        (r.as_dict() for r in package.relationships),
        key=lambda r: (r["source_part"], r["id"]),
    )

    # Feature detection
    has_calc_chain = CALC_CHAIN_PART in package.parts
    has_shared_strings = SHARED_STRINGS_PART in package.parts
    has_styles = STYLES_PART in package.parts

    # Worksheet count
    worksheet_parts = package.worksheet_parts()

    # Dangerous content inventory from security preflight
    security = package.security
    dangerous_categories = security.get("categories", {})
    dangerous_present = security.get("dangerous", False)

    # Feature projections
    tables = project_tables(package)
    charts = project_charts(package)
    pivot_caches = project_pivot_caches(package)
    external_links = project_external_links(package)
    drawings = project_drawings(package)
    data_validations = project_data_validations(package)
    conditional_formats = project_conditional_formats(package)
    worksheet_metadata = project_worksheet_metadata(package)
    hyperlinks = []
    workbook = package.xml("xl/workbook.xml")
    workbook_relationships = {
        relationship.relationship_id: relationship
        for relationship in package.relationships
        if relationship.source_part == "xl/workbook.xml"
    }
    for sheet in workbook.findall(f".//{{{NS['main']}}}sheet"):
        relationship = workbook_relationships.get(
            sheet.attrib.get(f"{{{NS['r']}}}id", "")
        )
        if relationship is not None and relationship.resolved_target:
            hyperlinks.extend(
                project_hyperlinks(
                    package,
                    relationship.resolved_target,
                    sheet.attrib.get("name", ""),
                )
            )

    operation_result: dict[str, Any] = {
        "mutation_authorized": False,
        "security_summary": _project_security_summary(security),
        "parts": parts_inventory,
        "part_count": len(parts_inventory),
        "content_types": content_types_list,
        "relationships": rels_list,
        "worksheet_count": len(worksheet_parts),
        "worksheet_parts": worksheet_parts,
        "has_calc_chain": has_calc_chain,
        "has_shared_strings": has_shared_strings,
        "has_styles": has_styles,
        "tables": tables,
        "charts": charts,
        "pivot_caches": pivot_caches,
        "external_links": external_links,
        "drawings": drawings,
        "data_validations": data_validations,
        "conditional_formats": conditional_formats,
        "worksheet_metadata": worksheet_metadata,
        "hyperlinks": hyperlinks,
        "comments": project_comments(package),
        "workbook_properties": project_workbook_properties(package.parts),
        "unknown_parts": package.unknown_parts,
        "dangerous_content": {
            "present": dangerous_present,
            "categories": {
                cat: records for cat, records in dangerous_categories.items() if records
            },
        },
    }
    return operation_result, warnings


def _project_security_summary(security: dict[str, Any]) -> dict[str, Any]:
    """Project the uniform security_summary from the OOXML security inventory.

    The XLSX security inventory's ``categories`` maps category names to lists
    of records; the uniform summary needs counts.
    """
    raw_categories = security.get("categories", {})
    counts = {name: len(records) for name, records in raw_categories.items()}
    return {
        "dangerous": bool(security.get("dangerous")),
        "categories": counts,
        "mutation_authorized": False,
    }
