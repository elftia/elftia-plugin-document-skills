"""Deterministic direct-OOXML emitter for normalized fixed-canvas scenes."""

import hashlib
from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS
from .scaffold import (
    _build_app_props,
    _build_core_props,
    _build_root_rels,
    _build_slide_layout,
    _build_slide_layout_rels,
    _build_slide_master,
    _build_slide_master_rels,
    _build_theme,
)
from .package import write_deterministic_zip
from .scene_normalizer import NormalizedScene

EMU_PER_PIXEL = 6_350
SLIDE_CX = 12_192_000
SLIDE_CY = 6_858_000
_P = NS["p"]
_A = NS["a"]
_R = NS["r"]
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML = "http://www.w3.org/XML/1998/namespace"


def emit_scene_pptx(
    destination: Path,
    scene: NormalizedScene,
    metadata: dict[str, str],
) -> dict[str, Any]:
    referenced = {
        item["asset_id"]
        for slide in scene.slides
        for item in slide
        if item["asset_id"] is not None
    }
    media = {
        asset_id: f"image{index}.{_asset_extension(scene.assets[asset_id])}"
        for index, asset_id in enumerate(sorted(referenced), 1)
    }
    parts: dict[str, bytes] = {
        "[Content_Types].xml": _content_types(len(scene.slides), scene, referenced),
        "_rels/.rels": _build_root_rels(),
        "ppt/presentation.xml": _presentation(len(scene.slides)),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(len(scene.slides)),
        "ppt/theme/theme1.xml": _build_theme(),
        "ppt/slideMasters/slideMaster1.xml": _build_slide_master(1, SLIDE_CX, SLIDE_CY),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _build_slide_master_rels(1),
        "ppt/slideLayouts/slideLayout1.xml": _build_slide_layout(1, SLIDE_CX, SLIDE_CY),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _build_slide_layout_rels(1),
        "docProps/core.xml": _build_core_props(metadata),
        "docProps/app.xml": _build_app_props([{} for _ in scene.slides]),
    }
    manifest_items: list[dict[str, Any]] = []
    for slide_index, slide in enumerate(scene.slides, 1):
        root_fill = scene.slide_fills[slide_index - 1] if scene.slide_fills else "transparent"
        slide_xml, slide_manifest, relationships = _slide(slide, slide_index, media, root_fill)
        parts[f"ppt/slides/slide{slide_index}.xml"] = slide_xml
        parts[f"ppt/slides/_rels/slide{slide_index}.xml.rels"] = _slide_rels(relationships, media)
        manifest_items.extend(slide_manifest)
    for asset_id, filename in media.items():
        asset = scene.assets[asset_id]
        bytes_value = asset["path"].read_bytes()
        if hashlib.sha256(bytes_value).hexdigest() != asset_id:
            raise ValueError("private asset hash changed before emission")
        parts[f"ppt/media/{filename}"] = bytes_value
    write_deterministic_zip(destination, parts)
    return {
        "slide_size": {"cx": SLIDE_CX, "cy": SLIDE_CY},
        "slides": len(scene.slides),
        "objects": len(manifest_items),
        "media": len(media),
        "items": manifest_items,
        "media_hashes": sorted(media),
    }


def _slide(
    items: tuple[dict[str, Any], ...],
    slide_index: int,
    media: dict[str, str],
    root_fill: str,
) -> tuple[bytes, list[dict[str, Any]], list[str]]:
    root = Element(f"{{{_P}}}sld")
    common = SubElement(root, f"{{{_P}}}cSld")
    _slide_background(common, root_fill)
    tree = SubElement(common, f"{{{_P}}}spTree")
    non_visual = SubElement(tree, f"{{{_P}}}nvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}cNvPr", {"id": "1", "name": ""})
    SubElement(non_visual, f"{{{_P}}}cNvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    group = SubElement(tree, f"{{{_P}}}grpSpPr")
    transform = SubElement(group, f"{{{_A}}}xfrm")
    for tag, attributes in (
        ("off", {"x": "0", "y": "0"}),
        ("ext", {"cx": str(SLIDE_CX), "cy": str(SLIDE_CY)}),
        ("chOff", {"x": "0", "y": "0"}),
        ("chExt", {"cx": str(SLIDE_CX), "cy": str(SLIDE_CY)}),
    ):
        SubElement(transform, f"{{{_A}}}{tag}", attributes)
    manifest: list[dict[str, Any]] = []
    relationships: list[str] = []
    for order, item in enumerate(items):
        shape_id = order + 2
        is_picture = item["outcome"] == "rasterized" or item["kind"] == "image"
        if is_picture:
            relationship_id = f"rIdImage{len(relationships) + 1}"
            _picture(tree, item, shape_id, relationship_id)
            relationships.append(item["asset_id"])
        else:
            _shape(tree, item, shape_id)
        manifest.append({
            "slide": slide_index,
            "source_id": item["source_id"],
            "shape_id": shape_id,
            "z_order": order,
            "kind": "image" if is_picture else item["kind"],
            "outcome": item["outcome"],
            "asset_sha256": item["asset_id"],
            "text_sha256": hashlib.sha256(item["text"].encode("utf-8")).hexdigest(),
            "geometry": {
                "x": _emu(item["x"]),
                "y": _emu(item["y"]),
                "cx": _emu(item["width"]),
                "cy": _emu(item["height"]),
            },
        })
    SubElement(SubElement(root, f"{{{_P}}}clrMapOvr"), f"{{{_A}}}masterClrMapping")
    return _xml(root), manifest, relationships


def _slide_background(common: Element, value: str) -> None:
    color, _ = _color(value)
    if color is None:
        return
    background = SubElement(common, f"{{{_P}}}bg")
    properties = SubElement(background, f"{{{_P}}}bgPr")
    _fill(properties, value, 1)
    SubElement(properties, f"{{{_A}}}effectLst")


def _shape(tree: Element, item: dict[str, Any], shape_id: int) -> None:
    shape = SubElement(tree, f"{{{_P}}}sp")
    non_visual = SubElement(shape, f"{{{_P}}}nvSpPr")
    SubElement(non_visual, f"{{{_P}}}cNvPr", {"id": str(shape_id), "name": item["source_id"][:80]})
    SubElement(non_visual, f"{{{_P}}}cNvSpPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    properties = SubElement(shape, f"{{{_P}}}spPr")
    _transform(properties, item)
    preset = {"rounded-rectangle": "roundRect", "ellipse": "ellipse", "line": "line"}.get(item["kind"], "rect")
    geometry = SubElement(properties, f"{{{_A}}}prstGeom", {"prst": preset})
    adjustments = SubElement(geometry, f"{{{_A}}}avLst")
    if item["kind"] == "rounded-rectangle":
        short_side = min(item["width"], item["height"])
        adjustment = max(0, min(50_000, int(round(item["radius"] / short_side * 100_000))))
        SubElement(adjustments, f"{{{_A}}}gd", {"name": "adj", "fmla": f"val {adjustment}"})
    _fill(properties, item["fill"], item["opacity"])
    _line(properties, item)
    if item["text"]:
        _text_body(shape, item)


def _picture(
    tree: Element,
    item: dict[str, Any],
    shape_id: int,
    relationship_id: str,
) -> None:
    picture = SubElement(tree, f"{{{_P}}}pic")
    non_visual = SubElement(picture, f"{{{_P}}}nvPicPr")
    SubElement(non_visual, f"{{{_P}}}cNvPr", {"id": str(shape_id), "name": item["source_id"][:80]})
    SubElement(non_visual, f"{{{_P}}}cNvPicPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    fill = SubElement(picture, f"{{{_P}}}blipFill")
    blip = SubElement(fill, f"{{{_A}}}blip", {f"{{{_R}}}embed": relationship_id})
    if item["opacity"] < 1:
        amount = max(0, min(100_000, int(round(item["opacity"] * 100_000))))
        SubElement(blip, f"{{{_A}}}alphaModFix", {"amt": str(amount)})
    crop = _crop(item)
    if any(crop.values()):
        SubElement(fill, f"{{{_A}}}srcRect", {key: str(value) for key, value in crop.items()})
    SubElement(SubElement(fill, f"{{{_A}}}stretch"), f"{{{_A}}}fillRect")
    properties = SubElement(picture, f"{{{_P}}}spPr")
    _transform(properties, item)
    preset = "roundRect" if item["radius"] > 0 else "rect"
    geometry = SubElement(properties, f"{{{_A}}}prstGeom", {"prst": preset})
    adjustments = SubElement(geometry, f"{{{_A}}}avLst")
    if preset == "roundRect":
        short_side = min(item["width"], item["height"])
        adjustment = max(0, min(50_000, int(round(item["radius"] / short_side * 100_000))))
        SubElement(adjustments, f"{{{_A}}}gd", {"name": "adj", "fmla": f"val {adjustment}"})
    _line(properties, item)


def _text_body(shape: Element, item: dict[str, Any]) -> None:
    body = SubElement(shape, f"{{{_P}}}txBody")
    insets = item["text_insets"]
    SubElement(body, f"{{{_A}}}bodyPr", {
        "wrap": "square",
        "lIns": str(_emu(insets["left"])),
        "tIns": str(_emu(insets["top"])),
        "rIns": str(_emu(insets["right"])),
        "bIns": str(_emu(insets["bottom"])),
    })
    SubElement(body, f"{{{_A}}}lstStyle")
    default_style = item["text_style"]
    paragraphs = item["paragraphs"] or [{
        "runs": [{"text": item["text"], "style": default_style}],
        "alignment": default_style.get("text_align", "left"),
        "line_height": default_style.get("line_height", "normal"),
    }]
    for paragraph_record in paragraphs:
        paragraph = SubElement(body, f"{{{_A}}}p")
        alignment = {
            "center": "ctr", "right": "r", "end": "r", "justify": "just",
        }.get(paragraph_record.get("alignment"), "l")
        paragraph_properties = SubElement(paragraph, f"{{{_A}}}pPr", {"algn": alignment})
        _line_spacing(paragraph_properties, paragraph_record.get("line_height"))
        for run_record in paragraph_record["runs"]:
            style = run_record["style"]
            run = SubElement(paragraph, f"{{{_A}}}r")
            run_properties = {"lang": "en-US", "sz": str(_font_size(style.get("font_size")))}
            weight = str(style.get("font_weight") or "")
            if weight == "bold" or (weight.isdigit() and int(weight) >= 600):
                run_properties["b"] = "1"
            if style.get("font_style") in {"italic", "oblique"}:
                run_properties["i"] = "1"
            if "underline" in str(style.get("text_decoration")):
                run_properties["u"] = "sng"
            if "line-through" in str(style.get("text_decoration")):
                run_properties["strike"] = "sngStrike"
            spacing = _character_spacing(style.get("letter_spacing"))
            if spacing is not None:
                run_properties["spc"] = str(spacing)
            run_pr = SubElement(run, f"{{{_A}}}rPr", run_properties)
            _fill(run_pr, style.get("color"), item["opacity"])
            family = str(style.get("font_family") or "Arial").split(",", 1)[0].strip(" '\"")[:64]
            SubElement(run_pr, f"{{{_A}}}latin", {"typeface": family or "Arial"})
            text = run_record["text"]
            text_node = SubElement(run, f"{{{_A}}}t")
            if text[0] in " \t\r\n" or text[-1] in " \t\r\n":
                text_node.set(f"{{{_XML}}}space", "preserve")
            text_node.text = text
        SubElement(paragraph, f"{{{_A}}}endParaRPr", {"lang": "en-US"})


def _line_spacing(paragraph_properties: Element, value: Any) -> None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)px", str(value))
    if match is None:
        return
    spacing = max(100, min(40_000, int(round(float(match.group(1)) * 50))))
    line_spacing = SubElement(paragraph_properties, f"{{{_A}}}lnSpc")
    SubElement(line_spacing, f"{{{_A}}}spcPts", {"val": str(spacing)})


def _character_spacing(value: Any) -> int | None:
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", str(value))
    if match is None:
        return None
    return max(-40_000, min(40_000, int(round(float(match.group(1)) * 75))))


def _transform(parent: Element, item: dict[str, Any]) -> None:
    rotation = int(round((item["rotation"] % 360) * 60_000))
    transform = SubElement(parent, f"{{{_A}}}xfrm", {"rot": str(rotation)})
    SubElement(transform, f"{{{_A}}}off", {"x": str(_emu(item["x"])), "y": str(_emu(item["y"]))})
    SubElement(transform, f"{{{_A}}}ext", {"cx": str(_emu(item["width"])), "cy": str(_emu(item["height"]))})


def _fill(parent: Element, value: Any, opacity: float) -> None:
    color, alpha = _color(value)
    if color is None or opacity <= 0:
        SubElement(parent, f"{{{_A}}}noFill")
        return
    solid = SubElement(parent, f"{{{_A}}}solidFill")
    rgb = SubElement(solid, f"{{{_A}}}srgbClr", {"val": color})
    effective = max(0, min(100_000, int(round(alpha * opacity * 100_000))))
    if effective < 100_000:
        SubElement(rgb, f"{{{_A}}}alpha", {"val": str(effective)})


def _line(parent: Element, item: dict[str, Any]) -> None:
    width = max(0, min(_emu(item["border_width"]), _emu(100)))
    line = SubElement(parent, f"{{{_A}}}ln", {"w": str(width)})
    color, alpha = _color(item["border_color"])
    if width <= 0 or color is None:
        SubElement(line, f"{{{_A}}}noFill")
    else:
        solid = SubElement(line, f"{{{_A}}}solidFill")
        rgb = SubElement(solid, f"{{{_A}}}srgbClr", {"val": color})
        effective = max(0, min(100_000, int(round(alpha * item["opacity"] * 100_000))))
        if effective < 100_000:
            SubElement(rgb, f"{{{_A}}}alpha", {"val": str(effective)})


def _content_types(slide_count: int, scene: NormalizedScene, referenced: set[str]) -> bytes:
    root = Element(f"{{{_CT}}}Types")
    defaults = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
    for asset_id in referenced:
        asset = scene.assets[asset_id]
        defaults[_asset_extension(asset)] = asset["mime"]
    for extension, content_type in sorted(defaults.items()):
        SubElement(root, f"{{{_CT}}}Default", {"Extension": extension, "ContentType": content_type})
    overrides = {
        "/ppt/presentation.xml": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        "/ppt/slideMasters/slideMaster1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
        "/ppt/slideLayouts/slideLayout1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
        "/ppt/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    }
    for index in range(1, slide_count + 1):
        overrides[f"/ppt/slides/slide{index}.xml"] = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
    for name, content_type in overrides.items():
        SubElement(root, f"{{{_CT}}}Override", {"PartName": name, "ContentType": content_type})
    return _xml(root)


def _presentation(slide_count: int) -> bytes:
    root = Element(f"{{{_P}}}presentation", {"saveSubsetFonts": "1"})
    master = SubElement(root, f"{{{_P}}}sldMasterIdLst")
    SubElement(master, f"{{{_P}}}sldMasterId", {"id": "2147483648", f"{{{_R}}}id": "rIdMaster"})
    slides = SubElement(root, f"{{{_P}}}sldIdLst")
    for index in range(1, slide_count + 1):
        SubElement(slides, f"{{{_P}}}sldId", {"id": str(255 + index), f"{{{_R}}}id": f"rIdSlide{index}"})
    SubElement(root, f"{{{_P}}}sldSz", {"cx": str(SLIDE_CX), "cy": str(SLIDE_CY), "type": "screen16x9"})
    SubElement(root, f"{{{_P}}}notesSz", {"cx": "6858000", "cy": "9144000"})
    return _xml(root)


def _presentation_rels(slide_count: int) -> bytes:
    root = Element(f"{{{_RELS}}}Relationships")
    SubElement(root, f"{{{_RELS}}}Relationship", {"Id": "rIdMaster", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "Target": "slideMasters/slideMaster1.xml"})
    for index in range(1, slide_count + 1):
        SubElement(root, f"{{{_RELS}}}Relationship", {"Id": f"rIdSlide{index}", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide", "Target": f"slides/slide{index}.xml"})
    return _xml(root)


def _slide_rels(relationships: list[str], media: dict[str, str]) -> bytes:
    root = Element(f"{{{_RELS}}}Relationships")
    SubElement(root, f"{{{_RELS}}}Relationship", {"Id": "rIdLayout", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "Target": "../slideLayouts/slideLayout1.xml"})
    for index, asset_id in enumerate(relationships, 1):
        SubElement(root, f"{{{_RELS}}}Relationship", {"Id": f"rIdImage{index}", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "Target": f"../media/{media[asset_id]}"})
    return _xml(root)


def _crop(item: dict[str, Any]) -> dict[str, int]:
    captured = item.get("image_crop") or {
        "left": 0, "top": 0, "right": 0, "bottom": 0,
    }
    return {
        "l": int(round(captured["left"] * 100_000)),
        "t": int(round(captured["top"] * 100_000)),
        "r": int(round(captured["right"] * 100_000)),
        "b": int(round(captured["bottom"] * 100_000)),
    }


def _color(value: Any) -> tuple[str | None, float]:
    if type(value) is not str or value in {"transparent", "rgba(0, 0, 0, 0)"}:
        return None, 0
    numbers = re.findall(r"[\d.]+", value)
    if value.startswith("rgb") and len(numbers) >= 3:
        rgb = "".join(f"{max(0, min(255, int(float(number)))):02X}" for number in numbers[:3])
        alpha = float(numbers[3]) if len(numbers) >= 4 else 1
        return rgb, max(0, min(1, alpha))
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value[1:].upper(), 1
    return None, 0


def _font_size(value: Any) -> int:
    size = float(value) if type(value) in {int, float} else 16
    return max(100, min(40_000, int(round(size * 50))))


def _asset_extension(asset: dict[str, Any]) -> str:
    return "png" if asset["mime"] == "image/png" else "jpg"


def _emu(value: float) -> int:
    return max(0, min(SLIDE_CX, int(round(value * EMU_PER_PIXEL))))


def _xml(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)
