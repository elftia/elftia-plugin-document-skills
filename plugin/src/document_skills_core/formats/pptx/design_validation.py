"""Theme, layout-recipe, and template-reuse validation for typed PPTX creation."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .design_contracts import DEFAULT_THEME, LAYOUT_RECIPES
from .mapping import map_slides
from .package import OpcPackage
from .projection import project_layout_recipes, project_theme


def assert_typed_design(
    path: Path,
    deck: dict[str, Any],
    creation: dict[str, Any] | None,
) -> dict[str, Any]:
    package = OpcPackage.open(path)
    creation = creation or {}
    template = creation.get("template_reuse")
    if template is not None:
        _assert_template_parts(package, template)
        return {
            "layout_count": len(package.slide_layout_parts()),
            "template_graph_reused": True,
            "theme_parts": len(package.theme_parts()),
        }

    failures: list[str] = []
    projected = project_theme(package)
    expected = deck.get("theme") or DEFAULT_THEME
    if projected is None:
        failures.append("theme")
    else:
        if projected.get("name") != expected["name"]:
            failures.append("theme-name")
        if projected.get("fonts") != expected["fonts"]:
            failures.append("theme-fonts")
        for key, value in expected["palette"].items():
            if projected.get("palette", {}).get(key) != value:
                failures.append(f"theme-palette-{key}")
    layouts = project_layout_recipes(package)
    layout_names = {
        item["name"].casefold().replace(" ", "-") for item in layouts
    }
    if not set(LAYOUT_RECIPES).issubset(layout_names):
        failures.append("layout-recipes")
    slides = map_slides(package)
    for index, (requested, slide) in enumerate(
        zip(deck["slides"], slides, strict=True),
        1,
    ):
        actual_name = (slide.get("layout") or {}).get("name", "")
        requested_recipe = requested.get(
            "recipe",
            "cover" if requested.get("layout") == "title" else "content",
        )
        if actual_name.casefold().replace(" ", "-") != requested_recipe:
            failures.append(f"slide-{index}-recipe")
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX typed design validation failed.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "layout_count": len(layouts),
        "recipes": len(deck["slides"]),
        "template_graph_reused": False,
        "theme_parts": len(package.theme_parts()),
    }


def _assert_template_parts(
    candidate: OpcPackage,
    evidence: dict[str, Any],
) -> None:
    source_path = Path(evidence["template"])
    source = OpcPackage.open(source_path)
    failures = []
    for part in (
        source.slide_master_parts()
        + source.slide_layout_parts()
        + source.theme_parts()
    ):
        if part not in candidate.parts or candidate.parts[part] != source.parts[part]:
            failures.append(part)
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX template design graph was not reused byte-for-byte.",
            details={"changed_or_missing_parts": failures},
        )
