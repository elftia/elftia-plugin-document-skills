"""Explicit Core-only XLSX seam through the real public façade."""

import json
import os
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
import sys
from typing import Any

import pytest

import document_skills_core.providers.defaults as provider_defaults
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode
from document_skills_core.core.process.runner import ProcessRunner

_CORE_ONLY_ENV = "DOCUMENT_SKILLS_XLSX_CORE_ONLY"


def _workbook() -> dict[str, Any]:
    return {
        "metadata": {"title": "Core-only XLSX", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "10", "type": "n"},
                            {"ref": "B2", "formula": "B1*2", "type": "n"},
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


def _public_run(
    project_root: Path,
    tmp_path: Path,
    name: str,
    request: dict[str, Any],
    *,
    core_only_value: str = "1",
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, Any]]:
    request_path = tmp_path / f"{name}-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    environment = os.environ.copy()
    environment[_CORE_ONLY_ENV] = core_only_value
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "skills/document-xlsx/scripts/run.py"),
            "run",
            "--request",
            str(request_path),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    assert completed.stderr == b""
    payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return completed, payload


def _assert_no_false_recalculated(result: dict[str, Any]) -> None:
    operation_result = result["diagnostics"]["operation_result"]
    formula_state = operation_result.get("formula_state")
    if formula_state is None:
        return
    assert formula_state["summary"]["no_unverified_claimed_recalculated"] is True
    assert all(
        cell.get("state") != "recalculated"
        for cell in formula_state["cells"].values()
    )


def test_public_core_only_runs_four_foundation_operations(
    project_root: Path,
    tmp_path: Path,
) -> None:
    created = tmp_path / "created.xlsx"
    edited = tmp_path / "edited.xlsx"
    requests = [
        (
            "create",
            {
                "schema_version": "1.0",
                "operation": "xlsx.create",
                "output": str(created),
                "arguments": {"workbook": _workbook(), "recalculation": "auto"},
            },
        ),
        (
            "read",
            {
                "schema_version": "1.0",
                "operation": "xlsx.read",
                "input": str(created),
                "arguments": {},
            },
        ),
        (
            "inspect",
            {
                "schema_version": "1.0",
                "operation": "xlsx.inspect.structure",
                "input": str(created),
                "arguments": {},
            },
        ),
        (
            "edit",
            {
                "schema_version": "1.0",
                "operation": "xlsx.edit",
                "input": str(created),
                "output": str(edited),
                "arguments": {
                    "edits": [
                        {
                            "sheet": "Sheet1",
                            "type": "cell_value",
                            "ref": "B1",
                            "value": "11",
                        }
                    ],
                    "recalculation": "auto",
                },
            },
        ),
    ]

    results: dict[str, dict[str, Any]] = {}
    for name, request in requests:
        completed, result = _public_run(project_root, tmp_path, name, request)
        assert completed.returncode == 0, result
        assert result["provider_chain"] == ["core-python"]
        _assert_no_false_recalculated(result)
        results[name] = result

    for name in ("create", "edit"):
        recalculation = results[name]["diagnostics"]["operation_result"][
            "recalculation"
        ]
        assert recalculation["policy"] == "auto"
        assert recalculation["outcome"] == "unavailable"
        assert recalculation["reason"] == "provider-not-configured"
    assert created.is_file()
    assert edited.is_file()


@pytest.mark.parametrize("value", ["", "true", "01", " 1", "2"])
def test_core_only_environment_rejects_non_binary_values(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(_CORE_ONLY_ENV, value)
    with pytest.raises(DocumentSkillsError) as failure:
        provider_defaults.build_default_registry(project_root)
    assert failure.value.code == ErrorCode.REQUEST_INVALID
    assert failure.value.status == "invalid_request"
    assert failure.value.details == {
        "setting": _CORE_ONLY_ENV,
        "allowed_values": ["0", "1"],
    }


@pytest.mark.parametrize(
    ("value", "expects_libreoffice"),
    [(None, True), ("0", True), ("1", False)],
)
def test_core_only_default_registry_seam_is_xlsx_only(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    expects_libreoffice: bool,
) -> None:
    if value is None:
        monkeypatch.delenv(_CORE_ONLY_ENV, raising=False)
    else:
        monkeypatch.setenv(_CORE_ONLY_ENV, value)
    observed: dict[str, object] = {}
    real_docx_builder = provider_defaults.build_docx_service
    real_pdf_builder = provider_defaults.build_pdf_service
    real_pptx_builder = provider_defaults.build_pptx_service
    real_xlsx_builder = provider_defaults.build_xlsx_service

    def capture_docx_builder(root: Path, *, libreoffice=None, dotnet=None):
        observed["docx"] = libreoffice
        return real_docx_builder(root, libreoffice=libreoffice, dotnet=dotnet)

    def capture_pdf_builder(root: Path, *, libreoffice=None):
        observed["pdf"] = libreoffice
        return real_pdf_builder(root, libreoffice=libreoffice)

    def capture_pptx_builder(root: Path, *, libreoffice=None, dotnet=None):
        observed["pptx"] = libreoffice
        observed["pptx-dotnet"] = dotnet
        return real_pptx_builder(root, libreoffice=libreoffice, dotnet=dotnet)

    def capture_xlsx_builder(root: Path, *, libreoffice=None):
        observed["xlsx"] = libreoffice
        return real_xlsx_builder(root, libreoffice=libreoffice)

    monkeypatch.setattr(provider_defaults, "build_docx_service", capture_docx_builder)
    monkeypatch.setattr(provider_defaults, "build_pdf_service", capture_pdf_builder)
    monkeypatch.setattr(provider_defaults, "build_pptx_service", capture_pptx_builder)
    monkeypatch.setattr(provider_defaults, "build_xlsx_service", capture_xlsx_builder)
    registry = provider_defaults.build_default_registry(project_root)

    assert (observed["xlsx"] is not None) is expects_libreoffice
    assert all(observed[format_id] is not None for format_id in ("docx", "pdf", "pptx"))
    assert observed["pptx-dotnet"] is not None
    assert "libreoffice" in registry.providers


def test_core_only_control_is_safely_forwarded_by_minimal_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_CORE_ONLY_ENV, "1")
    monkeypatch.setenv("DOCUMENT_SKILLS_UNRELATED_SECRET", "must-not-pass")

    environment = ProcessRunner._minimal_environment()

    assert environment[_CORE_ONLY_ENV] == "1"
    assert "DOCUMENT_SKILLS_UNRELATED_SECRET" not in environment


def test_public_core_only_invalid_value_fails_closed(
    project_root: Path,
    tmp_path: Path,
) -> None:
    completed, result = _public_run(
        project_root,
        tmp_path,
        "invalid-control",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(tmp_path / "must-not-exist.xlsx"),
            "arguments": {"workbook": _workbook(), "recalculation": "auto"},
        },
        core_only_value="true",
    )

    assert completed.returncode == 2
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID
    assert not (tmp_path / "must-not-exist.xlsx").exists()
