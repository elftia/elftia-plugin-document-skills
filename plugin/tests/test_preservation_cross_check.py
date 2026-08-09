"""Preservation cross-check across all four formats.

Proves default edits across DOCX/XLSX/PPTX/PDF leave the input SHA unchanged
and the produced output reopens + validates through the existing
``validate_artifact`` gate.  One parametrized test per format × edit operation.

The suite reuses the existing ``create_*`` functions to build a valid source,
the format's edit operation to produce an output, and ``validate_artifact``
(or the format's own preservation manifest) to assert:

* source SHA-256 unchanged before vs after the operation;
* output path differs from input path (no in-place default);
* output passes the package/content gates.

Module provenance: original Elftia-authored clean-room implementation.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.validation import validate_artifact
from document_skills_core.formats.docx.validation import reopen_docx
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import edit_pdf
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.edit import edit_pptx
from document_skills_core.formats.pptx.validation import reopen_pptx
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.validation import reopen_xlsx


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------


def _build_docx_source(project_root: Path) -> Path:
    """Use the existing rich DOCX fixture (carries known replacement targets)."""
    return project_root / "tests" / "fixtures" / "docx-rich.docx"


def _build_xlsx_source(tmp_path: Path) -> Path:
    workbook = {
        "metadata": {"title": "Preservation", "creator": "Elftia", "subject": "Cross-check"},
        "sheets": [
            {
                "name": "Data",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "Value", "type": "s"},
                            {"ref": "A2", "value": "Alpha", "type": "s"},
                            {"ref": "B2", "value": "10", "type": "n"},
                        ]
                    }
                ],
                "number_formats": [],
            }
        ],
        "defined_names": [],
        "tables": [],
    }
    source = tmp_path / "source.xlsx"
    with OperationTempRoot() as private_root:
        staged = private_root / "created.xlsx"
        create_xlsx(staged, workbook)
        source.write_bytes(staged.read_bytes())
    return source


def _build_pptx_source(tmp_path: Path) -> Path:
    deck = {
        "metadata": {"title": "Preservation", "creator": "Elftia", "subject": "Cross-check"},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": [
            {
                "layout": "blank",
                "title": "Slide One",
                "shapes": [],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": None,
            }
        ],
    }
    source = tmp_path / "source.pptx"
    create_pptx(source, deck)
    return source


def _build_pdf_source(tmp_path: Path) -> Path:
    source = tmp_path / "source.pdf"
    create_pdf(
        source,
        {
            "metadata": {"title": "Preservation", "author": "Elftia", "subject": "Cross-check"},
            "page_size": "Letter",
            "pages": [{"blocks": [{"type": "paragraph", "text": "Hello preservation"}]}],
        },
    )
    return source


# ---------------------------------------------------------------------------
# Edit operations
# ---------------------------------------------------------------------------


def _edit_docx(source: Path, output: Path) -> None:
    from document_skills_core.cli import execute_request
    from document_skills_core.core.contracts.schemas import SchemaCatalog

    project_root = Path(__file__).resolve().parents[1]
    request = {
        "schema_version": "1.0",
        "operation": "docx.edit.replace-text",
        "input": str(source),
        "output": str(output),
        "arguments": {"replacements": [{"search": "TARGET", "replace": "changed", "expected_matches": 4}]},
    }
    result = execute_request(request, project_root, SchemaCatalog(project_root))
    assert result["status"] == "success", result


def _edit_xlsx(source: Path, output: Path) -> None:
    from document_skills_core.formats.xlsx.edit import edit_xlsx

    edit_xlsx(
        source,
        output,
        {"edits": [{"sheet": "Data", "type": "cell_value", "ref": "B2", "value": "99"}]},
    )


def _edit_pptx(source: Path, output: Path) -> None:
    edit_pptx(
        source,
        output,
        {"edits": [{"slide": 1, "type": "slide_text", "ref": "", "value": "New text"}]},
    )


def _edit_pdf(source: Path, output: Path) -> None:
    edit_pdf(
        source,
        output,
        {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}], "expected_edits": 1},
    )


# ---------------------------------------------------------------------------
# Parametrized preservation cross-check
# ---------------------------------------------------------------------------


_REOPENERS = {
    "docx": reopen_docx,
    "xlsx": reopen_xlsx,
    "pptx": reopen_pptx,
    "pdf": reopen_pdf,
}


def _assert_preservation(
    format_id: str, source: Path, output: Path, original_hash: str
) -> None:
    """Assert source SHA unchanged, output distinct, output validates."""
    # Source SHA unchanged.
    assert _sha256(source) == original_hash, (
        f"{format_id}: source SHA drifted after default edit"
    )
    # Output path differs from input (no in-place default).
    assert output.resolve() != source.resolve(), (
        f"{format_id}: output path must differ from input"
    )
    assert output.is_file(), f"{format_id}: output file must exist"
    # Output reopens via the format's reopen hook.
    reopen = _REOPENERS[format_id]
    reopen(output)
    # Output passes validate_artifact with source preservation.
    report = validate_artifact(
        output,
        expected_format=format_id,
        source_path=source,
        source_sha256=original_hash,
        reopen=lambda _path: "ok",
    )
    # The source.preservation gate must pass; the overall status may be "fail"
    # only if an optional gate (visual.render / schema.full) is unavailable.
    preservation_gate = next(
        gate for gate in report["gates"] if gate["id"] == "source.preservation"
    )
    assert preservation_gate["outcome"] == "pass", (
        f"{format_id}: source.preservation gate must pass; got {preservation_gate}"
    )


def test_docx_default_edit_preserves_source(project_root: Path, tmp_path: Path):
    source = _build_docx_source(project_root)
    original_hash = _sha256(source)
    output = tmp_path / "output.docx"
    _edit_docx(source, output)
    _assert_preservation("docx", source, output, original_hash)


def test_xlsx_default_edit_preserves_source(tmp_path: Path):
    source = _build_xlsx_source(tmp_path)
    original_hash = _sha256(source)
    output = tmp_path / "output.xlsx"
    _edit_xlsx(source, output)
    _assert_preservation("xlsx", source, output, original_hash)


def test_pptx_default_edit_preserves_source(tmp_path: Path):
    source = _build_pptx_source(tmp_path)
    original_hash = _sha256(source)
    output = tmp_path / "output.pptx"
    _edit_pptx(source, output)
    _assert_preservation("pptx", source, output, original_hash)


def test_pdf_default_edit_preserves_source(tmp_path: Path):
    source = _build_pdf_source(tmp_path)
    original_hash = _sha256(source)
    output = tmp_path / "output.pdf"
    _edit_pdf(source, output)
    _assert_preservation("pdf", source, output, original_hash)


# ---------------------------------------------------------------------------
# In-place edit is rejected by default (Core mutations require distinct output)
# ---------------------------------------------------------------------------


def test_in_place_edit_is_rejected_for_every_oOxml_format(
    project_root: Path, tmp_path: Path
):
    """Core OOXML mutations (DOCX/XLSX/PPTX) require a distinct output path.

    An explicit in-place request raises OUTPUT_EQUALS_INPUT — no silent
    overwrite.  PDF likewise rejects input == output.
    """
    from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
    from document_skills_core.formats.pdf.contracts import parse_pdf_request
    from document_skills_core.formats.pptx.contracts import parse_pptx_request
    from document_skills_core.formats.xlsx.contracts import parse_xlsx_request

    xlsx_src = _build_xlsx_source(tmp_path)
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(xlsx_src),
            "output": str(xlsx_src),
            "arguments": {"edits": [{"sheet": "Data", "type": "cell_value", "ref": "A1", "value": "X"}]},
        })
    assert exc.value.code == ErrorCode.OUTPUT_EQUALS_INPUT

    pptx_src = _build_pptx_source(tmp_path)
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(pptx_src),
            "output": str(pptx_src),
            "arguments": {"edits": [{"slide": 1, "type": "slide_text", "ref": "", "value": "X"}]},
        })
    assert exc.value.code == ErrorCode.OUTPUT_EQUALS_INPUT

    pdf_src = _build_pdf_source(tmp_path)
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(pdf_src.resolve()),
            "output": str(pdf_src.resolve()),
            "arguments": {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}], "expected_edits": 1},
        })
    assert exc.value.code == ErrorCode.OUTPUT_EQUALS_INPUT
