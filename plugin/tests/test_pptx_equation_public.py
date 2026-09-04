"""Real frozen-uv public truth for B6 editable Office Math."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
from typing import Any

import pytest


def _public(
    project_root: Path,
    *arguments: str,
    cwd: Path | None = None,
) -> tuple[int, dict[str, Any]]:
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


def _request(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _fixtures(project_root: Path) -> Path:
    return project_root / "tests/fixtures/pptx/ecosystem_bc/equations"


def _equation(case: dict[str, Any], index: int) -> dict[str, Any]:
    column = index % 2
    row = index // 2
    return {
        "type": "equation",
        "id": f"eq-{case['id']}",
        "bbox": {
            "x": 0.5 + column * 4.7,
            "y": 0.7 + row * 1.1,
            "w": 4.3,
            "h": 0.8,
        },
        "source": case["source"],
        "fallback": "reject",
    }


def _create_value(
    output: Path,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(output),
        "arguments": {
            "deck": {
                "metadata": {
                    "title": "B6 editable equations",
                    "creator": "Elftia",
                    "subject": "B6",
                },
                "slide_size": {
                    "cx": "12192000",
                    "cy": "6858000",
                    "type": "screen16x9",
                },
                "slides": [
                    {
                        "layout": "content",
                        "title": "Native Office Math",
                        "shapes": [
                            _equation(case, index)
                            for index, case in enumerate(cases)
                        ],
                        "table": None,
                        "chart_reference": None,
                        "image_reference": None,
                        "notes": None,
                    }
                ],
            }
        },
    }


def _read(
    project_root: Path,
    tmp_path: Path,
    source: Path,
) -> dict[str, Any]:
    request = _request(
        tmp_path / f"read-{source.stem}.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.read",
            "input": str(source),
            "arguments": {},
        },
    )
    returncode, result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        cwd=tmp_path,
    )
    assert returncode == 0, result
    assert result["status"] == "success"
    return result["diagnostics"]["operation_result"]


def test_public_create_read_and_edit_round_trip_supported_equations(
    project_root: Path,
    tmp_path: Path,
) -> None:
    supported = json.loads(
        (_fixtures(project_root) / "supported.json").read_text(encoding="utf-8")
    )
    cases = supported["cases"]
    output = tmp_path / "equations.pptx"
    create_request = _request(
        tmp_path / "create.json",
        _create_value(output, cases),
    )

    returncode, created = _public(
        project_root,
        "run",
        "--request",
        str(create_request),
        cwd=tmp_path,
    )

    assert returncode == 0, created
    assert created["status"] in {"degraded", "success"}
    assert created["validation"]["status"] == "pass"
    equations = created["diagnostics"]["operation_result"]["creation"][
        "equations"
    ]
    assert len(equations) == len(cases)
    assert all(item["editable"] is True for item in equations)
    assert all(item["fallback"] == "native" for item in equations)
    assert all(
        item["consumer_compatibility"] == {
            "libreoffice": {"status": "not_run"},
            "powerpoint": {"status": "not_run"},
        }
        for item in equations
    )

    first_read = _read(project_root, tmp_path, output)
    projected = [
        shape
        for shape in first_read["slides"][0]["shapes"]
        if shape["type"] == "equation"
    ]
    assert len(projected) == len(cases)
    assert all(shape["equation"]["readback"] == {"status": "pass"} for shape in projected)

    edited_output = tmp_path / "equations-edited.pptx"
    edit_request = _request(
        tmp_path / "edit.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(output),
            "output": str(edited_output),
            "arguments": {
                "edits": [
                    {
                        "type": "equation_upsert",
                        "slide": 1,
                        "selector": projected[0]["selector"],
                        "precondition_sha256": projected[0][
                            "precondition_sha256"
                        ],
                        "equation": {
                            "type": "equation",
                            "id": projected[0]["name"],
                            "bbox": {"x": 0.5, "y": 0.7, "w": 4.3, "h": 0.8},
                            "source": {
                                "kind": "latex",
                                "value": r"E=\frac{mc^2}{2}",
                            },
                            "fallback": "reject",
                        },
                    },
                    {
                        "type": "equation_upsert",
                        "slide": 1,
                        "equation": {
                            "type": "equation",
                            "id": "eq-added",
                            "bbox": {"x": 5.2, "y": 5.1, "w": 4.3, "h": 0.8},
                            "source": {"kind": "latex", "value": r"\sqrt{x}"},
                            "fallback": "reject",
                        },
                    },
                ]
            },
        },
    )
    source_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    returncode, edited = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        cwd=tmp_path,
    )

    assert returncode == 0, edited
    assert edited["validation"]["status"] == "pass"
    assert hashlib.sha256(output.read_bytes()).hexdigest() == source_hash
    second_read = _read(project_root, tmp_path, edited_output)
    final_equations = [
        shape["equation"]
        for shape in second_read["slides"][0]["shapes"]
        if shape["type"] == "equation"
    ]
    assert final_equations[0]["canonical_latex"] == r"E=\frac{mc^{2}}{2}"
    assert final_equations[-1]["canonical_latex"] == r"\sqrt{x}"


@pytest.mark.parametrize("case_index", range(6))
def test_public_unsupported_equations_fail_without_output(
    project_root: Path,
    tmp_path: Path,
    case_index: int,
) -> None:
    unsupported = json.loads(
        (_fixtures(project_root) / "unsupported.json").read_text(encoding="utf-8")
    )
    case = unsupported["cases"][case_index]
    output = tmp_path / f"unsupported-{case_index}.pptx"
    request = _request(
        tmp_path / f"unsupported-{case_index}.json",
        _create_value(output, [case]),
    )

    returncode, result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        cwd=tmp_path,
    )

    assert returncode == 2
    assert result["status"] in {"failed", "invalid_request"}
    assert result["errors"][0]["code"] == case["expectedCode"]
    assert not output.exists()
