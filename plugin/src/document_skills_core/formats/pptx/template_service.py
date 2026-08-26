"""Transactional service orchestration for semantic template operations."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedPptxRequest
from .package import validate_pptx_source_path
from .results import success_result, template_inspection_validation
from .schema_validation import validate_schema_gate, with_schema_gate
from .template_inspect import inspect_template
from .template_materialize import (
    build_template_materialization_receipt,
    materialize_template,
    validate_materialized_template,
)
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation


def inspect_template_request(
    request: ParsedPptxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    validate_pptx_source_path(request.input_path)
    source = file_record(request.input_path, "input")
    destination = (
        None if request.output_path is None else destination_snapshot(request.output_path)
    )
    try:
        with OperationTempRoot() as private_root:
            operation_result, warnings, contact_sheet = inspect_template(
                request.input_path,
                request.arguments,
                provider=libreoffice,
                private_root=private_root,
                source_sha256=source.sha256,
            )
            validation = template_inspection_validation(operation_result)
            visual_status = operation_result["contact_sheet"]["status"]
            degraded = request.arguments["contact_sheet"] and visual_status != "passed"
            degradations = [] if not degraded else [{
                "code": "TEMPLATE_CONTACT_SHEET_UNAVAILABLE",
                "semantic_difference": (
                    "Structural inspection succeeded without the requested contact sheet."
                ),
                "missing_capabilities": ["libreoffice.render-image"],
                "recommended_providers": ["libreoffice"],
            }]
            if contact_sheet is None:
                assert_source_preserved(source.path, source.sha256)
                result = success_result(
                    request,
                    artifacts=[source.as_dict()],
                    operation_result=operation_result,
                    warnings=warnings,
                    validation=validation,
                    status="degraded" if degraded else "success",
                    degraded=degraded,
                    degradations=degradations,
                )
                schemas.validate("operation-result", result)
                return result
            assert request.output_path is not None and destination is not None
            staged = private_root / "template-contact-sheet.png"
            staged.write_bytes(contact_sheet)
            identity = file_record(staged, "output")
            validation["gates"].insert(
                0,
                gate_record(
                    "candidate.identity",
                    "pass",
                    evidence={"bytes": identity.bytes, "sha256": identity.sha256},
                ),
            )
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=warnings,
                source=source,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def create_from_template(
    request: ParsedPptxRequest,
    *,
    schemas: SchemaCatalog,
    dotnet: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    try:
        with OperationTempRoot() as private_root:
            staged = private_root / "created-from-template.pptx"
            materialization = materialize_template(
                request.input_path,
                staged,
                request.arguments,
                source_sha256=source.sha256,
            )
            operation_result = materialization.operation_result
            validation = validate_mutation(
                staged,
                source=source.path,
                source_sha256=source.sha256,
                manifest=materialization.preservation,
                assertion=lambda candidate: validate_materialized_template(
                    candidate,
                    purge_plan=materialization.purge_plan,
                    output_slide_ids=[
                        item["output_slide_id"] for item in request.arguments["pages"]
                    ],
                ),
                allow_removals=True,
            )
            validation = with_schema_gate(
                validation,
                validate_schema_gate(staged, dotnet),
            )
            schema_gate = next(
                gate for gate in validation["gates"] if gate["id"] == "schema.full"
            )
            operation_result["schema"] = {"status": schema_gate["outcome"]}
            operation_result["delivery_receipt"] = build_template_materialization_receipt(
                operation_result,
                source_sha256=source.sha256,
                candidate_path=staged,
            )
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=source,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise
