"""Real frozen-uv public truth for B5 SVG and scene operations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

import pytest
from tests.support.pptx_template_fixture import owner_contract_root

from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
)


def _public(
    project_root: Path,
    *arguments: str,
    cwd: Path | None = None,
) -> tuple[int, dict[str, object]]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pptx/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    assert process.returncode in {0, 2}, process.stderr.decode(
        "utf-8", errors="replace"
    )
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    payload, end = json.JSONDecoder().raw_decode(text)
    assert text[end:].strip() == ""
    assert type(payload) is dict
    return process.returncode, payload


def _request(path: Path, value: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _fixtures(project_root: Path) -> Path:
    return project_root / "tests" / "fixtures" / "pptx" / "ecosystem_bc"


def _owner_contract(project_root: Path) -> Path:
    candidate = owner_contract_root(project_root)
    if not candidate.is_dir():
        pytest.skip("owner presentation-contract package is not installed")
    return candidate


def _scene_arguments(contract_root: Path) -> dict[str, object]:
    return {
        "contract": {
            "manifest_sha256": PRESENTATION_CONTRACT_V1_PIN.manifest_sha256,
            "root": str(contract_root),
        },
        "identity": {
            "namespace": "example.synthetic",
            "source_template_id": "svg-roundtrip",
            "source_template_version": "1.0.0",
        },
        "mode": "strict",
    }


def test_public_capabilities_truthfully_advertise_b5_operations(
    project_root: Path,
) -> None:
    returncode, report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}

    assert returncode == 0
    for operation in ("pptx.create.from-svg", "pptx.scene.export"):
        assert operations[operation]["available"] is True
        assert operations[operation]["providers"] == ["core-python"]
        assert operations[operation]["fidelity"] == "core"


def test_public_svg_success_and_unsafe_failure_preserve_inputs(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixtures = _fixtures(project_root) / "svg"
    source = fixtures / "native-basic" / "native-basic.svg"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "native.pptx"
    success_request = _request(
        tmp_path / "svg-success.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.create.from-svg",
            "input": str(source),
            "output": str(output),
            "arguments": {"fallback_policy": "reject"},
        },
    )
    returncode, success = _public(
        project_root,
        "run",
        "--request",
        str(success_request),
        cwd=tmp_path,
    )

    assert returncode == 0
    assert success["status"] in {"success", "degraded"}
    assert success["validation"]["status"] == "pass"
    assert output.is_file()
    assert success["diagnostics"]["operation_result"]["coverage"][
        "whole_slide_raster"
    ] is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash

    unsafe = fixtures / "unsupported" / "script.svg"
    unsafe_hash = hashlib.sha256(unsafe.read_bytes()).hexdigest()
    unsafe_output = tmp_path / "unsafe.pptx"
    unsafe_request = _request(
        tmp_path / "svg-unsafe.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.create.from-svg",
            "input": str(unsafe),
            "output": str(unsafe_output),
            "arguments": {"fallback_policy": "element-rasterize"},
        },
    )
    returncode, failed = _public(
        project_root,
        "run",
        "--request",
        str(unsafe_request),
        cwd=tmp_path,
    )

    assert returncode == 2
    assert failed["status"] == "failed"
    assert failed["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert not unsafe_output.exists()
    assert hashlib.sha256(unsafe.read_bytes()).hexdigest() == unsafe_hash


def test_public_svg_rejects_excessive_group_depth_before_recursion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    body = "".join(f'<g id="group-{index}">' for index in range(65))
    body += '<rect id="leaf" x="10" y="10" width="100" height="100"/>'
    body += "</g>" * 65
    source = tmp_path / "deep-groups.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
        f'viewBox="0 0 1920 1080">{body}</svg>',
        encoding="utf-8",
        newline="\n",
    )
    output = tmp_path / "deep-groups.pptx"
    request = _request(
        tmp_path / "deep-groups.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.create.from-svg",
            "input": str(source),
            "output": str(output),
            "arguments": {"fallback_policy": "reject"},
        },
    )

    returncode, result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        cwd=tmp_path,
    )

    assert returncode == 2
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_RESOURCE_LIMIT"
    assert result["errors"][0]["details"] == {"limit": 64}
    assert not output.exists()


def test_public_scene_export_success_stale_contract_and_existing_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _fixtures(project_root) / "svg" / "roundtrip-source.pptx"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    contract_root = _owner_contract(project_root)
    output = tmp_path / "scene-bundle"
    success_request = _request(
        tmp_path / "scene-success.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.scene.export",
            "input": str(source),
            "output": str(output),
            "arguments": _scene_arguments(contract_root),
        },
    )
    returncode, success = _public(
        project_root,
        "run",
        "--request",
        str(success_request),
        cwd=tmp_path,
    )

    assert returncode == 0
    assert success["status"] == "success"
    assert success["validation"]["status"] == "pass"
    assert (output / "manifest.json").is_file()
    assert (output / "deck-ir.json").is_file()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash

    stale_output = tmp_path / "stale-bundle"
    stale_request_value = {
        "schema_version": "1.0",
        "operation": "pptx.scene.export",
        "input": str(source),
        "output": str(stale_output),
        "arguments": _scene_arguments(tmp_path / "missing-contract"),
    }
    stale_request = _request(tmp_path / "scene-stale.json", stale_request_value)
    returncode, stale = _public(
        project_root,
        "run",
        "--request",
        str(stale_request),
        cwd=tmp_path,
    )
    assert returncode == 2
    assert stale["status"] == "invalid_request"
    assert stale["errors"][0]["code"] == "DS_STALE_PRECONDITION"
    assert not stale_output.exists()

    existing = tmp_path / "existing-bundle"
    existing.mkdir()
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    existing_request = _request(
        tmp_path / "scene-existing.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.scene.export",
            "input": str(source),
            "output": str(existing),
            "arguments": _scene_arguments(contract_root),
        },
    )
    returncode, occupied = _public(
        project_root,
        "run",
        "--request",
        str(existing_request),
        cwd=tmp_path,
    )
    assert returncode == 2
    assert occupied["status"] == "invalid_request"
    assert occupied["errors"][0]["code"] == "DS_PATH_UNSAFE"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (existing / "manifest.json").exists()
