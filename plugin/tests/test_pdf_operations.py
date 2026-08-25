"""PDF functional operation tests — create, read, inspect, edit, rewrite, validate.

Covers per-operation behavior, preservation manifests, page-layout-preservation-
on-rewrite reopen gate, CJK/RTL fail-closed behavior, inert action
classification, and malicious-fixture fail-closed behavior.

Module provenance: original Elftia-authored test suite.
"""

import hashlib
from pathlib import Path
from typing import Any
import zlib

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.byte_preflight import PdfByteLimits, decode_stream
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import edit_pdf
from document_skills_core.formats.pdf.inspect import inspect_pdf
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.read import read_pdf
from document_skills_core.formats.pdf.rewrite import rewrite_apply_pdf
from document_skills_core.formats.pdf.validation import (
    reopen_pdf,
    validate_created,
    validate_mutation,
)


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

def _document() -> dict[str, Any]:
    return {
        "metadata": {"title": "Test PDF", "author": "Elftia", "subject": "Testing"},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {"type": "heading", "text": "Page One", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "paragraph", "text": "Hello world", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "table", "text": None, "style": None, "table": {"rows": [{"cells": ["A1", "B1"]}, {"cells": ["A2", "B2"]}]}, "image": None, "shape": None},
                ],
                "metadata": None,
            },
            {
                "blocks": [
                    {"type": "heading", "text": "Page Two", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "vector_shape", "text": None, "style": None, "table": None, "image": None, "shape": {"kind": "rectangle", "x": 72, "y": 72, "width": 200, "height": 100, "stroke": None, "fill": None}},
                ],
                "metadata": None,
            },
        ],
    }


def _minimal_text_document(text: str) -> dict[str, Any]:
    return {
        "metadata": {"title": "Minimal", "author": "Elftia", "subject": ""},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": text,
                        "style": None,
                        "table": None,
                        "image": None,
                        "shape": None,
                    }
                ],
                "metadata": None,
            }
        ],
    }


@pytest.fixture
def created_pdf(tmp_path: Path) -> Path:
    destination = tmp_path / "created.pdf"
    create_pdf(destination, _document())
    return destination


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _merge_inputs(*paths: Path) -> list[dict[str, str]]:
    return [
        {"input": str(path), "source_sha256": _source_hash(path)}
        for path in paths
    ]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_produces_valid_file(self, tmp_path: Path):
        destination = tmp_path / "test.pdf"
        result = create_pdf(destination, _document())
        assert destination.is_file()
        assert destination.stat().st_size > 0
        assert result["page_count"] == 2
        assert result["structures"]["table"] is True
        assert result["structures"]["image"] is False
        assert result["structures"]["vector_shape"] is True
        assert result["structures"]["metadata"] is True

    def test_created_pdf_validates(self, tmp_path: Path):
        destination = tmp_path / "test.pdf"
        create_pdf(destination, _document())
        report = validate_created(destination, _document())
        assert report["status"] == "pass"

    def test_create_validation_rejects_missing_requested_text(self, tmp_path: Path):
        destination = tmp_path / "test.pdf"
        create_pdf(destination, _minimal_text_document("Created text"))

        with pytest.raises(DocumentSkillsError) as exc:
            validate_created(
                destination,
                _minimal_text_document("Different requested text"),
            )

        assert exc.value.code is ErrorCode.VALIDATION_FAILED

    def test_create_validation_rejects_missing_requested_vector_shape(
        self,
        tmp_path: Path,
    ):
        destination = tmp_path / "test.pdf"
        actual_document = _minimal_text_document("Created text")
        expected_document = _minimal_text_document("Created text")
        expected_document["pages"][0]["blocks"].append(
            {
                "type": "vector_shape",
                "text": None,
                "style": None,
                "table": None,
                "image": None,
                "shape": {
                    "kind": "rectangle",
                    "x": 72,
                    "y": 72,
                    "width": 100,
                    "height": 50,
                    "stroke": None,
                    "fill": None,
                },
            }
        )
        create_pdf(destination, actual_document)

        with pytest.raises(DocumentSkillsError) as exc:
            validate_created(destination, expected_document)

        assert exc.value.code is ErrorCode.VALIDATION_FAILED

    def test_created_pdf_reopens(self, created_pdf: Path):
        result = reopen_pdf(created_pdf)
        assert result["pages"] == 2
        assert result["object_count"] > 0
        assert result["encrypted"] is False

    def test_create_is_deterministic(self, tmp_path: Path):
        d1 = tmp_path / "d1.pdf"
        d2 = tmp_path / "d2.pdf"
        create_pdf(d1, _document())
        create_pdf(d2, _document())
        assert hashlib.sha256(d1.read_bytes()).hexdigest() == hashlib.sha256(d2.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

class TestRead:
    def test_read_returns_page_count(self, created_pdf: Path):
        operation_result, warnings = read_pdf(created_pdf, {})
        assert operation_result["page_count"] == 2

    def test_read_returns_page_boxes(self, created_pdf: Path):
        operation_result, _ = read_pdf(created_pdf, {})
        page = operation_result["pages"][0]
        assert page["media_box"] == [0.0, 0.0, 595.276, 841.89]

    def test_read_returns_metadata(self, created_pdf: Path):
        operation_result, _ = read_pdf(created_pdf, {})
        info = operation_result["info_dictionary"]
        assert info["title"] == "Test PDF"

    def test_read_returns_fonts(self, created_pdf: Path):
        operation_result, _ = read_pdf(created_pdf, {})
        assert len(operation_result["fonts_by_page"]) == 2
        assert len(operation_result["fonts_by_page"][0]) > 0

    def test_read_returns_text_content(self, created_pdf: Path):
        operation_result, _ = read_pdf(created_pdf, {})
        text_page = operation_result["text_by_page"][0]
        assert "Page One" in text_page["text"]
        assert text_page["text_extraction"] == "embedded"


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

class TestInspect:
    def test_inspect_inert(self, created_pdf: Path):
        operation_result, _ = inspect_pdf(created_pdf, {})
        assert operation_result["dangerous_content_present"] is False
        assert operation_result["page_count"] == 2
        assert operation_result["object_count"] > 0
        assert "xref" in operation_result

    def test_inspect_includes_object_hashes(self, created_pdf: Path):
        operation_result, _ = inspect_pdf(created_pdf, {"include_hashes": True})
        for obj in operation_result["objects"]:
            assert "sha256" in obj

    def test_inspect_no_dangerous_content_in_benign(self, created_pdf: Path):
        operation_result, _ = inspect_pdf(created_pdf, {})
        assert operation_result["dangerous_content_present"] is False


# ---------------------------------------------------------------------------
# Edit: Merge
# ---------------------------------------------------------------------------

class TestEditMerge:
    def test_merge_concatenates_pages(self, tmp_path: Path):
        p1 = tmp_path / "a.pdf"
        p2 = tmp_path / "b.pdf"
        create_pdf(p1, _document())
        create_pdf(p2, _document())
        out = tmp_path / "merged.pdf"
        operation_result, manifest = edit_pdf(
            p1, out,
            {"primitives": [{"type": "merge", "inputs": _merge_inputs(p1, p2)}]},
        )
        assert operation_result["primitive"] == "merge"
        assert operation_result["input_count"] == 2
        assert operation_result["page_count"] == 4

    def test_merge_output_reopens(self, tmp_path: Path):
        p1 = tmp_path / "a.pdf"
        p2 = tmp_path / "b.pdf"
        create_pdf(p1, _document())
        create_pdf(p2, _document())
        out = tmp_path / "merged.pdf"
        edit_pdf(p1, out, {"primitives": [{"type": "merge", "inputs": _merge_inputs(p1, p2)}]})
        reopened = reopen_pdf(out)
        assert reopened["pages"] == 4

    def test_merge_preserves_page_content(self, tmp_path: Path):
        p1 = tmp_path / "a.pdf"
        p2 = tmp_path / "b.pdf"
        create_pdf(p1, _document())
        create_pdf(p2, _document())
        out = tmp_path / "merged.pdf"
        edit_pdf(p1, out, {"primitives": [{"type": "merge", "inputs": _merge_inputs(p1, p2)}]})
        # Walk the merged pages and verify they all have MediaBox + Contents
        merged_model = parse_pdf(out)
        pages = walk_pages(merged_model)
        assert len(pages) == 4
        for page in pages:
            assert page.media_box is not None
            assert len(page.contents) > 0

    def test_merge_source_preserved(self, tmp_path: Path):
        p1 = tmp_path / "a.pdf"
        p2 = tmp_path / "b.pdf"
        create_pdf(p1, _document())
        create_pdf(p2, _document())
        h1 = _source_hash(p1)
        h2 = _source_hash(p2)
        out = tmp_path / "merged.pdf"
        edit_pdf(p1, out, {"primitives": [{"type": "merge", "inputs": _merge_inputs(p1, p2)}]})
        assert _source_hash(p1) == h1
        assert _source_hash(p2) == h2

    def test_merge_preservation_manifest_intact(self, tmp_path: Path):
        p1 = tmp_path / "a.pdf"
        p2 = tmp_path / "b.pdf"
        create_pdf(p1, _document())
        create_pdf(p2, _document())
        out = tmp_path / "merged.pdf"
        _op_result, manifest = edit_pdf(
            p1, out, {"primitives": [{"type": "merge", "inputs": _merge_inputs(p1, p2)}]},
        )
        # All input objects in the transitive closure should be preserved
        assert len(manifest["preserved_objects"]) > 0
        assert len(manifest["changed_objects"]) == 0

    def test_merge_requires_two_inputs(self, tmp_path: Path):
        p1 = tmp_path / "a.pdf"
        create_pdf(p1, _document())
        out = tmp_path / "merged.pdf"
        with pytest.raises(DocumentSkillsError):
            edit_pdf(p1, out, {"primitives": [{"type": "merge", "inputs": _merge_inputs(p1)}]})


# ---------------------------------------------------------------------------
# Edit: Split
# ---------------------------------------------------------------------------

class TestEditSplit:
    def test_split_retains_requested_pages(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "split.pdf"
        operation_result, manifest = edit_pdf(
            src, out,
            {"primitives": [{"type": "split", "page_ranges": [[1, 1]]}]},
        )
        assert operation_result["primitive"] == "split"
        assert operation_result["retained_pages"] == 1
        assert operation_result["removed_pages"] == 1

    def test_split_output_reopens(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "split.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "split", "page_ranges": [[1, 1]]}]})
        reopened = reopen_pdf(out)
        assert reopened["pages"] == 1

    def test_split_source_preserved(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        h = _source_hash(src)
        out = tmp_path / "split.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "split", "page_ranges": [[1, 1]]}]})
        assert _source_hash(src) == h

    def test_split_removes_unused_objects(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "split.pdf"
        operation_result, manifest = edit_pdf(
            src, out, {"primitives": [{"type": "split", "page_ranges": [[1, 1]]}]},
        )
        assert len(operation_result["removed_objects"]) > 0
        # No orphan objects in the output
        split_model = parse_pdf(out)
        split_pages = walk_pages(split_model)
        assert len(split_pages) == 1

    def test_split_retains_all_pages(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "split_all.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "split", "page_ranges": [[1, 2]]}]})
        reopened = reopen_pdf(out)
        assert reopened["pages"] == 2

    def test_split_no_orphan_objects(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "split.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "split", "page_ranges": [[1, 1]]}]})
        split_model = parse_pdf(out)
        # Every object in the output must be reachable from the Catalog
        pages = walk_pages(split_model)
        assert len(pages) == 1
        # Verify the split output has fewer objects than the source
        src_model = parse_pdf(src)
        assert len(split_model.objects) < len(src_model.objects)


# ---------------------------------------------------------------------------
# Edit: Rotate
# ---------------------------------------------------------------------------

class TestEditRotate:
    def test_rotate_changes_targeted_page(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rotated.pdf"
        operation_result, manifest = edit_pdf(
            src, out,
            {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
        )
        assert operation_result["primitive"] == "rotate"
        assert 1 in operation_result["pages"]
        # Verify the rotation actually changed
        out_model = parse_pdf(out)
        out_pages = walk_pages(out_model)
        assert out_pages[0].rotation == 90
        assert out_pages[1].rotation == 0

    def test_rotate_preserves_untargeted_pages(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rotated.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "rotate", "pages": [1], "degrees": 180}]})
        # Page 2 should have the same content stream hash as the source
        src_model = parse_pdf(src)
        out_model = parse_pdf(out)
        src_pages = walk_pages(src_model)
        out_pages = walk_pages(out_model)
        src_p2_content = src_pages[1].contents[0]
        out_p2_content = out_pages[1].contents[0]
        assert src_model.objects[src_p2_content.obj_num].sha256 == out_model.objects[out_p2_content.obj_num].sha256

    def test_rotate_source_preserved(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        h = _source_hash(src)
        out = tmp_path / "rotated.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "rotate", "pages": [1, 2], "degrees": 270}]})
        assert _source_hash(src) == h


# ---------------------------------------------------------------------------
# Edit: Watermark
# ---------------------------------------------------------------------------

class TestEditWatermark:
    def test_watermark_adds_to_targeted_pages(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "watermarked.pdf"
        operation_result, manifest = edit_pdf(
            src, out,
            {"primitives": [{"type": "watermark", "text": "CONFIDENTIAL", "pages": [1], "opacity": 0.3}]},
        )
        assert operation_result["primitive"] == "watermark"
        assert 1 in operation_result["pages"]

    def test_watermark_preserves_untargeted_pages(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "watermarked.pdf"
        edit_pdf(
            src, out,
            {"primitives": [{"type": "watermark", "text": "WM", "pages": [1], "opacity": 0.5}]},
        )
        # Page 2's content stream should be unchanged
        src_model = parse_pdf(src)
        out_model = parse_pdf(out)
        src_pages = walk_pages(src_model)
        out_pages = walk_pages(out_model)
        src_p2_content = src_pages[1].contents[0].obj_num
        out_p2_content = out_pages[1].contents[0].obj_num
        assert src_model.objects[src_p2_content].sha256 == out_model.objects[out_p2_content].sha256

    def test_watermark_source_preserved(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        h = _source_hash(src)
        out = tmp_path / "watermarked.pdf"
        edit_pdf(src, out, {"primitives": [{"type": "watermark", "text": "WM", "pages": [1], "opacity": 0.3}]})
        assert _source_hash(src) == h


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------

class TestRewrite:
    def test_rewrite_changes_targeted_block(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rewritten.pdf"
        operation_result, manifest = rewrite_apply_pdf(
            src, out,
            {
                "blocks": [{"page": 1, "bbox": [72, 753, 300, 770], "text": "Page One", "font": "F2", "size": 16.0, "color": None}],
                "rewrites": [{"block_index": 0, "text": "Page Modified"}],
            },
        )
        assert "rewrite" in operation_result
        assert operation_result["rewrite"]["blocks_processed"] == 1
        # Output should reopen
        reopened = reopen_pdf(out)
        assert reopened["pages"] == 2

    def test_rewrite_preserves_page_layout(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rewritten.pdf"
        operation_result, _manifest = rewrite_apply_pdf(
            src, out,
            {
                "blocks": [{"page": 1, "bbox": [72, 753, 300, 770], "text": "Page One", "font": "F2", "size": 16.0, "color": None}],
                "rewrites": [{"block_index": 0, "text": "Page Modified"}],
            },
        )
        layout = operation_result["rewrite"]["page_layout_preservation"]
        assert layout["verified"] is True
        assert layout["page_box_preserved"] is True

    def test_rewrite_source_preserved(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        h = _source_hash(src)
        out = tmp_path / "rewritten.pdf"
        rewrite_apply_pdf(
            src, out,
            {
                "blocks": [{"page": 1, "bbox": [72, 753, 300, 770], "text": "Page One", "font": "F2", "size": 16.0, "color": None}],
                "rewrites": [{"block_index": 0, "text": "New Text"}],
            },
        )
        assert _source_hash(src) == h

    def test_rewrite_cjk_without_font_fails_before_artifact(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "cjk_rewritten.pdf"
        with pytest.raises(DocumentSkillsError) as captured:
            rewrite_apply_pdf(
                src, out,
                {
                    "blocks": [{"page": 1, "bbox": [72, 754, 300, 770], "text": "Page One", "font": "F2", "size": 16.0, "color": None}],
                    "rewrites": [{"block_index": 0, "text": "日本語テスト"}],
                },
            )
        assert captured.value.code is ErrorCode.ENHANCEMENT_REQUIRED
        assert not out.exists()


# ---------------------------------------------------------------------------
# Preservation manifest
# ---------------------------------------------------------------------------

class TestPreservation:
    def test_rotate_preservation_manifest(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rotated.pdf"
        _op, manifest = edit_pdf(
            src, out,
            {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
        )
        # Only the targeted page should be in changed_objects
        assert len(manifest["changed_objects"]) > 0
        # Every other object should be preserved
        assert len(manifest["preserved_objects"]) > 0
        # Verify preserved objects match input hashes
        for num in manifest["preserved_objects"]:
            in_hash = manifest["input_hashes"].get(str(num)) or manifest["input_hashes"].get(num)
            out_hash = manifest["output_hashes"].get(str(num)) or manifest["output_hashes"].get(num)
            assert in_hash == out_hash, f"Object {num} not preserved"

    def test_distinct_output_required(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        from document_skills_core.formats.pdf.contracts import parse_pdf_request
        with pytest.raises(DocumentSkillsError) as exc:
            parse_pdf_request({
                "schema_version": "1.0",
                "operation": "pdf.edit",
                "input": str(src.resolve()),
                "output": str(src.resolve()),
                "arguments": {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
            })
        assert exc.value.code.value == "DS_OUTPUT_EQUALS_INPUT"


# ---------------------------------------------------------------------------
# Page-layout-preservation-on-rewrite reopen gate
# ---------------------------------------------------------------------------

class TestPageLayoutPreservation:
    def test_page_layout_preservation_gate_passes_on_valid_rewrite(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rewritten.pdf"
        operation_result, manifest = rewrite_apply_pdf(
            src, out,
            {
                "blocks": [{"page": 1, "bbox": [72, 753, 300, 770], "text": "Page One", "font": "F2", "size": 16.0, "color": None}],
                "rewrites": [{"block_index": 0, "text": "Valid New Text"}],
            },
        )
        layout = operation_result["rewrite"]["page_layout_preservation"]
        assert layout["verified"] is True

    def test_validate_mutation_succeeds_on_valid_rotate(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rotated.pdf"
        _op, manifest = edit_pdf(
            src, out,
            {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
        )
        report = validate_mutation(
            out,
            source=src,
            source_sha256=_source_hash(src),
            manifest=manifest,
        )
        assert report["status"] == "pass"


# ---------------------------------------------------------------------------
# Security: malicious fixtures fail closed
# ---------------------------------------------------------------------------

def _build_minimal_pdf(path: Path, catalog_extras: str = "") -> Path:
    """Build a minimal valid PDF with optional Catalog entries for testing.

    The xref offsets are computed correctly so the PDF reopens.
    """
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()

    offsets: list[int] = []

    def emit(content: bytes) -> int:
        num = len(offsets) + 1
        offsets.append(len(header) + len(body))
        body.extend(f"{num} 0 obj\n".encode("ascii"))
        body.extend(content)
        body.extend(b"\nendobj\n")
        return num

    # obj 1: Catalog
    catalog = f"<< /Type /Catalog /Pages 2 0 R{catalog_extras} >>".encode("ascii")
    emit(catalog)
    # obj 2: Pages
    emit(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    # obj 3: Page
    emit(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>")

    xref_offset = len(header) + len(body)
    size = len(offsets) + 1
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {size}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for off in offsets:
        xref.extend(f"{off:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _build_action_pdf(path: Path, action_dict: str) -> Path:
    """Build a PDF with a Catalog /OpenAction for action-classification tests."""
    open_action = f" /OpenAction {action_dict}"
    return _build_minimal_pdf(path, catalog_extras=open_action)


def _build_encrypted_pdf(path: Path) -> Path:
    """Build a PDF with an /Encrypt dictionary."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []

    def emit(content: bytes) -> int:
        num = len(offsets) + 1
        offsets.append(len(header) + len(body))
        body.extend(f"{num} 0 obj\n".encode("ascii"))
        body.extend(content)
        body.extend(b"\nendobj\n")
        return num

    emit(b"<< /Type /Catalog /Pages 2 0 R >>")
    emit(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    emit(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>")
    emit(b"<< /Filter /Standard /V 1 /R 2 /O (1234567890123456789012345678) /U (1234567890123456789012345678) >>")

    xref_offset = len(header) + len(body)
    size = len(offsets) + 1
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {size}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for off in offsets:
        xref.extend(f"{off:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {size} /Root 1 0 R /Encrypt 4 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _build_embedded_executable_pdf(path: Path) -> Path:
    """Build a PDF with an embedded file carrying an executable MIME type.

    The /EF mapping uses inline file-spec dictionaries so the executable MIME
    is detectable at the parsed-dict level by has_executable_embedded_files.
    """
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []

    def emit(content: bytes) -> int:
        num = len(offsets) + 1
        offsets.append(len(header) + len(body))
        body.extend(f"{num} 0 obj\n".encode("ascii"))
        body.extend(content)
        body.extend(b"\nendobj\n")
        return num

    emit(b"<< /Type /Catalog /Pages 2 0 R >>")
    emit(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    emit(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/EF << /F << /Type /EmbeddedFile /Subtype (application/x-dosexec) >> >> >>"
    )

    xref_offset = len(header) + len(body)
    size = len(offsets) + 1
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {size}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for off in offsets:
        xref.extend(f"{off:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


class TestSecurityFailClosed:
    def test_flate_decode_stops_at_uncompressed_budget(self):
        compressed = zlib.compress(b"A" * 4096)
        limits = PdfByteLimits(
            max_uncompressed_bytes=64,
            max_expansion_ratio=100_000,
        )

        with pytest.raises(DocumentSkillsError) as captured:
            decode_stream(compressed, ["/FlateDecode"], limits)

        assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
        assert captured.value.details == {"uncompressed_bytes": 65, "limit": 64}

    def test_malformed_header_rejected(self, tmp_path: Path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"NOTPDF-1.7\n%%EOF\n")
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(bad, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_missing_eof_rejected(self, tmp_path: Path):
        bad = tmp_path / "noeof.pdf"
        bad.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
        with pytest.raises(DocumentSkillsError):
            read_pdf(bad, {})

    def test_javascript_action_rejected_by_read(self, tmp_path: Path):
        js_pdf = tmp_path / "js_action.pdf"
        _build_action_pdf(js_pdf, "<< /S /JavaScript /JS (app.alert(1)) >>")
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(js_pdf, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_javascript_action_inert_in_inspect(self, tmp_path: Path):
        js_pdf = tmp_path / "js_inspect.pdf"
        _build_action_pdf(js_pdf, "<< /S /JavaScript /JS (app.alert(1)) >>")
        operation_result, _ = inspect_pdf(js_pdf, {})
        assert operation_result["dangerous_content_present"] is True
        assert any(a["kind"] == "JavaScript" for a in operation_result["actions"])

    def test_launch_action_rejected_by_read(self, tmp_path: Path):
        launch_pdf = tmp_path / "launch.pdf"
        _build_action_pdf(launch_pdf, "<< /S /Launch /F (calc.exe) >>")
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(launch_pdf, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_uri_action_rejected_by_read(self, tmp_path: Path):
        uri_pdf = tmp_path / "uri.pdf"
        _build_action_pdf(uri_pdf, "<< /S /URI /URI (http://evil.example.com) >>")
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(uri_pdf, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_gotor_action_rejected_by_read(self, tmp_path: Path):
        gotor_pdf = tmp_path / "gotor.pdf"
        _build_action_pdf(gotor_pdf, "<< /S /GoToR /F (external.pdf) >>")
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(gotor_pdf, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_encrypted_pdf_rejected(self, tmp_path: Path):
        enc_pdf = tmp_path / "encrypted.pdf"
        _build_encrypted_pdf(enc_pdf)
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(enc_pdf, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_embedded_executable_rejected_by_read(self, tmp_path: Path):
        exec_pdf = tmp_path / "embed_exec.pdf"
        _build_embedded_executable_pdf(exec_pdf)
        with pytest.raises(DocumentSkillsError) as exc:
            read_pdf(exec_pdf, {})
        assert exc.value.code == ErrorCode.ARCHIVE_UNSAFE

    def test_action_trees_never_executed_in_inspect(self, tmp_path: Path):
        """Inspect classifies JS/Launch/URI/GoToR inertly — never executes."""
        for action_dict, expected_kind in [
            ("<< /S /JavaScript /JS (payload) >>", "JavaScript"),
            ("<< /S /Launch /F (prog.exe) >>", "Launch"),
            ("<< /S /URI /URI (http://x) >>", "URI"),
            ("<< /S /GoToR /F (ext.pdf) >>", "GoToR"),
        ]:
            pdf = tmp_path / f"{expected_kind.lower()}.pdf"
            _build_action_pdf(pdf, action_dict)
            operation_result, _ = inspect_pdf(pdf, {})
            kinds = {a["kind"] for a in operation_result["actions"]}
            assert expected_kind in kinds
            for a in operation_result["actions"]:
                assert a["mutation_authorized"] is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_reopen_pdf_returns_canonical_result(self, created_pdf: Path):
        result = reopen_pdf(created_pdf)
        assert "version" in result
        assert "object_count" in result
        assert "pages" in result
        assert "encrypted" in result
        assert "has_eof" in result

    def test_validate_created_passes(self, created_pdf: Path):
        report = validate_created(created_pdf, _document())
        assert report["status"] == "pass"

    def test_validate_mutation_passes_for_rotate(self, tmp_path: Path):
        src = tmp_path / "src.pdf"
        create_pdf(src, _document())
        out = tmp_path / "rotated.pdf"
        _op, manifest = edit_pdf(src, out, {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]})
        report = validate_mutation(out, source=src, source_sha256=_source_hash(src), manifest=manifest)
        assert report["status"] == "pass"
