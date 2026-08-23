"""XLSX dispatch and shared transactional mutation."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest, parse_xlsx_request
from .create import create_xlsx
from .edit import edit_xlsx
from .formula_analysis import validate_formula_analysis
from .formula_state import (
    build_formula_state_summary,
    should_downgrade,
)
from .inspect import inspect_xlsx
from .read import read_xlsx
from .recalculation import compare_final_preservation
from .recalculation_operation import execute_recalculation
from .recalculation_service import RecalculationOutcome, recalculate_candidate
from .results import (
    read_validation,
    success_result,
    with_formula_gate,
    with_recalculation_gate,
)
from .service_support import (
    allowed_removed_parts,
    formula_degradations,
    outcome_provider,
)
from .transaction import promote_candidate, write_candidate_result
from .validation import (
    assert_edits_applied,
    validate_created,
    validate_mutation,
)


class XlsxService:
    def __init__(self, project_root: Path, libreoffice=None) -> None:
        self.project_root = project_root.resolve()
        self.schemas = SchemaCatalog(self.project_root)
        self.libreoffice = libreoffice

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._execute(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            requested_fidelity = (
                options.get("fidelity", "core") if type(options) is dict else "unknown"
            )
            return make_error_result(
                operation,
                error,
                requested_fidelity=requested_fidelity,
            )

    def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_xlsx_request(request)
        if parsed.operation != operation:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "XLSX provider binding does not match the request operation.",
                status="invalid_request",
            )
        if operation == "xlsx.read":
            return self._read(parsed)
        if operation == "xlsx.inspect.structure":
            return self._inspect(parsed)
        if operation == "xlsx.create":
            return self._create(parsed)
        if operation == "xlsx.edit":
            return self._edit(parsed)
        return execute_recalculation(
            parsed,
            schemas=self.schemas,
            libreoffice=self.libreoffice,
        )

    def _read(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = read_xlsx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        if request.arguments["include_formulas"]:
            with OperationTempRoot() as private_root:
                outcome = recalculate_candidate(
                    request.input_path,
                    private_root,
                    libreoffice=self.libreoffice,
                    policy="auto",
                    formula_cells=operation_result.get("formula_state", {}).get(
                        "cells", {}
                    ),
                )
        else:
            outcome = RecalculationOutcome(
                request.input_path,
                {},
                None,
                {
                    "outcome": "not_run",
                    "policy": "auto",
                    "reason": "request-excluded-formulas",
                    "formula_cells": 0,
                },
                [],
            )
        formula_cells = outcome.formula_cells
        recalculation_provider = outcome_provider(outcome)
        operation_result["formula_state"]["cells"] = formula_cells
        formula_summary = build_formula_state_summary(
            formula_cells,
            recalculation_provider=recalculation_provider,
        )
        operation_result["formula_state"]["summary"] = formula_summary
        operation_result["recalculation"] = outcome.evidence
        degraded = should_downgrade(formula_summary)
        formula_analysis, validation = validate_formula_analysis(
            request.input_path,
            read_validation("operation.structured-read", operation_result),
            required=False,
        )
        operation_result["formula_analysis"] = formula_analysis
        validation = with_recalculation_gate(validation, outcome.evidence)
        if formula_analysis["categories"]["external_reference"]:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "External-workbook formulas require inert structural inspection.",
                details={"formula_analysis": formula_analysis},
                validation=validation,
            )
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=validation,
            status="degraded" if degraded else "success",
            degraded=degraded,
            degradations=formula_degradations(
                degraded,
                "Formulas require recalculation by an accepted provider.",
            ),
            achieved_fidelity="enhanced" if outcome.provider_chain else "core",
            provider_chain=outcome.provider_chain,
        )

    def _inspect(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = inspect_xlsx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        formula_analysis, validation = validate_formula_analysis(
            request.input_path,
            read_validation("operation.inert-inspection", operation_result),
            required=False,
            allow_dangerous_inventory=True,
        )
        operation_result["formula_analysis"] = formula_analysis
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=validation,
        )

    def _create(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.output_path is not None
        workbook = request.arguments["workbook"]
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "created.xlsx"
            creation = create_xlsx(staged, workbook)
            validation = validate_created(staged, workbook, creation=creation)
            formula_analysis, validation = validate_formula_analysis(
                staged,
                validation,
                required=True,
            )
            formula_cells = creation.get("formula_cells", {})
            outcome = recalculate_candidate(
                staged,
                private_root,
                libreoffice=self.libreoffice,
                policy=request.arguments["recalculation"],
                formula_cells=formula_cells,
            )
            if outcome.candidate != staged:
                validation = validate_created(
                    outcome.candidate,
                    workbook,
                    creation=creation,
                )
                formula_analysis, validation = validate_formula_analysis(
                    outcome.candidate,
                    validation,
                    required=True,
                )
            formula_cells = outcome.formula_cells
            formula_summary = build_formula_state_summary(
                formula_cells,
                recalculation_provider=outcome_provider(outcome),
            )
            operation_result = {
                "creation": {
                    "sheets": creation["sheets"],
                    "shared_strings_count": creation["shared_strings_count"],
                    "styles": creation["styles"],
                    "tables": creation.get("tables", []),
                    "data_validations": creation.get("data_validations", []),
                    "conditional_formats": creation.get("conditional_formats", []),
                    "charts": creation.get("charts", []),
                    "worksheet_metadata": creation.get("worksheet_metadata", []),
                    "hyperlinks": creation.get("hyperlinks", []),
                    "comments": creation.get("comments", []),
                    "workbook_properties": creation.get("metadata", {}),
                },
                "formula_state": {
                    "cells": formula_cells,
                    "summary": formula_summary,
                },
                "recalculation": outcome.evidence,
                "formula_analysis": formula_analysis,
            }
            degraded = should_downgrade(formula_summary)
            validation = with_formula_gate(validation, operation_result)
            validation = with_recalculation_gate(
                validation,
                outcome.evidence,
                required=(
                    request.arguments["recalculation"] == "required"
                    and outcome.evidence["outcome"] == "pass"
                ),
            )
            result = write_candidate_result(
                self.schemas,
                request,
                outcome.candidate,
                validation,
                operation_result,
                warnings=[],
                source=None,
                status="degraded" if degraded else "success",
                degraded=degraded,
                degradations=formula_degradations(
                    degraded,
                    "Created formulas require recalculation by an accepted provider.",
                ),
                achieved_fidelity="enhanced" if outcome.provider_chain else "core",
                provider_chain=outcome.provider_chain,
            )
            return promote_candidate(
                request,
                outcome.candidate,
                result,
                source=None,
                destination=destination,
            )

    def _edit(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        assert request.output_path is not None
        assert_distinct_paths(
            request.input_path,
            request.output_path,
            in_place=False,
        )
        source_record = file_record(request.input_path, "input")
        destination = destination_snapshot(request.output_path)
        try:
            with OperationTempRoot() as private_root:
                staged = private_root / "edited.xlsx"
                operation_result, manifest = edit_xlsx(
                    request.input_path, staged, request.arguments
                )
                validation = validate_mutation(
                    staged,
                    source=request.input_path,
                    source_sha256=source_record.sha256,
                    manifest=manifest,
                    allowed_removed_parts=allowed_removed_parts(
                        request.arguments["edits"],
                        manifest.removed,
                    ),
                    assertion=lambda candidate: assert_edits_applied(
                        candidate,
                        request.arguments["edits"],
                        source=request.input_path,
                    ),
                )
                formula_analysis, validation = validate_formula_analysis(
                    staged,
                    validation,
                    required=True,
                )
                outcome = recalculate_candidate(
                    staged,
                    private_root,
                    libreoffice=self.libreoffice,
                    policy=request.arguments["recalculation"],
                    formula_cells=operation_result.get("formula_state", {}).get(
                        "cells", {}
                    ),
                )
                final_manifest = manifest
                if outcome.manifest is not None:
                    final_manifest = compare_final_preservation(
                        request.input_path,
                        outcome.candidate,
                        allowed_changed=(
                            set(manifest.changed) | set(outcome.manifest.changed)
                        ),
                        expected_added=set(manifest.added),
                        expected_removed=set(manifest.removed),
                    )
                    validation = validate_mutation(
                        outcome.candidate,
                        source=request.input_path,
                        source_sha256=source_record.sha256,
                        manifest=final_manifest,
                        allowed_removed_parts=allowed_removed_parts(
                            request.arguments["edits"],
                            final_manifest.removed,
                        ),
                        assertion=lambda candidate: assert_edits_applied(
                            candidate,
                            request.arguments["edits"],
                            source=request.input_path,
                        ),
                    )
                    formula_analysis, validation = validate_formula_analysis(
                        outcome.candidate,
                        validation,
                        required=True,
                    )
                operation_result["formula_state"]["cells"] = outcome.formula_cells
                operation_result["preservation"] = final_manifest.as_dict()
                operation_result["recalculation"] = outcome.evidence
                operation_result["formula_analysis"] = formula_analysis
                formula_summary = build_formula_state_summary(
                    outcome.formula_cells,
                    recalculation_provider=outcome_provider(outcome),
                )
                operation_result["formula_state"]["summary"] = formula_summary
                degraded = should_downgrade(formula_summary)
                validation = with_formula_gate(validation, operation_result)
                validation = with_recalculation_gate(
                    validation,
                    outcome.evidence,
                    required=(
                        request.arguments["recalculation"] == "required"
                        and outcome.evidence["outcome"] == "pass"
                    ),
                )
                result = write_candidate_result(
                    self.schemas,
                    request,
                    outcome.candidate,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source_record,
                    status="degraded" if degraded else "success",
                    degraded=degraded,
                    degradations=formula_degradations(
                        degraded,
                        "Edited formulas require recalculation by an accepted provider.",
                    ),
                    achieved_fidelity="enhanced" if outcome.provider_chain else "core",
                    provider_chain=outcome.provider_chain,
                )
                return promote_candidate(
                    request,
                    outcome.candidate,
                    result,
                    source=source_record,
                    destination=destination,
                )
        except Exception as error:
            merge_source_preservation_failure(
                error, source_record.path, source_record.sha256
            )
            raise


def build_xlsx_service(project_root: Path, libreoffice=None) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    service = XlsxService(project_root, libreoffice=libreoffice)
    return service.execute
