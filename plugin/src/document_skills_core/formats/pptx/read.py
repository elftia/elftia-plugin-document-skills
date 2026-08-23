"""Structured PPTX deck read — deterministic slide/shape/text projection."""

from pathlib import Path
from typing import Any

from document_skills_core.core.io.core_properties import project_core_properties

from .mapping import map_slides
from .package import OpcPackage
from .projection import (
    project_charts,
    project_defined_names,
    project_external_links,
    project_image_references,
    project_layout_recipes,
    project_media,
    project_slide_size,
    project_theme,
)


def read_pptx(
    path: str | Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a PPTX deck and return (operation_result, warnings)."""
    package = OpcPackage.open(path)
    max_slides = arguments.get("max_slides", 1_000)
    max_shapes = arguments.get("max_shapes_per_slide", 500)
    include_notes = arguments.get("include_notes", True)
    include_connectors = arguments.get("include_connectors", True)

    slides = map_slides(package)
    warnings: list[dict[str, Any]] = []

    if len(slides) > max_slides:
        slides = slides[:max_slides]
        warnings.append({
            "code": "DS_SLIDE_LIMIT",
            "message": f"Slide limit reached; truncated to {max_slides}.",
            "details": {"limit": max_slides},
        })

    for slide in slides:
        if len(slide["shapes"]) > max_shapes:
            warnings.append({
                "code": "DS_SHAPE_LIMIT",
                "message": f"Slide {slide['number']} shape limit exceeded; truncated.",
                "details": {"slide": slide["number"], "limit": max_shapes},
            })
            slide["shapes"] = slide["shapes"][:max_shapes]
        if not include_notes:
            slide["notes"] = None
        if not include_connectors:
            slide["shapes"] = [s for s in slide["shapes"] if s.get("type") != "connector"]

    slide_size = project_slide_size(package)
    defined_names = project_defined_names(package)
    charts = project_charts(package)
    media = project_media(package)
    external_links = project_external_links(package)

    for slide in slides:
        image_refs: list[dict[str, Any]] = []
        if slide.get("part"):
            image_refs = project_image_references(package, slide["part"])
        slide["image_references"] = image_refs

    operation_result: dict[str, Any] = {
        "metadata": project_core_properties(package.parts),
        "slides": slides,
        "slide_count": len(slides),
        "slide_size": slide_size,
        "defined_names": defined_names,
        "charts": charts,
        "media": media,
        "external_links": external_links,
        "layout_recipes": project_layout_recipes(package),
        "theme": project_theme(package),
    }
    return operation_result, warnings
