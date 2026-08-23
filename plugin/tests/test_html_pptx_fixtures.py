"""Deterministic repository-authored HTML/image/scene/PPTX fixture coverage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.formats.pptx.html_capture import HtmlDeckCapture
from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.scene import SceneDeck, parse_scene_deck
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.scene_normalizer import normalize_scene
from document_skills_core.formats.pptx.validation import validate_scene_created
from document_skills_core.providers.html_browser import HtmlBrowserDetector
from tools.audit import audit_fixtures

_RECIPE = "tests/fixtures/recipes/html_pptx_fixtures.py"
_METADATA = {
    "title": "Repository-authored HTML fixture",
    "creator": "Elftia",
    "subject": "",
}


def test_html_fixture_recipe_regenerates_twice_to_checked_in_bytes(
    project_root: Path,
    tmp_path: Path,
):
    recipe = project_root / _RECIPE
    generated_roots = [tmp_path / "first", tmp_path / "second"]
    for destination in generated_roots:
        subprocess.run(
            [sys.executable, str(recipe), "--output", str(destination)],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=False,
            shell=False,
            timeout=60,
        )
    first = _generated_files(generated_roots[0])
    second = _generated_files(generated_roots[1])
    assert first == second
    fixtures = project_root / "tests/fixtures"
    checked_manifest = _json(fixtures / "manifest.json")
    checked_records = [
        record
        for record in checked_manifest["fixtures"]
        if record.get("recipe") == _RECIPE
    ]
    generated_manifest = _json(generated_roots[0] / "manifest.json")
    assert generated_manifest["fixtures"] == checked_records
    for name, payload in first.items():
        if name != "manifest.json":
            assert (fixtures / name).read_bytes() == payload


def test_native_scene_fixture_emits_exact_deterministic_reopenable_pptx(
    project_root: Path,
    tmp_path: Path,
):
    fixtures = project_root / "tests/fixtures"
    scene_path = fixtures / "html-native-scene.json"
    raw = _json(scene_path)
    scene = normalize_scene(parse_scene_deck(raw, fixtures, len(scene_path.read_bytes())))
    generated = tmp_path / "generated.pptx"
    manifest = emit_scene_pptx(generated, scene, _METADATA)
    expected = fixtures / "html-native.expected.pptx"

    assert generated.read_bytes() == expected.read_bytes()
    assert scene.slide_fills == ("rgb(244, 238, 222)", "rgb(244, 238, 222)")
    assert manifest["slides"] == 2
    assert manifest["objects"] == 6
    assert manifest["media"] == 1
    assert [item["source_id"] for item in manifest["items"]] == [
        "slide-1-back",
        "slide-1-front",
        "slide-1-title",
        "slide-1-image",
        "slide-2-shape",
        "slide-2-title",
    ]
    report = validate_scene_created(expected, scene, manifest)
    assert report["status"] == "pass"
    title = scene.slides[0][2]
    image = scene.slides[0][3]
    assert image["outcome"] == "native"
    assert (image["opacity"], image["border_width"], image["radius"]) == (0.5, 4, 20)
    assert [run["text"] for run in title["paragraphs"][0]["runs"]] == [
        "Native ",
        "editable",
        " deck",
    ]
    with zipfile.ZipFile(expected) as archive:
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
    background = slide.find(
        f"{{{NS['p']}}}cSld/{{{NS['p']}}}bg/{{{NS['p']}}}bgPr/"
        f"{{{NS['a']}}}solidFill/{{{NS['a']}}}srgbClr"
    )
    assert background is not None and background.get("val") == "F4EEDE"
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    text_nodes = list(slide.iter(f"{{{NS['a']}}}t"))
    assert [node.get(xml_space) for node in text_nodes[:3]] == ["preserve", None, "preserve"]
    picture = slide.find(f"{{{NS['p']}}}cSld/{{{NS['p']}}}spTree/{{{NS['p']}}}pic")
    assert picture is not None
    assert picture.find(
        f"{{{NS['p']}}}blipFill/{{{NS['a']}}}blip/{{{NS['a']}}}alphaModFix"
    ).get("amt") == "50000"
    assert picture.find(
        f"{{{NS['p']}}}spPr/{{{NS['a']}}}prstGeom"
    ).get("prst") == "roundRect"
    assert picture.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}ln").get("w") == "25400"


def test_fixture_manifest_hashes_every_original_elftia_html_artifact(project_root: Path):
    fixtures = project_root / "tests/fixtures"
    manifest = _json(fixtures / "manifest.json")
    records = [record for record in manifest["fixtures"] if record.get("recipe") == _RECIPE]

    assert len(records) == 8
    assert audit_fixtures(project_root)["fixture_count"] == len(manifest["fixtures"])
    for record in records:
        path = fixtures / record["path"]
        assert record["authorship"] == "original-elftia"
        assert record["origin"] == "generated"
        assert record["redistribution_allowed"] is True
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        assert b"cthulhu" not in path.read_bytes().lower()


def test_fallback_and_adversarial_fixture_matrix_is_explicit(project_root: Path):
    fixtures = project_root / "tests/fixtures"
    cases = _json(fixtures / "html-pptx-cases.expected.json")
    fallback = cases["fallback"]["cases"]
    assert set(fallback.values()) == {
        "css_box_shadow",
        "complex_pseudo_element",
        "css_background_image",
        "css_filter",
        "css_clip_path",
        "forced_element_raster",
        "semantic_flattening_guard",
        "font_substitution",
    }
    assert set(cases["adversarial"]["cases"]) == {
        "script-disabled",
        "service-worker-blocked",
        "remote-url-blocked",
        "custom-scheme-blocked",
        "file-url-blocked",
        "parent-traversal",
        "symlink-escape",
        "data-url-blocked",
        "asset-count-limit",
        "image-pixel-limit",
        "dom-node-limit",
        "text-byte-limit",
        "non-finite-geometry",
        "capture-timeout",
    }
    html = (fixtures / cases["adversarial"]["html"]).read_text(encoding="utf-8")
    assert "serviceWorker.register" in html
    assert "https://example.invalid" in html
    assert "file:///" in html
    assert "custom:payload" in html
    assert "../outside.png" in html
    assert "AAAAA===" in html


def test_real_browser_classifies_repository_fallback_fixture(
    project_root: Path,
):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    fixtures = project_root / "tests/fixtures"
    base = project_root / ".document-skills-tmp/document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        captured = HtmlDeckCapture(project_root, detector).capture(
            fixtures / "html-fallback-deck.html",
            private_root,
            "element-rasterize",
        )
        by_id = {
            item["source_id"]: item
            for slide in captured.slides
            for item in slide["items"]
        }
        assert by_id["box-shadow"]["reason"] == "css_box_shadow"
        assert by_id["gradient"]["reason"] == "css_background_image"
        assert by_id["filter"]["reason"] == "css_filter"
        assert by_id["clip"]["reason"] == "css_clip_path"
        assert by_id["forced"]["reason"] == "forced_element_raster"
        assert by_id["complex-pseudo"]["reason"] == "complex_pseudo_element"
        assert by_id["whole-slide"]["reason"] == "semantic_flattening_guard"
        assert by_id["missing-font"]["font_evidence"]["substitution"] is not None
        first_slide = SceneDeck(
            slides=(captured.slides[0],),
            assets=captured.assets,
            blocked_resources=captured.blocked_resources,
            observed=captured.observed,
            scene_bytes=captured.scene_bytes,
            visual_sources=(),
        )
        normalized = normalize_scene(first_slide)
        assert normalized.diagnostics["outcomes"] == {
            "native": 1,
            "rasterized": 6,
        }


def test_real_browser_keeps_uniform_styled_image_native(project_root: Path):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    fixtures = project_root / "tests/fixtures"
    base = project_root / ".document-skills-tmp/document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        captured = HtmlDeckCapture(project_root, detector).capture(
            fixtures / "html-native-deck.html",
            private_root,
            "element-rasterize",
        )
        image = next(
            item
            for slide in captured.slides
            for item in slide["items"]
            if item["source_id"] == "slide-1-image"
        )
        assert image["unsupported"] == []
        assert image["capture_outcome"] is None
        assert image["opacity"] == 0.5
        assert image["border_width"] == 4
        assert image["border_color"] == "rgb(10, 20, 30)"
        assert image["radius"] == 20


def test_real_browser_keeps_adversarial_fixture_static_and_blocks_resources(
    project_root: Path,
):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    fixtures = project_root / "tests/fixtures"
    base = project_root / ".document-skills-tmp/document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        captured = HtmlDeckCapture(project_root, detector).capture(
            fixtures / "html-adversarial-deck.html",
            private_root,
            "fail",
        )
        assert len(captured.slides) == 1
        assert all(
            item["source_id"] != "script-created"
            for item in captured.slides[0]["items"]
        )
        assert captured.blocked_resources["by_reason"] == {
            "custom_scheme_blocked": 1,
            "data_url_blocked": 1,
            "file_url_blocked": 1,
            "path_escape": 1,
            "remote_url_blocked": 1,
        }
        assert all(
            item["capture_outcome"] == "rejected"
            for item in captured.slides[0]["items"]
        )


def _generated_files(root: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in root.iterdir()
        if path.is_file()
    }


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value
