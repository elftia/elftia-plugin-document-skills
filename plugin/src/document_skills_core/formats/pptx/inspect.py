"""Inert structural inspection of PPTX package features."""

from pathlib import Path
from typing import Any

from .package import OpcPackage
from .projection import (
    project_charts,
    project_custom_xml,
    project_external_links,
    project_media,
)


def inspect_pptx(
    path: str | Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inspect a PPTX package structure inertly."""
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    include_hashes = arguments.get("include_hashes", True)
    warnings: list[dict[str, Any]] = []

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

    content_types_list = sorted(
        ({"part": k, "content_type": v} for k, v in package.content_types.items()),
        key=lambda item: item["part"],
    )

    rels_list = sorted(
        (r.as_dict() for r in package.relationships),
        key=lambda r: (r["source_part"], r["id"]),
    )

    slide_parts = package.slide_parts()
    slide_master_parts = package.slide_master_parts()
    slide_layout_parts = package.slide_layout_parts()
    notes_slide_parts = package.notes_slide_parts()
    notes_master_parts = package.notes_master_parts()
    theme_parts = package.theme_parts()

    charts = project_charts(package)
    media = project_media(package)
    external_links = project_external_links(package)
    custom_xml = project_custom_xml(package)

    security = package.security
    dangerous_categories = security.get("categories", {})
    dangerous_present = security.get("dangerous", False)

    operation_result: dict[str, Any] = {
        "mutation_authorized": False,
        "security_summary": _project_security_summary(security),
        "parts": parts_inventory,
        "part_count": len(parts_inventory),
        "content_types": content_types_list,
        "relationships": rels_list,
        "slide_count": len(slide_parts),
        "slide_parts": slide_parts,
        "slide_master_count": len(slide_master_parts),
        "slide_master_parts": slide_master_parts,
        "slide_layout_count": len(slide_layout_parts),
        "slide_layout_parts": slide_layout_parts,
        "notes_master_count": len(notes_master_parts),
        "notes_master_parts": notes_master_parts,
        "notes_slide_count": len(notes_slide_parts),
        "notes_slide_parts": notes_slide_parts,
        "theme_count": len(theme_parts),
        "theme_parts": theme_parts,
        "charts": charts,
        "media": media,
        "external_links": external_links,
        "custom_xml": custom_xml,
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
    """Project the uniform security_summary from the OOXML security inventory."""
    raw_categories = security.get("categories", {})
    counts = {name: len(records) for name, records in raw_categories.items()}
    return {
        "dangerous": bool(security.get("dangerous")),
        "categories": counts,
        "mutation_authorized": False,
    }
