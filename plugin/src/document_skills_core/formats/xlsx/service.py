"""Four-operation XLSX dispatch and shared transactional mutation."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest, parse_xlsx_request
from .create import create_xlsx
from .edit import edit_xlsx
from .formula_state import (
    assert_invariant,
    build_formula_cell_state,
    build_formula_state_summary,
    derive_read_state,
    should_downgrade,
)
from .inspect import inspect_xlsx
from .read import read_xlsx
from .results import read_validation, success_result, with_formula_gate
from .transaction import promote_candidate, write_candidate_result
from .validation import assert_edits_applied, validate_created, validate_mutation


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
        return self._edit(parsed)

    def _read(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = read_xlsx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        # Consult LibreOffice for recalculation
        recalculation_provider, formula_cells = self._try_recalc(
            request.input_path,
            operation_result.get("formula_state", {}).get("cells", {}),
        )
        if recalculation_provider is not None:
            operation_result["formula_state"]["cells"] = formula_cells
        formula_summary = build_formula_state_summary(
            formula_cells,
            recalculation_provider=recalculation_provider,
        )
        operation_result["formula_state"]["summary"] = formula_summary
        degraded = should_downgrade(formula_summary)
        degradations: list[dict[str, Any]] = []
        if degraded:
            degradations.append({
                "code": "outstanding-formula-recalculation",
                "semantic_difference": "Formulas require recalculation by an accepted provider.",
                "missing_capabilities": ["recalculation"],
                "recommended_providers": ["libreoffice"],
            })
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.structured-read", operation_result),
            status="degraded" if degraded else "success",
            degraded=degraded,
            degradations=degradations,
        )

    def _try_recalc(
        self, input_path: Path, core_cells: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        """Consult LibreOffice for recalculation. Returns (provider, cells).

        When LibreOffice is absent or fails, returns (None, core_cells) so the
        Core formula-state logic is byte-identical.
        """
        if not core_cells or self.libreoffice is None:
            return None, core_cells
        recalculated = self.libreoffice.try_recalc_xlsx(input_path)
        if recalculated is None:
            return None, core_cells
        updated = dict(core_cells)
        for ref, record in core_cells.items():
            if ref in recalculated and recalculated[ref] is not None:
                new_state = derive_read_state(
                    has_cached_value=True,
                    recalculation_provider="libreoffice",
                )
                updated[ref] = build_formula_cell_state(
                    state=new_state,
                    formula=record.get("formula", ""),
                    cached_value=recalculated[ref],
                    precedents_count=record.get("precedents_count", 0),
                    dependents_count=record.get("dependents_count", 0),
                )
        assert_invariant(updated, recalculation_provider="libreoffice")
        return "libreoffice", updated

    def _inspect(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = inspect_xlsx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.inert-inspection", operation_result),
        )

    def _create(self, request: ParsedXlsxRequest) -> dict[str, Any]:
        assert request.output_path is not None
        workbook = request.arguments["workbook"]
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "created.xlsx"
            creation = create_xlsx(staged, workbook)
            validation = validate_created(staged, workbook, creation=creation)
            # Build formula state for degradation
            formula_cells = creation.get("formula_cells", {})
            formula_summary = build_formula_state_summary(formula_cells)
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
            }
            degraded = should_downgrade(formula_summary)
            degradations: list[dict[str, Any]] = []
            if degraded:
                degradations.append({
                    "code": "outstanding-formula-recalculation",
                    "semantic_difference": "Created formulas require recalculation by an accepted provider.",
                    "missing_capabilities": ["recalculation"],
                    "recommended_providers": ["libreoffice"],
                })
            validation = with_formula_gate(validation, operation_result)
            result = write_candidate_result(
                self.schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=None,
                status="degraded" if degraded else "success",
                degraded=degraded,
                degradations=degradations,
            )
            return promote_candidate(
                request,
                staged,
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
                    allowed_removed_parts=(
                        set(manifest.removed)
                        if any(
                            edit["type"] in {
                                "sheet_delete",
                                "table_delete",
                                "chart_delete",
                                "comment_delete",
                            }
                            for edit in request.arguments["edits"]
                        )
                        else set()
                    ),
                    assertion=lambda candidate: assert_edits_applied(
                        candidate,
                        request.arguments["edits"],
                        source=request.input_path,
                    ),
                )
                # Build formula state for degradation
                formula_summary = build_formula_state_summary(
                    operation_result.get("formula_state", {}).get("cells", {})
                )
                operation_result["formula_state"]["summary"] = formula_summary
                degraded = should_downgrade(formula_summary)
                degradations: list[dict[str, Any]] = []
                if degraded:
                    degradations.append({
                        "code": "outstanding-formula-recalculation",
                        "semantic_difference": "Edited formulas require recalculation by an accepted provider.",
                        "missing_capabilities": ["recalculation"],
                        "recommended_providers": ["libreoffice"],
                    })
                validation = with_formula_gate(validation, operation_result)
                result = write_candidate_result(
                    self.schemas,
                    request,
                    staged,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source_record,
                    status="degraded" if degraded else "success",
                    degraded=degraded,
                    degradations=degradations,
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
                error, source_record.path, source_record.sha256
            )
            raise


def build_xlsx_service(project_root: Path, libreoffice=None) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    service = XlsxService(project_root, libreoffice=libreoffice)
    return service.execute
