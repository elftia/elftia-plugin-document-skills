"""Transactional PPTX edit orchestration and validation."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedPptxRequest
from .edit import edit_pptx
from .lifecycle_validation import validate_slide_lifecycle
from .object_contracts import OBJECT_EDIT_TYPES
from .object_validation import validate_object_edits
from .schema_validation import validate_schema_gate, with_schema_gate
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation, validate_reorder


def execute_pptx_edit(
    request: ParsedPptxRequest,
    schemas: SchemaCatalog,
    dotnet: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    keep_vba = request.arguments.get("keep_vba", False) is True
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / ("edited.pptm" if keep_vba else "edited.pptx")
            operation_result, manifest = edit_pptx(
                request.input_path,
                staged,
                request.arguments,
            )
            edits = request.arguments["edits"]
            only_reorder = all(edit["type"] == "slide_reorder" for edit in edits)
            lifecycle_types = {
                "slide_add",
                "slide_copy",
                "slide_delete",
                "slide_duplicate",
            }
            has_lifecycle = any(edit["type"] in lifecycle_types for edit in edits)
            has_objects = any(edit["type"] in OBJECT_EDIT_TYPES for edit in edits)
            assertion = _edit_assertion(
                staged,
                request,
                operation_result,
                keep_vba=keep_vba,
                only_reorder=only_reorder,
                has_lifecycle=has_lifecycle,
                has_objects=has_objects,
            )
            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                assertion=assertion,
                allow_removals=any(
                    edit["type"] in {
                        "chart_delete",
                        "image_delete",
                        "image_replace",
                        "slide_delete",
                    }
                    for edit in edits
                ),
                allow_vba=keep_vba,
            )
            validation = with_schema_gate(
                validation,
                validate_schema_gate(staged, dotnet),
            )
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
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


def _edit_assertion(
    staged: Path,
    request: ParsedPptxRequest,
    operation_result: dict[str, Any],
    *,
    keep_vba: bool,
    only_reorder: bool,
    has_lifecycle: bool,
    has_objects: bool,
):
    if only_reorder:
        return lambda _candidate: validate_reorder(
            staged,
            source=request.input_path,
            allow_vba=keep_vba,
        )
    if not (has_lifecycle or has_objects):
        return None

    def assertion(_candidate: Path) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        if has_lifecycle:
            evidence["slide_lifecycle"] = validate_slide_lifecycle(
                staged,
                source=request.input_path,
                edits=request.arguments["edits"],
                operation_result=operation_result,
                allow_vba=keep_vba,
            )
        if has_objects:
            evidence["object_edits"] = validate_object_edits(
                staged,
                edits=request.arguments["edits"],
                operation_result=operation_result,
                allow_vba=keep_vba,
            )
        return evidence

    return assertion
