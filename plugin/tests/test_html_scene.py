"""Strict SceneDeck ceilings, classification, hints, and suppression tests."""

import copy
import hashlib
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.scene import parse_scene_deck
from document_skills_core.formats.pptx.scene_normalizer import normalize_scene
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


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
    "letter_spacing": "normal",
}


def _item(source_id: str = "item", **overrides):
    value = {
        "source_id": source_id,
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
        "text": "Hello",
        "text_style": STYLE,
        "text_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "paragraphs": [{
            "runs": [{"text": "Hello", "style": STYLE}],
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
                "glyphs": 5,
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
    value.update(overrides)
    return value


def _raw(items, assets=None, blocked=None):
    return {
        "version": 1,
        "canvas": {"width": 1920, "height": 1080},
        "limits": LIMITS,
        "observed": {
            "slides": 1,
            "dom_nodes": len(items) + 1,
            "paint_items": len(items),
            "text_bytes": sum(len(item["text"].encode()) for item in items),
            "asset_bytes": sum(asset["bytes"] for asset in assets or []),
            "total_asset_bytes": sum(asset["bytes"] for asset in assets or []),
            "resource_requests": 0,
            "images": sum(item["kind"] == "image" for item in items),
            "assets": len(assets or []),
            "capture_bytes": 1024 + sum(asset["bytes"] for asset in assets or []),
        },
        "blocked_resources": blocked or {"total": 0, "by_reason": {}, "samples": [], "truncated": 0},
        "visual_sources": [],
        "slides": [{
            "index": 1,
            "width": 1920,
            "height": 1080,
            "x": 0,
            "y": 0,
            "root_fill": "rgb(255, 255, 255)",
            "root_unsupported": [],
            "items": items,
        }],
        "assets": assets or [],
    }


def _asset(tmp_path: Path):
    digest = hashlib.sha256(PNG_1X1).hexdigest()
    assets = tmp_path / "assets"
    assets.mkdir()
    filename = f"asset-{digest}.png"
    (assets / filename).write_bytes(PNG_1X1)
    return assets, {
        "id": digest,
        "filename": filename,
        "mime": "image/png",
        "bytes": len(PNG_1X1),
        "width": 1,
        "height": 1,
        "purpose": "element-fallback",
    }


def test_scene_parser_accepts_bounded_finite_fixed_canvas(tmp_path: Path):
    deck = parse_scene_deck(_raw([_item()]), tmp_path, 1024)
    assert len(deck.slides) == 1
    assert deck.observed["paint_items"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"x": float("nan")},
        {"x": -1},
        {"width": 2_000},
        {"paragraphs": [{"unknown": []}]},
    ],
)
def test_scene_parser_rejects_nonfinite_out_of_bounds_and_invalid_runs(tmp_path: Path, change):
    with pytest.raises(DocumentSkillsError):
        parse_scene_deck(_raw([_item(**change)]), tmp_path, 1024)


def test_scene_parser_rejects_limit_policy_and_asset_hash_drift(tmp_path: Path):
    raw = _raw([_item()])
    raw["limits"] = {**LIMITS, "paint_items": 9_000}
    with pytest.raises(DocumentSkillsError):
        parse_scene_deck(raw, tmp_path, 1024)

    assets_dir, asset = _asset(tmp_path)
    item = _item(
        kind="image", text="", paragraphs=[], asset_id=asset["id"],
        image_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
    )
    (assets_dir / asset["filename"]).write_bytes(b"drift")
    with pytest.raises(DocumentSkillsError):
        parse_scene_deck(_raw([item], [asset]), assets_dir, 1024)


def test_scene_parser_rejects_unbound_counts_duplicate_ids_and_run_text(tmp_path: Path):
    base = _raw([_item()])
    cases = []
    observed_drift = copy.deepcopy(base)
    observed_drift["observed"]["text_bytes"] += 1
    cases.append((observed_drift, 1024))
    duplicate_ids = _raw([_item("duplicate"), _item("duplicate", dom_index=1, paint_order=1)])
    cases.append((duplicate_ids, 1024))
    run_drift = copy.deepcopy(base)
    run_drift["slides"][0]["items"][0]["paragraphs"][0]["runs"][0]["text"] = "Different"
    cases.append((run_drift, 1024))
    cases.append((base, 32 * 1024 * 1024 + 1))

    for raw, scene_bytes in cases:
        with pytest.raises(DocumentSkillsError):
            parse_scene_deck(raw, tmp_path, scene_bytes)


def test_scene_parser_enforces_image_asset_and_dom_count_ceilings(tmp_path: Path):
    too_many_assets = _raw([])
    too_many_assets["assets"] = [{} for _ in range(513)]
    too_many_images = _raw([
        _item(
            f"image-{index}",
            kind="image",
            text="",
            paragraphs=[],
            dom_index=index,
            paint_order=index,
        )
        for index in range(513)
    ])
    too_many_dom_nodes = _raw([_item()])
    too_many_dom_nodes["observed"]["dom_nodes"] = 20_001

    for raw in (too_many_assets, too_many_images, too_many_dom_nodes):
        with pytest.raises(DocumentSkillsError):
            parse_scene_deck(raw, tmp_path, 1024)


def test_scene_parser_binds_image_mime_dimensions_and_filename_to_actual_bytes(tmp_path: Path):
    assets_dir, asset = _asset(tmp_path)
    item = _item(
        kind="image", text="", paragraphs=[], asset_id=asset["id"],
        image_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
    )
    cases = [
        {"width": 2},
        {"mime": "image/jpeg"},
        {"filename": "renamed.png"},
        {"purpose": "unknown"},
    ]
    for change in cases:
        changed = {**asset, **change}
        with pytest.raises(DocumentSkillsError):
            parse_scene_deck(_raw([item,], [changed]), assets_dir, 1024)


def test_normalizer_classifies_approximations_and_simple_pseudo(tmp_path: Path):
    item = _item(
        approximations=["box_shadow_omitted"],
        unknown_hints=["data-pptx-unknown"],
        pseudo=[{
            "source_id": "item:before",
            "content": "★",
            "simple": True,
            "reason": None,
            "x": 20,
            "y": 30,
            "width": 20,
            "height": 20,
            "paint_slot": 2,
            "paint_order": 1,
            "opacity": 1,
            "color": "rgb(0, 0, 0)",
            "font_family": "Arial",
            "font_size": 16,
            "font_weight": "400",
            "font_style": "normal",
            "text_decoration": "none",
            "text_align": "left",
            "line_height": "normal",
            "letter_spacing": "normal",
        }],
    )
    normalized = normalize_scene(parse_scene_deck(_raw([item]), tmp_path, 1024))
    assert [entry["outcome"] for entry in normalized.slides[0]] == ["native", "approximated"]
    assert normalized.diagnostics["unknown_hints"]["total"] == 1


def test_normalizer_suppresses_descendants_of_rasterized_parent(tmp_path: Path):
    assets_dir, asset = _asset(tmp_path)
    parent = _item(
        "parent",
        kind="rectangle",
        text="",
        paragraphs=[],
        capture_outcome="rasterized",
        reason="css_gradient",
        asset_id=asset["id"],
        image_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
    )
    child = _item("child", parent_source_id="parent", dom_ancestor_ids=["parent"])
    normalized = normalize_scene(
        parse_scene_deck(_raw([parent, child], [asset]), assets_dir, 1024)
    )
    assert [entry["source_id"] for entry in normalized.slides[0]] == ["parent"]
    assert normalized.diagnostics["duplicate_descendants_suppressed"] == 1


def test_normalizer_suppresses_subtrees_independent_of_paint_order_and_parent_pseudo(tmp_path: Path):
    assets_dir, asset = _asset(tmp_path)
    child = _item(
        "child", parent_source_id="parent", dom_ancestor_ids=["parent"],
        dom_index=1, paint_order=1,
    )
    parent = _item(
        "parent",
        kind="rectangle",
        text="",
        paragraphs=[],
        dom_index=0,
        paint_order=2,
        capture_outcome="rasterized",
        reason="forced_element_raster",
        asset_id=asset["id"],
        image_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
        pseudo=[{
            "source_id": "parent:before",
            "content": "duplicate",
            "simple": True,
            "reason": None,
            "x": 20,
            "y": 30,
            "width": 80,
            "height": 20,
            "paint_slot": 2,
            "paint_order": 3,
            "opacity": 1,
            "color": "rgb(0, 0, 0)",
            "font_family": "Arial",
            "font_size": 16,
            "font_weight": "400",
            "font_style": "normal",
            "text_decoration": "none",
            "text_align": "left",
            "line_height": "normal",
            "letter_spacing": "normal",
        }],
    )
    normalized = normalize_scene(
        parse_scene_deck(_raw([child, parent], [asset]), assets_dir, 1024)
    )

    assert [entry["source_id"] for entry in normalized.slides[0]] == ["parent"]
    assert normalized.diagnostics["duplicate_descendants_suppressed"] == 1


def test_normalizer_ignore_hint_suppresses_the_ignored_subtree(tmp_path: Path):
    parent = _item("ignored", ignored=True, paint_order=1)
    child = _item(
        "child", parent_source_id="ignored", dom_ancestor_ids=["ignored"],
        dom_index=1, paint_order=2,
    )

    normalized = normalize_scene(parse_scene_deck(_raw([parent, child]), tmp_path, 1024))

    assert normalized.slides[0] == ()
    assert normalized.diagnostics["reasons"] == {"ignored_by_hint": 1}
    assert normalized.diagnostics["duplicate_descendants_suppressed"] == 1


def test_normalizer_aggregates_bounded_fidelity_css_font_block_and_limit_diagnostics(tmp_path: Path):
    assets_dir, asset = _asset(tmp_path)
    rasterized = [
        _item(
            f"raster-{index}",
            kind="rectangle",
            text="",
            paragraphs=[],
            dom_index=index,
            paint_order=index,
            capture_outcome="rasterized",
            reason="css_filter",
            unsupported=["css_filter", "css_clip_path"],
            asset_id=asset["id"],
            image_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
        )
        for index in range(35)
    ]
    substituted = _item("font", dom_index=35, paint_order=35)
    substituted["font_evidence"] = {
        "requested_families": ["Missing Font", "Arial"],
        "computed_family": '"Missing Font", Arial',
        "platform_fonts": [{
            "family": "Arial",
            "postscript": "ArialMT",
            "custom": False,
            "glyphs": 5,
        }],
        "substitution": {"requested": "Missing Font", "actual": "Arial"},
        "truncated": False,
    }
    blocked = {
        "total": 40,
        "by_reason": {"remote_url_blocked": 40},
        "samples": [
            {
                "reason": "remote_url_blocked",
                "resource_hash": hashlib.sha256(str(index).encode()).hexdigest(),
                "count": 1,
            }
            for index in range(32)
        ],
        "truncated": 8,
    }

    normalized = normalize_scene(
        parse_scene_deck(_raw([*rasterized, substituted], [asset], blocked), assets_dir, 1024)
    )
    diagnostics = normalized.diagnostics

    assert diagnostics["outcomes"] == {"native": 1, "rasterized": 35}
    assert diagnostics["fidelity"]["rasterized"]["count"] == 35
    assert diagnostics["fidelity"]["rasterized"]["area"] == 35 * 300 * 100
    assert len(diagnostics["fidelity"]["rasterized"]["samples"]) == 32
    assert diagnostics["fidelity"]["rasterized"]["truncated"] == 3
    assert diagnostics["unsupported_css"]["total"] == 70
    assert diagnostics["unsupported_css"]["by_reason"] == {
        "css_clip_path": 35,
        "css_filter": 35,
    }
    assert len(diagnostics["unsupported_css"]["samples"]) == 32
    assert diagnostics["unsupported_css"]["truncated"] == 38
    assert diagnostics["font_evidence"]["total"] == 1
    assert diagnostics["font_evidence"]["substitutions"] == 1
    assert diagnostics["font_evidence"]["samples"][0]["substitution"] == {
        "requested": "Missing Font", "actual": "Arial",
    }
    assert diagnostics["blocked_resources"]["total"] == 40
    assert diagnostics["blocked_resources"]["truncated"] == 8
    assert diagnostics["limits"]["observed"]["paint_items"] == 36
    assert diagnostics["limits"]["ceilings"]["paint_items"] == 8_000
    assert diagnostics["limits"]["utilization"]["paint_items"] == pytest.approx(36 / 8_000)


def test_normalizer_rejects_unsupported_or_semantic_flattening_item(tmp_path: Path):
    for item in [
        _item(unsupported=["css_filter"]),
        _item(capture_outcome="rejected", reason="semantic_flattening_guard"),
    ]:
        with pytest.raises(DocumentSkillsError):
            normalize_scene(parse_scene_deck(_raw([item]), tmp_path, 1024))
