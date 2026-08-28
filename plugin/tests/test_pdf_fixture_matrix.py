"""Determinism, registry, and semantic checks for PDF completion fixtures."""

import json
from pathlib import Path
import subprocess
import sys

from fontTools.ttLib import TTFont
from PIL import Image, ImageOps
import pytest

from document_skills_core.formats.pdf.mapping import map_text_blocks
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.resources import inventory_fonts, inventory_images
from tools.audit import audit_fixtures


def _fixture_root(project_root: Path) -> Path:
    return project_root / "tests" / "fixtures"


def _completion_root(project_root: Path) -> Path:
    return _fixture_root(project_root) / "pdf-completion"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _flat_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(root.iterdir())
        if path.is_file()
    }


def test_recipe_regenerates_twice_to_registered_checked_in_bytes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    recipe = fixture_root / "recipes" / "pdf_completion_fixtures.py"
    generated_roots = [tmp_path / "first", tmp_path / "second"]
    generated_records = []

    for destination in generated_roots:
        completed = subprocess.run(
            [
                sys.executable,
                str(recipe),
                "--output",
                str(destination),
                "--fixture-root",
                str(fixture_root),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            shell=False,
            timeout=60,
        )
        generated_records.append(json.loads(completed.stdout.decode("utf-8")))

    first = _flat_file_bytes(generated_roots[0])
    second = _flat_file_bytes(generated_roots[1])
    checked_in = _flat_file_bytes(_completion_root(project_root))
    assert len(first) == 13
    assert first == second == checked_in
    assert generated_records[0] == generated_records[1]
    assert len(generated_records[0]) == 13

    manifest = _load_json(fixture_root / "manifest.json")
    registered = [
        record
        for record in manifest["fixtures"]
        if record["path"].startswith("pdf-completion/")
    ]
    assert generated_records[0] == registered


def test_pdf_completion_fixtures_pass_repository_registry_audit(
    project_root: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    manifest = _load_json(fixture_root / "manifest.json")
    registered = {
        record["path"]
        for record in manifest["fixtures"]
        if record["path"].startswith("pdf-completion/")
    }
    actual = {
        path.relative_to(fixture_root).as_posix()
        for path in _completion_root(project_root).iterdir()
        if path.is_file()
    }

    assert len(registered) == 13
    assert registered == actual
    report = audit_fixtures(project_root)
    assert report["status"] == "pass"


def test_ocr_pdf_inputs_match_provider_independent_oracles(
    project_root: Path,
) -> None:
    completion_root = _completion_root(project_root)
    oracle = _load_json(completion_root / "oracles.json")
    cases = oracle["cases"]
    assert len(cases) == 6

    seen_kinds = set()
    image_backed_kinds = {"scanned", "cjk-rtl", "multi-column", "low-quality"}
    for case in cases:
        path = completion_root / case["path"]
        model = parse_pdf(path)
        reopened = parse_pdf(path)
        pages = walk_pages(model)
        reopened_pages = walk_pages(reopened)

        assert reopened.raw == model.raw == path.read_bytes()
        assert len(pages) == len(reopened_pages) == case["page_count"]
        assert pages[0].rotation == reopened_pages[0].rotation == case["rotation"]
        assert case["expected_text"]
        assert case["oracle_scope"] == (
            "provider-independent-input-and-expected-semantics"
        )

        images = inventory_images(model, pages[0].resources)
        native_text = [block.text for block in map_text_blocks(model, pages)]
        assert len(images) == 1
        if case["kind"] == "mixed":
            assert "Native layer" in native_text
            assert "Native layer" in case["expected_text"]
        else:
            assert native_text == []
        if case["kind"] in image_backed_kinds:
            assert images[0].width > 0
            assert images[0].height > 0
        seen_kinds.add(case["kind"])

    assert image_backed_kinds <= seen_kinds
    assert seen_kinds == {
        "scanned",
        "mixed",
        "rotated",
        "cjk-rtl",
        "multi-column",
        "low-quality",
    }


def test_exif_orientation_fixture_preserves_stored_geometry(
    project_root: Path,
) -> None:
    completion_root = _completion_root(project_root)
    oracle = _load_json(completion_root / "oracles.json")
    expected = oracle["assets"]["exif-orientation-6.jpg"]
    with Image.open(completion_root / "exif-orientation-6.jpg") as image:
        assert list(image.size) == expected["stored_size"] == [48, 32]
        assert image.getexif()[274] == expected["exif_orientation"] == 6
        assert ImageOps.exif_transpose(image).size == (32, 48)


def test_emoji_font_and_pdf_publish_embedded_unicode_mapping(
    project_root: Path,
) -> None:
    completion_root = _completion_root(project_root)
    oracle = _load_json(completion_root / "oracles.json")
    font_oracle = oracle["assets"]["emoji-success.ttf"]
    pdf_oracle = oracle["assets"]["emoji-success.pdf"]

    with TTFont(completion_root / "emoji-success.ttf") as font:
        codepoints = {
            codepoint
            for table in font["cmap"].tables
            for codepoint in table.cmap
        }
    assert set(font_oracle["required_codepoints"]) <= codepoints
    assert 0x1F600 in codepoints

    pdf_path = completion_root / "emoji-success.pdf"
    model = parse_pdf(pdf_path)
    pages = walk_pages(model)
    fonts = inventory_fonts(model, pages[0].resources)
    assert len(pages) == 1
    assert len(fonts) == 1
    assert fonts[0].embedded is pdf_oracle["embedded_font"] is True
    assert fonts[0].cmap is not None
    assert pdf_oracle["unicode"] == "😀"
    assert b"<0002>" in model.raw
    assert b"<D83DDE00>" in model.raw
    assert parse_pdf(pdf_path).raw == model.raw


def test_malformed_provider_corpus_covers_three_distinct_failures(
    project_root: Path,
) -> None:
    completion_root = _completion_root(project_root)
    oracle = _load_json(completion_root / "oracles.json")
    expected = {
        "provider-malformed-truncated.bin": "truncated-json",
        "provider-malformed-binding.bin": "nonce-binding-mismatch",
        "provider-malformed-binary.bin": "non-utf8-output",
    }
    assert oracle["malformed_provider_outputs"] == expected
    assert {
        path.name for path in completion_root.glob("provider-malformed-*.bin")
    } == set(expected)

    truncated = (completion_root / "provider-malformed-truncated.bin").read_bytes()
    with pytest.raises(json.JSONDecodeError):
        json.loads(truncated.decode("utf-8"))

    binding = json.loads(
        (completion_root / "provider-malformed-binding.bin").read_text(
            encoding="utf-8"
        )
    )
    assert binding == {"command": "pdf.ocr", "nonce": "wrong", "result": {}}
    assert binding["nonce"] != "fixture"

    binary = (completion_root / "provider-malformed-binary.bin").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        binary.decode("utf-8", errors="strict")


def test_oracle_makes_no_ocr_provider_success_claim(project_root: Path) -> None:
    oracle_path = _completion_root(project_root) / "oracles.json"
    oracle = _load_json(oracle_path)
    rendered = oracle_path.read_text(encoding="utf-8").casefold()

    assert oracle["provider_claim"] == "input-only-no-ocr-accuracy-claim"
    assert "tesseract" not in rendered
    assert "poppler" not in rendered
