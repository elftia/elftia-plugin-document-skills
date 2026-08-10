"""PPTX functional operation tests — create, read, inspect, edit, reorder."""

import zipfile
from pathlib import Path
from typing import Any

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.contracts import parse_pptx_request
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.edit import edit_pptx
from document_skills_core.formats.pptx.inspect import inspect_pptx
from document_skills_core.formats.pptx.package import write_deterministic_zip
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.formats.pptx.validation import (
    reopen_pptx,
    validate_created,
    validate_reorder,
)


def _deck() -> dict[str, Any]:
    return {
        "metadata": {"title": "Test Deck", "creator": "Elftia", "subject": "Testing"},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": [
            {
                "layout": "title",
                "title": "Title Slide",
                "shapes": [
                    {"text": "Subtitle", "runs": [{"text": "Subtitle", "style": None}]}
                ],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": "Welcome notes",
            },
            {
                "layout": "content",
                "title": "Content Slide",
                "shapes": [
                    {"text": "Body", "runs": [{"text": "Bold text", "style": {"b": "1"}}]}
                ],
                "table": {
                    "rows": [
                        {"cells": ["A1", "B1"]},
                        {"cells": ["A2", "B2"]},
                    ]
                },
                "chart_reference": {"title": "Sales", "chart_type": "bar"},
                "image_reference": {"filename": "image.png", "content_type": "image/png"},
                "notes": "Content notes",
            },
        ],
    }


@pytest.fixture
def created_deck(tmp_path: Path) -> Path:
    destination = tmp_path / "created.pptx"
    create_pptx(destination, _deck())
    return destination


class TestCreate:
    def test_create_produces_valid_file(self, tmp_path: Path):
        destination = tmp_path / "test.pptx"
        creation = create_pptx(destination, _deck())
        assert destination.is_file()
        assert destination.stat().st_size > 0
        assert creation["slides"] == 2
        assert creation["layouts"] == 2
        assert creation["has_chart"] is True
        assert creation["has_image"] is True
        assert creation["has_table"] is True
        assert creation["has_notes"] is True

    def test_created_deck_fails_consumer_package_validation(self, tmp_path: Path):
        destination = tmp_path / "test.pptx"
        create_pptx(destination, _deck())
        with pytest.raises(DocumentSkillsError) as captured:
            validate_created(destination, _deck())
        assert any(
            gate["id"] == "operation.consumer-package-conformance"
            and gate["outcome"] == "fail"
            for gate in captured.value.validation["gates"]
        )

    def test_created_deck_reopens(self, created_deck: Path):
        result = reopen_pptx(created_deck)
        assert result["slides"] == 2
        assert result["parts"] > 0

    def test_create_is_deterministic(self, tmp_path: Path):
        d1 = tmp_path / "d1.pptx"
        d2 = tmp_path / "d2.pptx"
        create_pptx(d1, _deck())
        create_pptx(d2, _deck())
        import hashlib
        assert hashlib.sha256(d1.read_bytes()).hexdigest() == hashlib.sha256(d2.read_bytes()).hexdigest()


class TestRead:
    def test_read_returns_slides_in_order(self, created_deck: Path):
        operation_result, warnings = read_pptx(created_deck, {})
        slides = operation_result["slides"]
        assert len(slides) == 2
        assert slides[0]["number"] == 1
        assert slides[1]["number"] == 2

    def test_read_includes_shapes(self, created_deck: Path):
        operation_result, warnings = read_pptx(created_deck, {})
        slides = operation_result["slides"]
        assert len(slides[0]["shapes"]) > 0

    def test_read_includes_slide_size(self, created_deck: Path):
        operation_result, warnings = read_pptx(created_deck, {})
        size = operation_result["slide_size"]
        assert size is not None
        assert size["cx"] == "9144000"
        assert size["cy"] == "6858000"

    def test_read_includes_layout_reference(self, created_deck: Path):
        operation_result, warnings = read_pptx(created_deck, {})
        for slide in operation_result["slides"]:
            assert slide["layout"] is not None

    def test_read_includes_chart_references(self, created_deck: Path):
        operation_result, warnings = read_pptx(created_deck, {})
        charts = operation_result["charts"]
        assert len(charts) > 0
        assert charts[0]["chart_type"] in {"bar", "unknown"}


class TestInspect:
    def test_inspect_invents_full_structure(self, created_deck: Path):
        operation_result, warnings = inspect_pptx(created_deck, {})
        assert operation_result["mutation_authorized"] is False
        assert operation_result["slide_count"] == 2
        assert operation_result["slide_master_count"] >= 1
        assert operation_result["slide_layout_count"] >= 2
        assert operation_result["theme_count"] >= 1
        assert operation_result["part_count"] > 0

    def test_inspect_includes_part_hashes(self, created_deck: Path):
        operation_result, warnings = inspect_pptx(created_deck, {"include_hashes": True})
        for part in operation_result["parts"]:
            assert "sha256" in part


class TestEdit:
    def test_edit_slide_text_preserves_source(self, created_deck: Path, tmp_path: Path):
        import hashlib
        source_hash = hashlib.sha256(created_deck.read_bytes()).hexdigest()
        output = tmp_path / "edited.pptx"
        operation_result, manifest = edit_pptx(
            created_deck, output,
            {"edits": [{"slide": 1, "type": "slide_text", "ref": "", "value": "New text"}]},
        )
        assert output.is_file()
        assert hashlib.sha256(created_deck.read_bytes()).hexdigest() == source_hash
        assert "ppt/slides/slide1.xml" in manifest.changed

    def test_edit_notes_preserves_parent_slide(self, created_deck: Path, tmp_path: Path):
        output = tmp_path / "notes-edited.pptx"
        operation_result, manifest = edit_pptx(
            created_deck, output,
            {"edits": [{"slide": 1, "type": "notes_text", "ref": "", "value": "Updated notes"}]},
        )
        assert output.is_file()
        assert "ppt/notesSlides/notesSlide1.xml" in manifest.changed
        slide1_hash = manifest.input_hashes.get("ppt/slides/slide1.xml")
        slide1_output = manifest.output_hashes.get("ppt/slides/slide1.xml")
        assert slide1_hash == slide1_output

    def test_edit_counts(self, created_deck: Path, tmp_path: Path):
        output = tmp_path / "edited.pptx"
        operation_result, manifest = edit_pptx(
            created_deck, output,
            {"edits": [
                {"slide": 1, "type": "slide_text", "ref": "", "value": "Edited 1"},
                {"slide": 2, "type": "slide_text", "ref": "", "value": "Edited 2"},
            ]},
        )
        assert operation_result["edit_counts"]["slide_text"] == 2


class TestReorder:
    def test_reorder_preserves_slide_payloads(self, created_deck: Path, tmp_path: Path):
        output = tmp_path / "reordered.pptx"
        operation_result, manifest = edit_pptx(
            created_deck, output,
            {"edits": [{"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"}]},
        )
        assert "reorder" in operation_result
        reorder = operation_result["reorder"][0]
        assert reorder["pre_position"] == 2
        assert reorder["post_position"] == 1
        assert reorder["shape_ids_preserved"] is True
        # Every slide payload must be byte-identical
        for part_name in manifest.preserved:
            if part_name.startswith("ppt/slides/slide") and part_name.endswith(".xml"):
                assert manifest.input_hashes[part_name] == manifest.output_hashes[part_name]

    def test_reorder_preserves_layout_and_master_refs(self, created_deck: Path, tmp_path: Path):
        output = tmp_path / "reordered.pptx"
        edit_pptx(
            created_deck, output,
            {"edits": [{"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"}]},
        )
        # Run the structure-equality-on-reorder gate
        result = validate_reorder(output, source=created_deck)
        assert result["structure_equal"] is True

    def test_reorder_only_changes_presentation_xml(self, created_deck: Path, tmp_path: Path):
        output = tmp_path / "reordered.pptx"
        operation_result, manifest = edit_pptx(
            created_deck, output,
            {"edits": [{"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"}]},
        )
        changed = set(manifest.changed)
        assert "ppt/presentation.xml" in changed
        # No slide payloads should be changed
        slide_changes = [c for c in changed if c.startswith("ppt/slides/slide") and c.endswith(".xml")]
        assert slide_changes == []

    def test_reorder_source_preserved(self, created_deck: Path, tmp_path: Path):
        import hashlib
        source_hash = hashlib.sha256(created_deck.read_bytes()).hexdigest()
        output = tmp_path / "reordered.pptx"
        edit_pptx(
            created_deck, output,
            {"edits": [{"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"}]},
        )
        assert hashlib.sha256(created_deck.read_bytes()).hexdigest() == source_hash


# ---------------------------------------------------------------------------
# Helpers for adversarial corruption tests
# ---------------------------------------------------------------------------

def _read_parts(path: Path) -> dict[str, bytes]:
    parts: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts[name] = archive.read(info)
    return parts


def _rewrite_part(source: Path, destination: Path, part_name: str, new_payload: bytes) -> None:
    parts = _read_parts(source)
    parts[part_name] = new_payload
    write_deterministic_zip(destination, parts)


def _reorder(source: Path, destination: Path) -> None:
    edit_pptx(
        source, destination,
        {"edits": [{"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"}]},
    )


class TestReorderValidationGaps:
    """Adversarial regression: the structure-equality-on-reorder gate must
    catch all 5 spec-required comparison categories beyond shape IDs, text
    frames, layout/master refs, and the notes PART path.

    These probes corrupt one category at a time in a reordered candidate and
    assert that ``validate_reorder`` raises ``DS_VALIDATION_FAILED``.
    """

    def test_corrupt_notes_text_rejected(self, created_deck: Path, tmp_path: Path):
        reordered = tmp_path / "reordered.pptx"
        _reorder(created_deck, reordered)
        notes_part = "ppt/notesSlides/notesSlide2.xml"
        parts = _read_parts(reordered)
        notes_xml = parts[notes_part].decode("utf-8")
        corrupted = notes_xml.replace("Notes for slide 2", "CORRUPTED_NOTES").encode("utf-8")
        corrupted_path = tmp_path / "corrupted.pptx"
        _rewrite_part(reordered, corrupted_path, notes_part, corrupted)
        with pytest.raises(DocumentSkillsError) as exc_info:
            validate_reorder(corrupted_path, source=created_deck)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_corrupt_table_cell_text_rejected(self, created_deck: Path, tmp_path: Path):
        reordered = tmp_path / "reordered.pptx"
        _reorder(created_deck, reordered)
        slide_part = "ppt/slides/slide2.xml"
        parts = _read_parts(reordered)
        slide_xml = parts[slide_part].decode("utf-8")
        corrupted = slide_xml.replace("<a:t>A1</a:t>", "<a:t>HACKED</a:t>").encode("utf-8")
        corrupted_path = tmp_path / "corrupted.pptx"
        _rewrite_part(reordered, corrupted_path, slide_part, corrupted)
        with pytest.raises(DocumentSkillsError) as exc_info:
            validate_reorder(corrupted_path, source=created_deck)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_corrupt_chart_rel_rejected(self, created_deck: Path, tmp_path: Path):
        reordered = tmp_path / "reordered.pptx"
        _reorder(created_deck, reordered)
        rels_part = "ppt/slides/_rels/slide2.xml.rels"
        parts = _read_parts(reordered)
        rels_xml = parts[rels_part].decode("utf-8")
        corrupted = rels_xml.replace(
            'Target="../charts/chart1.xml"',
            'Target="../theme/theme1.xml"',
        ).encode("utf-8")
        corrupted_path = tmp_path / "corrupted.pptx"
        _rewrite_part(reordered, corrupted_path, rels_part, corrupted)
        with pytest.raises(DocumentSkillsError) as exc_info:
            validate_reorder(corrupted_path, source=created_deck)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_corrupt_image_rel_rejected(self, created_deck: Path, tmp_path: Path):
        reordered = tmp_path / "reordered.pptx"
        _reorder(created_deck, reordered)
        rels_part = "ppt/slides/_rels/slide2.xml.rels"
        parts = _read_parts(reordered)
        rels_xml = parts[rels_part].decode("utf-8")
        corrupted = rels_xml.replace(
            'Target="../media/image1.png"',
            'Target="../theme/theme1.xml"',
        ).encode("utf-8")
        corrupted_path = tmp_path / "corrupted.pptx"
        _rewrite_part(reordered, corrupted_path, rels_part, corrupted)
        with pytest.raises(DocumentSkillsError) as exc_info:
            validate_reorder(corrupted_path, source=created_deck)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_corrupt_connector_geometry_rejected(self, created_deck: Path, tmp_path: Path):
        # Inject a connector shape into slide2 of the source deck.
        source_with_connector = tmp_path / "with_connector.pptx"
        slide_part = "ppt/slides/slide2.xml"
        parts = _read_parts(created_deck)
        slide_xml = parts[slide_part].decode("utf-8")
        connector_xml = (
            "<p:cxnSp>"
            "<p:nvCxnSpPr>"
            '<p:cNvPr id="100" name="Connector100"/>'
            "<p:cNvCxnSpPr/>"
            "<p:nvPr/>"
            "</p:nvCxnSpPr>"
            "<p:spPr>"
            "<a:xfrm>"
            '<a:off x="100" y="200"/>'
            '<a:ext cx="300" cy="0"/>'
            "</a:xfrm>"
            '<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            "</p:spPr>"
            "</p:cxnSp>"
        )
        modified = slide_xml.replace("</p:spTree>", connector_xml + "</p:spTree>")
        parts[slide_part] = modified.encode("utf-8")
        write_deterministic_zip(source_with_connector, parts)

        reordered = tmp_path / "reordered.pptx"
        _reorder(source_with_connector, reordered)

        # Corrupt the connector offset geometry in the reordered candidate.
        parts2 = _read_parts(reordered)
        corrupted_slide = parts2[slide_part].decode("utf-8")
        corrupted = corrupted_slide.replace(
            '<a:off x="100" y="200"/>',
            '<a:off x="999" y="999"/>',
        ).encode("utf-8")
        corrupted_path = tmp_path / "corrupted.pptx"
        _rewrite_part(reordered, corrupted_path, slide_part, corrupted)
        with pytest.raises(DocumentSkillsError) as exc_info:
            validate_reorder(corrupted_path, source=source_with_connector)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED
