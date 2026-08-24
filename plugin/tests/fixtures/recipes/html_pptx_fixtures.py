"""Generate deterministic original Elftia HTML-to-PPTX acceptance fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from document_skills_core.formats.pptx.scene import SCENE_LIMITS, parse_scene_deck
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.scene_normalizer import normalize_scene

RECIPE = "tests/fixtures/recipes/html_pptx_fixtures.py"


def generate(output: Path) -> list[dict[str, object]]:
    output.mkdir(parents=True, exist_ok=True)
    local_image = output / "html-native-image.png"
    local_image.write_bytes(_checker_png(16, 16))
    digest = hashlib.sha256(local_image.read_bytes()).hexdigest()
    scene_asset = output / f"asset-{digest}.png"
    scene_asset.write_bytes(local_image.read_bytes())

    native_html = output / "html-native-deck.html"
    native_html.write_text(_native_html(), encoding="utf-8", newline="\n")
    fallback_html = output / "html-fallback-deck.html"
    fallback_html.write_text(_fallback_html(), encoding="utf-8", newline="\n")
    adversarial_html = output / "html-adversarial-deck.html"
    adversarial_html.write_text(_adversarial_html(), encoding="utf-8", newline="\n")

    raw_scene = _native_scene(digest, scene_asset.name, len(scene_asset.read_bytes()))
    scene_path = output / "html-native-scene.json"
    scene_bytes = _bound_scene_bytes(raw_scene)
    scene_path.write_bytes(scene_bytes)
    scene = parse_scene_deck(raw_scene, output, len(scene_bytes))
    normalized = normalize_scene(scene)
    expected_pptx = output / "html-native.expected.pptx"
    manifest = emit_scene_pptx(
        expected_pptx,
        normalized,
        {"title": "Repository-authored HTML fixture", "creator": "Elftia", "subject": ""},
    )
    cases_path = output / "html-pptx-cases.expected.json"
    _write_json(
        cases_path,
        {
            "schema_version": "1.0",
            "native": {
                "html": native_html.name,
                "scene": scene_path.name,
                "pptx": expected_pptx.name,
                "slides": 2,
                "objects": manifest["objects"],
                "media": manifest["media"],
                "paint_order_source_ids": [
                    [item["source_id"] for item in raw_scene["slides"][0]["items"]],
                    [item["source_id"] for item in raw_scene["slides"][1]["items"]],
                ],
            },
            "fallback": {
                "html": fallback_html.name,
                "cases": {
                    "box-shadow": "css_box_shadow",
                    "complex-pseudo": "complex_pseudo_element",
                    "gradient": "css_background_image",
                    "filter": "css_filter",
                    "clip": "css_clip_path",
                    "forced": "forced_element_raster",
                    "whole-slide": "semantic_flattening_guard",
                    "missing-font": "font_substitution",
                },
            },
            "adversarial": {
                "html": adversarial_html.name,
                "cases": [
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
                ],
                "limits": SCENE_LIMITS,
            },
        },
    )
    purposes = {
        native_html.name: ("Native fixed-canvas HTML deck with mixed runs, two slides, paint order, and local image", "benign"),
        local_image.name: ("Repository-authored local image referenced by the native HTML deck", "benign"),
        scene_asset.name: ("Hash-bound private-scene image used to deterministically emit the expected PPTX", "benign"),
        scene_path.name: ("Deterministic private-scene oracle for native HTML conversion", "oracle"),
        expected_pptx.name: ("Deterministic direct-OOXML output oracle for the native scene", "oracle"),
        fallback_html.name: ("Editable approximation, element fallback, pseudo, hint, guard, and font fixture", "benign-fallback"),
        adversarial_html.name: ("Static hostile-resource and disabled-script HTML fixture", "adversarial"),
        cases_path.name: ("HTML-to-PPTX native, fallback, adversarial, and limit oracle matrix", "oracle"),
    }
    return [
        _record(output / name, purpose, classification)
        for name, (purpose, classification) in purposes.items()
    ]


def _native_html() -> str:
    return """<!doctype html>
<meta charset="utf-8">
<style>
*{box-sizing:border-box}html,body{margin:0}.slide{position:relative;width:1920px;height:1080px;overflow:hidden;background:#f4eede}
.title{position:absolute;left:120px;top:90px;width:1200px;height:120px;margin:0;font:64px/1.2 Arial;color:#142850}
.back{position:absolute;left:120px;top:280px;width:560px;height:360px;background:#d9e9ff}
.front{position:absolute;left:400px;top:420px;width:560px;height:360px;background:#2058a8;border:4px solid #142850;border-radius:24px}
.photo{position:absolute;left:1120px;top:260px;width:320px;height:320px;object-fit:cover;opacity:.5;border:4px solid #0a141e;border-radius:20px}
</style>
<section class="slide">
  <h1 class="title" data-pptx-id="slide-1-title">Native <span style="font-weight:700;color:#d64b32">editable</span> deck</h1>
  <div class="back" data-pptx-id="slide-1-back"></div>
  <div class="front" data-pptx-id="slide-1-front"></div>
  <img class="photo" data-pptx-id="slide-1-image" src="html-native-image.png" alt="fixture">
</section>
<section class="slide">
  <h1 class="title" data-pptx-id="slide-2-title">Second slide<br><span style="font-style:italic">mixed run</span></h1>
  <div class="front" data-pptx-id="slide-2-shape"></div>
</section>
"""


def _fallback_html() -> str:
    return """<!doctype html>
<meta charset="utf-8">
<style>
*{box-sizing:border-box}html,body{margin:0}.slide{position:relative;width:1920px;height:1080px;background:#fff}
.item{position:absolute;width:240px;height:160px}.shadow{left:80px;top:80px;background:#def;box-shadow:12px 12px 24px #345}
.gradient{left:360px;top:80px;background-image:linear-gradient(45deg,#125,#8cf)}
.filter{left:640px;top:80px;background:#acf;filter:blur(3px)}.clip{left:920px;top:80px;background:#fac;clip-path:polygon(50% 0,100% 100%,0 100%)}
.forced{left:1200px;top:80px;background:#cfc}.pseudo{left:1480px;top:80px;background:#eee}.pseudo::before{content:'complex';background-image:linear-gradient(red,blue)}
.missing{left:80px;top:360px;width:700px;font:48px 'Definitely Missing Fixture Font',Arial}
.flatten{left:10px;top:10px;width:1900px;height:1000px;background:#fff}
</style>
<section class="slide">
  <div class="item shadow" data-pptx-id="box-shadow"></div>
  <div class="item gradient" data-pptx-id="gradient"></div>
  <div class="item filter" data-pptx-id="filter"></div>
  <div class="item clip" data-pptx-id="clip"></div>
  <div class="item forced" data-pptx-id="forced" data-pptx-raster="true"></div>
  <div class="item pseudo" data-pptx-id="complex-pseudo"></div>
  <div class="missing" data-pptx-id="missing-font">Font substitution evidence</div>
</section>
<section class="slide"><div class="flatten" data-pptx-id="whole-slide" data-pptx-raster="true"><p>Editable descendant</p></div></section>
"""


def _adversarial_html() -> str:
    return """<!doctype html>
<meta charset="utf-8">
<style>*{box-sizing:border-box}html,body{margin:0}.slide{position:relative;width:1920px;height:1080px}img{display:block;width:100px;height:100px}</style>
<script>
navigator.serviceWorker.register('worker.js');
document.write('<section class="slide" data-pptx-id="script-created"></section>');
</script>
<section class="slide">
  <img src="https://example.invalid/remote.png" alt="remote">
  <img src="file:///private.png" alt="file">
  <img src="custom:payload" alt="custom">
  <img src="../outside.png" alt="parent">
  <img src="data:image/png;base64,AAAAA===" alt="malformed">
</section>
"""


def _native_scene(digest: str, filename: str, asset_bytes: int) -> dict[str, object]:
    title = _item("slide-1-title", "text", 120, 90, 1200, 120, text="Native editable deck")
    title["paragraphs"] = [{
        "runs": [
            {"text": "Native ", "style": _style()},
            {"text": "editable", "style": _style(font_weight="700", color="rgb(214, 75, 50)")},
            {"text": " deck", "style": _style()},
        ],
        "alignment": "left",
        "line_height": "76.8px",
    }]
    back = _item("slide-1-back", "rectangle", 120, 280, 560, 360)
    front = _item("slide-1-front", "rounded-rectangle", 400, 420, 560, 360)
    front.update(radius=24, border_width=4, fill="rgb(32, 88, 168)")
    image = _item("slide-1-image", "image", 1120, 260, 320, 320)
    image.update(
        asset_id=digest,
        image_width=16,
        image_height=16,
        object_fit="cover",
        opacity=0.5,
        border_width=4,
        border_color="rgb(10, 20, 30)",
        radius=20,
    )
    second_title = _item("slide-2-title", "text", 120, 90, 1200, 220, text="Second slide\nmixed run")
    second_title["paragraphs"] = [
        {"runs": [{"text": "Second slide", "style": _style()}], "alignment": "left", "line_height": "76.8px"},
        {"runs": [{"text": "mixed run", "style": _style(font_style="italic")}], "alignment": "left", "line_height": "76.8px"},
    ]
    second_shape = _item("slide-2-shape", "ellipse", 400, 420, 560, 360)
    slides = [
        _slide(1, [back, front, title, image]),
        _slide(2, [second_shape, second_title]),
    ]
    for slide in slides:
        for paint_order, item in enumerate(slide["items"], 1):
            item["paint_order"] = paint_order
            item["dom_index"] = paint_order - 1
    text_bytes = sum(
        len(item["text"].encode("utf-8"))
        for slide in slides
        for item in slide["items"]
    )
    return {
        "version": 1,
        "canvas": {"width": 1920, "height": 1080},
        "limits": SCENE_LIMITS,
        "observed": {
            "slides": 2,
            "dom_nodes": 8,
            "paint_items": 6,
            "text_bytes": text_bytes,
            "asset_bytes": asset_bytes,
            "total_asset_bytes": asset_bytes,
            "resource_requests": 0,
            "images": 1,
            "assets": 1,
            "capture_bytes": 0,
        },
        "blocked_resources": {"total": 0, "by_reason": {}, "samples": [], "truncated": 0},
        "visual_sources": [],
        "slides": slides,
        "assets": [{
            "id": digest,
            "filename": filename,
            "mime": "image/png",
            "bytes": asset_bytes,
            "width": 16,
            "height": 16,
            "purpose": "source-image",
        }],
    }


def _item(
    source_id: str,
    kind: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    text: str = "",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "parent_source_id": None,
        "dom_ancestor_ids": [],
        "dom_index": 0,
        "z_index": 0,
        "paint_order": 0,
        "kind": kind,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "rotation": 0,
        "opacity": 1,
        "fill": "rgb(217, 233, 255)",
        "border_color": "rgb(20, 40, 80)",
        "border_width": 0,
        "radius": 0,
        "text": text,
        "text_style": _style(),
        "text_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "paragraphs": ([{"runs": [{"text": text, "style": _style()}], "alignment": "left", "line_height": "normal"}] if text else []),
        "requested_font": "Arial",
        "font_evidence": {
            "requested_families": ["Arial"],
            "computed_family": "Arial",
            "platform_fonts": [{"family": "Arial", "postscript": "ArialMT", "custom": False, "glyphs": len(text)}],
            "substitution": None,
            "truncated": False,
        },
        "pseudo": [],
        "image_src": None,
        "image_width": None,
        "image_height": None,
        "object_fit": "fill",
        "object_position": "50% 50%",
        "image_crop": ({"left": 0, "top": 0, "right": 0, "bottom": 0} if kind == "image" else None),
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


def _style(**overrides: object) -> dict[str, object]:
    return {
        "font_family": "Arial",
        "font_size": 64,
        "font_weight": "400",
        "font_style": "normal",
        "text_decoration": "none",
        "color": "rgb(20, 40, 80)",
        "text_align": "left",
        "line_height": "76.8px",
        "letter_spacing": "normal",
        **overrides,
    }


def _slide(index: int, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "index": index,
        "width": 1920,
        "height": 1080,
        "x": 0,
        "y": 0,
        "root_fill": "rgb(244, 238, 222)",
        "root_unsupported": [],
        "items": items,
    }


def _bound_scene_bytes(scene: dict[str, object]) -> bytes:
    observed = scene["observed"]
    for _attempt in range(8):
        payload = _json_bytes(scene)
        total = len(payload) + observed["asset_bytes"]
        if observed["capture_bytes"] == total:
            return payload
        observed["capture_bytes"] = total
    raise RuntimeError("Scene capture byte binding did not converge.")


def _checker_png(width: int, height: int) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend((32, 96, 192, 255) if (x + y) % 2 else (240, 180, 40, 255))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _chunk(b"IEND", b"")


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_json_bytes(value))


def _record(path: Path, purpose: str, classification: str) -> dict[str, object]:
    return {
        "path": path.name,
        "format": path.suffix.lstrip("."),
        "purpose": purpose,
        "origin": "generated",
        "authorship": "original-elftia",
        "recipe": RECIPE,
        "recipe_dependencies": [],
        "license": "GPL-3.0",
        "redistribution_allowed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "security_classification": classification,
    }


def _load_retained_records(output: Path) -> list[dict[str, object]]:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        record
        for record in manifest.get("fixtures", [])
        if type(record) is dict and record.get("recipe") != RECIPE
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    retained = _load_retained_records(output)
    records = generate(output)
    _write_json(
        output / "manifest.json",
        {"schema_version": "1.0", "fixtures": [*retained, *records]},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
