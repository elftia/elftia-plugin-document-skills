"""Typed body-paragraph formatting edits with immutable-input selectors."""

from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .content_control_editing import (
    apply_content_control_plan,
    assert_content_control_inventory,
    project_content_controls,
)
from .contracts import ParsedDocxRequest
from .edit_planning import PlannedEdit, plan_edits
from .field_editing import apply_field_plan, assert_field_inventory, project_fields
from .formatting import (
    set_paragraph_style,
    set_run_style,
)
from .image_editing import ImageEditPlan
from .image_edit_apply import apply_image_plan
from .image_edit_validation import assert_image_plans
from .link_edit_apply import apply_link_plan
from .link_edit_validation import assert_link_plans
from .link_editing import LinkEditPlan
from .mapping import document_stories
from .note_editing import apply_note_plan, assert_note_inventory
from .numbering_editing import apply_numbering_plan, assert_numbering_plans
from .package import OpcPackage
from .section_edit_apply import apply_section_plan
from .section_edit_validation import assert_section_plans
from .section_editing import SectionEditPlan
from .structural_diff import summarize_structural_diff
from .table_edit_apply import apply_table_plan
from .table_edit_validation import assert_table_state
from .table_model import table_semantic_state
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation
from .xml_utils import paragraph, xml_bytes

def edit_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    """Apply a bounded formatting plan, validate privately, then promote."""

    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    keep_vba = request.arguments.get("keep_vba", False)
    try:
        package = OpcPackage.open(
            request.input_path,
            allow_vba_preservation=keep_vba,
        )
        body = document_stories(package, include_headers_footers=False)[0]
        (
            plan,
            image_state,
            table_state,
            section_state,
            link_state,
            field_state,
            note_state,
            content_control_state,
            numbering_state,
        ) = plan_edits(
            package, body, request.arguments["edits"]
        )
        _apply_plan(plan)
        expected_fields = (
            project_fields([body])[0] if field_state is not None else None
        )
        expected_notes = note_state.inventory() if note_state is not None else None
        expected_content_controls = (
            project_content_controls([body])[0]
            if content_control_state is not None
            else None
        )
        expected_tables = table_semantic_state(body.root) if table_state is not None else None
        document_payload = xml_bytes(body.root)
        expected_sha256 = sha256(document_payload).hexdigest()
        changed_parts = {body.part: document_payload}
        expected_part_hashes = {body.part: expected_sha256}
        formatting_roots = {
            item.part: item.story_root
            for item in plan
            if item.part is not None
            and item.part != body.part
            and item.story_root is not None
        }
        for part, root in sorted(formatting_roots.items()):
            payload = xml_bytes(root)
            changed_parts[part] = payload
            expected_part_hashes[part] = sha256(payload).hexdigest()
        added_parts: dict[str, bytes] = {}
        for state in (image_state, section_state, note_state):
            if state is None:
                continue
            state_changed, state_added = state.package_parts(document_payload)
            _merge_part_payloads(changed_parts, state_changed)
            _merge_part_payloads(added_parts, state_added)
        image_plans = [item.image for item in plan if item.image is not None]
        section_plans = [item.section for item in plan if item.section is not None]
        link_plans = [item.link for item in plan if item.link is not None]
        numbering_plans = [
            item.numbering for item in plan if item.numbering is not None
        ]
        with OperationTempRoot() as private_root:
            staged = private_root / ("edit-output.docm" if keep_vba else "edit-output.docx")
            manifest = package.write_copy(
                staged,
                changed_parts=changed_parts,
                added_parts=added_parts,
            )
            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                assertion=lambda candidate: _assert_edit_candidate(
                    candidate,
                    part=body.part,
                    expected_sha256=expected_sha256,
                    expected_part_hashes=expected_part_hashes,
                    expected_edits=len(plan),
                    image_plans=image_plans,
                    expected_tables=expected_tables,
                    section_plans=section_plans,
                    link_plans=link_plans,
                    expected_fields=expected_fields,
                    expected_notes=expected_notes,
                    expected_content_controls=expected_content_controls,
                    numbering_plans=numbering_plans,
                    allow_vba_preservation=keep_vba,
                ),
                allow_vba_preservation=keep_vba,
            )
            counts = Counter(item.value["type"] for item in plan)
            scoped_formatting = any(
                item.value["type"] in {"paragraph_style", "run_style"}
                and "part" in item.value["target"]
                for item in plan
            )
            selector_policy = (
                "immutable-input-story-part-paragraph"
                if scoped_formatting
                else "immutable-input-body-paragraph-and-section-sha256"
                if section_state is not None
                else "immutable-input-body-paragraph-and-numbering-graph"
                if numbering_state is not None
                else "immutable-input-body-content-control-sha256-text"
                if content_control_state is not None
                else "immutable-input-body-paragraph-and-note-id-text"
                if note_state is not None
                else "immutable-input-body-paragraph-and-field"
                if field_state is not None
                else "immutable-input-body-paragraph-and-internal-link"
                if link_state is not None
                else "immutable-input-body-paragraph-image-relationship-and-table-sha256"
                if image_plans and table_state is not None
                else "immutable-input-body-paragraph-and-image-relationship"
                if image_plans
                else "immutable-input-body-paragraph-and-table-sha256"
                if table_state is not None
                else "immutable-input-body-paragraph"
            )
            warnings = (
                [
                    {
                        "code": "DS_FIELD_UPDATE_PENDING",
                        "message": "Word fields were marked dirty and require a consumer refresh.",
                        "details": {"consumer_refresh_required": True},
                    }
                ]
                if field_state is not None
                else []
            )
            operation_result = {
                "edit": {
                    "applied": len(plan),
                    "primitive_counts": dict(sorted(counts.items())),
                    "selector_policy": selector_policy,
                },
                "preservation": manifest.as_dict(),
                "structure_diff": summarize_structural_diff(
                    package,
                    OpcPackage.open(
                        staged,
                        allow_vba_preservation=keep_vba,
                    ),
                ),
            }
            if keep_vba:
                operation_result["vba_preservation"] = {"mode": "keep-vba-inert"}
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
            )
    except Exception as error:
        merge_source_preservation_failure(
            error,
            source_record.path,
            source_record.sha256,
        )
        raise


def _apply_plan(plan: list[PlannedEdit]) -> None:
    for item in plan:
        edit = item.value
        edit_type = edit["type"]
        if item.image is not None:
            apply_image_plan(item.image)
            continue
        if item.table is not None:
            apply_table_plan(item.table)
            continue
        if item.section is not None:
            apply_section_plan(item.section)
            continue
        if item.link is not None:
            apply_link_plan(item.link)
            continue
        if item.field is not None:
            apply_field_plan(item.field)
            continue
        if item.note is not None:
            apply_note_plan(item.note)
            continue
        if item.content_control is not None:
            apply_content_control_plan(item.content_control)
            continue
        if item.numbering is not None:
            apply_numbering_plan(item.numbering)
            continue
        assert item.paragraph is not None
        assert item.parent is not None
        if edit_type == "paragraph_delete":
            item.parent.remove(item.paragraph)
        elif edit_type == "paragraph_insert":
            position = list(item.parent).index(item.paragraph)
            if edit["position"] == "after":
                position += 1
            item.parent.insert(position, paragraph(edit["text"], style=edit["style"]))
        elif edit_type == "paragraph_style":
            set_paragraph_style(item.paragraph, edit["style"])
        elif edit_type == "run_style":
            for run in item.runs:
                set_run_style(run, edit["style"])


def _assert_edit_candidate(
    path: Path,
    *,
    part: str,
    expected_sha256: str,
    expected_part_hashes: dict[str, str],
    expected_edits: int,
    image_plans: list[ImageEditPlan],
    expected_tables: list[dict[str, Any]] | None,
    section_plans: list[SectionEditPlan],
    link_plans: list[LinkEditPlan],
    expected_fields: list[dict[str, Any]] | None,
    expected_notes: list[dict[str, Any]] | None,
    expected_content_controls: list[dict[str, Any]] | None,
    numbering_plans: list[Any],
    allow_vba_preservation: bool = False,
) -> dict[str, Any]:
    package = OpcPackage.open(
        path,
        allow_vba_preservation=allow_vba_preservation,
    )
    for expected_part, expected_hash in expected_part_hashes.items():
        actual_sha256 = package.part_hashes.get(expected_part)
        if actual_sha256 != expected_hash:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Edited DOCX does not match the immutable formatting plan.",
                details={"part": expected_part},
            )
    result = {
        "applied_edits": expected_edits,
        "changed_part": part,
        "planned_part_sha256": expected_sha256,
        "planned_parts_sha256": expected_part_hashes,
    }
    if image_plans or expected_tables is not None or link_plans or numbering_plans:
        body = document_stories(package, include_headers_footers=False)[0]
    elif expected_fields is not None:
        body = document_stories(package, include_headers_footers=False)[0]
    elif expected_notes is not None:
        body = document_stories(package, include_headers_footers=False)[0]
    elif expected_content_controls is not None:
        body = document_stories(package, include_headers_footers=False)[0]
    if image_plans:
        result.update(assert_image_plans(package, body, image_plans))
    if expected_tables is not None:
        result.update(assert_table_state(body, expected_tables))
    if section_plans:
        result.update(assert_section_plans(package, section_plans))
    if link_plans:
        result.update(assert_link_plans(body, link_plans))
    if expected_fields is not None:
        result.update(assert_field_inventory(body, expected_fields))
    if expected_notes is not None:
        result.update(assert_note_inventory(package, expected_notes))
    if expected_content_controls is not None:
        result.update(
            assert_content_control_inventory(body, expected_content_controls)
        )
    if numbering_plans:
        result.update(assert_numbering_plans(body, numbering_plans))
    return result


def _merge_part_payloads(target: dict[str, bytes], additions: dict[str, bytes]) -> None:
    for part, payload in additions.items():
        existing = target.get(part)
        if existing is not None and existing != payload:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "DOCX edit groups produced conflicting package part plans.",
                status="invalid_request",
                details={"part": part},
            )
        target[part] = payload
