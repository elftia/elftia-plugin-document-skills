"""XLSX public command surface tests — frozen uv subprocess boundary."""

import json
from pathlib import Path
import subprocess

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
    cwd: Path | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-xlsx/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=30,
    )
    if check:
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    payload, end = decoder.raw_decode(text)
    assert text[end:].strip() == ""
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _workbook() -> dict[str, object]:
    return {
        "metadata": {"title": "Public XLSX", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "10", "type": "n"},
                            {"ref": "B2", "formula": "B1*2", "type": "n"},
                        ],
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
def public_created(project_root: Path, tmp_path: Path) -> Path:
    output = tmp_path / "public-created.xlsx"
    request = _request(
        tmp_path,
        "create.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _workbook()},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] in {"success", "degraded"}
    SchemaCatalog(project_root).validate("operation-result", result)
    return output


def test_public_capabilities_list_xlsx_operations(project_root: Path) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert "xlsx.read" in operations
    assert "xlsx.inspect.structure" in operations
    assert "xlsx.create" in operations
    assert "xlsx.edit" in operations
    assert all(item["available"] for item in operations.values() if "xlsx" in item["operation"])


def test_public_doctor_succeeds(project_root: Path) -> None:
    report = _public(project_root, "doctor", "--json")
    assert report["status"] == "healthy"


def test_public_create_and_read(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] in {"success", "degraded"}
    assert result["diagnostics"]["operation_result"]["sheet_count"] == 1


def test_public_inspect_inert(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(inspect_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["mutation_authorized"] is False


def test_public_edit_produces_distinct_output(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-edited.xlsx"
    edit_request = _request(
        tmp_path,
        "edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "A1", "value": "Modified"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] in {"success", "degraded"}
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


def test_public_validate_reopens_valid_xlsx(project_root: Path, public_created: Path) -> None:
    result = _public(
        project_root,
        "validate",
        "--input",
        str(public_created),
        "--json",
    )
    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "pass"
    assert outcomes["provider.reopen"] == "pass"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"


def test_public_unknown_operation_rejected(project_root: Path, tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.nonexistent",
            "input": str(tmp_path / "input.xlsx"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_OPERATION_UNKNOWN"


def test_public_formula_state_never_recalculated(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    """The core invariant: no formula is ever reported as recalculated without a provider."""
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(public_created),
            "arguments": {"include_formulas": True},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    formula_state = result["diagnostics"]["operation_result"]["formula_state"]
    for ref, cell in formula_state["cells"].items():
        assert cell["state"] != "recalculated", f"Cell {ref} falsely reports recalculated"
    assert formula_state["summary"]["no_unverified_claimed_recalculated"] is True
    assert formula_state["summary"]["recalculation_provider"] == "unavailable"


def test_public_edit_invalidates_dependents(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    """Editing a precedent marks dependent formulas as recalculation_required."""
    output = tmp_path / "invalidated.xlsx"
    edit_request = _request(
        tmp_path,
        "edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "99"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    formula_cells = result["diagnostics"]["operation_result"].get("formula_state", {}).get("cells", {})
    # The formula B2=B1*2 should be invalidated because B1 was edited
    invalidated = [
        ref for ref, c in formula_cells.items()
        if c.get("state") == "recalculation_required"
    ]
    assert len(invalidated) > 0, "Expected dependent invalidation"
