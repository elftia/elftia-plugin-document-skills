"""XLSX operation tests — create, read, inspect, edit through the real service."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.xlsx.constants import (
    FORMULA_STATE_RECALCULATION_REQUIRED,
    FORMULA_STATE_STALE,
)
from document_skills_core.formats.xlsx.service import XlsxService


def _service(project_root: Path) -> XlsxService:
    return XlsxService(project_root)


def _sample_workbook() -> dict:
    return {
        "metadata": {"title": "Test Workbook", "creator": "Test", "subject": "Testing"},
        "sheets": [
            {
                "name": "Data",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "Value", "type": "s"},
                            {"ref": "A2", "value": "Alpha", "type": "s"},
                            {"ref": "B2", "value": "10", "type": "n"},
                            {"ref": "A3", "value": "Beta", "type": "s"},
                            {"ref": "B3", "value": "20", "type": "n"},
                        ],
                    },
                    {
                        "cells": [
                            {"ref": "A5", "value": "Total", "type": "s"},
                            {"ref": "B5", "formula": "SUM(B2:B3)", "type": "n"},
                        ],
                    },
                ],
                "number_formats": [],
            },
            {
                "name": "Summary",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Result", "type": "s"},
                            {"ref": "B1", "formula": "Data!B5*2", "type": "n"},
                        ],
                    }
                ],
                "number_formats": [],
            },
        ],
        "defined_names": [
            {"name": "TotalVal", "ref": "Data!$B$5", "scope": "workbook"},
        ],
        "tables": [
            {"name": "DataTable", "ref": "A1:B3", "sheet": "Data", "style": "TableStyleMedium2"},
        ],
        "chart_reference": {
            "title": "Values Chart",
            "data_ref": "Data!B2:B3",
            "sheet": "Data",
        },
        "page_setup": {
            "orientation": "portrait",
            "header": "Test Header",
            "footer": "Test Footer",
        },
    }


@pytest.fixture
def created_xlsx(project_root: Path, tmp_path: Path) -> Path:
    output = tmp_path / "created.xlsx"
    service = _service(project_root)
    result = service.execute("xlsx.create", {
        "schema_version": "1.0",
        "operation": "xlsx.create",
        "output": str(output),
        "arguments": {"workbook": _sample_workbook()},
    })
    assert result["status"] in {"success", "degraded"}
    assert output.is_file()
    return output


class TestCreateOperation:
    def test_create_produces_valid_workbook(self, project_root: Path, tmp_path: Path):
        output = tmp_path / "test.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.create", {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _sample_workbook()},
        })
        assert result["status"] in {"success", "degraded"}
        assert result["provider_chain"] == []
        assert output.is_file()
        assert result["artifacts"][-1]["sha256"]

    def test_created_formulas_report_recalculation_required(self, project_root: Path, tmp_path: Path):
        output = tmp_path / "formulas.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.create", {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _sample_workbook()},
        })
        formula_state = result["diagnostics"]["operation_result"]["formula_state"]
        for ref, cell_state in formula_state["cells"].items():
            assert cell_state["state"] != "recalculated", f"Cell {ref} falsely reports recalculated"
            assert cell_state["state"] in {"recalculation_required", "stale"}

    def test_create_with_formulas_is_degraded(self, project_root: Path, tmp_path: Path):
        """A workbook with formulas must report degraded status when recalculation is outstanding."""
        output = tmp_path / "degraded.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.create", {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _sample_workbook()},
        })
        assert result["status"] == "degraded"
        assert result["degraded"] is True
        assert any(d["code"] == "outstanding-formula-recalculation" for d in result["degradations"])


class TestReadOperation:
    def test_read_returns_structure(self, project_root: Path, created_xlsx: Path):
        service = _service(project_root)
        result = service.execute("xlsx.read", {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(created_xlsx),
            "arguments": {},
        })
        op_result = result["diagnostics"]["operation_result"]
        assert result["status"] in {"success", "degraded"}
        assert op_result["sheet_count"] == 2
        sheets = op_result["sheets"]
        assert sheets[0]["name"] == "Data"
        assert sheets[1]["name"] == "Summary"

    def test_read_reports_formula_state(self, project_root: Path, created_xlsx: Path):
        service = _service(project_root)
        result = service.execute("xlsx.read", {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(created_xlsx),
            "arguments": {},
        })
        formula_state = result["diagnostics"]["operation_result"]["formula_state"]
        # There should be formula cells (SUM and cross-sheet ref)
        assert len(formula_state["cells"]) > 0
        # No formula should report recalculated without a provider
        for ref, cell in formula_state["cells"].items():
            assert cell["state"] != "recalculated"
        assert formula_state["summary"]["no_unverified_claimed_recalculated"] is True

    def test_read_preserves_source(self, project_root: Path, created_xlsx: Path):
        import hashlib
        original_hash = hashlib.sha256(created_xlsx.read_bytes()).hexdigest()
        service = _service(project_root)
        service.execute("xlsx.read", {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(created_xlsx),
            "arguments": {},
        })
        assert hashlib.sha256(created_xlsx.read_bytes()).hexdigest() == original_hash


class TestInspectOperation:
    def test_inspect_returns_inventory(self, project_root: Path, created_xlsx: Path):
        service = _service(project_root)
        result = service.execute("xlsx.inspect.structure", {
            "schema_version": "1.0",
            "operation": "xlsx.inspect.structure",
            "input": str(created_xlsx),
            "arguments": {},
        })
        op_result = result["diagnostics"]["operation_result"]
        assert result["status"] == "success"
        assert op_result["mutation_authorized"] is False
        assert op_result["part_count"] > 0
        assert op_result["worksheet_count"] == 2

    def test_inspection_does_not_authorize_mutation(self, project_root: Path, created_xlsx: Path):
        service = _service(project_root)
        result = service.execute("xlsx.inspect.structure", {
            "schema_version": "1.0",
            "operation": "xlsx.inspect.structure",
            "input": str(created_xlsx),
            "arguments": {},
        })
        assert result["diagnostics"]["operation_result"]["mutation_authorized"] is False


class TestEditOperation:
    def test_edit_cell_value(self, project_root: Path, created_xlsx: Path, tmp_path: Path):
        output = tmp_path / "edited.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.edit", {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(created_xlsx),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "cell_value", "ref": "B2", "value": "99"},
                ],
            },
        })
        assert result["status"] in {"success", "degraded"}
        assert output.is_file()
        assert created_xlsx.is_file()  # source preserved

    def test_edit_preserves_source(self, project_root: Path, created_xlsx: Path, tmp_path: Path):
        import hashlib
        original_hash = hashlib.sha256(created_xlsx.read_bytes()).hexdigest()
        output = tmp_path / "edited.xlsx"
        service = _service(project_root)
        service.execute("xlsx.edit", {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(created_xlsx),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "cell_value", "ref": "A2", "value": "Modified"},
                ],
            },
        })
        assert hashlib.sha256(created_xlsx.read_bytes()).hexdigest() == original_hash

    def test_edit_formula_invalidates_dependents(self, project_root: Path, created_xlsx: Path, tmp_path: Path):
        """Editing a precedent cell should mark dependents as recalculation_required."""
        output = tmp_path / "invalidated.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.edit", {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(created_xlsx),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "cell_value", "ref": "B2", "value": "100"},
                ],
            },
        })
        formula_state = result["diagnostics"]["operation_result"].get("formula_state", {})
        cells = formula_state.get("cells", {})
        # At least one formula should be recalculation_required
        recalc_required = [
            ref for ref, c in cells.items()
            if c.get("state") == FORMULA_STATE_RECALCULATION_REQUIRED
        ]
        assert len(recalc_required) > 0, "Expected at least one dependent invalidated"

    def test_edit_output_equals_input_rejected(self, project_root: Path, created_xlsx: Path):
        service = _service(project_root)
        result = service.execute("xlsx.edit", {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(created_xlsx),
            "output": str(created_xlsx),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "cell_value", "ref": "A1", "value": "X"},
                ],
            },
        })
        assert result["status"] == "invalid_request"
        assert result["errors"][0]["code"] == "DS_OUTPUT_EQUALS_INPUT"
