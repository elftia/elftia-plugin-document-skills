"""Reconstruction-specific validation tests over emitted PPTX packages."""

from copy import deepcopy
from pathlib import Path
import struct
from typing import Any
from xml.etree.ElementTree import fromstring, tostring
import zipfile
import zlib

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.package import write_deterministic_zip
from document_skills_core.formats.pptx.reconstruction_models import (
    parse_reconstruction_observations,
    screen_reconstruction_raster,
)
from document_skills_core.formats.pptx.reconstruction_scene import (
    project_reconstruction_scene,
    union_area,
)
from document_skills_core.formats.pptx.reconstruction_validation import (
    with_reconstruction_gate,
)
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx


def _png(width: int = 100, height: int = 100) -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        checksum = zlib.crc32(kind + value) & 0xFFFFFFFF
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + (b"\x10\x20\x30" * width)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height, level=9))
        + chunk(b"IEND", b"")
    )


def _observation() -> dict[str, Any]:
    return {
        "canvas": {"width": 100, "height": 100},
        "elements": [
            {
                "confidence": 0.5,
                "geometry": {"x": 10, "y": 10, "width": 50, "height": 40},
                "id": "uncertain-region",
                "kind": "shape",
                "reading_order": 0,
                "source_region": {"x": 10, "y": 10, "width": 50, "height": 40},
                "style": {
                    "border_color": "#000000",
                    "border_width": 0,
                    "color": "#000000",
                    "fill": "#FFFFFF",
                    "font_family": "Arial",
                    "font_size": 20,
                    "font_weight": 400,
                    "radius": 0,
                    "text_align": "left",
                },
                "text": "",
            }
        ],
    }


def _candidate(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    raster = screen_reconstruction_raster(source)
    observations = parse_reconstruction_observations(_observation(), raster)
    private_root = tmp_path / "private"
    private_root.mkdir()
    scene, receipt = project_reconstruction_scene(
        observations,
        raster,
        private_root,
        0.75,
    )
    staged = tmp_path / "candidate.pptx"
    emission = emit_scene_pptx(staged, scene, {"title": "Validation"})
    return staged, scene, emission, receipt


def _validation() -> dict[str, Any]:
    return {"schema_version": "1.0", "status": "pass", "gates": []}


def test_reconstruction_gate_accepts_bound_cropped_picture(tmp_path: Path):
    staged, scene, emission, receipt = _candidate(tmp_path)

    validation = with_reconstruction_gate(
        _validation(),
        staged,
        scene,
        emission,
        receipt,
    )

    gate = validation["gates"][-1]
    assert gate["outcome"] == "pass"
    assert gate["evidence"]["picture_elements"] == 1


def test_reconstruction_gate_rejects_inventory_mismatch(tmp_path: Path):
    staged, scene, emission, receipt = _candidate(tmp_path)
    tampered = deepcopy(emission)
    tampered["items"][0]["source_id"] = "different"

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, tampered, receipt)


def test_reconstruction_gate_rejects_invalid_coverage(tmp_path: Path):
    staged, scene, emission, receipt = _candidate(tmp_path)
    tampered = deepcopy(receipt)
    tampered["editable_coverage"]["by_area"]["ratio"] = 1.0

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, emission, tampered)


def test_reconstruction_gate_rejects_missing_scene_crop(tmp_path: Path):
    staged, scene, emission, receipt = _candidate(tmp_path)
    scene.slides[0][0]["image_crop"] = None

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, emission, receipt)


@pytest.mark.parametrize(
    "crop",
    [
        {"bottom": 0, "left": 0, "right": 0, "top": 0},
        {"bottom": 0, "left": -0.1, "right": 0, "top": 0},
        {"bottom": 0, "left": 0.5, "right": 0.5, "top": 0},
        {"bottom": 1.0, "left": 0, "right": 0, "top": 0},
    ],
    ids=["uncropped", "negative", "horizontal-collapse", "out-of-range"],
)
def test_reconstruction_gate_rejects_invalid_scene_crop(
    tmp_path: Path,
    crop: dict[str, float],
):
    staged, scene, emission, receipt = _candidate(tmp_path)
    scene.slides[0][0]["image_crop"] = crop

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, emission, receipt)


def test_overlap_safe_union_area_never_double_counts_elements() -> None:
    rectangles = [
        {"x": 0.0, "y": 0.0, "width": 80.0, "height": 80.0},
        {"x": 20.0, "y": 20.0, "width": 80.0, "height": 80.0},
    ]

    assert union_area(rectangles) == 9_200.0
    assert union_area(rectangles) < sum(
        item["width"] * item["height"] for item in rectangles
    )


@pytest.mark.parametrize("mutation", ["missing-crop", "hidden-picture"])
def test_reconstruction_gate_rejects_unsafe_picture_xml(
    tmp_path: Path,
    mutation: str,
):
    staged, scene, emission, receipt = _candidate(tmp_path)
    with zipfile.ZipFile(staged) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    slide_name = "ppt/slides/slide1.xml"
    root = fromstring(parts[slide_name])
    picture = next(root.iter(f"{{{NS['p']}}}pic"))
    if mutation == "missing-crop":
        fill = picture.find(f"{{{NS['p']}}}blipFill")
        source_rect = fill.find(f"{{{NS['a']}}}srcRect")
        fill.remove(source_rect)
    else:
        non_visual = picture.find(f"{{{NS['p']}}}nvPicPr/{{{NS['p']}}}cNvPr")
        non_visual.set("hidden", "1")
    parts[slide_name] = tostring(root, encoding="utf-8", xml_declaration=True)
    write_deterministic_zip(staged, parts)

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, emission, receipt)


def test_reconstruction_gate_rejects_valid_but_wrong_package_crop(tmp_path: Path):
    staged, scene, emission, receipt = _candidate(tmp_path)
    with zipfile.ZipFile(staged) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    slide_name = "ppt/slides/slide1.xml"
    root = fromstring(parts[slide_name])
    picture = next(root.iter(f"{{{NS['p']}}}pic"))
    source_rect = picture.find(
        f"{{{NS['p']}}}blipFill/{{{NS['a']}}}srcRect"
    )
    source_rect.set("l", "12345")
    parts[slide_name] = tostring(root, encoding="utf-8", xml_declaration=True)
    write_deterministic_zip(staged, parts)

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, emission, receipt)


def test_reconstruction_gate_rejects_full_slide_package_transform(tmp_path: Path):
    staged, scene, emission, receipt = _candidate(tmp_path)
    with zipfile.ZipFile(staged) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    slide_name = "ppt/slides/slide1.xml"
    root = fromstring(parts[slide_name])
    picture = next(root.iter(f"{{{NS['p']}}}pic"))
    transform = picture.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}xfrm")
    offset = transform.find(f"{{{NS['a']}}}off")
    extent = transform.find(f"{{{NS['a']}}}ext")
    offset.attrib.update({"x": "0", "y": "0"})
    extent.attrib.update({"cx": "12192000", "cy": "6858000"})
    parts[slide_name] = tostring(root, encoding="utf-8", xml_declaration=True)
    write_deterministic_zip(staged, parts)

    with pytest.raises(DocumentSkillsError):
        with_reconstruction_gate(_validation(), staged, scene, emission, receipt)
