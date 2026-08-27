"""Bounded before/after DOCX structure summary for mutation evidence."""

from typing import Any

from .constants import qn
from .mapping import document_stories, iter_paragraphs
from .package import OpcPackage
from .projection import project_images, project_sections


def summarize_structural_diff(
    before: OpcPackage,
    after: OpcPackage,
) -> dict[str, Any]:
    before_counts = _structure_counts(before)
    after_counts = _structure_counts(after)
    before_parts = set(before.parts)
    after_parts = set(after.parts)
    shared = before_parts & after_parts
    return {
        "counts": {
            name: {
                "before": before_counts[name],
                "after": after_counts[name],
                "delta": after_counts[name] - before_counts[name],
            }
            for name in (
                "paragraphs",
                "tables",
                "images",
                "sections",
                "relationships",
                "parts",
            )
        },
        "changed_parts": sorted(
            name
            for name in shared
            if before.part_hashes[name] != after.part_hashes[name]
        ),
        "added_parts": sorted(after_parts - before_parts),
        "removed_parts": sorted(before_parts - after_parts),
    }


def _structure_counts(package: OpcPackage) -> dict[str, int]:
    stories = document_stories(package)
    return {
        "paragraphs": sum(
            1
            for story in stories
            for _paragraph in iter_paragraphs(story.root)
        ),
        "tables": sum(
            1
            for story in stories
            for _table in story.root.iter(qn("w", "tbl"))
        ),
        "images": sum(len(project_images(package, story)) for story in stories),
        "sections": len(project_sections(package)),
        "relationships": len(package.relationships),
        "parts": len(package.parts),
    }
