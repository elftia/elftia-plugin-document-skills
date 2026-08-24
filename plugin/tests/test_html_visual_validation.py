"""Optional LibreOffice visual comparison for HTML-scene PPTX output."""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import zlib

from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.scene_normalizer import NormalizedScene
from document_skills_core.formats.pptx.visual_validation import validate_scene_visuals


def test_visual_validation_passes_only_after_thresholded_pixel_comparison(tmp_path: Path):
    source = _png(8, 8, (20, 80, 160, 255))
    candidate, scene = _candidate(tmp_path, source)
    provider = _FakeLibreOffice(source)

    gate = validate_scene_visuals(candidate, scene, provider, tmp_path / "visual")

    assert gate["outcome"] == "pass"
    assert gate["required"] is False
    assert gate["validator"] == "libreoffice"
    assert gate["evidence"]["slides_compared"] == 1
    assert gate["evidence"]["thresholds"] == {
        "mean_absolute_error_max": 0.08,
        "changed_pixel_ratio_max": 0.2,
        "changed_pixel_delta": 0.12,
        "aspect_ratio_delta_max": 0.01,
        "sample_grid": {"width": 96, "height": 54},
        "region_grid": {"columns": 12, "rows": 6},
        "max_region_differences": 24,
    }


def test_visual_validation_reports_threshold_failure_as_optional_fail(tmp_path: Path):
    source = _png(8, 8, (255, 255, 255, 255))
    rendered = _png(8, 8, (0, 0, 0, 255))
    candidate, scene = _candidate(tmp_path, source)

    gate = validate_scene_visuals(
        candidate,
        scene,
        _FakeLibreOffice(rendered),
        tmp_path / "visual",
    )

    assert gate["outcome"] == "fail"
    assert gate["required"] is False
    comparison = gate["evidence"]["comparisons"][0]
    assert comparison["mean_absolute_error"] == 1.0
    assert comparison["changed_pixel_ratio"] == 1.0
    assert len(comparison["region_differences"]) == 24
    assert comparison["region_differences_truncated"] == 48
    assert comparison["region_differences"][0]["source_bbox"] == {
        "x": 0,
        "y": 0,
        "width": 1,
        "height": 1,
    }
    assert comparison["within_thresholds"] is False


def test_visual_validation_reports_font_and_fallback_context_without_exemption(
    tmp_path: Path,
):
    source = _png(8, 8, (20, 80, 160, 255))
    candidate, scene = _candidate(tmp_path, source)
    scene.diagnostics.update({
        "font_evidence": {
            "substitutions": 1,
            "samples": [{
                "source_id": "title",
                "substitution": {"requested": "Missing", "actual": "Arial"},
            }],
        },
        "fidelity": {
            "rasterized": {
                "count": 1,
                "area": 400,
                "samples": [{
                    "source_id": "filtered",
                    "element_selector": '[data-elftia-source-id="filtered"]',
                    "reason": "css_filter",
                    "area": 400,
                    "bbox": {"x": 10, "y": 20, "width": 20, "height": 20},
                    "asset_sha256": "a" * 64,
                }],
                "truncated": 0,
            },
        },
    })

    gate = validate_scene_visuals(candidate, scene, _FakeLibreOffice(source), tmp_path / "visual")

    context = gate["evidence"]["context"]
    assert context["font_substitutions"] == 1
    assert context["fallback_elements"] == 1
    assert context["fallback_samples"][0]["reason"] == "css_filter"
    assert gate["evidence"]["exemptions"] == []


def test_visual_validation_reports_absent_provider_as_unavailable(tmp_path: Path):
    source = _png(8, 8, (20, 80, 160, 255))
    candidate, scene = _candidate(tmp_path, source)

    gate = validate_scene_visuals(candidate, scene, None, tmp_path / "visual")

    assert gate["outcome"] == "unavailable"
    assert gate["required"] is False
    assert "unavailable" in gate["evidence"]["reason"].casefold()


def test_visual_validation_reports_renderer_failure_without_false_pass(tmp_path: Path):
    source = _png(8, 8, (20, 80, 160, 255))
    candidate, scene = _candidate(tmp_path, source)

    gate = validate_scene_visuals(
        candidate,
        scene,
        _FakeLibreOffice(None),
        tmp_path / "visual",
    )

    assert gate["outcome"] == "fail"
    assert gate["required"] is False
    assert gate["evidence"]["reason"] == "libreoffice-render-failed"


class _FakeLibreOffice:
    def __init__(self, rendered: bytes | None) -> None:
        self.rendered = rendered
        self.inputs: list[Path] = []

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            True,
            path="/accepted/soffice",
            version="25.2.0",
        )

    def try_render_to_image(self, input_path: Path) -> bytes | None:
        self.inputs.append(input_path)
        return self.rendered


def _candidate(tmp_path: Path, source_png: bytes) -> tuple[Path, NormalizedScene]:
    digest = hashlib.sha256(source_png).hexdigest()
    source = tmp_path / f"asset-{digest}.png"
    source.write_bytes(source_png)
    item = {
        "source_id": "visual-item",
        "kind": "rectangle",
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 50,
        "rotation": 0,
        "opacity": 1,
        "fill": "rgb(20, 80, 160)",
        "border_color": "rgb(0, 0, 0)",
        "border_width": 0,
        "radius": 0,
        "text": "",
        "paragraphs": [],
        "outcome": "native",
        "asset_id": None,
    }
    scene = NormalizedScene(
        slides=((item,),),
        assets={
            digest: {
                "id": digest,
                "path": source,
                "purpose": "visual-source",
            }
        },
        diagnostics={},
        visual_sources=({"slide": 1, "asset_id": digest},),
    )
    candidate = tmp_path / "candidate.pptx"
    emit_scene_pptx(candidate, scene, {})
    return candidate, scene


def _png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))
    return signature + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b"")


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
