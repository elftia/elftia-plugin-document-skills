"""Sequential bounded PDF edit transaction orchestration.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .byte_preflight import preflight_pdf
from .edit_semantics import preflight_edit_primitive
from .mutation_plan import (
    aggregate_manifests,
    authorize_step_manifest,
    declare_mutation_plan,
)
from .object_model import IndirectReference, PdfDict, PdfObjectModel, parse_pdf
from .page_tree import walk_pages

PrimitiveRunner = Callable[
    [PdfObjectModel, dict[str, Any], Path, dict[int, str]],
    tuple[dict[str, Any], dict[str, Any]],
]
def run_edit_pipeline(
    input_path: Path,
    output_path: Path,
    primitives: list[dict[str, Any]],
    *,
    run_primitive: PrimitiveRunner,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply primitives in request order and publish only the final candidate."""
    if preflight_pdf(input_path).encrypted:
        _reject_encrypted_edit()
    original_model = parse_pdf(input_path)
    if original_model.trailer.encrypt is not None:
        _reject_encrypted_edit()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    original_hashes = original_model.object_hashes()
    current_path = input_path
    staged_paths: list[Path] = []
    primitive_results: list[dict[str, Any]] = []
    step_manifests: list[dict[str, Any]] = []
    watermark_stage_hashes: dict[int, dict[str, str]] = {}
    watermark_source_objects: dict[int, list[int]] = {}
    try:
        for index, primitive in enumerate(primitives):
            current_model = parse_pdf(current_path)
            preflight_edit_primitive(current_model, primitive)
            plan = declare_mutation_plan(current_model, primitive)
            if primitive["type"] == "watermark":
                # This comes from the parsed input/prior authorized stage, not
                # from the watermark writer's report.
                watermark_source_objects[index] = sorted(current_model.objects)
            staged_path = _new_staged_path(output_path, index)
            staged_paths.append(staged_path)
            result, primitive_manifest = run_primitive(
                current_model,
                primitive,
                staged_path,
                current_model.object_hashes(),
            )
            output_model = parse_pdf(staged_path)
            step_manifest = authorize_step_manifest(
                plan,
                primitive_manifest,
                current_model.object_hashes(),
                output_model.object_hashes(),
            )
            step_manifests.append(step_manifest)
            if primitive["type"] == "watermark":
                watermark_stage_hashes[index] = _watermark_role_hashes(
                    result,
                    step_manifest,
                )
            primitive_results.append({
                "index": index,
                **_with_mutation_report(
                    result,
                    step_manifest,
                    current_model,
                    output_model,
                    {primitive["type"]},
                ),
            })
            current_path = staged_path

        final_model = parse_pdf(current_path)
        manifest = aggregate_manifests(original_hashes, step_manifests)
        manifest["_watermark_stage_hashes"] = watermark_stage_hashes
        manifest["_watermark_source_objects"] = watermark_source_objects
        os.replace(current_path, output_path)
        staged_paths.remove(current_path)
        if len(primitive_results) == 1:
            single_result = dict(primitive_results[0])
            single_result.pop("index", None)
            single_result["preservation"] = manifest
            return _with_mutation_report(
                single_result,
                manifest,
                original_model,
                final_model,
                {primitives[0]["type"]},
            ), manifest
        transaction_result = {
            "primitive_count": len(primitive_results),
            "primitives": primitive_results,
            "preservation": manifest,
        }
        return _with_mutation_report(
            transaction_result,
            manifest,
            original_model,
            final_model,
            {primitive["type"] for primitive in primitives},
        ), manifest
    finally:
        for staged_path in staged_paths:
            staged_path.unlink(missing_ok=True)


def _reject_encrypted_edit() -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Encrypted PDF inputs must be decrypted before pdf.edit.",
        status="enhancement_required",
        details={"capability": "pdf.decrypt"},
    )


def _watermark_role_hashes(
    result: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, str]:
    """Snapshot authorized stage hashes for objects named by watermark roles."""
    object_numbers: set[int] = set()
    uses = result.get("watermark_uses")
    if isinstance(uses, list):
        for record in uses:
            if not isinstance(record, dict):
                continue
            for field in ("content_object", "font_object", "image_object"):
                value = record.get(field)
                if type(value) is int:
                    object_numbers.add(value)
    image = result.get("image")
    if isinstance(image, dict):
        image_object = image.get("image_object")
        if type(image_object) is int:
            object_numbers.add(image_object)
        soft_mask = image.get("soft_mask")
        if isinstance(soft_mask, dict):
            soft_mask_object = soft_mask.get("object")
            if type(soft_mask_object) is int:
                object_numbers.add(soft_mask_object)
    hashes = manifest.get("expected_output_hashes")
    if not isinstance(hashes, dict):
        return {}
    trusted: dict[str, str] = {}
    for number in sorted(object_numbers):
        digest = hashes.get(str(number))
        if isinstance(digest, str):
            trusted[str(number)] = digest
    return trusted


def _new_staged_path(output_path: Path, index: int) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{output_path.name}.primitive-{index}-",
        suffix=".pdf",
        dir=output_path.parent,
        delete=False,
    )
    path = Path(handle.name)
    handle.close()
    return path


_OBJECT_SET_FIELDS = (
    "changed_objects",
    "added_objects",
    "removed_objects",
)
_PAGE_TREE_PRIMITIVES = {
    "merge",
    "split",
    "page_insert",
    "page_sequence",
}


def _with_mutation_report(
    result: dict[str, Any],
    manifest: dict[str, Any],
    source_model: PdfObjectModel,
    output_model: PdfObjectModel,
    primitive_types: set[str],
) -> dict[str, Any]:
    """Project canonical object and page impact evidence onto an edit result."""
    reported = dict(result)
    reported["preservation"] = manifest
    for field in _OBJECT_SET_FIELDS:
        reported[field] = _canonical_object_set(manifest, field)
    reported["page_impact"] = _page_impact(
        source_model,
        output_model,
        manifest,
        primitive_types,
    )
    return reported


def _canonical_object_set(manifest: dict[str, Any], field: str) -> list[int]:
    values = manifest.get(field)
    if type(values) is not list or any(
        type(value) is not int or value < 1 for value in values
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF edit preservation manifest has an invalid object set.",
            details={"field": field},
        )
    canonical = sorted(set(values))
    if values != canonical:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF edit preservation manifest object sets must be sorted and unique.",
            details={"field": field},
        )
    return list(values)


def _page_impact(
    source_model: PdfObjectModel,
    output_model: PdfObjectModel,
    manifest: dict[str, Any],
    primitive_types: set[str],
) -> dict[str, Any]:
    source_page_count = len(walk_pages(source_model))
    output_page_count = len(walk_pages(output_model))
    if primitive_types & _PAGE_TREE_PRIMITIVES:
        mode = "page_tree"
        source_pages = list(range(1, source_page_count + 1))
        output_pages = list(range(1, output_page_count + 1))
    elif primitive_types == {"page_labels"}:
        mode = "page_labels"
        source_pages = list(range(1, source_page_count + 1))
        output_pages = list(range(1, output_page_count + 1))
    elif primitive_types == {"metadata_update"}:
        mode = "document_metadata"
        source_pages = []
        output_pages = []
    elif primitive_types == {"outline"}:
        mode = "document_navigation"
        source_pages = []
        output_pages = []
    else:
        source_objects = set(_canonical_object_set(manifest, "changed_objects"))
        source_objects.update(_canonical_object_set(manifest, "removed_objects"))
        output_objects = set(_canonical_object_set(manifest, "changed_objects"))
        output_objects.update(_canonical_object_set(manifest, "added_objects"))
        source_pages = _pages_reaching_objects(source_model, source_objects)
        output_pages = _pages_reaching_objects(output_model, output_objects)
        if len(primitive_types) > 1:
            mode = "mixed"
        elif source_pages or output_pages:
            mode = "page_content"
        else:
            mode = "document"
    return {
        "mode": mode,
        "source_page_count": source_page_count,
        "output_page_count": output_page_count,
        "source_pages": source_pages,
        "output_pages": output_pages,
    }


def _pages_reaching_objects(
    model: PdfObjectModel,
    object_numbers: set[int],
) -> list[int]:
    if not object_numbers:
        return []
    return [
        page.page_number
        for page in walk_pages(model)
        if _reachable_objects(model, page.obj_num) & object_numbers
    ]


def _reachable_objects(model: PdfObjectModel, root_object: int) -> set[int]:
    reachable: set[int] = set()
    pending = [root_object]
    while pending:
        object_number = pending.pop()
        if object_number in reachable or object_number not in model.objects:
            continue
        reachable.add(object_number)
        pending.extend(
            reference.obj_num
            for reference in _references(model.objects[object_number].value)
            if reference.obj_num not in reachable
        )
    return reachable


def _references(value: Any) -> list[IndirectReference]:
    if isinstance(value, IndirectReference):
        return [value]
    if isinstance(value, PdfDict):
        return [
            reference
            for key, item in value.entries.items()
            if key != "/Parent"
            for reference in _references(item)
        ]
    if isinstance(value, list):
        return [reference for item in value for reference in _references(item)]
    if isinstance(value, tuple):
        return [
            reference
            for item in value
            if isinstance(item, (IndirectReference, PdfDict, list, tuple))
            for reference in _references(item)
        ]
    return []
