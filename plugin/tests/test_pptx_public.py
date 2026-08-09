"""PPTX public command surface tests — frozen uv subprocess boundary."""

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
            str(project_root / "skills/document-pptx/scripts/run.py"),
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


def _deck() -> dict[str, object]:
    return {
        "metadata": {"title": "Public PPTX", "creator": "Test", "subject": ""},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": [
            {
                "layout": "title",
                "title": "Title",
                "shapes": [
                    {"text": "Body", "runs": [{"text": "Body", "style": None}]}
                ],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": "Speaker notes",
            },
            {
                "layout": "content",
                "title": "Content",
                "shapes": [
                    {"text": "Content body", "runs": [{"text": "Content", "style": None}]}
                ],
                "table": {"rows": [{"cells": ["A", "B"]}]},
                "chart_reference": {"title": "Chart", "chart_type": "bar"},
                "image_reference": {"filename": "img.png", "content_type": "image/png"},
                "notes": None,
            },
        ],
    }


@pytest.fixture
def public_created(project_root: Path, tmp_path: Path) -> Path:
    output = tmp_path / "public-created.pptx"
    request = _request(
        tmp_path,
        "create.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.create",
            "output": str(output),
            "arguments": {"deck": _deck()},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success"
    SchemaCatalog(project_root).validate("operation-result", result)
    return output


def test_public_capabilities_list_pptx_operations(project_root: Path) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert "pptx.read" in operations
    assert "pptx.inspect.structure" in operations
    assert "pptx.create" in operations
    assert "pptx.edit" in operations
    assert all(item["available"] for item in operations.values() if "pptx" in item["operation"])


def test_public_doctor_succeeds(project_root: Path) -> None:
    report = _public(project_root, "doctor", "--json")
    assert report["status"] == "healthy"


def test_public_create_and_read(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["slide_count"] == 2


def test_public_inspect_inert(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(inspect_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["mutation_authorized"] is False


def test_public_edit_produces_distinct_output(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-edited.pptx"
    edit_request = _request(
        tmp_path,
        "edit.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"slide": 1, "type": "slide_text", "ref": "", "value": "Modified"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] == "success"
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


def test_public_reorder_preserves_slides(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-reordered.pptx"
    edit_request = _request(
        tmp_path,
        "reorder.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] == "success"
    op_result = result["diagnostics"]["operation_result"]
    assert "reorder" in op_result
    assert op_result["reorder"][0]["shape_ids_preserved"] is True


def test_public_validate_reopens_valid_pptx(project_root: Path, public_created: Path) -> None:
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
            "operation": "pptx.nonexistent",
            "input": str(tmp_path / "input.pptx"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"


def test_public_create_is_deterministic(project_root: Path, tmp_path: Path) -> None:
    import hashlib
    output1 = tmp_path / "d1.pptx"
    output2 = tmp_path / "d2.pptx"
    for out in [output1, output2]:
        req = _request(tmp_path, f"create_{out.stem}.json", {
            "schema_version": "1.0",
            "operation": "pptx.create",
            "output": str(out),
            "arguments": {"deck": _deck()},
        })
        _public(project_root, "run", "--request", str(req))
    assert hashlib.sha256(output1.read_bytes()).hexdigest() == hashlib.sha256(output2.read_bytes()).hexdigest()
