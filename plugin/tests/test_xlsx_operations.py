"""XLSX operation tests — create, read, inspect, edit through the real service."""

import hashlib
from pathlib import Path
import zipfile

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.xlsx.constants import (
    FORMULA_STATE_RECALCULATION_REQUIRED,
    FORMULA_STATE_STALE,
)
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.service import XlsxService


def _service(project_root: Path) -> XlsxService:
    return XlsxService(project_root)


def _strip_style_children(path: Path) -> None:
    """Replace styles.xml with an empty-container form that fails the style gate."""

    with zipfile.ZipFile(path, "r") as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["xl/styles.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        b'<fonts count="1"/><fills count="2"/><borders count="1"/>'
        b'<cellStyleXfs count="1"/><cellXfs count="1"/>'
        b'<cellStyles count="1"/><dxfs count="0"/></styleSheet>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(parts.items()):
            archive.writestr(name, data)


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


def _bounded_workbook() -> dict:
    return {
        "metadata": {"title": "Bounded", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "10", "type": "n"},
                        ]
                    }
                ],
                "number_formats": [],
            }
        ],
        "defined_names": [],
        "tables": [],
        "chart_reference": None,
        "page_setup": None,
    }


@pytest.fixture
def created_xlsx(project_root: Path, tmp_path: Path) -> Path:
    from openpyxl import Workbook

    output = tmp_path / "created.xlsx"
    workbook = Workbook()
    data = workbook.active
    data.title = "Data"
    data["A1"] = "Name"
    data["B1"] = "Value"
    data["A2"] = "Alpha"
    data["B2"] = 10
    data["A3"] = "Beta"
    data["B3"] = 20
    data["A5"] = "Total"
    data["B5"] = "=SUM(B2:B3)"
    summary = workbook.create_sheet("Summary")
    summary["A1"] = "Result"
    summary["B1"] = "=Data!B5*2"
    workbook.save(output)
    return output


class TestCreateOperation:
    def test_disconnected_create_request_fails_before_output(self, project_root: Path, tmp_path: Path):
        output = tmp_path / "test.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.create", {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _sample_workbook()},
        })
        assert result["status"] == "enhancement_required"
        assert result["provider_chain"] == []
        assert not output.exists()
        assert not result["artifacts"]

    def test_disconnected_create_does_not_report_formula_success(self, project_root: Path, tmp_path: Path):
        output = tmp_path / "formulas.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.create", {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _sample_workbook()},
        })
        assert result["status"] == "enhancement_required"
        assert "operation_result" not in result["diagnostics"]
        assert not output.exists()

    def test_create_with_disconnected_features_is_not_degraded(self, project_root: Path, tmp_path: Path):
        output = tmp_path / "degraded.xlsx"
        service = _service(project_root)
        result = service.execute("xlsx.create", {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _sample_workbook()},
        })
        assert result["status"] == "enhancement_required"
        assert result["degraded"] is False
        assert not result["degradations"]
        assert not output.exists()


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
        assert any(
            gate["id"] == "operation.consumer-package-conformance"
            and gate["outcome"] == "pass"
            for gate in result["validation"]["gates"]
        )

    def test_edit_rejects_consumer_invalid_package_without_promotion(
        self,
        project_root: Path,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "core-invalid.xlsx"
        create_xlsx(source, _bounded_workbook())
        _strip_style_children(source)
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        output = tmp_path / "existing.xlsx"
        existing = b"existing-destination-must-survive"
        output.write_bytes(existing)
        service = _service(project_root)

        result = service.execute(
            "xlsx.edit",
            {
                "schema_version": "1.0",
                "operation": "xlsx.edit",
                "input": str(source),
                "output": str(output),
                "arguments": {
                    "edits": [
                        {
                            "sheet": "Sheet1",
                            "type": "cell_value",
                            "ref": "B1",
                            "value": "42",
                        }
                    ]
                },
            },
        )

        SchemaCatalog(project_root).validate("operation-result", result)
        assert result["status"] == "failed"
        assert result["validation"]["status"] == "fail"
        assert any(
            gate["id"] == "operation.consumer-package-conformance"
            and gate["required"] is True
            and gate["outcome"] == "fail"
            for gate in result["validation"]["gates"]
        )
        assert result["artifacts"] == []
        assert output.read_bytes() == existing
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256

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
                    {"sheet": "Data", "type": "cell_value", "ref": "B3", "value": "21"},
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
