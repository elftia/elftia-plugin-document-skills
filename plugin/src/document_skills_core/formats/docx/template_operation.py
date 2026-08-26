"""Transactional orchestration for scalar template application."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedDocxRequest
from .package import OpcPackage
from .style_overlay import (
    StyleOverlayPlan,
    assert_style_overlay,
    plan_style_overlay,
)
from .structural_diff import summarize_structural_diff
from .template import TemplatePlan, plan_template
from .template_base import (
    compare_template_base_preservation,
    open_template_base,
    stage_template_base,
)
from .template_regions import plan_template_regions
from .transaction import promote_candidate, write_candidate_result
from .validation import assert_template_semantics, validate_mutation


def template_operation(
    request: ParsedDocxRequest,
    *,
    project_root: Path,
    schemas: SchemaCatalog,
    apply_backend: Callable[..., tuple[Any, dict[str, Any]]],
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    try:
        package, base_plan = open_template_base(request.input_path)
        variables = request.arguments["variables"]
        regions = request.arguments.get("regions", [])
        region_plan = plan_template_regions(package, regions)
        overlay_record = None
        overlay_plan = None
        overlay_request = request.arguments.get("style_overlay")
        if overlay_request is not None:
            overlay_source = overlay_request["source"]
            assert_distinct_paths(
                overlay_source,
                request.output_path,
                in_place=False,
            )
            overlay_record = file_record(overlay_source, "input")
            if overlay_record.sha256 != overlay_request["expected_source_sha256"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Template style overlay source hash did not match.",
                    details={"reason": "expected-style-source-sha256"},
                )
            overlay_package, _overlay_base = open_template_base(overlay_source)
            overlay_plan = plan_style_overlay(
                package,
                overlay_package,
                overlay_request,
            )
        with OperationTempRoot() as private_root:
            additional_changed_parts = dict(region_plan.changed_parts)
            if overlay_plan is not None:
                additional_changed_parts.update(overlay_plan.changed_parts)
            staged_source = stage_template_base(
                package,
                request.input_path,
                private_root,
                base_plan,
                additional_changed_parts=additional_changed_parts or None,
            )
            staged_package = OpcPackage.open(staged_source)
            plan = plan_template(
                staged_package,
                variables,
                required_story_parts=(
                    {"word/document.xml"}
                    if regions
                    else None
                ),
            )
            warnings = (
                [
                    {
                        "code": "DS_TEMPLATE_UNUSED_VARIABLES",
                        "message": "Some supplied template variables were unused.",
                        "details": {"unused_variables": list(plan.unused)},
                    }
                ]
                if plan.unused
                else []
            )
            staged = private_root / "template-output.docx"
            _backend_manifest, backend = apply_backend(
                project_root,
                staged_source,
                staged,
                variables=variables,
                plan=plan,
            )
            manifest = compare_template_base_preservation(
                package,
                staged,
                story_parts=plan.changed_parts,
                base_plan=base_plan,
                additional_changed_parts=(
                    set(additional_changed_parts) or None
                ),
            )
            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                assertion=lambda candidate: _assert_template_candidate(
                    candidate,
                    plan,
                    overlay_plan,
                ),
            )
            operation_result = {
                "template": plan.as_dict(),
                "template_base": base_plan.as_dict(),
                "backend": backend,
                "preservation": manifest.as_dict(),
                "structure_diff": summarize_structural_diff(
                    package,
                    OpcPackage.open(staged),
                ),
            }
            if overlay_plan is not None and overlay_record is not None:
                operation_result["style_overlay"] = overlay_plan.as_dict(
                    overlay_record
                )
            if regions:
                operation_result["template_regions"] = region_plan.as_dict()
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=warnings,
                source=source_record,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source_record,
                destination=destination,
                guard_sources=(
                    (overlay_record,)
                    if overlay_record is not None
                    else ()
                ),
            )
    except Exception as error:
        merge_source_preservation_failure(
            error,
            source_record.path,
            source_record.sha256,
        )
        raise


def _assert_template_candidate(
    path: Path,
    template_plan: TemplatePlan,
    overlay_plan: StyleOverlayPlan | None,
) -> dict[str, Any]:
    result = assert_template_semantics(path, template_plan)
    if overlay_plan is not None:
        result.update(assert_style_overlay(path, overlay_plan))
    return result
