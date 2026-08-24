"""Semantic validation for master, layout, and theme edit transactions."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, PRESENTATION_MAIN, local_name
from .design_edit_contracts import DESIGN_EDIT_TYPES
from .macro_policy import open_presentation_package

_P = f"{{{NS['p']}}}"
_R_ID = f"{{{NS['r']}}}id"


def validate_design_edits(
    path: Path,
    *,
    edits: list[dict[str, Any]],
    operation_result: dict[str, Any],
    allow_vba: bool = False,
) -> dict[str, Any]:
    package = open_presentation_package(path, allow_vba=allow_vba, candidate=True)
    failures: list[str] = []
    hierarchy = _validate_hierarchy(package, failures)
    design_edits = [edit for edit in edits if edit["type"] in DESIGN_EDIT_TYPES]
    evidence = operation_result.get("design_edits", [])
    if len(evidence) != len(design_edits):
        failures.append("design-evidence-count")
    for index, (edit, item) in enumerate(
        zip(design_edits, evidence, strict=False),
        1,
    ):
        _validate_edit(package, edit, item, failures, index)
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX design graph validation failed.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "design_edits": len(design_edits),
        **hierarchy,
        "inheritance_valid": True,
    }


def _validate_hierarchy(package: Any, failures: list[str]) -> dict[str, int]:
    presentation = package.xml(PRESENTATION_MAIN)
    identifiers = presentation.find(f"{_P}sldMasterIdLst")
    registered = {
        node.attrib.get(_R_ID, "")
        for node in ([] if identifiers is None else list(identifiers))
    }
    numeric = [
        node.attrib.get("id", "")
        for node in ([] if identifiers is None else list(identifiers))
    ]
    if len(numeric) != len(set(numeric)):
        failures.append("duplicate-master-id")
    relationships = {
        relationship.relationship_id: relationship
        for relationship in package.part_rels(PRESENTATION_MAIN)
        if relationship.relationship_type.endswith("/slideMaster")
    }
    if registered != set(relationships):
        failures.append("master-registration")
    layout_total = 0
    for relationship_id, relationship in relationships.items():
        master = relationship.resolved_target
        if relationship_id not in registered or master not in package.parts:
            failures.append(f"master-{relationship_id}-part")
            continue
        master_relationships = package.part_rels(master)
        themes = [item for item in master_relationships if item.relationship_type.endswith("/theme")]
        layouts = [item for item in master_relationships if item.relationship_type.endswith("/slideLayout")]
        if len(themes) != 1 or themes[0].resolved_target not in package.parts:
            failures.append(f"master-{relationship_id}-theme")
        root = package.xml(master)
        layout_ids = root.find(f"{_P}sldLayoutIdLst")
        listed = {
            node.attrib.get(_R_ID, "")
            for node in ([] if layout_ids is None else list(layout_ids))
        }
        layout_numeric = [
            node.attrib.get("id", "")
            for node in ([] if layout_ids is None else list(layout_ids))
        ]
        if len(layout_numeric) != len(set(layout_numeric)):
            failures.append(f"master-{relationship_id}-duplicate-layout-id")
        if listed != {item.relationship_id for item in layouts} or not layouts:
            failures.append(f"master-{relationship_id}-layout-registration")
        for layout_relationship in layouts:
            layout = layout_relationship.resolved_target
            if layout not in package.parts:
                failures.append(f"master-{relationship_id}-layout-part")
                continue
            inverse = [
                item
                for item in package.part_rels(layout)
                if item.relationship_type.endswith("/slideMaster")
            ]
            if len(inverse) != 1 or inverse[0].resolved_target != master:
                failures.append(f"master-{relationship_id}-layout-inheritance")
        layout_total += len(layouts)
    for slide in package.slide_parts():
        layouts = [
            item
            for item in package.part_rels(slide)
            if item.relationship_type.endswith("/slideLayout")
        ]
        if len(layouts) != 1 or layouts[0].resolved_target not in package.parts:
            failures.append(f"{slide}-layout")
    return {"layouts": layout_total, "masters": len(relationships)}


def _validate_edit(
    package: Any,
    edit: dict[str, Any],
    evidence: dict[str, Any],
    failures: list[str],
    index: int,
) -> None:
    kind = edit["type"]
    if evidence.get("type") != kind:
        failures.append(f"edit-{index}-type")
        return
    if kind == "master_delete":
        for part in evidence.get("removed_parts", []):
            if part in package.parts:
                failures.append(f"edit-{index}-removed-master-part")
        return
    if kind == "layout_delete":
        if evidence.get("layout_part") in package.parts:
            failures.append(f"edit-{index}-removed-layout-part")
        return
    master = evidence.get("master_part")
    if master not in package.parts:
        failures.append(f"edit-{index}-master")
    if kind in {"layout_add", "layout_copy", "master_add"}:
        if evidence.get("layout_part") not in package.parts:
            failures.append(f"edit-{index}-layout")
    if kind == "master_copy":
        for mapping in evidence.get("dependencies", []):
            if mapping.get("target_part") not in package.parts:
                failures.append(f"edit-{index}-dependency")
    if kind in {"master_add", "theme_update"}:
        theme = evidence.get("theme_part")
        if theme not in package.parts:
            failures.append(f"edit-{index}-theme")
        elif kind == "theme_update":
            projected = _project_theme(package.xml(theme))
            expected = edit["theme"]
            if projected["name"] != expected["name"]:
                failures.append(f"edit-{index}-theme-name")
            if projected["fonts"] != expected["fonts"]:
                failures.append(f"edit-{index}-theme-fonts")
            if projected["palette"] != expected["palette"]:
                failures.append(f"edit-{index}-theme-palette")
            if projected["shadow_enabled"] != expected["effects"]["shadow"]["enabled"]:
                failures.append(f"edit-{index}-theme-effects")


def _project_theme(root: Any) -> dict[str, Any]:
    scheme = next((node for node in root.iter() if local_name(node.tag) == "clrScheme"), None)
    palette = {}
    if scheme is not None:
        for slot in list(scheme):
            color = next(iter(slot), None)
            if color is not None:
                palette[local_name(slot.tag)] = color.attrib.get(
                    "lastClr",
                    color.attrib.get("val", ""),
                )
    font_scheme = next((node for node in root.iter() if local_name(node.tag) == "fontScheme"), None)
    fonts = {"major": "", "minor": ""}
    if font_scheme is not None:
        for key, tag in (("major", "majorFont"), ("minor", "minorFont")):
            collection = next(
                (node for node in list(font_scheme) if local_name(node.tag) == tag),
                None,
            )
            latin = None if collection is None else next(
                (node for node in collection if local_name(node.tag) == "latin"),
                None,
            )
            if latin is not None:
                fonts[key] = latin.attrib.get("typeface", "")
    return {
        "fonts": fonts,
        "name": root.attrib.get("name", ""),
        "palette": palette,
        "shadow_enabled": any(local_name(node.tag) == "outerShdw" for node in root.iter()),
    }
