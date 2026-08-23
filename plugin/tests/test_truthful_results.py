"""Public frozen-uv false-success requests must fail closed."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.xlsx.create import create_xlsx


_SENTINEL = b"existing-destination-must-survive"


def test_unsupported_docx_formatting_has_typed_gate_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    _assert_fail_closed(
        project_root,
        tmp_path,
        "docx",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(tmp_path / "formatted.docx"),
            "arguments": {
                "report": {
                    "blocks": [
                        {
                            "type": "paragraph",
                            "text": "Formal text",
                            "font": "SimSun",
                            "alignment": "center",
                            "line_spacing": 1.5,
                        }
                    ]
                }
            },
        },
        {"invalid_request", "enhancement_required"},
    )


@pytest.mark.parametrize(
    "feature",
    ["chart", "page-setup"],
)
def test_disconnected_xlsx_create_feature_fails_closed(
    project_root: Path,
    tmp_path: Path,
    feature: str,
) -> None:
    workbook = copy.deepcopy(_workbook())
    if feature == "row-style":
        workbook["sheets"][0]["rows"][0]["style"] = {"bold": True}
    elif feature == "cell-style":
        workbook["sheets"][0]["rows"][0]["cells"][0]["style"] = {"bold": True}
    elif feature == "number-format":
        workbook["sheets"][0]["number_formats"] = [{"id": 165, "code": "0.00"}]
    elif feature == "table":
        workbook["tables"] = [
            {
                "name": "Table1",
                "ref": "A1:B1",
                "sheet": "Sheet1",
                "style": "TableStyleMedium2",
            }
        ]
    elif feature == "chart":
        workbook["chart_reference"] = {
            "title": "Chart",
            "data_ref": "Sheet1!$A$1:$B$1",
            "sheet": "Sheet1",
        }
    else:
        workbook["page_setup"] = {
            "orientation": "landscape",
            "header": "Header",
            "footer": "Footer",
        }
    _assert_fail_closed(
        project_root,
        tmp_path,
        "xlsx",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(tmp_path / f"{feature}.xlsx"),
            "arguments": {"workbook": workbook},
        },
        {"enhancement_required", "invalid_request"},
    )


def test_xlsx_unsafe_structural_delete_is_enhancement_required_and_preserves_source(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.xlsx"
    workbook = _workbook()
    workbook["sheets"][0]["rows"][0]["cells"].append(
        {"ref": "C1", "formula": "B1", "type": "n"}
    )
    create_xlsx(source, workbook)
    _assert_fail_closed(
        project_root,
        tmp_path,
        "xlsx",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(tmp_path / "structural.xlsx"),
            "arguments": {
                "edits": [
                    {
                        "sheet": "Sheet1",
                        "type": "column_delete",
                        "ref": "B",
                        "count": 1,
                    }
                ]
            },
        },
        {"enhancement_required"},
        source=source,
    )


def test_current_bounded_xlsx_candidate_passes_required_package_gate(
    project_root: Path,
    tmp_path: Path,
) -> None:
    _assert_succeeds_with_promotion(
        project_root,
        tmp_path,
        "xlsx",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(tmp_path / "bounded.xlsx"),
            "arguments": {"workbook": _workbook()},
        },
    )


def test_current_typed_pptx_candidate_passes_required_package_gate(
    project_root: Path,
    tmp_path: Path,
) -> None:
    _assert_succeeds_with_promotion(
        project_root,
        tmp_path,
        "pptx",
        {
            "schema_version": "1.0",
            "operation": "pptx.create",
            "output": str(tmp_path / "bounded.pptx"),
            "arguments": {"deck": _deck()},
        },
    )


@pytest.mark.parametrize("case", ["image", "cjk", "style"])
def test_unsupported_or_lossy_pdf_create_fails_closed(
    project_root: Path,
    tmp_path: Path,
    case: str,
) -> None:
    document = _pdf_document()
    first = document["pages"][0]["blocks"][0]
    if case == "image":
        document["pages"][1]["blocks"].append(
            {
                "type": "image",
                "text": None,
                "style": None,
                "table": None,
                "image": {"filename": "requested.png", "content_type": "image/png"},
                "shape": None,
            }
        )
    elif case == "cjk":
        first["text"] = "中文标题"
    else:
        first["style"] = {"font": "Helvetica-Bold", "color": [1, 0, 0]}
    _assert_fail_closed(
        project_root,
        tmp_path,
        "pdf",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(tmp_path / f"{case}.pdf"),
            "arguments": {"document": document},
        },
        {"enhancement_required", "invalid_request"},
    )


def test_lossy_pdf_rewrite_is_not_degraded_or_promoted(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    create_pdf(source, _pdf_document())
    _assert_fail_closed(
        project_root,
        tmp_path,
        "pdf",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(tmp_path / "rewritten.pdf"),
            "arguments": {
                "blocks": [
                    {
                        "page": 1,
                        "bbox": [72, 754, 300, 770],
                        "text": "Title",
                        "font": "F2",
                        "size": 16.0,
                        "color": None,
                    }
                ],
                "rewrites": [{"block_index": 0, "text": "日本語テスト"}],
            },
        },
        {"enhancement_required"},
        source=source,
    )


def _assert_fail_closed(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
    request: dict[str, Any],
    statuses: set[str],
    *,
    source: Path | None = None,
) -> None:
    destination = Path(request["output"])
    destination.write_bytes(_SENTINEL)
    destination_before = _sha256(destination)
    source_before = _sha256(source) if source is not None else None
    request_path = tmp_path / f"request-{format_id}-{destination.stem}.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, format_id, request_path)

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] in statuses
    assert result["status"] not in {"success", "degraded"}
    assert not any(item["role"] == "output" for item in result["artifacts"])
    assert result["validation"]["status"] in {"fail", "unavailable", "not_run"}
    assert any(
        gate["required"] and gate["outcome"] != "pass"
        for gate in result["validation"]["gates"]
    )
    assert _sha256(destination) == destination_before
    if source is not None:
        assert _sha256(source) == source_before


def _assert_succeeds_with_promotion(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
    request: dict[str, Any],
) -> None:
    destination = Path(request["output"])
    destination.write_bytes(_SENTINEL)
    request_path = tmp_path / f"request-{format_id}-{destination.stem}.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, format_id, request_path)

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] in {"success", "degraded"}
    assert any(item["role"] == "output" for item in result["artifacts"])
    assert destination.read_bytes() != _SENTINEL


def _public(
    project_root: Path,
    format_id: str,
    request_path: Path,
) -> dict[str, Any]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / f"skills/document-{format_id}/scripts/run.py"),
            "run",
            "--request",
            str(request_path),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def _workbook() -> dict[str, Any]:
    return {
        "metadata": {"title": "Bounded XLSX", "creator": "Test", "subject": ""},
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


def _deck() -> dict[str, Any]:
    return {
        "metadata": {"title": "Bounded PPTX", "creator": "Test", "subject": ""},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": [
            {
                "layout": "title",
                "title": "Title",
                "shapes": [{"text": "Body", "runs": [{"text": "Body", "style": None}]}],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": None,
            },
            {
                "layout": "content",
                "title": "Content",
                "shapes": [{"text": "Text", "runs": [{"text": "Text", "style": None}]}],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": None,
            },
        ],
    }


def _pdf_document() -> dict[str, Any]:
    return {
        "metadata": {"title": "Bounded PDF", "author": "Test", "subject": ""},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {
                        "type": "heading",
                        "text": "Title",
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
                        "text": "Content",
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


def _sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()
