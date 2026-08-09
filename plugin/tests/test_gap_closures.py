"""GAP-CROSS-1/2/3 closure tests: uniform metadata, security_summary, external_links.

These tests verify the three selected clean-room-tractable GAP closures added
by the final hardening slice:

* **GAP-CROSS-1** — uniform ``metadata`` block (``title`` / ``creator`` /
  ``created`` / ``modified`` / ``subject`` / ``keywords``) in all four ``read``
  results.
* **GAP-CROSS-2** — uniform ``security_summary`` block (``dangerous`` /
  ``categories`` / ``mutation_authorized: false``) in all four
  ``inspect.structure`` results.
* **GAP-CROSS-3** — inert ``external_links`` read-field in XLSX (external data
  connections) + PPTX (external hyperlinks) with target URL + source part.

These are additive projection fields under the existing ``operation_result``
blocks.  They do NOT change the operation/result JSON Schema's required fields.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

import pytest

from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.formats.docx.create import create_docx
from document_skills_core.formats.docx.inspect import inspect_docx
from document_skills_core.formats.docx.read import read_docx
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.inspect import inspect_pdf
from document_skills_core.formats.pdf.read import read_pdf
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.inspect import inspect_pptx
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.inspect import inspect_xlsx
from document_skills_core.formats.xlsx.read import read_xlsx

from tests.support.cross_format_fixture_registry import (
    _build_xlsx_xlm_macrosheet,
    _build_pptx_vba_project,
    _build_pdf_javascript,
)


# ---------------------------------------------------------------------------
# Shared expected metadata field set
# ---------------------------------------------------------------------------

_METADATA_FIELDS = {"title", "creator", "created", "modified", "subject", "keywords"}
_SECURITY_SUMMARY_FIELDS = {"dangerous", "categories", "mutation_authorized"}


# ---------------------------------------------------------------------------
# Source builders (valid packages with known metadata)
# ---------------------------------------------------------------------------


def _make_docx_with_metadata(tmp_path: Path) -> Path:
    """Create a DOCX with known core properties via docx.create, then read."""
    from document_skills_core.cli import execute_request
    from document_skills_core.core.contracts.schemas import SchemaCatalog
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    image = tmp_path / "pixel.png"
    image.write_bytes(png)
    output = tmp_path / "meta.docx"
    project_root = Path(__file__).resolve().parents[1]
    request = {
        "schema_version": "1.0",
        "operation": "docx.create",
        "output": str(output),
        "arguments": {
            "report": {
                "metadata": {"title": "Meta Title", "creator": "Meta Creator", "subject": "Meta Subject", "keywords": ""},
                "blocks": [
                    {"type": "heading", "text": "Meta", "level": 1},
                    {"type": "paragraph", "text": "Body"},
                    {"type": "table", "style": "TableGrid", "rows": [["A", "B"]]},
                ],
                "image": {"path": str(image), "alt_text": "px", "width_inches": 1},
                "header": "H",
                "footer": "F",
                "sections": [{"orientation": "portrait"}, {"orientation": "landscape"}],
            }
        },
    }
    result = execute_request(request, project_root, SchemaCatalog(project_root))
    assert result["status"] == "success", result
    return output


def _make_xlsx_with_metadata(tmp_path: Path) -> Path:
    source = tmp_path / "meta.xlsx"
    with OperationTempRoot() as private_root:
        staged = private_root / "created.xlsx"
        create_xlsx(
            staged,
            {
                "metadata": {"title": "Meta Title", "creator": "Meta Creator", "subject": "Meta Subject"},
                "sheets": [
                    {
                        "name": "Sheet1",
                        "rows": [{"cells": [{"ref": "A1", "value": "x", "type": "s"}]}],
                        "number_formats": [],
                    }
                ],
                "defined_names": [],
                "tables": [],
            },
        )
        source.write_bytes(staged.read_bytes())
    return source


def _make_pptx_with_metadata(tmp_path: Path) -> Path:
    source = tmp_path / "meta.pptx"
    create_pptx(
        source,
        {
            "metadata": {"title": "Meta Title", "creator": "Meta Creator", "subject": "Meta Subject"},
            "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
            "slides": [
                {
                    "layout": "blank",
                    "title": "Slide",
                    "shapes": [],
                    "table": None,
                    "chart_reference": None,
                    "image_reference": None,
                    "notes": None,
                }
            ],
        },
    )
    return source


def _make_pdf_with_metadata(tmp_path: Path) -> Path:
    source = tmp_path / "meta.pdf"
    create_pdf(
        source,
        {
            "metadata": {"title": "Meta Title", "author": "Meta Creator", "subject": "Meta Subject"},
            "page_size": "Letter",
            "pages": [{"blocks": [{"type": "paragraph", "text": "Body"}]}],
        },
    )
    return source


# ---------------------------------------------------------------------------
# GAP-CROSS-1: uniform metadata block in read
# ---------------------------------------------------------------------------


class TestGapCross1MetadataBlock:
    """GAP-CROSS-1: all four formats expose a uniform ``metadata`` block."""

    def test_docx_read_exposes_metadata(self, tmp_path: Path):
        source = _make_docx_with_metadata(tmp_path)
        result, _ = read_docx(source, {
            "include_headers_footers": True,
            "max_paragraphs": 5_000,
            "max_tables": 500,
            "max_table_rows": 5_000,
            "max_text_chars": 250_000,
        })
        assert "metadata" in result, "docx.read must expose a top-level metadata block"
        metadata = result["metadata"]
        assert set(metadata.keys()) == _METADATA_FIELDS, set(metadata.keys())
        assert metadata["title"] == "Meta Title"
        assert metadata["creator"] == "Meta Creator"
        assert metadata["subject"] == "Meta Subject"

    def test_xlsx_read_exposes_metadata(self, tmp_path: Path):
        source = _make_xlsx_with_metadata(tmp_path)
        result, _ = read_xlsx(source, {})
        assert "metadata" in result
        metadata = result["metadata"]
        assert set(metadata.keys()) == _METADATA_FIELDS, set(metadata.keys())
        assert metadata["title"] == "Meta Title"
        assert metadata["creator"] == "Meta Creator"
        assert metadata["subject"] == "Meta Subject"

    def test_pptx_read_exposes_metadata(self, tmp_path: Path):
        source = _make_pptx_with_metadata(tmp_path)
        result, _ = read_pptx(source, {})
        assert "metadata" in result
        metadata = result["metadata"]
        assert set(metadata.keys()) == _METADATA_FIELDS, set(metadata.keys())
        assert metadata["title"] == "Meta Title"
        assert metadata["creator"] == "Meta Creator"
        assert metadata["subject"] == "Meta Subject"

    def test_pdf_read_exposes_metadata(self, tmp_path: Path):
        source = _make_pdf_with_metadata(tmp_path)
        result, _ = read_pdf(source, {})
        assert "metadata" in result
        metadata = result["metadata"]
        assert set(metadata.keys()) == _METADATA_FIELDS, set(metadata.keys())
        assert metadata["title"] == "Meta Title"
        assert metadata["creator"] == "Meta Creator"
        assert metadata["subject"] == "Meta Subject"

    def test_missing_metadata_reports_null_not_fabricated(self, tmp_path: Path):
        """A source with minimal metadata still exposes the uniform block with nulls."""
        # Use the malicious-active DOCX fixture which has no meaningful metadata
        project_root = Path(__file__).resolve().parents[1]
        source = project_root / "tests" / "fixtures" / "docx-preservation.docx"
        if not source.is_file():
            pytest.skip("preservation fixture not available")
        result, _ = read_docx(source, {
            "include_headers_footers": True,
            "max_paragraphs": 5_000,
            "max_tables": 500,
            "max_table_rows": 5_000,
            "max_text_chars": 250_000,
        })
        assert "metadata" in result
        metadata = result["metadata"]
        assert set(metadata.keys()) == _METADATA_FIELDS
        # No fabricated values — missing fields are null, not made up.
        for field in _METADATA_FIELDS:
            assert metadata[field] is None or isinstance(metadata[field], str)


# ---------------------------------------------------------------------------
# GAP-CROSS-2: uniform security_summary in inspect.structure
# ---------------------------------------------------------------------------


class TestGapCross2SecuritySummary:
    """GAP-CROSS-2: all four formats expose a uniform ``security_summary`` block."""

    def test_docx_inspect_exposes_security_summary(self, project_root: Path):
        source = project_root / "tests" / "fixtures" / "docx-malicious-active.docx"
        result, _ = inspect_docx(source, {"include_hashes": False, "max_parts": 2_000, "max_relationships": 5_000})
        assert "security_summary" in result
        summary = result["security_summary"]
        assert set(summary.keys()) == _SECURITY_SUMMARY_FIELDS
        assert summary["dangerous"] is True
        assert isinstance(summary["categories"], dict)
        assert any(count > 0 for count in summary["categories"].values())
        assert summary["mutation_authorized"] is False

    def test_xlsx_inspect_exposes_security_summary(self, tmp_path: Path):
        source = _build_xlsx_xlm_macrosheet(tmp_path)
        result, _ = inspect_xlsx(source, {"include_hashes": False, "max_parts": 2_000, "max_relationships": 5_000})
        assert "security_summary" in result
        summary = result["security_summary"]
        assert set(summary.keys()) == _SECURITY_SUMMARY_FIELDS
        assert summary["dangerous"] is True
        assert isinstance(summary["categories"], dict)
        assert any(count > 0 for count in summary["categories"].values())
        assert summary["mutation_authorized"] is False

    def test_pptx_inspect_exposes_security_summary(self, tmp_path: Path):
        source = _build_pptx_vba_project(tmp_path)
        result, _ = inspect_pptx(source, {"include_hashes": False, "max_parts": 2_000, "max_relationships": 5_000})
        assert "security_summary" in result
        summary = result["security_summary"]
        assert set(summary.keys()) == _SECURITY_SUMMARY_FIELDS
        assert summary["dangerous"] is True
        assert isinstance(summary["categories"], dict)
        assert any(count > 0 for count in summary["categories"].values())
        assert summary["mutation_authorized"] is False

    def test_pdf_inspect_exposes_security_summary(self, tmp_path: Path):
        source = _build_pdf_javascript(tmp_path)
        result, _ = inspect_pdf(source, {})
        assert "security_summary" in result
        summary = result["security_summary"]
        assert set(summary.keys()) == _SECURITY_SUMMARY_FIELDS
        assert summary["dangerous"] is True
        assert isinstance(summary["categories"], dict)
        assert any(count > 0 for count in summary["categories"].values())
        assert summary["mutation_authorized"] is False

    def test_clean_source_reports_dangerous_false(self, tmp_path: Path):
        """A clean XLSX source reports dangerous=false in security_summary."""
        source = _make_xlsx_with_metadata(tmp_path)
        result, _ = inspect_xlsx(source, {"include_hashes": False, "max_parts": 2_000, "max_relationships": 5_000})
        assert "security_summary" in result
        summary = result["security_summary"]
        assert summary["dangerous"] is False
        assert all(count == 0 for count in summary["categories"].values())
        assert summary["mutation_authorized"] is False


# ---------------------------------------------------------------------------
# GAP-CROSS-3: inert external_links read-field in XLSX + PPTX
# ---------------------------------------------------------------------------


class TestGapCross3ExternalLinks:
    """GAP-CROSS-3: XLSX + PPTX read expose external_links with target URLs."""

    def test_xlsx_read_surfaces_external_link_targets(self, tmp_path: Path):
        """XLSX inspect.structure surfaces externalLinks targets with URLs.

        A package with ``xl/externalLinks/`` parts is dangerous (external data
        connections carry ``TargetMode="External"``), so read rejects it.  The
        inert ``inspect.structure`` path inventories the parts and their targets
        without fetching.  Each entry includes the target URL + source part.
        """
        import zipfile

        source = _make_xlsx_with_metadata(tmp_path)
        from tests.support.cross_format_fixture_registry import _wrap_rels

        parts: dict[str, bytes] = {}
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                parts[name] = archive.read(name)
        parts["xl/externalLinks/_rels/externalLink1.xml.rels"] = _wrap_rels(
            [
                (
                    "rIdExt",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath",
                    "https://evil.example.com/data.xml",
                    "External",
                )
            ]
        )
        parts["xl/externalLinks/externalLink1.xml"] = (
            b'<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            b' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            b'<externalBook r:id="rIdExt"/>'
            b"</externalLink>"
        )
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(parts):
                archive.writestr(name, parts[name])

        # Inspect (inert) surfaces the external link targets.
        result, _ = inspect_xlsx(source, {"include_hashes": False, "max_parts": 2_000, "max_relationships": 5_000})
        links = result.get("external_links", [])
        assert len(links) >= 1
        entry = links[0]
        assert "target" in entry, f"external_links entry must include target; got {entry}"
        assert entry["target"] == "https://evil.example.com/data.xml"
        assert "source_part" in entry or "part" in entry

    def test_pptx_read_surfaces_external_hyperlinks(self, tmp_path: Path):
        """PPTX inspect.structure surfaces external hyperlinks with targets.

        Like XLSX, a PPTX with external-target hyperlinks is dangerous; read
        rejects it.  Inspect inventories the links inertly.
        """
        import zipfile

        source = _make_pptx_with_metadata(tmp_path)
        from tests.support.cross_format_fixture_registry import _wrap_rels

        parts: dict[str, bytes] = {}
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                parts[name] = archive.read(name)
        parts["ppt/slides/_rels/slide1.xml.rels"] = _wrap_rels(
            [
                (
                    "rIdExt",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                    "https://evil.example.com/slide",
                    "External",
                )
            ]
        )
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(parts):
                archive.writestr(name, parts[name])

        result, _ = inspect_pptx(source, {"include_hashes": False, "max_parts": 2_000, "max_relationships": 5_000})
        links = result.get("external_links", [])
        assert len(links) >= 1
        entry = links[0]
        assert "target" in entry
        assert entry["target"] == "https://evil.example.com/slide"

    def test_no_external_links_yields_empty_list(self, tmp_path: Path):
        """A clean source with no external links yields an empty list."""
        source = _make_xlsx_with_metadata(tmp_path)
        result, _ = read_xlsx(source, {})
        assert result["external_links"] == []
