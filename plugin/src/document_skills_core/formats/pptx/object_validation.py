"""Semantic validation for transactional PPTX object edits."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_contracts import OBJECT_EDIT_TYPES
from .object_parts import require_internal_relationship
from .object_xml import (
    A,
    R,
    drawable_elements,
    non_visual_properties,
    object_hash,
    select_object,
    slide_shape_tree,
)
from .macro_policy import open_presentation_package
from .package import OpcPackage


def validate_object_edits(
    path: Path,
    *,
    edits: list[dict[str, Any]],
    operation_result: dict[str, Any],
    allow_vba: bool = False,
) -> dict[str, Any]:
    candidate = open_presentation_package(path, allow_vba=allow_vba, candidate=True)
    evidence_items = operation_result.get("object_edits", [])
    object_edits = [edit for edit in edits if edit["type"] in OBJECT_EDIT_TYPES]
    failures: list[str] = []
    if len(evidence_items) != len(object_edits):
        failures.append("object-evidence-count")

    removed_parts = {
        part
        for evidence in evidence_items
        for part in evidence.get("removed_parts", [])
    }
    added_parts = {
        part
        for evidence in evidence_items
        for part in evidence.get("added_parts", [])
    }
    for part in sorted(removed_parts):
        if part in candidate.parts:
            failures.append(f"removed-part:{part}")
    for part in sorted(added_parts - removed_parts):
        if part not in candidate.parts:
            failures.append(f"added-part:{part}")

    final_objects: dict[tuple[str, str], dict[str, Any]] = {}
    final_notes: dict[str, dict[str, Any]] = {}
    for evidence in evidence_items:
        if evidence.get("type") == "notes_update":
            final_notes[evidence.get("notes_part", "")] = evidence
            continue
        key = (evidence.get("slide_part", ""), evidence.get("object_id", ""))
        final_objects[key] = evidence

    lifecycle_delete = any(edit["type"] == "slide_delete" for edit in edits)
    for (slide_part, object_id), evidence in final_objects.items():
        if slide_part not in candidate.parts:
            if not lifecycle_delete:
                failures.append(f"missing-slide:{slide_part}")
            continue
        root = candidate.xml(slide_part)
        if evidence.get("after_sha256") is None:
            present_ids = {
                non_visual_properties(element).attrib.get("id", "")
                for element in drawable_elements(slide_shape_tree(root))
            }
            if object_id in present_ids:
                failures.append(f"deleted-object:{slide_part}:{object_id}")
            continue
        try:
            selected = select_object(root, {"id": object_id, "name": None, "type": None})
        except DocumentSkillsError:
            failures.append(f"selected-object:{slide_part}:{object_id}")
            continue
        if object_hash(selected) != evidence.get("after_sha256"):
            failures.append(f"object-hash:{slide_part}:{object_id}")
        _validate_click_action(candidate, slide_part, selected, evidence, failures)

    for notes_part, evidence in final_notes.items():
        if notes_part not in candidate.parts:
            failures.append(f"notes-part:{notes_part}")
        elif candidate.part_hashes[notes_part] != evidence.get("after_sha256"):
            failures.append(f"notes-hash:{notes_part}")

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX object edit validation failed.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "edited_objects": len(final_objects),
        "notes_updates": len(final_notes),
        "object_graph_valid": True,
    }


def _validate_click_action(
    candidate: OpcPackage,
    slide_part: str,
    selected: Any,
    evidence: dict[str, Any],
    failures: list[str],
) -> None:
    edit_type = evidence.get("type", "")
    if not edit_type.startswith(("action_", "hyperlink_")):
        return
    click = non_visual_properties(selected).find(A("hlinkClick"))
    if edit_type.endswith("_remove"):
        if click is not None:
            failures.append(f"click-remove:{slide_part}:{evidence.get('object_id')}")
        return
    if click is None:
        failures.append(f"click-missing:{slide_part}:{evidence.get('object_id')}")
        return
    if edit_type.startswith("action_"):
        if not click.attrib.get("action", "").startswith("ppaction://hlinkshowjump"):
            failures.append(f"action-uri:{slide_part}:{evidence.get('object_id')}")
        if click.attrib.get(R("id")):
            failures.append(f"action-relationship:{slide_part}:{evidence.get('object_id')}")
        return
    relationship_id = click.attrib.get(R("id"), "")
    try:
        require_internal_relationship(
            candidate,
            slide_part,
            relationship_id,
            "slide",
        )
    except DocumentSkillsError:
        failures.append(f"hyperlink-relationship:{slide_part}:{evidence.get('object_id')}")
