"""Conditional real OpenXML SDK regression for x14 spreadsheet extensions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from document_skills_core.core.capabilities import ProviderCatalog
from document_skills_core.formats.xlsx.service import XlsxService
from document_skills_core.providers import build_default_registry
from document_skills_core.providers.dotnet.constants import RUNTIME_PREFIX
from test_xlsx_sparkline import _workbook


@pytest.fixture(scope="module")
def dotnet_sdk() -> str:
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
        env=_dotnet_environment(),
    )
    if sdk_probe.returncode != 0 or not sdk_probe.stdout.strip():
        pytest.skip("dotnet SDK is not callable")
    return dotnet


@pytest.fixture
def x14_workbooks(
    project_root: Path,
    tmp_path: Path,
) -> tuple[Path, Path]:
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
    malformed = tmp_path / "malformed-x14-sparklines.xlsx"
    _remove_required_sparkline_location(valid, malformed)
    return valid, malformed


def test_real_openxml_helper_accepts_and_rejects_x14_sparklines(
    dotnet_sdk: str,
    project_root: Path,
    x14_workbooks: tuple[Path, Path],
) -> None:
    helper = (
        project_root
        / "src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj"
    )
    environment = _dotnet_environment()
    restored = subprocess.run(
        [
            dotnet_sdk,
            "restore",
            str(helper),
            "--locked-mode",
            "--use-lock-file",
        ],
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

    valid, malformed = x14_workbooks
    valid_schema = _validate_helper(
        dotnet_sdk,
        helper,
        project_root,
        valid,
        environment,
    )
    assert valid_schema["file_format"] == "Microsoft365"
    assert valid_schema["valid"] is True, valid_schema["errors"]

    invalid_schema = _validate_helper(
        dotnet_sdk,
        helper,
        project_root,
        malformed,
        environment,
    )
    assert invalid_schema["file_format"] == "Microsoft365"
    assert invalid_schema["valid"] is False
    assert invalid_schema["errors"]


def test_default_registry_provider_validates_real_x14_sparklines(
    dotnet_sdk: str,
    project_root: Path,
    x14_workbooks: tuple[Path, Path],
) -> None:
    runtime_probe = subprocess.run(
        [dotnet_sdk, "--list-runtimes"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        timeout=15,
        check=False,
        env=_dotnet_environment(),
    )
    if runtime_probe.returncode != 0 or RUNTIME_PREFIX not in runtime_probe.stdout:
        pytest.skip("Microsoft.NETCore.App 8.x is not installed")

    registry = build_default_registry(project_root)
    provider = registry.providers["dotnet-openxml"]
    evidence = registry.detect(provider)
    if evidence["available"] is not True:
        pytest.skip(f"dotnet-openxml provider unavailable: {evidence['reason']}")
    valid, malformed = x14_workbooks
    valid_result = _validate_provider(registry, valid)
    assert valid_result["provider_chain"] == ["dotnet-openxml"]
    valid_schema = valid_result["diagnostics"]["operation_result"]["schema"]
    assert valid_schema["file_format"] == "Microsoft365"
    assert valid_schema["valid"] is True, valid_schema["errors"]

    invalid_result = _validate_provider(registry, malformed)
    assert invalid_result["provider_chain"] == ["dotnet-openxml"]
    invalid_schema = invalid_result["diagnostics"]["operation_result"]["schema"]
    assert invalid_schema["file_format"] == "Microsoft365"
    assert invalid_schema["valid"] is False
    assert invalid_schema["errors"]


def _validate_provider(
    registry: ProviderCatalog,
    workbook: Path,
) -> dict[str, object]:
    return registry.execute({
        "schema_version": "1.0",
        "operation": "xlsx.validate.schema",
        "input": str(workbook),
        "arguments": {"max_errors": 20},
    })


def _validate_helper(
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


def _dotnet_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] = "0"
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    environment["DOTNET_ROLL_FORWARD"] = "Major"
    return environment


def test_dotnet_subprocess_environment_disables_global_path_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOTNET_ADD_GLOBAL_TOOLS_TO_PATH", "1")

    assert _dotnet_environment()["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] == "0"


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
