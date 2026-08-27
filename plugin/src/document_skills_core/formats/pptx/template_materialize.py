"""Safe semantic template materialization over the baseline slide graph copier."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_PARTS, MAX_PPTX_BYTES
from .image import MAX_TOTAL_IMAGE_BYTES
from .mapping import map_slides
from .mutation import MutablePptxPackage
from .package import OpcPackage, PreservationManifest
from .slide_graph import copy_slide, delete_slide
from .template_binding import apply_template_bindings
from .template_content_lint import lint_materialized_content, validate_binding_plan
from .template_descriptor import (
    TemplateDescriptor,
    load_template_descriptor,
    validate_catalog_binding,
)
from .template_inspect import _apply_semantics, _project_pages
from .template_purge import (
    TemplatePurgePlan,
    plan_template_purge,
    template_private_closure,
    validate_template_purge,
)


@dataclass(frozen=True)
class TemplateMaterialization:
    operation_result: dict[str, Any]
    preservation: PreservationManifest
    purge_plan: TemplatePurgePlan
    content_descriptor: TemplateDescriptor
    output_object_sources: dict[str, str]


def materialize_template(
    source_path: Path,
    candidate_path: Path,
    arguments: dict[str, Any],
    *,
    source_sha256: str,
) -> TemplateMaterialization:
    if arguments["expected_input_sha256"] != source_sha256:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "The template input hash no longer matches the creation precondition.",
            status="invalid_request",
            details={
                "actual_sha256": source_sha256,
                "expected_sha256": arguments["expected_input_sha256"],
            },
        )
    descriptor = load_template_descriptor(arguments["descriptor"])
    catalog = validate_catalog_binding(
        descriptor,
        arguments["catalog_ref"],
        input_sha256=source_sha256,
        delivery_profile=arguments["delivery_profile"],
    )
    source = OpcPackage.open(source_path)
    projected = _project_pages(source)
    diagnostics = _apply_semantics(projected, descriptor)
    if diagnostics:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template stable addresses do not match the semantic descriptor.",
            status="failed",
            details={"diagnostics": diagnostics[:64]},
        )
    preflight_lint = validate_binding_plan(arguments["pages"], descriptor)
    selected_ids = {item["source_slide_id"] for item in arguments["pages"]}
    purge_plan = plan_template_purge(source, selected_ids)
    source_pages = {item["source_slide_id"]: item for item in projected}

    target = MutablePptxPackage(source)
    for position in range(len(map_slides(target)), 0, -1):
        delete_slide(target, position)
    resource_budget = _validate_resource_plan(
        source,
        target,
        arguments["pages"],
        source_pages,
    )

    slide_mapping: list[dict[str, Any]] = []
    binding_receipts: list[dict[str, Any]] = []
    object_mapping: list[dict[str, Any]] = []
    added_image_bytes = 0
    for page in arguments["pages"]:
        source_page = source_pages.get(page["source_slide_id"])
        if source_page is None:
            _invalid("Requested semantic source slide is absent.")
        copied = copy_slide(
            target,
            source,
            source_page["order"],
            len(map_slides(target)) + 1,
            cross_deck=False,
        )
        expected_hashes = {
            item["slot_id"]: item["expected_hash"]
            for item in source_page["semantic_slots"]
        }
        receipts, objects, page_image_bytes = apply_template_bindings(
            target,
            target_position=copied.target_position,
            page=page,
            descriptor=descriptor,
            expected_hashes=expected_hashes,
            image_byte_limit=MAX_TOTAL_IMAGE_BYTES - added_image_bytes,
        )
        added_image_bytes += page_image_bytes
        if added_image_bytes > MAX_TOTAL_IMAGE_BYTES:
            _resource_limit(
                "Template binding images exceed the aggregate byte budget.",
                actual=added_image_bytes,
                ceiling=MAX_TOTAL_IMAGE_BYTES,
            )
        _enforce_working_package_budget(target)
        binding_receipts.extend({
            **item,
            "output_slide_id": page["output_slide_id"],
            "source_slide_id": page["source_slide_id"],
        } for item in receipts)
        object_mapping.extend({
            **item,
            "output_slide_id": page["output_slide_id"],
            "source_slide_id": page["source_slide_id"],
        } for item in objects)
        slide_mapping.append({
            "dependency_mapping": copied.as_dict()["dependencies"],
            "output_slide_id": page["output_slide_id"],
            "output_slide_part": copied.target_slide_part,
            "source_slide_id": page["source_slide_id"],
            "source_slide_part": copied.source_slide_part,
        })

    resource_budget.update({
        "actual_image_bytes": added_image_bytes,
        "actual_uncompressed_bytes": sum(
            len(payload) for payload in target.parts.values()
        ),
        "actual_parts": len(target.parts),
    })

    preservation = target.emit(candidate_path)
    output_object_sources = {
        item["output_object_id"]: item["source_object_id"]
        for item in object_mapping
    }
    postflight_lint = lint_materialized_content(
        candidate_path,
        descriptor=descriptor,
        output_object_sources=output_object_sources,
    )
    purge = validate_template_purge(
        candidate_path,
        purge_plan,
        output_slide_ids=[item["output_slide_id"] for item in arguments["pages"]],
    )
    operation_result = {
        "binding_receipt": binding_receipts,
        "catalog": catalog,
        "changed_objects": [
            {
                "after_sha256": item["after_sha256"],
                "before_sha256": item["before_sha256"],
                "output_slide_id": item["output_slide_id"],
                "slot_id": item["slot_id"],
            }
            for item in binding_receipts
        ],
        "consumer": {
            "a_contract": descriptor.contract_consumer,
            "core_opc": {"status": "passed"},
            "libreoffice": {"status": "not_run"},
            "powerpoint": {"status": "not_run"},
        },
        "content_lint": {
            "postflight": postflight_lint,
            "preflight": preflight_lint,
        },
        "license_status": catalog["license_status"],
        "object_mapping": object_mapping,
        "physical_purge": purge,
        "preservation": preservation.as_dict(),
        "preserved_objects": {
            "shared_layout_master_theme": "preserved_by_slide_graph_reachability",
        },
        "purge_manifest": {
            "parts": list(purge_plan.private_parts),
            "unselected_slide_ids": list(purge_plan.unselected_slides),
        },
        "resource_budget": resource_budget,
        "schema": {"status": "not_run"},
        "source_mapping": {
            "objects": object_mapping,
            "slides": slide_mapping,
        },
        "visual": {"status": "not_run"},
    }
    return TemplateMaterialization(
        operation_result,
        preservation,
        purge_plan,
        descriptor,
        output_object_sources,
    )


def _validate_resource_plan(
    source: OpcPackage,
    target: MutablePptxPackage,
    pages: list[dict[str, Any]],
    source_pages: dict[str, dict[str, Any]],
) -> dict[str, int | str]:
    """Reject oversized repeated dependency graphs before copying any page."""

    projected_bytes = sum(len(payload) for payload in target.parts.values())
    projected_parts = len(target.parts)
    relationship_overhead = 0
    for page in pages:
        source_page = source_pages.get(page["source_slide_id"])
        if source_page is None or source_page.get("part") is None:
            _invalid("Requested semantic source slide is absent.")
        private_parts = template_private_closure(source, source_page["part"])
        projected_parts += len(private_parts)
        projected_bytes += sum(
            len(source.parts[item])
            for item in private_parts
            if item in source.parts
        )
        relationship_overhead += 1024 * sum(
            1 for item in private_parts if item.endswith(".rels")
        )

    planned_image_bytes = 0
    planned_images = 0
    for page in pages:
        for binding in page["bindings"]:
            value = binding["value"]
            if value.get("type") != "image-ref" or type(value.get("path")) is not str:
                continue
            image_path = Path(value["path"])
            try:
                if image_path.is_file():
                    planned_image_bytes += image_path.stat().st_size
                    planned_images += 1
            except OSError:
                continue
    if planned_image_bytes > MAX_TOTAL_IMAGE_BYTES:
        _resource_limit(
            "Template binding images exceed the aggregate byte budget.",
            actual=planned_image_bytes,
            ceiling=MAX_TOTAL_IMAGE_BYTES,
        )
    projected_bytes += planned_image_bytes + relationship_overhead
    projected_parts += planned_images
    if projected_bytes > MAX_PPTX_BYTES or projected_parts > MAX_PARTS:
        _resource_limit(
            "Repeated template dependencies exceed the candidate package budget.",
            projected_bytes=projected_bytes,
            byte_ceiling=MAX_PPTX_BYTES,
            projected_parts=projected_parts,
            part_ceiling=MAX_PARTS,
        )
    return {
        "image_bytes": planned_image_bytes,
        "projected_bytes": projected_bytes,
        "projected_parts": projected_parts,
        "status": "passed",
    }


def _enforce_working_package_budget(target: MutablePptxPackage) -> None:
    actual_bytes = sum(len(payload) for payload in target.parts.values())
    actual_parts = len(target.parts)
    if actual_bytes > MAX_PPTX_BYTES or actual_parts > MAX_PARTS:
        _resource_limit(
            "Materialized template exceeds the candidate package budget.",
            actual_bytes=actual_bytes,
            byte_ceiling=MAX_PPTX_BYTES,
            actual_parts=actual_parts,
            part_ceiling=MAX_PARTS,
        )


def build_template_materialization_receipt(
    operation_result: dict[str, Any],
    *,
    source_sha256: str,
    candidate_path: Path,
) -> dict[str, Any]:
    payload = {
        "binding_receipt_sha256": _canonical_hash(operation_result["binding_receipt"]),
        "catalog": operation_result["catalog"],
        "consumer": operation_result["consumer"],
        "input_sha256": source_sha256,
        "license_status": operation_result["license_status"],
        "operation": "pptx.create.from-template",
        "output_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "purge_manifest_sha256": _canonical_hash(operation_result["purge_manifest"]),
        "schema": operation_result["schema"],
        "schema_version": "1.0",
        "source_mapping_sha256": _canonical_hash(operation_result["source_mapping"]),
        "visual": operation_result["visual"],
    }
    return {**payload, "receipt_sha256": _canonical_hash(payload)}


def validate_materialized_template(
    candidate_path: Path,
    *,
    purge_plan: TemplatePurgePlan,
    output_slide_ids: list[str],
    descriptor: TemplateDescriptor,
    output_object_sources: dict[str, str],
) -> dict[str, Any]:
    purge = validate_template_purge(
        candidate_path,
        purge_plan,
        output_slide_ids=output_slide_ids,
    )
    lint = lint_materialized_content(
        candidate_path,
        descriptor=descriptor,
        output_object_sources=output_object_sources,
    )
    return {"content_lint": lint, "physical_purge": purge}


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _invalid(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
    )


def _resource_limit(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.RESOURCE_LIMIT,
        message,
        status="failed",
        details=details,
    )
