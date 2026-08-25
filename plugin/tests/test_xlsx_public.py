"""XLSX public command surface tests — frozen uv subprocess boundary."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.xlsx.create import create_xlsx


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
    from openpyxl import Workbook

    output = tmp_path / "public-created.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet["A1"] = "Name"
    sheet["B1"] = 10
    sheet["B2"] = "=B1*2"
    workbook.save(output)
    return output


def test_public_create_is_truthful_and_promotes_bounded_artifact(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bounded.xlsx"
    request = _request(
        tmp_path,
        "create-bounded.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _workbook()},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] in {"success", "degraded"}
    assert output.is_file()
    assert any(
        item["path"] == str(output.resolve())
        for item in result["artifacts"]
    )
    assert any(
        gate["id"] == "operation.consumer-package-conformance"
        and gate["outcome"] == "pass"
        for gate in result["validation"]["gates"]
    )


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
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "42"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] in {"success", "degraded"}
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])
    assert any(
        gate["id"] == "operation.consumer-package-conformance"
        and gate["outcome"] == "pass"
        for gate in result["validation"]["gates"]
    )


def test_public_edit_rejects_consumer_invalid_package_and_preserves_paths(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "core-invalid.xlsx"
    create_xlsx(source, _workbook())
    _strip_style_children(source)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "existing.xlsx"
    existing = b"existing-public-destination"
    output.write_bytes(existing)
    edit_request = _request(
        tmp_path,
        "invalid-edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "42"}
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(edit_request), check=False)

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


def test_public_formula_state_never_claims_unverified_recalculation(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    """Recalculated formulas must be provider-backed rather than unverified claims."""
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
    summary = formula_state["summary"]
    if summary["recalculation_provider"] == "unavailable":
        for ref, cell in formula_state["cells"].items():
            assert cell["state"] != "recalculated", f"Cell {ref} falsely reports recalculated"
    assert summary["no_unverified_claimed_recalculated"] is True


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
