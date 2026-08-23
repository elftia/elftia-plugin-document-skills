"""Composite deep structural, chart, and static-layout PPTX validator."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart_validation import validate_chart_packages
from .deep_graph_validation import validate_part_graph
from .mapping import map_slides
from .macro_policy import validate_vba_package
from .package import OpcPackage
from .static_layout_validation import audit_static_layout


def validate_deep_package(path: Path, *, allow_vba: bool = False) -> dict[str, Any]:
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    security = _validate_security_inventory(package, allow_vba=allow_vba)
    slides = map_slides(package)
    return {
        "charts": validate_chart_packages(package),
        "graph": validate_part_graph(package),
        "inventory": {
            "charts": len(package.chart_parts()),
            "layouts": len(package.slide_layout_parts()),
            "masters": len(package.slide_master_parts()),
            "media": len(package.media_parts()),
            "notes": len(package.notes_slide_parts()),
            "slide_order": [slide.get("part") for slide in slides],
            "slides": len(slides),
            "themes": len(package.theme_parts()),
        },
        "security": security,
        "static_layout": audit_static_layout(package),
        "valid": True,
    }


def _validate_security_inventory(
    package: OpcPackage,
    *,
    allow_vba: bool,
) -> dict[str, Any]:
    vba = validate_vba_package(package, candidate=True) if allow_vba else None
    categories = package.security.get("categories", {})
    disallowed = {
        name: values
        for name, values in categories.items()
        if name != "ole" and (not allow_vba or name != "vba") and values
    }
    allowed_relationships = {
        (relationship.relationship_part, relationship.relationship_id): relationship.resolved_target
        for relationship in package.relationships
        if relationship.source_part.startswith("ppt/charts/chart")
        and relationship.target_mode == "Internal"
        and relationship.relationship_type.rsplit("/", 1)[-1] == "package"
        and relationship.resolved_target is not None
        and relationship.resolved_target.startswith("ppt/embeddings/")
        and relationship.resolved_target.casefold().endswith(".xlsx")
    }
    allowed_parts = set(allowed_relationships.values())
    invalid_ole: list[dict[str, Any]] = []
    for item in categories.get("ole", []):
        part = item.get("part")
        relationship_key = (item.get("source"), item.get("id"))
        if part in allowed_parts or relationship_key in allowed_relationships:
            continue
        invalid_ole.append(item)
    if disallowed or invalid_ole:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PPTX deep validation rejected active or externally linked content.",
            details={
                "categories": sorted(disallowed),
                "invalid_embedded_items": invalid_ole[:32],
            },
        )
    return {
        "embedded_workbooks": len(allowed_parts),
        "other_dangerous_categories": ["vba"] if vba is not None else [],
        "policy": (
            "exact-vba-copy-through-and-internal-xlsx-chart-workbooks"
            if vba is not None
            else "read-only-internal-xlsx-chart-workbooks"
        ),
        "vba": vba,
    }
