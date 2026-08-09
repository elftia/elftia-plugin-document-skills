"""Private HTML capture envelope trust-boundary tests."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.process import ProcessResult
from document_skills_core.formats.pptx.html_capture import HtmlDeckCapture, _capture_status
from document_skills_core.formats.pptx.scene_normalizer import normalize_scene
from document_skills_core.providers.html_browser import HtmlBrowserDetector


LIMITS = {
    "slides": 100,
    "dom_nodes": 20_000,
    "paint_items": 8_000,
    "text_bytes": 4 * 1024 * 1024,
    "image_bytes": 8 * 1024 * 1024,
    "image_pixels": 40_000_000,
    "images": 512,
    "assets": 512,
    "total_asset_bytes": 32 * 1024 * 1024,
    "resource_requests": 512,
    "scene_bytes": 32 * 1024 * 1024,
    "capture_bytes": 32 * 1024 * 1024,
}
STYLE = {
    "font_family": "Arial",
    "font_size": 32,
    "font_weight": "400",
    "font_style": "normal",
    "text_decoration": "none",
    "color": "rgb(0, 0, 0)",
    "text_align": "left",
    "line_height": "normal",
}


class AcceptedDetector:
    def __init__(self, browser: Path) -> None:
        self.browser = browser

    def require_browser_path(self) -> Path:
        return self.browser


class SceneFileRunner:
    def __init__(self, *, asset_bytes_delta: int = 0) -> None:
        self.request: dict[str, object] | None = None
        self.stdout_bytes = 0
        self.asset_bytes_delta = asset_bytes_delta
        self.limits: tuple[float, int] | None = None

    def run(self, _provider, _executable, _args, **kwargs) -> ProcessResult:
        request = kwargs["stdin_json"]
        self.request = request
        self.limits = (kwargs["timeout_seconds"], kwargs["output_limit"])
        Path(request["assets_dir"]).mkdir()
        scene = _scene("editable " * 2_500)
        for _attempt in range(8):
            encoded = f"{json.dumps(scene, separators=(',', ':'))}\n".encode()
            if scene["observed"]["capture_bytes"] == len(encoded):
                break
            scene["observed"]["capture_bytes"] = len(encoded)
        encoded = f"{json.dumps(scene, separators=(',', ':'))}\n".encode()
        Path(request["scene_path"]).write_bytes(encoded)
        status = {
            "protocol_version": "1.0",
            "command": "capture",
            "nonce": request["nonce"],
            "ok": True,
            "scene_bytes": len(encoded),
            "asset_bytes": scene["observed"]["asset_bytes"] + self.asset_bytes_delta,
            "reason": None,
        }
        stdout = json.dumps(status, separators=(",", ":"))
        self.stdout_bytes = len(stdout.encode())
        return ProcessResult(0, stdout, "", 1)


def _scene(text: str) -> dict[str, object]:
    item = {
        "source_id": "title",
        "parent_source_id": None,
        "dom_ancestor_ids": [],
        "dom_index": 0,
        "z_index": 0,
        "paint_order": 0,
        "kind": "text",
        "x": 10,
        "y": 20,
        "width": 300,
        "height": 100,
        "rotation": 0,
        "opacity": 1,
        "fill": "rgba(0, 0, 0, 0)",
        "border_color": "rgb(0, 0, 0)",
        "border_width": 0,
        "radius": 0,
        "text": text,
        "text_style": STYLE,
        "paragraphs": [{
            "runs": [{"text": text, "style": STYLE}],
            "alignment": "left",
            "line_height": "normal",
        }],
        "requested_font": "Arial",
        "font_evidence": {
            "requested_families": ["Arial"],
            "computed_family": "Arial",
            "platform_fonts": [{
                "family": "Arial",
                "postscript": "ArialMT",
                "custom": False,
                "glyphs": len(text),
            }],
            "substitution": None,
            "truncated": False,
        },
        "pseudo": [],
        "image_src": None,
        "image_width": None,
        "image_height": None,
        "object_fit": "fill",
        "object_position": "50% 50%",
        "image_crop": None,
        "force_raster": False,
        "ignored": False,
        "unknown_hints": [],
        "unsupported": [],
        "approximations": [],
        "editable_descendants": 0,
        "capture_outcome": None,
        "reason": None,
        "asset_id": None,
    }
    text_bytes = len(text.encode())
    return {
        "version": 1,
        "canvas": {"width": 1920, "height": 1080},
        "limits": LIMITS,
        "observed": {
            "slides": 1,
            "dom_nodes": 2,
            "paint_items": 1,
            "text_bytes": text_bytes,
            "asset_bytes": 0,
            "total_asset_bytes": 0,
            "resource_requests": 0,
            "images": 0,
            "assets": 0,
            "capture_bytes": 0,
        },
        "blocked_resources": {"total": 0, "by_reason": {}, "samples": [], "truncated": 0},
        "visual_sources": [],
        "slides": [{
            "index": 1,
            "width": 1920,
            "height": 1080,
            "x": 0,
            "y": 0,
            "root_fill": "rgb(255, 255, 255)",
            "root_unsupported": [],
            "items": [item],
        }],
        "assets": [],
    }


def _capture_fixture(tmp_path: Path, runner: SceneFileRunner):
    project = tmp_path / "project"
    script = project / "runtime" / "node" / "html_capture.mjs"
    script.parent.mkdir(parents=True)
    script.write_text("// fixture", encoding="utf-8")
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"browser")
    source = tmp_path / "deck.html"
    source.write_text("<section class='slide'></section>", encoding="utf-8")
    private_root = project / "document-skills-operations" / "operation-test"
    private_root.mkdir(parents=True)
    capture = HtmlDeckCapture(project, AcceptedDetector(browser), runner=runner)
    return capture, source, private_root


def test_capture_moves_large_scene_through_nonce_bound_private_file(tmp_path: Path):
    runner = SceneFileRunner()
    capture, source, private_root = _capture_fixture(tmp_path, runner)

    deck = capture.capture(source, private_root, "element-rasterize")

    assert deck.scene_bytes > 16_384
    assert runner.stdout_bytes < 1_024
    assert runner.limits == (45.0, 16_384)
    assert runner.request is not None
    assert set(runner.request) == {
        "protocol_version", "command", "nonce", "token", "html_path",
        "private_root", "scene_path", "assets_dir", "profile_root",
        "browser_executable", "fallback_policy",
        "capture_visuals",
    }
    assert "editable" not in json.dumps(runner.request)
    assert Path(str(runner.request["scene_path"])).parent == private_root.resolve()
    assert source.read_text(encoding="utf-8") == "<section class='slide'></section>"


def test_capture_rejects_status_asset_total_that_disagrees_with_private_scene(tmp_path: Path):
    runner = SceneFileRunner(asset_bytes_delta=1)
    capture, source, private_root = _capture_fixture(tmp_path, runner)

    with pytest.raises(DocumentSkillsError, match="asset byte binding"):
        capture.capture(source, private_root, "element-rasterize")


@pytest.mark.parametrize("size", [0, 8 * 1024 * 1024 + 1])
def test_capture_rejects_empty_or_oversized_html_before_provider_execution(tmp_path: Path, size: int):
    runner = SceneFileRunner()
    capture, source, private_root = _capture_fixture(tmp_path, runner)
    source.write_bytes(b"x" * size)

    with pytest.raises(DocumentSkillsError):
        capture.capture(source, private_root, "element-rasterize")

    assert runner.request is None


@pytest.mark.parametrize(
    "change",
    [
        {"ok": True, "scene_bytes": 0},
        {"ok": True, "reason": "capture_failed"},
        {"ok": False, "scene_bytes": 1, "reason": "capture_failed"},
        {"ok": False, "reason": None},
        {"ok": False, "reason": "not a stable reason"},
    ],
)
def test_capture_status_binds_success_failure_fields(change: dict[str, object]):
    nonce = "a" * 64
    status = {
        "protocol_version": "1.0",
        "command": "capture",
        "nonce": nonce,
        "ok": True,
        "scene_bytes": 1,
        "asset_bytes": 0,
        "reason": None,
    }
    status.update(change)

    with pytest.raises(DocumentSkillsError):
        _capture_status(status, nonce)


def test_real_capture_uses_fixed_canvas_transform_pseudo_and_browser_paint_evidence(
    project_root: Path,
    tmp_path: Path,
):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    source = tmp_path / "scene.html"
    source.write_text(
        """<!doctype html><meta charset="utf-8"><style>
        *{box-sizing:border-box}html,body{margin:0}.slide{position:relative;width:1920px;height:1080px}
        .item{position:absolute;background:rgb(10,20,30)}
        #rotated{left:100px;top:100px;width:200px;height:100px;transform:rotate(30deg)}
        #back{left:400px;top:100px;width:100px;height:100px;z-index:1}
        #front{left:420px;top:120px;width:100px;height:100px;z-index:10}
        #simple{left:600px;top:100px;width:100px;height:100px}
        #simple::before{content:'S';position:absolute;left:10px;top:12px;color:rgb(1,2,3);font:20px Arial}
        #complex{left:800px;top:100px;width:100px;height:100px}
        #complex::after{content:'C';background-image:linear-gradient(red,blue)}
        #mixed{left:100px;top:300px;width:600px;height:180px;background:transparent;
          font:32px/1.4 Arial;text-align:center;color:rgb(10,20,30)}
        #missingfont{position:absolute;left:800px;top:300px;width:500px;height:100px;
          font:32px 'Definitely Missing Font',Arial}
        </style><section class="slide">
        <div id="rotated" class="item" data-pptx-id="rotated"></div>
        <div id="front" class="item" data-pptx-id="front"></div>
        <div id="back" class="item" data-pptx-id="back"></div>
        <div id="simple" class="item" data-pptx-id="simple"></div>
        <div id="complex" class="item" data-pptx-id="complex"></div>
        <div id="mixed" data-pptx-id="mixed">Alpha <span style="font-weight:700;color:rgb(200,10,20)">Bold</span><br>
          <span style="font-style:italic;text-decoration:underline">Italic</span></div>
        <div id="missingfont" data-pptx-id="missingfont" data-pptx-role="triangle"
          data-pptx-raster="sometimes" data-pptx-ignore="maybe" data-pptx-xml="forbidden">
          Missing font fallback</div>
        </section>""",
        encoding="utf-8",
    )
    base = project_root / ".document-skills-tmp" / "document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        deck = HtmlDeckCapture(project_root, detector).capture(source, private_root, "fail")
        operation_path = private_root

    items = list(deck.slides[0]["items"])
    by_id = {item["source_id"]: item for item in items}
    rotated = by_id["rotated"]
    assert rotated["x"] == pytest.approx(100, abs=0.05)
    assert rotated["y"] == pytest.approx(100, abs=0.05)
    assert rotated["width"] == pytest.approx(200, abs=0.05)
    assert rotated["height"] == pytest.approx(100, abs=0.05)
    assert rotated["rotation"] == pytest.approx(30, abs=0.05)
    assert [item["paint_order"] for item in items] == sorted(item["paint_order"] for item in items)
    assert next(index for index, item in enumerate(items) if item["source_id"] == "front") > next(
        index for index, item in enumerate(items) if item["source_id"] == "back"
    )
    assert by_id["simple"]["pseudo"][0]["simple"] is True
    assert by_id["simple"]["pseudo"][0]["source_id"] == "simple:before"
    assert by_id["complex"]["pseudo"][0]["simple"] is False
    assert "complex_pseudo_element" in by_id["complex"]["unsupported"]
    mixed = by_id["mixed"]
    assert mixed["text"] == "Alpha Bold\nItalic"
    assert [[run["text"] for run in paragraph["runs"]] for paragraph in mixed["paragraphs"]] == [
        ["Alpha ", "Bold"],
        ["Italic"],
    ]
    assert mixed["paragraphs"][0]["runs"][1]["style"]["font_weight"] == "700"
    assert mixed["paragraphs"][0]["runs"][1]["style"]["color"] == "rgb(200, 10, 20)"
    assert mixed["paragraphs"][1]["runs"][0]["style"]["font_style"] == "italic"
    assert "underline" in mixed["paragraphs"][1]["runs"][0]["style"]["text_decoration"]
    assert mixed["text_style"]["text_align"] == "center"
    assert mixed["text_style"]["line_height"] == "44.8px"
    assert set(mixed["font_evidence"]) == {
        "requested_families", "computed_family", "platform_fonts", "substitution", "truncated",
    }
    assert sum(font["glyphs"] for font in mixed["font_evidence"]["platform_fonts"]) >= len("AlphaBoldItalic")
    missing_font = by_id["missingfont"]["font_evidence"]
    assert missing_font["requested_families"][0] == "Definitely Missing Font"
    assert missing_font["platform_fonts"]
    assert missing_font["substitution"]["requested"] == "Definitely Missing Font"
    assert missing_font["substitution"]["actual"] in {
        font["family"] for font in missing_font["platform_fonts"]
    }
    assert set(by_id["missingfont"]["unknown_hints"]) == {
        "data-pptx-role:invalid-value",
        "data-pptx-raster:invalid-value",
        "data-pptx-ignore:invalid-value",
        "data-pptx-xml",
    }
    assert not operation_path.exists()

    wrong_size = tmp_path / "wrong-size.html"
    wrong_size.write_text(
        "<style>.slide{width:100px;height:100px}</style><section class='slide'></section>",
        encoding="utf-8",
    )
    with OperationTempRoot(base=base) as private_root:
        with pytest.raises(DocumentSkillsError):
            HtmlDeckCapture(project_root, detector).capture(wrong_size, private_root, "fail")


def test_real_capture_binds_transparent_wrappers_and_positioned_pseudo_geometry(
    project_root: Path,
    tmp_path: Path,
):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    image = base64.b64encode(
        (project_root / "tests/fixtures/html-native-image.png").read_bytes()
    ).decode()
    source = tmp_path / "nested.html"
    source.write_text(
        f"""<!doctype html><meta charset="utf-8"><style>
        *{{box-sizing:border-box}}html,body{{margin:0}}.slide{{position:relative;width:1920px;height:1080px}}
        .outer{{position:absolute;left:40px;top:50px;width:900px;height:500px}}
        .inner{{position:relative;width:100%;height:100%}}
        .shape{{position:absolute;left:20px;top:30px;width:180px;height:90px;background:rgb(10,20,30)}}
        .text{{position:absolute;left:220px;top:30px;width:260px;height:90px;font:28px Arial}}
        img{{position:absolute;left:500px;top:30px;width:120px;height:80px}}
        .card{{position:absolute;left:100px;top:600px;width:500px;height:300px;background:white;font:24px Arial}}
        .card::before{{content:'BEFORE';position:absolute;left:20px;top:30px;width:100px;height:30px;font:20px Arial}}
        .card::after{{content:'AFTER';position:absolute;right:10px;bottom:10px;width:90px;height:25px;font:18px Arial}}
        .asym{{position:absolute;left:900px;top:600px;width:300px;height:200px;background:white;
          border-top:2px solid red;border-right:20px dashed blue;border-radius:5px 40px 60px 10px}}
        </style><section class="slide"><div class="outer"><div class="inner">
        <div class="shape" data-pptx-id="nested-shape"></div>
        <div class="text" data-pptx-id="nested-text">Editable</div>
        <img data-pptx-id="nested-image" src="data:image/png;base64,{image}">
        </div></div><div class="card" data-pptx-id="card">Body</div>
        <div class="asym" data-pptx-id="asym-shape"></div></section>""",
        encoding="utf-8",
    )
    base = project_root / ".document-skills-tmp/document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        deck = HtmlDeckCapture(project_root, detector).capture(
            source, private_root, "element-rasterize"
        )
    by_id = {item["source_id"]: item for item in deck.slides[0]["items"]}
    for source_id in ("nested-shape", "nested-text", "nested-image"):
        assert by_id[source_id]["parent_source_id"] is None
        assert len(by_id[source_id]["dom_ancestor_ids"]) == 2
    before, after = by_id["card"]["pseudo"]
    assert (before["simple"], before["x"], before["y"], before["width"], before["height"]) == (
        True, 120, 630, 100, 30,
    )
    assert (after["simple"], after["x"], after["y"], after["width"], after["height"]) == (
        True, 500, 865, 90, 25,
    )
    assert before["paint_order"] < by_id["card"]["paint_order"] + 2 < after["paint_order"]
    assert by_id["asym-shape"]["unsupported"] == [
        "shape_border_unsupported", "shape_radius_unsupported",
    ]
    assert by_id["asym-shape"]["capture_outcome"] == "rasterized"
    assert by_id["asym-shape"]["reason"] == "shape_border_unsupported"
    normalized = normalize_scene(deck)
    assert normalized.diagnostics["unsupported_css"]["by_reason"] == {
        "shape_border_unsupported": 1,
        "shape_radius_unsupported": 1,
    }


@pytest.mark.parametrize(
    ("reference", "reason"),
    [
        ("https://example.invalid/one.css", "remote_url_blocked"),
        ("file:///private.css", "file_url_blocked"),
        ("custom:payload", "custom_scheme_blocked"),
        ("../outside.css", "path_escape"),
    ],
)
def test_real_capture_reports_each_forbidden_resource_reason(
    project_root: Path,
    tmp_path: Path,
    reference: str,
    reason: str,
):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    source = tmp_path / "resource.html"
    source.write_text(
        "<!doctype html><link rel='stylesheet' href='"
        + reference
        + "'><style>html,body{margin:0}.slide{width:1920px;height:1080px}</style>"
        + "<section class='slide'></section>",
        encoding="utf-8",
    )
    base = project_root / ".document-skills-tmp/document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        deck = HtmlDeckCapture(project_root, detector).capture(source, private_root, "fail")
    assert deck.blocked_resources["total"] == 1
    assert deck.blocked_resources["by_reason"] == {reason: 1}
    assert deck.blocked_resources["samples"][0]["reason"] == reason
    assert len(deck.blocked_resources["samples"][0]["resource_hash"]) == 64
    assert deck.blocked_resources["truncated"] == 0


def test_real_capture_counts_resource_occurrences_beyond_sample_limit(
    project_root: Path,
    tmp_path: Path,
):
    detector = HtmlBrowserDetector(project_root)
    evidence = detector.detect()
    if not evidence.available:
        pytest.skip(evidence.reason)
    links = "".join(
        f"<link rel='stylesheet' href='https://example.invalid/{index}.css'>"
        for index in range(40)
    )
    source = tmp_path / "many-resources.html"
    source.write_text(
        "<!doctype html>" + links
        + "<style>html,body{margin:0}.slide{width:1920px;height:1080px}</style>"
        + "<section class='slide'></section>",
        encoding="utf-8",
    )
    base = project_root / ".document-skills-tmp/document-skills-operations"
    with OperationTempRoot(base=base) as private_root:
        deck = HtmlDeckCapture(project_root, detector).capture(source, private_root, "fail")
    assert deck.blocked_resources["total"] == 40
    assert deck.blocked_resources["by_reason"] == {"remote_url_blocked": 40}
    assert len(deck.blocked_resources["samples"]) == 32
    assert deck.blocked_resources["truncated"] == 8
