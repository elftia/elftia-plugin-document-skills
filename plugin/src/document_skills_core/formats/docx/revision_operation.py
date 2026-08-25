"""Transactional public tracked-revision mutation operation."""

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

from .contracts import ParsedDocxRequest
from .package import OpcPackage
from .revisions import (
    assert_revision_scope,
    normalize_apply_diagnostics,
    project_revision_records,
    remaining_selected_ids,
)
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation


def revision_apply_operation(
    request: ParsedDocxRequest,
    *,
    dotnet: Any,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    source_package = OpcPackage.open(request.input_path)
    if dotnet is None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX revision mutation requires the dotnet-openxml provider.",
            status="enhancement_required",
            details={"recommended_providers": ["dotnet-openxml"]},
        )
    target_ids = list(request.arguments["revision_ids"])
    filters = request.arguments.get("filters")
    scope = request.arguments.get("scope")
    provider_scope = assert_revision_scope(source_package, scope)
    try:
        if not target_ids or filters is not None or scope is not None:
            source_records = dotnet.read_revisions(
                request.input_path,
                1_001,
                filters=filters,
                scope=provider_scope,
                revision_ids=target_ids or None,
            )
            source_projection = project_revision_records(
                source_records,
                max_revisions=1_000,
                package=source_package,
                filters=filters,
                scope=scope,
            )
            if source_projection["truncated"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Revision mutation exceeds the 1000-revision transaction bound.",
                )
            selected_ids = list(
                dict.fromkeys(item["id"] for item in source_projection["items"])
            )
            if target_ids:
                missing_ids = [item for item in target_ids if item not in selected_ids]
                if missing_ids:
                    raise DocumentSkillsError(
                        ErrorCode.VALIDATION_FAILED,
                        "Requested revision ids are outside the filters or scope.",
                        details={"unmatched_ids": missing_ids},
                    )
            else:
                target_ids = selected_ids
            if not target_ids:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "No revisions matched the requested transaction selection.",
                )
        with OperationTempRoot() as private_root:
            staged = private_root / "revisions-output.docx"
            raw_diagnostics = dotnet.apply_revisions(
                request.input_path,
                staged,
                target_ids,
                request.arguments["action"],
            )
            diagnostics = normalize_apply_diagnostics(
                raw_diagnostics,
                target_ids=target_ids,
            )
            if diagnostics["unmatched_ids"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "One or more requested revision ids were not found.",
                    details={"unmatched_ids": diagnostics["unmatched_ids"]},
                )
            output_package = OpcPackage.open(staged)
            manifest = source_package.compare_preservation(
                output_package,
                allowed_changed={"word/document.xml"},
            )

            def assert_revisions(candidate: Path) -> dict[str, Any]:
                candidate_package = OpcPackage.open(candidate)
                remaining = remaining_selected_ids(
                    dotnet.read_revisions(
                        candidate,
                        1_001,
                        filters=None,
                        scope=None,
                        revision_ids=target_ids,
                    ),
                    selected_ids=target_ids,
                    package=candidate_package,
                )
                if remaining:
                    raise DocumentSkillsError(
                        ErrorCode.VALIDATION_FAILED,
                        "Applied revisions remain in the candidate.",
                        details={"remaining_selected_ids": remaining},
                    )
                return {"remaining_selected_ids": remaining}

            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                assertion=assert_revisions,
            )
            revision_result = {
                "action": request.arguments["action"],
                "matched_ids": diagnostics["matched_ids"],
                "remaining_selected_ids": [],
                "unmatched_ids": diagnostics["unmatched_ids"],
            }
            selection = {
                key: request.arguments[key]
                for key in ("filters", "scope")
                if key in request.arguments
            }
            if selection:
                revision_result["selection"] = selection
            operation_result = {
                "revisions": revision_result,
                "preservation": manifest.as_dict(),
            }
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=source_record,
                achieved_fidelity="enhanced",
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
