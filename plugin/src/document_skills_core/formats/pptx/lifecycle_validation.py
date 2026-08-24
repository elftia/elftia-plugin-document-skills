"""Semantic validation for transactional slide lifecycle edits."""

from collections import Counter
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .mapping import map_slides
from .macro_policy import open_presentation_package
from .package import OpcPackage


def validate_slide_lifecycle(
    path: Path,
    *,
    source: Path,
    edits: list[dict[str, Any]],
    operation_result: dict[str, Any],
    allow_vba: bool = False,
) -> dict[str, Any]:
    source_package = open_presentation_package(source, allow_vba=allow_vba)
    candidate = open_presentation_package(path, allow_vba=allow_vba, candidate=True)
    source_slides = map_slides(source_package)
    candidate_slides = map_slides(candidate)
    failures: list[str] = []

    expected_count = len(source_slides)
    for edit in edits:
        if edit["type"] in {"slide_add", "slide_copy", "slide_duplicate"}:
            expected_count += 1
        elif edit["type"] == "slide_delete":
            expected_count -= 1
    if len(candidate_slides) != expected_count:
        failures.append("slide-count")
    _validate_presentation_ids(candidate, failures)
    _validate_shape_ids(candidate, candidate_slides, failures)

    evidence_items = operation_result.get("slide_lifecycle", [])
    lifecycle_edits = [
        edit
        for edit in edits
        if edit["type"] in {"slide_add", "slide_copy", "slide_delete", "slide_duplicate"}
    ]
    if len(evidence_items) != len(lifecycle_edits):
        failures.append("lifecycle-evidence-count")
    for index, (edit, evidence) in enumerate(
        zip(lifecycle_edits, evidence_items, strict=False),
        start=1,
    ):
        kind = edit["type"]
        if evidence.get("type") != kind:
            failures.append(f"edit-{index}-type")
            continue
        if kind == "slide_delete":
            for removed in evidence.get("removed_parts", []):
                if removed in candidate.parts:
                    failures.append(f"edit-{index}-removed-part")
            continue
        if kind == "slide_add":
            _validate_added_slide(candidate, evidence, failures, index)
            continue
        _validate_copied_slide(
            candidate,
            source_package,
            source,
            edit,
            evidence,
            failures,
            index,
        )

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX slide lifecycle validation failed.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "lifecycle_edits": len(lifecycle_edits),
        "slide_count": len(candidate_slides),
        "slide_graph_valid": True,
    }


def _validate_added_slide(
    candidate: OpcPackage,
    evidence: dict[str, Any],
    failures: list[str],
    index: int,
) -> None:
    slide_part = evidence.get("slide_part")
    if slide_part not in candidate.parts:
        failures.append(f"edit-{index}-added-slide")
        return
    relationships = candidate.part_rels(slide_part)
    kinds = {item.relationship_type.rsplit("/", 1)[-1] for item in relationships}
    if "slideLayout" not in kinds:
        failures.append(f"edit-{index}-layout")
    image = evidence.get("image")
    if image is not None:
        part = image.get("embedded_media_part")
        if part not in candidate.parts or candidate.part_hashes.get(part) != image.get("source_asset_sha256"):
            failures.append(f"edit-{index}-image")
    chart = evidence.get("chart")
    if chart is not None and chart.get("chart_part") not in candidate.parts:
        failures.append(f"edit-{index}-chart")


def _validate_copied_slide(
    candidate: OpcPackage,
    default_source: OpcPackage,
    default_source_path: Path,
    edit: dict[str, Any],
    evidence: dict[str, Any],
    failures: list[str],
    index: int,
) -> None:
    copy_source = default_source
    if edit["type"] == "slide_copy" and edit.get("source") is not None:
        requested = Path(edit["source"]).resolve()
        if requested != default_source_path.resolve():
            copy_source = OpcPackage.open(requested)
    source_part = evidence.get("source_slide_part")
    target_part = evidence.get("target_slide_part")
    if source_part not in copy_source.parts or target_part not in candidate.parts:
        failures.append(f"edit-{index}-slide-part")
        return
    if copy_source.parts[source_part] != candidate.parts[target_part]:
        failures.append(f"edit-{index}-slide-payload")
    source_kinds = Counter(
        item.relationship_type.rsplit("/", 1)[-1]
        for item in copy_source.part_rels(source_part)
    )
    target_kinds = Counter(
        item.relationship_type.rsplit("/", 1)[-1]
        for item in candidate.part_rels(target_part)
    )
    if source_kinds != target_kinds:
        failures.append(f"edit-{index}-relationship-types")
    for item in evidence.get("dependencies", []):
        source_dependency = item.get("source_part")
        target_dependency = item.get("target_part")
        if target_dependency not in candidate.parts:
            failures.append(f"edit-{index}-dependency")
            continue
        if (
            source_dependency in copy_source.parts
            and target_dependency not in default_source.parts
            and copy_source.parts[source_dependency] != candidate.parts[target_dependency]
        ):
            failures.append(f"edit-{index}-dependency-payload")


def _validate_presentation_ids(package: OpcPackage, failures: list[str]) -> None:
    presentation = package.xml("ppt/presentation.xml")
    slide_ids = presentation.find(f"{{{NS['p']}}}sldIdLst")
    nodes = [] if slide_ids is None else list(slide_ids)
    numeric_ids = [node.attrib.get("id", "") for node in nodes]
    relationship_ids = [node.attrib.get(f"{{{NS['r']}}}id", "") for node in nodes]
    if len(numeric_ids) != len(set(numeric_ids)):
        failures.append("duplicate-slide-id")
    if len(relationship_ids) != len(set(relationship_ids)):
        failures.append("duplicate-slide-relationship-id")


def _validate_shape_ids(
    package: OpcPackage,
    slides: list[dict[str, Any]],
    failures: list[str],
) -> None:
    for slide in slides:
        part = slide.get("part")
        if part is None:
            continue
        root = package.xml(part)
        ids = [
            node.attrib.get("id", "")
            for node in root.iter(f"{{{NS['p']}}}cNvPr")
        ]
        if len(ids) != len(set(ids)):
            failures.append(f"slide-{slide['number']}-duplicate-shape-id")
