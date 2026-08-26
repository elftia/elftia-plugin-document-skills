"""Transactional public operation for compatible high-fidelity DOCX merge."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
    same_path,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedDocxRequest
from .merge_graph import build_compatible_merge
from .merge_validation import assert_merge_candidate
from .package import OpcPackage
from .structural_diff import summarize_structural_diff
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation


def merge_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    base_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    source_records = []
    try:
        base = OpcPackage.open(request.input_path)
        sources = []
        for index, source_request in enumerate(request.arguments["sources"]):
            source_path = source_request["path"]
            if same_path(source_path, request.input_path):
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "DOCX merge source must differ from the base.",
                    status="invalid_request",
                    details={"source_index": index},
                )
            assert_distinct_paths(source_path, request.output_path, in_place=False)
            record = file_record(source_path, "input")
            source_records.append(record)
            if record.sha256 != source_request["expected_sha256"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "DOCX merge source hash did not match.",
                    details={
                        "reason": "expected-source-sha256",
                        "source_index": index,
                    },
                )
            sources.append(OpcPackage.open(source_path))
        plan = build_compatible_merge(
            base,
            sources,
            style_conflict_policy=request.arguments["style_conflict_policy"],
            numbering_conflict_policy=request.arguments["numbering_conflict_policy"],
        )
        with OperationTempRoot() as private_root:
            staged = private_root / "merge-output.docx"
            manifest = base.write_copy(
                staged,
                changed_parts=plan.changed_parts,
                added_parts=plan.added_parts,
            )
            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=base_record.sha256,
                manifest=manifest,
                assertion=lambda candidate: assert_merge_candidate(candidate, plan),
            )
            operation_result = {
                "merge": {
                    "source_count": len(source_records),
                    "copied_body_blocks": plan.copied_body_blocks,
                    "styles": plan.styles_status,
                    "style_mappings": list(plan.style_mappings),
                    "numbering": plan.numbering_status,
                    "abstract_num_mappings": list(plan.abstract_num_mappings),
                    "num_mappings": list(plan.num_mappings),
                    "bookmark_mappings": list(plan.bookmark_mappings),
                    "preserved_fields": plan.expected_field_count,
                    "preserved_content_controls": plan.expected_content_control_count,
                    "note_mappings": list(plan.note_mappings),
                    "preserved_notes": plan.expected_note_count,
                    "comment_mappings": list(plan.comment_mappings),
                    "preserved_comments": plan.expected_comment_count,
                    "revision_mappings": list(plan.revision_mappings),
                    "preserved_revisions": plan.expected_revision_count,
                    "move_range_mappings": list(plan.move_range_mappings),
                    "move_name_mappings": list(plan.move_name_mappings),
                    "preserved_move_ranges": plan.expected_move_range_count,
                    "sources": [
                        {
                            "path": record.path,
                            "sha256": record.sha256,
                            "bytes": record.bytes,
                        }
                        for record in source_records
                    ],
                    "part_mappings": list(plan.part_mappings),
                },
                "preservation": manifest.as_dict(),
                "structure_diff": summarize_structural_diff(
                    base,
                    OpcPackage.open(staged),
                ),
            }
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=base_record,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=base_record,
                destination=destination,
                guard_sources=tuple(source_records),
            )
    except Exception as error:
        merge_source_preservation_failure(
            error,
            base_record.path,
            base_record.sha256,
        )
        for record in source_records:
            merge_source_preservation_failure(error, record.path, record.sha256)
        raise
