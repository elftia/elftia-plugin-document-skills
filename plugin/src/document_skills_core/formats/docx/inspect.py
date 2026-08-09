"""Inert DOCX package and Word feature inventory."""

from pathlib import Path
from typing import Any

from .package import OpcPackage
from .projection import feature_counts, project_sections


def inspect_docx(path: Path, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    max_parts = arguments["max_parts"]
    max_relationships = arguments["max_relationships"]
    part_names = sorted(package.parts)
    relationship_records = [
        item.as_dict()
        for item in sorted(
            package.relationships,
            key=lambda item: (
                item.source_part,
                item.relationship_id,
                item.target,
            ),
        )
    ]
    truncated_parts = len(part_names) > max_parts
    truncated_relationships = len(relationship_records) > max_relationships
    parts = [
        {
            "name": name,
            "bytes": len(package.parts[name]),
            "content_type": package.content_type_for(name),
            **({"sha256": package.part_hashes[name]} if arguments["include_hashes"] else {}),
        }
        for name in part_names[:max_parts]
    ]
    media = [item for item in parts if item["name"].startswith("word/media/")]
    result = {
        "policy": "inert-inspection",
        "mutation_authorized": False,
        "security_summary": _project_security_summary(package.security),
        "package": {
            "part_count": len(package.parts),
            "parts": parts,
            "content_types": package.content_types,
            "relationship_count": len(package.relationships),
            "relationships": relationship_records[:max_relationships],
            "media": media,
            "unknown_parts": package.unknown_parts,
        },
        "word_features": feature_counts(package),
        "sections": project_sections(package),
        "dangerous_content": package.security,
        "truncated": {
            "parts": truncated_parts,
            "relationships": truncated_relationships,
        },
    }
    warnings = []
    if truncated_parts or truncated_relationships:
        warnings.append(
            {
                "code": "DS_INSPECTION_TRUNCATED",
                "message": "Structural inventory reached a caller-selected bound.",
                "details": result["truncated"],
            }
        )
    if package.security["dangerous"]:
        warnings.append(
            {
                "code": "DS_DANGEROUS_CONTENT_INVENTORIED",
                "message": "Dangerous content was inventoried inertly and was not authorized.",
                "details": {"counts": package.security["counts"]},
            }
        )
    return result, warnings


def _project_security_summary(security: dict[str, Any]) -> dict[str, Any]:
    """Project the uniform security_summary block from the DOCX security inventory."""
    counts = security.get("counts", {})
    return {
        "dangerous": bool(security.get("dangerous")),
        "categories": {name: int(count) for name, count in counts.items()},
        "mutation_authorized": False,
    }
