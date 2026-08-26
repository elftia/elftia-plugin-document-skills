"""Public comment operations with provider and promotion containment."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .comments import (
    assert_added_comment,
    assert_comment_anchor,
    assert_resolved_comment,
    project_comment_records,
)
from .contracts import ParsedDocxRequest
from .package import OpcPackage
from .results import read_validation, success_result
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation


def comments_read_operation(
    request: ParsedDocxRequest,
    *,
    dotnet: Any | None,
) -> dict[str, Any]:
    assert request.input_path is not None
    source = file_record(request.input_path, "input")
    OpcPackage.open(request.input_path)
    if dotnet is None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX comment reading requires the dotnet-openxml provider.",
            status="enhancement_required",
            details={"recommended_providers": ["dotnet-openxml"]},
        )
    maximum = request.arguments["max_comments"]
    raw_records = dotnet.read_comments(request.input_path, maximum + 1)
    comments = project_comment_records(raw_records, max_comments=maximum)
    assert_source_preserved(source.path, source.sha256)
    operation_result = {"comments": comments}
    return success_result(
        request,
        artifacts=[source.as_dict()],
        operation_result=operation_result,
        warnings=[],
        validation=read_validation("operation.comments-read", operation_result),
        achieved_fidelity="enhanced",
    )


def comments_add_operation(
    request: ParsedDocxRequest,
    *,
    dotnet: Any | None,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    source_package = OpcPackage.open(request.input_path)
    if request.arguments["anchor"] is not None:
        assert_comment_anchor(source_package, request.arguments["anchor"])
    if dotnet is None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX comment mutation requires the dotnet-openxml provider.",
            status="enhancement_required",
            details={"recommended_providers": ["dotnet-openxml"]},
        )
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / "comments-output.docx"
            comment_id = dotnet.add_comment(
                request.input_path,
                staged,
                request.arguments,
            )
            if type(comment_id) is not str or not comment_id or len(comment_id) > 128:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "Comment provider returned an invalid comment id.",
                )
            output_package = OpcPackage.open(staged)
            manifest = source_package.compare_preservation(
                output_package,
                allowed_changed={
                    "[Content_Types].xml",
                    "word/_rels/document.xml.rels",
                    "word/comments.xml",
                    "word/commentsExtended.xml",
                    "word/document.xml",
                },
                allowed_added={"word/comments.xml", "word/commentsExtended.xml"},
            )

            verified_comment: dict[str, Any] = {}

            def assert_comment(candidate: Path) -> dict[str, Any]:
                record = assert_added_comment(
                    dotnet.read_comments(candidate, 10_001),
                    comment_id=comment_id,
                    author=request.arguments["author"],
                    text=request.arguments["text"],
                    anchor=request.arguments["anchor"],
                    parent_comment_id=request.arguments["parent_comment_id"],
                )
                verified_comment.update(record)
                return {"comment_id": comment_id, "verified": True}

            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                assertion=assert_comment,
            )
            operation_result = {
                "comment": verified_comment,
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


def comments_resolve_operation(
    request: ParsedDocxRequest,
    *,
    dotnet: Any | None,
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
            "DOCX comment resolution requires the dotnet-openxml provider.",
            status="enhancement_required",
            details={"recommended_providers": ["dotnet-openxml"]},
        )
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / "comments-resolved.docx"
            mutation = dotnet.resolve_comment(
                request.input_path,
                staged,
                request.arguments["comment_id"],
                request.arguments["resolved"],
            )
            if mutation != {
                "comment_id": request.arguments["comment_id"],
                "resolved": request.arguments["resolved"],
            }:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "Comment provider returned an invalid resolution result.",
                )
            output_package = OpcPackage.open(staged)
            manifest = source_package.compare_preservation(
                output_package,
                allowed_changed={
                    "[Content_Types].xml",
                    "word/_rels/document.xml.rels",
                    "word/comments.xml",
                    "word/commentsExtended.xml",
                },
                allowed_added={"word/commentsExtended.xml"},
            )
            verified_comment: dict[str, Any] = {}

            def assert_resolution(candidate: Path) -> dict[str, Any]:
                record = assert_resolved_comment(
                    dotnet.read_comments(candidate, 10_001),
                    comment_id=request.arguments["comment_id"],
                    resolved=request.arguments["resolved"],
                )
                verified_comment.update(record)
                return {
                    "comment_id": request.arguments["comment_id"],
                    "resolved": request.arguments["resolved"],
                    "verified": True,
                }

            validation = validate_mutation(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                manifest=manifest,
                assertion=assert_resolution,
            )
            operation_result = {
                "comment": verified_comment,
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
