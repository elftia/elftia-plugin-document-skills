"""Strict private SceneDeck model and hard-ceiling parser."""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SLIDE_KEYS = {"index", "width", "height", "x", "y", "root_fill", "root_unsupported", "items"}
_ITEM_KEYS = {
    "source_id", "parent_source_id", "dom_ancestor_ids", "dom_index", "z_index", "paint_order", "kind", "x", "y", "width",
    "height", "rotation", "opacity", "fill", "border_color", "border_width", "radius", "text",
    "text_style", "paragraphs", "requested_font", "font_evidence", "pseudo", "image_src", "image_width", "image_height",
    "object_fit", "object_position", "image_crop", "force_raster", "ignored", "unknown_hints", "unsupported", "approximations",
    "editable_descendants", "capture_outcome", "reason", "asset_id",
}
_ASSET_KEYS = {"id", "filename", "mime", "bytes", "width", "height", "purpose"}
_KINDS = {"rectangle", "rounded-rectangle", "ellipse", "line", "text", "image"}
_MAX_SLIDES = 100
_MAX_ITEMS = 8_000
_MAX_TEXT_BYTES = 4 * 1024 * 1024
_MAX_ASSET_BYTES = 32 * 1024 * 1024
_MAX_ASSETS = 512
_MAX_IMAGES = 512
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_TEXT_STYLE_KEYS = {
    "font_family", "font_size", "font_weight", "font_style", "text_decoration",
    "color", "text_align", "line_height",
}
_BLOCKED_RESOURCE_KEYS = {"total", "by_reason", "samples", "truncated"}
_BLOCKED_RESOURCE_SAMPLE_KEYS = {"reason", "resource_hash", "count"}
_PSEUDO_KEYS = {
    "source_id", "content", "simple", "reason", "x", "y", "width", "height",
    "paint_slot", "paint_order", "opacity", "color", "font_family", "font_size",
    "font_weight", "font_style", "text_decoration", "text_align", "line_height",
}
SCENE_LIMITS = {
    "slides": _MAX_SLIDES,
    "dom_nodes": 20_000,
    "paint_items": _MAX_ITEMS,
    "text_bytes": _MAX_TEXT_BYTES,
    "image_bytes": 8 * 1024 * 1024,
    "image_pixels": 40_000_000,
    "images": _MAX_IMAGES,
    "assets": _MAX_ASSETS,
    "total_asset_bytes": _MAX_ASSET_BYTES,
    "resource_requests": _MAX_ASSETS,
    "scene_bytes": _MAX_ASSET_BYTES,
    "capture_bytes": _MAX_ASSET_BYTES,
}
_EXPECTED_LIMITS = SCENE_LIMITS


@dataclass(frozen=True)
class SceneDeck:
    slides: tuple[dict[str, Any], ...]
    assets: dict[str, dict[str, Any]]
    blocked_resources: dict[str, Any]
    observed: dict[str, int]
    scene_bytes: int
    visual_sources: tuple[dict[str, Any], ...]


def parse_scene_deck(value: Any, assets_dir: Path, scene_bytes: int) -> SceneDeck:
    if type(scene_bytes) is not int or not 0 < scene_bytes <= _EXPECTED_LIMITS["scene_bytes"]:
        _invalid("Scene capture byte evidence is invalid.")
    if type(value) is not dict or set(value) != {
        "version", "canvas", "limits", "observed", "blocked_resources", "visual_sources", "slides", "assets"
    }:
        _invalid("SceneDeck fields are invalid.")
    if value["version"] != 1 or value["canvas"] != {"width": 1920, "height": 1080}:
        _invalid("SceneDeck version or canvas is unsupported.")
    if value["limits"] != _EXPECTED_LIMITS:
        _invalid("SceneDeck limit policy does not match the trusted parser.")
    slides = value["slides"]
    assets = value["assets"]
    blocked = value["blocked_resources"]
    observed = value["observed"]
    visual_sources = value["visual_sources"]
    if type(slides) is not list or not 1 <= len(slides) <= _MAX_SLIDES:
        _invalid("SceneDeck slide count exceeds policy.")
    if (
        type(assets) is not list
        or len(assets) > _MAX_ASSETS
        or type(blocked) is not dict
        or type(visual_sources) is not list
        or len(visual_sources) > len(slides)
        or type(observed) is not dict
    ):
        _invalid("SceneDeck collections are invalid.")
    _parse_blocked_resources(blocked)
    parsed_assets = _parse_assets(assets, assets_dir)
    parsed_visuals = _parse_visual_sources(visual_sources, len(slides), parsed_assets)
    item_count = 0
    text_bytes = 0
    image_count = 0
    referenced_assets: set[str] = set()
    referenced_assets.update(item["asset_id"] for item in parsed_visuals)
    for expected_index, slide in enumerate(slides, 1):
        if type(slide) is not dict or set(slide) != _SLIDE_KEYS:
            _invalid("Scene slide fields are invalid.")
        if slide["index"] != expected_index or slide["width"] != 1920 or slide["height"] != 1080:
            _invalid("Scene slide geometry is invalid.")
        if slide["root_unsupported"]:
            _invalid("Unsupported slide-root styling cannot be flattened.")
        if not _valid_css_color(slide["root_fill"]):
            _invalid("Scene slide background is invalid.")
        if type(slide["items"]) is not list:
            _invalid("Scene slide items are invalid.")
        source_ids = [item.get("source_id") for item in slide["items"] if type(item) is dict]
        if len(source_ids) != len(slide["items"]) or len(set(source_ids)) != len(source_ids):
            _invalid("Scene source identities are duplicated or invalid.")
        previous_paint_order = -1
        for item in slide["items"]:
            _parse_item(item, parsed_assets)
            if item["parent_source_id"] is not None and item["parent_source_id"] not in source_ids:
                _invalid("Scene item parent identity is invalid.")
            if item["parent_source_id"] is not None and item["parent_source_id"] not in item["dom_ancestor_ids"]:
                _invalid("Scene item public ancestry is not bound to its DOM ancestry.")
            if item["paint_order"] < previous_paint_order:
                _invalid("Scene items are not in captured paint order.")
            previous_paint_order = item["paint_order"]
            item_count += 1
            text_bytes += len(item["text"].encode("utf-8"))
            image_count += item["kind"] == "image"
            if item["asset_id"] is not None:
                referenced_assets.add(item["asset_id"])
    if item_count > _MAX_ITEMS or text_bytes > _MAX_TEXT_BYTES:
        _invalid("Scene item or text ceiling was exceeded.")
    expected_observed = {
        "slides", "dom_nodes", "paint_items", "text_bytes", "asset_bytes",
        "total_asset_bytes", "resource_requests", "images", "assets", "capture_bytes",
    }
    if set(observed) != expected_observed or any(type(item) is not int or item < 0 for item in observed.values()):
        _invalid("Scene limit evidence is invalid.")
    asset_bytes = sum(asset["bytes"] for asset in parsed_assets.values())
    if (
        observed["slides"] != len(slides)
        or observed["paint_items"] != item_count
        or observed["text_bytes"] != text_bytes
        or observed["asset_bytes"] != asset_bytes
        or observed["total_asset_bytes"] < asset_bytes
        or observed["images"] != image_count
        or observed["assets"] != len(parsed_assets)
        or observed["capture_bytes"] != scene_bytes + asset_bytes
        or observed["dom_nodes"] < item_count + len(slides)
        or referenced_assets != set(parsed_assets)
    ):
        _invalid("Scene observed counts do not match payload.")
    if (
        observed["dom_nodes"] > _EXPECTED_LIMITS["dom_nodes"]
        or observed["text_bytes"] > _EXPECTED_LIMITS["text_bytes"]
        or observed["asset_bytes"] > _EXPECTED_LIMITS["total_asset_bytes"]
        or observed["total_asset_bytes"] > _EXPECTED_LIMITS["total_asset_bytes"]
        or observed["resource_requests"] > _EXPECTED_LIMITS["resource_requests"]
        or observed["images"] > _EXPECTED_LIMITS["images"]
        or observed["assets"] > _EXPECTED_LIMITS["assets"]
        or observed["capture_bytes"] > _EXPECTED_LIMITS["capture_bytes"]
    ):
        _invalid("Scene observed limits exceed policy.")
    return SceneDeck(
        tuple(slides),
        parsed_assets,
        dict(blocked),
        dict(observed),
        scene_bytes,
        tuple(parsed_visuals),
    )


def _parse_visual_sources(
    values: list[Any],
    slide_count: int,
    assets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_slides: set[int] = set()
    for value in values:
        if (
            type(value) is not dict
            or set(value) != {"slide", "asset_id"}
            or type(value["slide"]) is not int
            or not 1 <= value["slide"] <= slide_count
            or value["slide"] in seen_slides
            or value["asset_id"] not in assets
            or assets[value["asset_id"]]["purpose"] != "visual-source"
        ):
            _invalid("Scene visual-source evidence is invalid.")
        seen_slides.add(value["slide"])
        result.append(value)
    if result and seen_slides != set(range(1, slide_count + 1)):
        _invalid("Scene visual-source coverage is incomplete.")
    return result


def _parse_blocked_resources(value: dict[str, Any]) -> None:
    if set(value) != _BLOCKED_RESOURCE_KEYS:
        _invalid("Blocked-resource evidence fields are invalid.")
    total = value["total"]
    by_reason = value["by_reason"]
    samples = value["samples"]
    truncated = value["truncated"]
    if (
        type(total) is not int
        or not 0 <= total <= SCENE_LIMITS["resource_requests"]
        or type(truncated) is not int
        or not 0 <= truncated <= total
        or type(by_reason) is not dict
        or len(by_reason) > 64
        or type(samples) is not list
        or len(samples) > 32
    ):
        _invalid("Blocked-resource evidence exceeds policy.")
    if any(
        type(reason) is not str
        or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason) is None
        or type(count) is not int
        or count <= 0
        for reason, count in by_reason.items()
    ):
        _invalid("Blocked-resource reason evidence is invalid.")
    sampled = 0
    for sample in samples:
        if (
            type(sample) is not dict
            or set(sample) != _BLOCKED_RESOURCE_SAMPLE_KEYS
            or sample["reason"] not in by_reason
            or type(sample["resource_hash"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", sample["resource_hash"]) is None
            or type(sample["count"]) is not int
            or sample["count"] <= 0
        ):
            _invalid("Blocked-resource sample evidence is invalid.")
        sampled += sample["count"]
    if sum(by_reason.values()) != total or total - sampled != truncated:
        _invalid("Blocked-resource aggregate evidence does not match samples.")


def _parse_assets(values: list[Any], assets_dir: Path) -> dict[str, dict[str, Any]]:
    if assets_dir.is_symlink() or not assets_dir.is_dir():
        _invalid("Scene asset directory binding failed.")
    canonical_assets = assets_dir.resolve(strict=True)
    result: dict[str, dict[str, Any]] = {}
    total = 0
    for asset in values:
        if type(asset) is not dict or set(asset) != _ASSET_KEYS:
            _invalid("Scene asset fields are invalid.")
        asset_id = asset["id"]
        filename = asset["filename"]
        if (
            type(asset_id) is not str
            or len(asset_id) != 64
            or type(filename) is not str
            or Path(filename).name != filename
            or asset["mime"] not in {"image/png", "image/jpeg"}
            or type(asset["bytes"]) is not int
            or not 0 < asset["bytes"] <= 8 * 1024 * 1024
            or type(asset["width"]) is not int
            or type(asset["height"]) is not int
            or not 0 < asset["width"] * asset["height"] <= 40_000_000
            or asset["purpose"] not in {"source-image", "element-fallback", "visual-source"}
        ):
            _invalid("Scene asset metadata is invalid.")
        expected_extension = "png" if asset["mime"] == "image/png" else "jpg"
        if filename != f"asset-{asset_id}.{expected_extension}" or asset_id in result:
            _invalid("Scene asset identity is invalid.")
        path = assets_dir / filename
        if (
            path.is_symlink()
            or not path.is_file()
            or path.resolve(strict=True).parent != canonical_assets
            or path.stat().st_size != asset["bytes"]
        ):
            _invalid("Scene asset file binding failed.")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != asset_id:
            _invalid("Scene asset hash binding failed.")
        mime, width, height = _image_metadata(payload)
        if mime != asset["mime"] or width != asset["width"] or height != asset["height"]:
            _invalid("Scene decoded-image evidence does not match the private asset.")
        total += asset["bytes"]
        result[asset_id] = {**asset, "path": path}
    if total > _MAX_ASSET_BYTES:
        _invalid("Scene total asset ceiling was exceeded.")
    return result


def _image_metadata(payload: bytes) -> tuple[str, int, int]:
    png_signature = b"\x89PNG\r\n\x1a\n"
    if (
        len(payload) >= 24
        and payload.startswith(png_signature)
        and payload[12:16] == b"IHDR"
    ):
        width = int.from_bytes(payload[16:20], "big")
        height = int.from_bytes(payload[20:24], "big")
        if width > 0 and height > 0:
            return "image/png", width, height
    if len(payload) >= 4 and payload[:2] == b"\xff\xd8" and payload[-2:] == b"\xff\xd9":
        offset = 2
        start_of_frame = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while offset + 4 <= len(payload):
            if payload[offset] != 0xFF:
                offset += 1
                continue
            marker = payload[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if offset + 2 > len(payload):
                break
            length = int.from_bytes(payload[offset:offset + 2], "big")
            if length < 2 or offset + length > len(payload):
                break
            if marker in start_of_frame and length >= 7:
                height = int.from_bytes(payload[offset + 3:offset + 5], "big")
                width = int.from_bytes(payload[offset + 5:offset + 7], "big")
                if width > 0 and height > 0:
                    return "image/jpeg", width, height
            offset += length
    _invalid("Scene asset is not a supported, structurally valid image.")


def _parse_item(item: Any, assets: dict[str, dict[str, Any]]) -> None:
    if type(item) is not dict or set(item) != _ITEM_KEYS:
        _invalid("Scene item fields are invalid.")
    if (
        item["kind"] not in _KINDS
        or type(item["source_id"]) is not str
        or _SOURCE_ID.fullmatch(item["source_id"]) is None
        or type(item["parent_source_id"]) not in {str, type(None)}
    ):
        _invalid("Scene item identity or kind is invalid.")
    if (
        type(item["dom_ancestor_ids"]) is not list
        or len(item["dom_ancestor_ids"]) > 128
        or len(set(item["dom_ancestor_ids"])) != len(item["dom_ancestor_ids"])
        or any(type(value) is not str or _SOURCE_ID.fullmatch(value) is None for value in item["dom_ancestor_ids"])
    ):
        _invalid("Scene DOM ancestry evidence is invalid.")
    if (
        type(item["dom_index"]) is not int
        or item["dom_index"] < 0
        or type(item["z_index"]) is not int
        or type(item["paint_order"]) is not int
        or item["paint_order"] < 0
    ):
        _invalid("Scene paint-order evidence is invalid.")
    for field in ("x", "y", "width", "height", "rotation", "opacity", "border_width", "radius"):
        if type(item[field]) not in {int, float} or not math.isfinite(item[field]):
            _invalid("Scene geometry contains a non-finite value.")
    if (
        item["x"] < 0
        or item["y"] < 0
        or item["width"] <= 0
        or item["height"] <= 0
        or item["x"] + item["width"] > 1920.01
        or item["y"] + item["height"] > 1080.01
    ):
        _invalid("Scene item is outside the fixed slide canvas.")
    if (
        not 0 <= item["opacity"] <= 1
        or not -360 <= item["rotation"] <= 360
        or not 0 <= item["border_width"] <= 100
        or not 0 <= item["radius"] <= 1920
    ):
        _invalid("Scene bounded drawing values are invalid.")
    if type(item["text"]) is not str or len(item["text"].encode("utf-8")) > 64_000:
        _invalid("Scene item text is invalid.")
    _parse_text_style(item["text_style"])
    if type(item["paragraphs"]) is not list or len(item["paragraphs"]) > 100:
        _invalid("Scene text paragraphs are invalid.")
    for paragraph in item["paragraphs"]:
        if (
            type(paragraph) is not dict
            or set(paragraph) != {"runs", "alignment", "line_height"}
            or paragraph["alignment"] not in {"start", "end", "left", "right", "center", "justify"}
            or type(paragraph["line_height"]) is not str
            or len(paragraph["line_height"]) > 32
            or type(paragraph["runs"]) is not list
            or not 1 <= len(paragraph["runs"]) <= 256
        ):
            _invalid("Scene text runs are invalid.")
        for run in paragraph["runs"]:
            if (
                type(run) is not dict
                or set(run) != {"text", "style"}
                or type(run["text"]) is not str
                or not run["text"]
                or len(run["text"].encode("utf-8")) > 64_000
            ):
                _invalid("Scene text run fields are invalid.")
            _parse_text_style(run["style"])
    joined_text = "\n".join(
        "".join(run["text"] for run in paragraph["runs"])
        for paragraph in item["paragraphs"]
    )
    if joined_text != item["text"]:
        _invalid("Scene paragraph/run text does not match the item text.")
    evidence = item["font_evidence"]
    if (
        type(evidence) is not dict
        or set(evidence) != {"requested_families", "computed_family", "platform_fonts", "substitution", "truncated"}
        or type(evidence["requested_families"]) is not list
        or len(evidence["requested_families"]) > 8
        or any(type(value) is not str or not value or len(value) > 128 for value in evidence["requested_families"])
        or type(evidence["computed_family"]) is not str
        or len(evidence["computed_family"]) > 512
        or type(evidence["platform_fonts"]) is not list
        or len(evidence["platform_fonts"]) > 8
        or type(evidence["truncated"]) is not bool
        or type(item["requested_font"]) not in {str, type(None)}
    ):
        _invalid("Scene font evidence is invalid.")
    for font in evidence["platform_fonts"]:
        if (
            type(font) is not dict
            or set(font) != {"family", "postscript", "custom", "glyphs"}
            or type(font["family"]) is not str
            or not font["family"]
            or len(font["family"]) > 128
            or type(font["postscript"]) is not str
            or len(font["postscript"]) > 128
            or type(font["custom"]) is not bool
            or type(font["glyphs"]) is not int
            or font["glyphs"] < 0
        ):
            _invalid("Scene platform-font evidence is invalid.")
    substitution = evidence["substitution"]
    if substitution is not None and (
        type(substitution) is not dict
        or set(substitution) != {"requested", "actual"}
        or type(substitution["requested"]) is not str
        or type(substitution["actual"]) is not str
    ):
        _invalid("Scene font substitution evidence is invalid.")
    for field in ("unknown_hints", "unsupported", "approximations", "pseudo"):
        if type(item[field]) is not list or len(item[field]) > 64:
            _invalid("Scene item diagnostic samples are invalid.")
        if field != "pseudo" and any(type(value) is not str or not value or len(value) > 80 for value in item[field]):
            _invalid("Scene item diagnostic values are invalid.")
    _parse_pseudos(item["pseudo"])
    if (
        type(item["force_raster"]) is not bool
        or type(item["ignored"]) is not bool
        or type(item["editable_descendants"]) is not int
        or not 0 <= item["editable_descendants"] <= 20_000
        or item["capture_outcome"] not in {None, "rasterized", "rejected"}
        or type(item["reason"]) not in {str, type(None)}
        or type(item["image_src"]) not in {str, type(None)}
        or type(item["object_fit"]) is not str
        or type(item["object_position"]) is not str
    ):
        _invalid("Scene item classification evidence is invalid.")
    if item["asset_id"] is not None and item["asset_id"] not in assets:
        _invalid("Scene item references an unknown private asset.")
    crop = item["image_crop"]
    if crop is not None and (
        type(crop) is not dict
        or set(crop) != {"left", "top", "right", "bottom"}
        or any(type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value < 1 for value in crop.values())
        or crop["left"] + crop["right"] >= 1
        or crop["top"] + crop["bottom"] >= 1
    ):
        _invalid("Scene image crop evidence is invalid.")
    if item["asset_id"] is not None and crop is None:
        _invalid("Scene emitted image is missing crop evidence.")


def _parse_text_style(style: Any) -> None:
    if type(style) is not dict or set(style) != _TEXT_STYLE_KEYS:
        _invalid("Scene text style fields are invalid.")
    if (
        type(style["font_family"]) is not str
        or not style["font_family"]
        or len(style["font_family"]) > 512
        or type(style["font_size"]) not in {int, float}
        or not math.isfinite(style["font_size"])
        or not 0 < style["font_size"] <= 800
    ):
        _invalid("Scene font style is invalid.")
    for field in ("font_weight", "font_style", "text_decoration", "color", "text_align", "line_height"):
        if type(style[field]) is not str or len(style[field]) > 128:
            _invalid("Scene text style value is invalid.")


def _parse_pseudos(values: list[Any]) -> None:
    for value in values:
        if (
            type(value) is not dict
            or set(value) != _PSEUDO_KEYS
            or type(value["source_id"]) is not str
            or _SOURCE_ID.fullmatch(value["source_id"]) is None
            or type(value["content"]) is not str
            or not value["content"]
            or len(value["content"].encode("utf-8")) > 64_000
            or type(value["simple"]) is not bool
            or type(value["reason"]) not in {str, type(None)}
            or value["paint_slot"] not in {2, 4}
            or type(value["paint_order"]) is not int
            or value["paint_order"] < 0
            or type(value["opacity"]) not in {int, float}
            or not math.isfinite(value["opacity"])
            or not 0 <= value["opacity"] <= 1
        ):
            _invalid("Scene pseudo-element evidence is invalid.")
        for field in ("x", "y", "width", "height", "font_size"):
            if type(value[field]) not in {int, float} or not math.isfinite(value[field]):
                _invalid("Scene pseudo-element geometry is invalid.")
        if value["simple"] and (
            value["reason"] is not None
            or value["width"] <= 0
            or value["height"] <= 0
            or value["x"] < 0
            or value["y"] < 0
            or value["x"] + value["width"] > 1920.01
            or value["y"] + value["height"] > 1080.01
        ):
            _invalid("Simple pseudo-element geometry is invalid.")
        if not value["simple"] and value["reason"] != "complex_pseudo_element":
            _invalid("Complex pseudo-element reason is invalid.")
        for field in (
            "color", "font_family", "font_weight", "font_style",
            "text_decoration", "text_align", "line_height",
        ):
            if type(value[field]) is not str or len(value[field]) > 512:
                _invalid("Scene pseudo-element style is invalid.")


def _valid_css_color(value: Any) -> bool:
    if type(value) is not str or not value or len(value) > 64:
        return False
    if value == "transparent" or re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return True
    numbers = re.findall(r"[\d.]+", value)
    return value.startswith(("rgb(", "rgba(")) and len(numbers) in {3, 4}


def _invalid(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message)
