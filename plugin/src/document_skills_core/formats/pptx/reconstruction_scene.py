"""Projection and coverage for validated reconstruction observations."""

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .reconstruction_models import RasterEvidence, ReconstructionObservations
from .scene import SCENE_LIMITS, parse_scene_deck
from .scene_normalizer import NormalizedScene, normalize_scene

_SLIDE_WIDTH = 1_920
_SLIDE_HEIGHT = 1_080


def project_reconstruction_scene(
    observations: ReconstructionObservations,
    raster: RasterEvidence,
    private_root: Path,
    confidence_threshold: float,
) -> tuple[NormalizedScene, dict[str, Any]]:
    projected = [
        _project_element(item, observations.canvas, raster, confidence_threshold)
        for item in observations.elements
    ]
    if any(
        item["uses_raster"]
        and (
            _is_full_canvas(item["source_region"], observations.canvas)
            or _is_full_canvas(item["observation_geometry"], observations.canvas)
        )
        for item in projected
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Whole-slide raster reconstruction is forbidden.",
            details={"whole_slide_raster": True},
        )
    assets_dir = private_root / "reconstruction-assets"
    assets_dir.mkdir()
    asset = None
    if any(item["uses_raster"] for item in projected):
        extension = "png" if raster.media_type == "image/png" else "jpg"
        filename = f"asset-{raster.sha256}.{extension}"
        (assets_dir / filename).write_bytes(raster.bytes_value)
        asset = {
            "bytes": raster.byte_count,
            "filename": filename,
            "height": raster.height,
            "id": raster.sha256,
            "mime": raster.media_type,
            "purpose": "source-image",
            "width": raster.width,
        }
    items = [
        _scene_item(item, raster.sha256 if item["uses_raster"] else None, raster)
        for item in projected
    ]
    raw, scene_bytes = _bind_scene_bytes(
        _scene_deck(items, [] if asset is None else [asset], observations)
    )
    scene = normalize_scene(parse_scene_deck(raw, assets_dir, scene_bytes))
    receipt = _receipt(projected, observations, confidence_threshold)
    return scene, receipt


def _project_element(
    item: dict[str, Any],
    canvas: dict[str, int],
    raster: RasterEvidence,
    threshold: float,
) -> dict[str, Any]:
    editable = item["confidence"] >= threshold
    uses_raster = not editable or item["kind"] == "image"
    return {
        **item,
        "geometry": _scale_rect(item["geometry"], canvas),
        "observation_geometry": dict(item["geometry"]),
        "outcome": "editable" if editable else "rasterized",
        "uses_raster": uses_raster,
        "crop": _crop(item["source_region"], raster),
    }


def _scene_item(
    item: dict[str, Any],
    asset_id: str | None,
    raster: RasterEvidence,
) -> dict[str, Any]:
    style = item["style"]
    text_style = {
        "color": _rgb(style["color"]),
        "font_family": style["font_family"],
        "font_size": style["font_size"],
        "font_style": "normal",
        "font_weight": str(int(style["font_weight"])),
        "letter_spacing": "normal",
        "line_height": "normal",
        "text_align": style["text_align"],
        "text_decoration": "none",
    }
    text = item["text"] if item["outcome"] == "editable" else ""
    is_text = item["kind"] == "text" and item["outcome"] == "editable"
    is_shape = item["kind"] == "shape" and item["outcome"] == "editable"
    scene_kind = (
        "text"
        if is_text
        else "rounded-rectangle"
        if is_shape and style["radius"] > 0
        else "rectangle"
        if is_shape
        else "image"
    )
    return {
        "approximations": [],
        "asset_id": asset_id,
        "border_color": _rgb(style["border_color"]),
        "border_width": style["border_width"] if is_shape else 0,
        "capture_outcome": "rasterized" if item["outcome"] == "rasterized" else None,
        "dom_ancestor_ids": [],
        "dom_index": item["reading_order"],
        "editable_descendants": 0,
        "fill": _rgb(style["fill"]) if is_shape else "rgba(0, 0, 0, 0)",
        "force_raster": item["outcome"] == "rasterized",
        "font_evidence": {
            "computed_family": style["font_family"],
            "platform_fonts": [],
            "requested_families": [style["font_family"]],
            "substitution": None,
            "truncated": False,
        },
        "height": item["geometry"]["height"],
        "ignored": False,
        "image_crop": item["crop"] if asset_id is not None else None,
        "image_height": raster.height if asset_id is not None else None,
        "image_src": "reconstruction-source" if asset_id is not None else None,
        "image_width": raster.width if asset_id is not None else None,
        "kind": scene_kind,
        "object_fit": "fill",
        "object_position": "50% 50%",
        "opacity": 1,
        "paint_order": item["reading_order"],
        "paragraphs": (
            [{
                "alignment": text_style["text_align"],
                "line_height": "normal",
                "runs": [{"style": text_style, "text": text}],
            }]
            if text
            else []
        ),
        "parent_source_id": None,
        "pseudo": [],
        "radius": style["radius"] if is_shape else 0,
        "reason": "low_confidence" if item["outcome"] == "rasterized" else None,
        "requested_font": style["font_family"],
        "rotation": 0,
        "source_id": item["id"],
        "text": text,
        "text_insets": {"bottom": 0, "left": 0, "right": 0, "top": 0},
        "text_style": text_style,
        "unknown_hints": [],
        "unsupported": [],
        "width": item["geometry"]["width"],
        "x": item["geometry"]["x"],
        "y": item["geometry"]["y"],
        "z_index": 0,
    }


def _scene_deck(
    items: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    observations: ReconstructionObservations,
) -> dict[str, Any]:
    asset_bytes = sum(asset["bytes"] for asset in assets)
    text_bytes = sum(len(item["text"].encode("utf-8")) for item in items)
    return {
        "assets": assets,
        "blocked_resources": {
            "by_reason": {},
            "samples": [],
            "total": 0,
            "truncated": 0,
        },
        "canvas": {"height": _SLIDE_HEIGHT, "width": _SLIDE_WIDTH},
        "limits": dict(SCENE_LIMITS),
        "observed": {
            "asset_bytes": asset_bytes,
            "assets": len(assets),
            "capture_bytes": observations.serialized_bytes + asset_bytes,
            "dom_nodes": len(items) + 1,
            "images": sum(item["kind"] == "image" for item in items),
            "paint_items": len(items),
            "resource_requests": 0,
            "slides": 1,
            "text_bytes": text_bytes,
            "total_asset_bytes": asset_bytes,
        },
        "slides": [{
            "height": _SLIDE_HEIGHT,
            "index": 1,
            "items": items,
            "root_fill": "rgb(255, 255, 255)",
            "root_unsupported": [],
            "width": _SLIDE_WIDTH,
            "x": 0,
            "y": 0,
        }],
        "version": 1,
        "visual_sources": [],
    }


def _bind_scene_bytes(raw: dict[str, Any]) -> tuple[dict[str, Any], int]:
    observed = raw["observed"]
    for _attempt in range(8):
        payload = json.dumps(
            raw,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        capture_bytes = len(payload) + observed["asset_bytes"]
        if observed["capture_bytes"] == capture_bytes:
            return raw, len(payload)
        observed["capture_bytes"] = capture_bytes
    raise RuntimeError("Scene capture byte binding did not converge.")


def _receipt(
    elements: list[dict[str, Any]],
    observations: ReconstructionObservations,
    threshold: float,
) -> dict[str, Any]:
    editable = [item for item in elements if item["outcome"] == "editable"]
    total_area = union_area(item["source_region"] for item in elements)
    editable_area = union_area(item["source_region"] for item in editable)
    return {
        "canvas": dict(observations.canvas),
        "confidence_threshold": threshold,
        "editable_coverage": {
            "by_area": {
                "editable": editable_area,
                "ratio": 0.0 if total_area == 0 else editable_area / total_area,
                "total": total_area,
            },
            "by_object_count": {
                "editable": len(editable),
                "ratio": len(editable) / len(elements),
                "total": len(elements),
            },
        },
        "elements": [
            {
                "confidence": item["confidence"],
                "geometry": item["observation_geometry"],
                "id": item["id"],
                "kind": item["kind"],
                "outcome": item["outcome"],
                "reading_order": item["reading_order"],
                "source_region": item["source_region"],
                "text": item["text"],
            }
            for item in elements
        ],
        "ocr_text": [item["text"] for item in elements if item["text"]],
        "whole_slide_raster": False,
    }


def union_area(rectangles: Iterable[dict[str, float]]) -> float:
    values = list(rectangles)
    if not values:
        return 0.0
    xs = sorted({edge for item in values for edge in (item["x"], item["x"] + item["width"])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (item["y"], item["y"] + item["height"])
            for item in values
            if item["x"] < right and item["x"] + item["width"] > left
        )
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start > end:
                    covered += end - start
                    start, end = next_start, next_end
                else:
                    end = max(end, next_end)
            covered += end - start
        area += (right - left) * covered
    return area


def _scale_rect(rect: dict[str, float], canvas: dict[str, int]) -> dict[str, float]:
    return {
        "height": rect["height"] * _SLIDE_HEIGHT / canvas["height"],
        "width": rect["width"] * _SLIDE_WIDTH / canvas["width"],
        "x": rect["x"] * _SLIDE_WIDTH / canvas["width"],
        "y": rect["y"] * _SLIDE_HEIGHT / canvas["height"],
    }


def _crop(rect: dict[str, float], raster: RasterEvidence) -> dict[str, float]:
    return {
        "bottom": 1 - (rect["y"] + rect["height"]) / raster.height,
        "left": rect["x"] / raster.width,
        "right": 1 - (rect["x"] + rect["width"]) / raster.width,
        "top": rect["y"] / raster.height,
    }


def _is_full_canvas(rect: dict[str, float], canvas: dict[str, int]) -> bool:
    return (
        rect["x"] == 0
        and rect["y"] == 0
        and rect["width"] == canvas["width"]
        and rect["height"] == canvas["height"]
    )


def _rgb(value: str) -> str:
    return f"rgb({int(value[1:3], 16)}, {int(value[3:5], 16)}, {int(value[5:7], 16)})"


__all__ = ["project_reconstruction_scene", "union_area"]
