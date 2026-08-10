"""Public committed-output truth across all four format service seams."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any

from openpyxl import Workbook
import pytest
from pptx import Presentation

from document_skills_core.cli import execute_request
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.pdf.create import create_pdf


_EDIT_FORMATS = ("docx", "xlsx", "pptx", "pdf")


def test_public_supported_docx_create_with_existing_output_returns_committed_result(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing.docx"
    output.write_bytes(b"prior-output")
    request = _create_request("docx", output)

    result = _execute(project_root, request)

    _assert_committed_existing_result(result, output)


@pytest.mark.parametrize("format_id", _EDIT_FORMATS)
def test_public_edit_with_existing_output_returns_committed_result(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
) -> None:
    source, request = _edit_request(project_root, tmp_path, format_id)
    output = Path(str(request["output"]))
    output.write_bytes(b"prior-output")
    source_before = source.read_bytes()

    result = _execute(project_root, request)

    _assert_committed_existing_result(result, output, expected_artifacts=2)
    assert source.read_bytes() == source_before


@pytest.mark.parametrize("format_id", _EDIT_FORMATS)
def test_public_edit_source_race_merges_with_committed_output(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_id: str,
) -> None:
    source, request = _edit_request(project_root, tmp_path, format_id)
    output = Path(str(request["output"]))
    output.write_bytes(b"prior-output")
    transaction = importlib.import_module(
        f"document_skills_core.formats.{format_id}.transaction"
    )
    real_assert = transaction.assert_source_preserved
    checks = 0

    def change_source_after_commit(path: str | Path, expected: str) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            Path(path).write_bytes(b"concurrent-source-writer")
        real_assert(path, expected)

    monkeypatch.setattr(
        transaction,
        "assert_source_preserved",
        change_source_after_commit,
    )
    result = _execute(project_root, request)

    _assert_committed_existing_result(result, output, expected_artifacts=2)
    assert checks == 2
    assert source.read_bytes() == b"concurrent-source-writer"
    assert {warning["code"] for warning in result["warnings"]} == {
        "DS_PROMOTION_RESIDUE_PRESERVED",
        "DS_SOURCE_CHANGED_AFTER_COMMIT",
    }
    promotion = result["diagnostics"]["promotion"]
    assert promotion["state"] == "committed_with_warnings"
    assert promotion["filesystem_state"] == "committed_with_residue"
    assert promotion["source_preservation"]["status"] == "fail"
    assert (
        promotion["source_preservation"]["error"]["code"]
        == "DS_VALIDATION_FAILED"
    )


def _execute(project_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    return execute_request(request, project_root, SchemaCatalog(project_root))


def _create_request(format_id: str, output: Path) -> dict[str, Any]:
    if format_id == "docx":
        arguments = {
            "report": {
                "blocks": [
                    {"type": "heading", "text": "Committed", "level": 1},
                    {"type": "paragraph", "text": "Bounded public output."},
                ]
            }
        }
    else:
        arguments = {"document": _pdf_document()}
    return {
        "schema_version": "1.0",
        "operation": f"{format_id}.create",
        "output": str(output),
        "arguments": arguments,
    }


def _edit_request(
    project_root: Path,
    root: Path,
    format_id: str,
) -> tuple[Path, dict[str, Any]]:
    source = root / f"source.{format_id}"
    output = root / f"existing-edit.{format_id}"
    if format_id == "docx":
        created = _execute(
            project_root,
            {
                "schema_version": "1.0",
                "operation": "docx.create",
                "output": str(source),
                "arguments": {
                    "report": {
                        "blocks": [
                            {"type": "paragraph", "text": "source marker"}
                        ]
                    }
                },
            },
        )
        assert created["status"] == "success", created
        arguments = {
            "replacements": [
                {
                    "search": "source marker",
                    "replace": "edited marker",
                    "expected_matches": 1,
                }
            ]
        }
        operation = "docx.edit.replace-text"
    elif format_id == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet["A1"] = "Name"
        sheet["B1"] = "Value"
        sheet["A2"] = "Alpha"
        sheet["B2"] = 10
        workbook.save(source)
        arguments = {
            "edits": [
                {
                    "sheet": "Data",
                    "type": "cell_value",
                    "ref": "B2",
                    "value": "99",
                }
            ]
        }
        operation = "xlsx.edit"
    elif format_id == "pptx":
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = "Source title"
        presentation.save(source)
        arguments = {
            "edits": [
                {
                    "slide": 1,
                    "type": "slide_text",
                    "ref": "",
                    "value": "Edited title",
                }
            ]
        }
        operation = "pptx.edit"
    else:
        create_pdf(source, _pdf_document())
        arguments = {
            "primitives": [
                {"type": "rotate", "pages": [1], "degrees": 90}
            ]
        }
        operation = "pdf.edit"
    return source, {
        "schema_version": "1.0",
        "operation": operation,
        "input": str(source),
        "output": str(output),
        "arguments": arguments,
    }


def _pdf_document() -> dict[str, Any]:
    return {
        "metadata": {"title": "Committed PDF", "author": "Elftia"},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Page one",
                        "style": None,
                        "table": None,
                        "image": None,
                        "shape": None,
                    }
                ],
                "metadata": None,
            },
            {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Page two",
                        "style": None,
                        "table": None,
                        "image": None,
                        "shape": None,
                    }
                ],
                "metadata": None,
            },
        ],
    }


def _assert_committed_existing_result(
    result: dict[str, Any],
    output: Path,
    *,
    expected_artifacts: int = 1,
) -> None:
    assert result["status"] in {"success", "degraded"}, result
    assert result["achieved_fidelity"] != "none"
    assert result["validation"]["status"] == "pass"
    assert result["errors"] == []
    assert len(result["artifacts"]) == expected_artifacts
    output_artifact = result["artifacts"][-1]
    assert output_artifact["path"] == str(output.resolve())
    assert output_artifact["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output_artifact["bytes"] == output.stat().st_size
    promotion = result["diagnostics"]["promotion"]
    assert promotion["promotion_committed"] is True
    assert promotion["filesystem_state"] == "committed_with_residue"
    assert promotion["destination_capture_preserved"] is True
    assert promotion["residue_observation_stable"] is True
    assert len(promotion["transaction_residues"]) == 1
    capture = promotion["transaction_residues"][0]
    assert capture["role"] == "destination_capture"
    assert capture["stable"] is True
    assert capture["identity_matches_expected"] is True
    assert Path(str(capture["path"])).read_bytes() == b"prior-output"
    assert "DS_PROMOTION_RESIDUE_PRESERVED" in {
        warning["code"] for warning in result["warnings"]
    }
