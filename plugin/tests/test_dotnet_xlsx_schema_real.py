"""Conditional real OpenXML SDK regression for x14 spreadsheet extensions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from document_skills_core.formats.xlsx.service import XlsxService
from test_xlsx_sparkline import _workbook


def test_real_openxml_microsoft365_schema_accepts_and_rejects_x14_sparklines(
    project_root: Path,
    tmp_path: Path,
) -> None:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("dotnet SDK is not installed")
    sdk_probe = subprocess.run(
        [dotnet, "--list-sdks"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        timeout=15,
        check=False,
    )
    if sdk_probe.returncode != 0 or not sdk_probe.stdout.strip():
        pytest.skip("dotnet SDK is not callable")

    helper = (
        project_root
        / "src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj"
    )
    environment = os.environ.copy()
    environment["DOTNET_ROLL_FORWARD"] = "Major"
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    restored = subprocess.run(
        [dotnet, "restore", str(helper), "--locked-mode", "--use-lock-file"],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        timeout=120,
        check=False,
        env=environment,
    )
    assert restored.returncode == 0, (
        f"locked NuGet restore failed with exit {restored.returncode}"
    )

    valid = tmp_path / "valid-x14-sparklines.xlsx"
    created = XlsxService(project_root).execute(
        "xlsx.create",
        {
            "operation": "xlsx.create",
            "output": str(valid),
            "arguments": {"workbook": _workbook()},
        },
    )
    assert created["status"] == "success", created
    valid_result = _validate(dotnet, helper, project_root, valid, environment)
    assert valid_result["file_format"] == "Microsoft365"
    assert valid_result["valid"] is True, valid_result["errors"]

    malformed = tmp_path / "malformed-x14-sparklines.xlsx"
    _remove_required_sparkline_location(valid, malformed)
    invalid_result = _validate(
        dotnet,
        helper,
        project_root,
        malformed,
        environment,
    )
    assert invalid_result["file_format"] == "Microsoft365"
    assert invalid_result["valid"] is False
    assert invalid_result["errors"]


def _validate(
    dotnet: str,
    helper: Path,
    project_root: Path,
    workbook: Path,
    environment: dict[str, str],
) -> dict[str, object]:
    completed = subprocess.run(
        [
            dotnet,
            "run",
            "--no-restore",
            "--project",
            str(helper),
            "--",
            "--xlsx-schema-validate",
        ],
        cwd=project_root,
        input=json.dumps({"input_path": str(workbook), "max_errors": 20}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        timeout=120,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, (
        f"OpenXML helper failed with exit {completed.returncode}"
    )
    return json.loads(completed.stdout)


def _remove_required_sparkline_location(source: Path, output: Path) -> None:
    target = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(source, "r") as source_archive:
        with zipfile.ZipFile(output, "w") as output_archive:
            for item in source_archive.infolist():
                payload = source_archive.read(item.filename)
                if item.filename == target:
                    marker = b"<xm:sqref>E2</xm:sqref>"
                    assert marker in payload
                    payload = payload.replace(marker, b"", 1)
                output_archive.writestr(item, payload)
