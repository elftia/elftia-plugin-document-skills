"""Direct-OOXML scene emitter fidelity and determinism tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile
from xml.etree.ElementTree import tostring

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.package import write_deterministic_zip
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.scene_normalizer import NormalizedScene
from document_skills_core.formats.pptx.validation import validate_scene_created
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


def test_scene_emitter_builds_deterministic_internal_fixed_canvas_package(tmp_path: Path):
    scene = NormalizedScene(
        slides=(
            (_item("first", x=1, y=2, width=3, height=4), _item("second", x=10, y=20)),
            (_item("third", x=100, y=200),),
        ),
        assets={},
        diagnostics={},
    )
    first = tmp_path / "first.pptx"
    second = tmp_path / "second.pptx"

    first_manifest = emit_scene_pptx(first, scene, {"title": "Deterministic"})
    second_manifest = emit_scene_pptx(second, scene, {"title": "Deterministic"})

    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(second.read_bytes()).hexdigest()
    assert first_manifest == second_manifest
    assert first_manifest["slide_size"] == {"cx": 12_192_000, "cy": 6_858_000}
    assert first_manifest["items"][0]["geometry"] == {
        "x": 6_350,
        "y": 12_700,
        "cx": 19_050,
        "cy": 25_400,
    }
    assert [entry["shape_id"] for entry in first_manifest["items"]] == [2, 3, 2]
    assert [entry["z_order"] for entry in first_manifest["items"]] == [0, 1, 0]

    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert {
            "ppt/presentation.xml",
            "ppt/theme/theme1.xml",
            "ppt/slideMasters/slideMaster1.xml",
            "ppt/slideLayouts/slideLayout1.xml",
            "ppt/slides/slide1.xml",
            "ppt/slides/slide2.xml",
        } <= names
        presentation = fromstring(archive.read("ppt/presentation.xml"))
        size = presentation.find(f"{{{NS['p']}}}sldSz")
        assert size is not None
        assert size.attrib == {"cx": "12192000", "cy": "6858000", "type": "screen16x9"}
        relationships = [
            fromstring(archive.read(name))
            for name in names
            if name.endswith(".rels")
        ]
        for root in relationships:
            for relationship in root:
                assert relationship.get("TargetMode") is None
                assert "://" not in relationship.get("Target", "")
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
        ids = [element.get("id") for element in slide.iter(f"{{{NS['p']}}}cNvPr")]
        assert ids == ["1", "2", "3"]
        group_transform = slide.find(
            f"{{{NS['p']}}}cSld/{{{NS['p']}}}spTree/"
            f"{{{NS['p']}}}grpSpPr/{{{NS['a']}}}xfrm"
        )
        assert group_transform is not None
        assert [child.tag.rsplit("}", 1)[-1] for child in group_transform] == [
            "off",
            "ext",
            "chOff",
            "chExt",
        ]


def test_scene_emitter_rejects_a_child_of_a_non_group_parent(tmp_path: Path):
    parent = _item("parent", x=10, y=20)
    child = _item("child", x=30, y=40)
    child["parent_source_id"] = "parent"
    scene = NormalizedScene(
        slides=((parent, child),),
        assets={},
        diagnostics={},
    )
    output = tmp_path / "invalid-parent.pptx"

    with pytest.raises(
        DocumentSkillsError,
        match="Scene child references a missing non-group parent",
    ):
        emit_scene_pptx(output, scene, {})

    assert not output.exists()


def test_scene_emitter_preserves_non_white_slide_background_in_output_bytes(tmp_path: Path):
    item = _item("foreground", x=10, y=20)
    colored = NormalizedScene(
        slides=((item,),),
        assets={},
        diagnostics={},
        slide_fills=("rgb(244, 238, 222)",),
    )
    transparent = NormalizedScene(slides=((item,),), assets={}, diagnostics={})
    colored_path = tmp_path / "colored.pptx"
    transparent_path = tmp_path / "transparent.pptx"

    emit_scene_pptx(colored_path, colored, {})
    emit_scene_pptx(transparent_path, transparent, {})

    assert hashlib.sha256(colored_path.read_bytes()).hexdigest() != hashlib.sha256(
        transparent_path.read_bytes()
    ).hexdigest()
    with zipfile.ZipFile(colored_path) as archive:
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
    background = slide.find(
        f"{{{NS['p']}}}cSld/{{{NS['p']}}}bg/{{{NS['p']}}}bgPr/"
        f"{{{NS['a']}}}solidFill/{{{NS['a']}}}srgbClr"
    )
    assert background is not None and background.get("val") == "F4EEDE"


def test_scene_emitter_maps_editable_geometry_rotation_fill_opacity_and_borders(tmp_path: Path):
    rectangle = _item("rectangle", x=10, y=20)
    rectangle.update(fill="rgba(100, 150, 200, 0.5)", opacity=0.5)
    rounded = _item("rounded", x=120, y=20, width=200, height=100)
    rounded.update(kind="rounded-rectangle", radius=20)
    ellipse = _item("ellipse", x=330, y=20)
    ellipse.update(kind="ellipse", rotation=45)
    line = _item("line", x=440, y=20, width=200, height=10)
    line.update(
        kind="line",
        rotation=90,
        fill="transparent",
        border_width=2,
        border_color="rgba(10, 20, 30, 0.5)",
        opacity=0.5,
    )
    output = tmp_path / "geometry.pptx"

    emit_scene_pptx(
        output,
        NormalizedScene(slides=((rectangle, rounded, ellipse, line),), assets={}, diagnostics={}),
        {},
    )

    with zipfile.ZipFile(output) as archive:
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
    shapes = {
        shape.find(f".//{{{NS['p']}}}cNvPr").get("name"): shape
        for shape in slide.iter(f"{{{NS['p']}}}sp")
    }
    assert _preset(shapes["rectangle"]) == "rect"
    rectangle_alpha = shapes["rectangle"].find(f".//{{{NS['a']}}}solidFill/{{{NS['a']}}}srgbClr/{{{NS['a']}}}alpha")
    assert rectangle_alpha is not None and rectangle_alpha.get("val") == "25000"

    rounded_geometry = shapes["rounded"].find(f".//{{{NS['a']}}}prstGeom")
    assert rounded_geometry is not None and rounded_geometry.get("prst") == "roundRect"
    adjustment = rounded_geometry.find(f"{{{NS['a']}}}avLst/{{{NS['a']}}}gd")
    assert adjustment is not None
    assert adjustment.attrib == {"name": "adj", "fmla": "val 20000"}

    assert _preset(shapes["ellipse"]) == "ellipse"
    assert shapes["ellipse"].find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}xfrm").get("rot") == "2700000"
    assert _preset(shapes["line"]) == "line"
    assert shapes["line"].find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}xfrm").get("rot") == "5400000"
    line_properties = shapes["line"].find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}ln")
    assert line_properties is not None and line_properties.get("w") == "12700"
    line_alpha = line_properties.find(f"{{{NS['a']}}}solidFill/{{{NS['a']}}}srgbClr/{{{NS['a']}}}alpha")
    assert line_alpha is not None and line_alpha.get("val") == "25000"


def test_scene_emitter_writes_editable_paragraphs_and_formatted_runs(tmp_path: Path):
    text_box = _item("text-box", x=10, y=20, width=600, height=200)
    first_style = {
        **text_box["text_style"],
        "font_family": "Aptos, Arial",
        "font_size": 32,
        "font_weight": "700",
        "color": "rgba(200, 10, 20, 0.5)",
        "letter_spacing": "2px",
    }
    second_style = {
        **text_box["text_style"],
        "font_size": 20,
        "font_style": "italic",
        "text_decoration": "underline line-through",
    }
    text_box.update(
        kind="text",
        fill="transparent",
        opacity=0.5,
        text="Bold\nItalic strike",
        paragraphs=[
            {
                "runs": [{"text": "Bold", "style": first_style}],
                "alignment": "center",
                "line_height": "44.8px",
            },
            {
                "runs": [{"text": "Italic strike", "style": second_style}],
                "alignment": "right",
                "line_height": "normal",
            },
        ],
        text_insets={"left": 10, "top": 20, "right": 30, "bottom": 40},
    )
    output = tmp_path / "text.pptx"

    emit_scene_pptx(
        output,
        NormalizedScene(slides=((text_box,),), assets={}, diagnostics={}),
        {},
    )

    with zipfile.ZipFile(output) as archive:
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
    paragraphs = list(slide.iter(f"{{{NS['a']}}}p"))
    body_properties = slide.find(f".//{{{NS['a']}}}bodyPr")
    assert body_properties is not None
    assert body_properties.attrib == {
        "wrap": "square",
        "lIns": "63500",
        "tIns": "127000",
        "rIns": "190500",
        "bIns": "254000",
    }
    assert len(paragraphs) == 2
    assert paragraphs[0].find(f"{{{NS['a']}}}pPr").get("algn") == "ctr"
    assert paragraphs[1].find(f"{{{NS['a']}}}pPr").get("algn") == "r"
    spacing = paragraphs[0].find(f"{{{NS['a']}}}pPr/{{{NS['a']}}}lnSpc/{{{NS['a']}}}spcPts")
    assert spacing is not None and spacing.get("val") == "2240"
    first_run = paragraphs[0].find(f"{{{NS['a']}}}r")
    first_properties = first_run.find(f"{{{NS['a']}}}rPr")
    assert first_properties.get("sz") == "1600"
    assert first_properties.get("b") == "1"
    assert first_properties.get("spc") == "150"
    assert first_properties.find(f"{{{NS['a']}}}latin").get("typeface") == "Aptos"
    alpha = first_properties.find(f"{{{NS['a']}}}solidFill/{{{NS['a']}}}srgbClr/{{{NS['a']}}}alpha")
    assert alpha is not None and alpha.get("val") == "25000"
    second_properties = paragraphs[1].find(f"{{{NS['a']}}}r/{{{NS['a']}}}rPr")
    assert second_properties.get("sz") == "1000"
    assert second_properties.get("i") == "1"
    assert second_properties.get("u") == "sng"
    assert second_properties.get("strike") == "sngStrike"
    assert "".join(element.text or "" for element in slide.iter(f"{{{NS['a']}}}t")) == "BoldItalic strike"


def test_scene_emitter_marks_boundary_whitespace_for_opc_consumers(tmp_path: Path):
    text_box = _item("boundary-spaces", x=10, y=20)
    style = text_box["text_style"]
    text_box.update(
        kind="text",
        text="Native editable deck",
        paragraphs=[{
            "runs": [
                {"text": "Native ", "style": style},
                {"text": "editable", "style": style},
                {"text": " deck", "style": style},
            ],
            "alignment": "left",
            "line_height": "normal",
        }],
    )
    output = tmp_path / "boundary-spaces.pptx"

    emit_scene_pptx(output, NormalizedScene(slides=((text_box,),), assets={}, diagnostics={}), {})

    with zipfile.ZipFile(output) as archive:
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
    runs = list(slide.iter(f"{{{NS['a']}}}t"))
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    assert [run.get(xml_space) for run in runs] == ["preserve", None, "preserve"]


def test_scene_emitter_packages_real_deduplicated_internal_images_with_capture_crop(tmp_path: Path):
    digest = hashlib.sha256(PNG_1X1).hexdigest()
    asset_path = tmp_path / f"asset-{digest}.png"
    asset_path.write_bytes(PNG_1X1)
    asset = {
        "id": digest,
        "filename": asset_path.name,
        "mime": "image/png",
        "bytes": len(PNG_1X1),
        "width": 1,
        "height": 1,
        "purpose": "source-image",
        "path": asset_path,
    }
    first = _item("image-one", x=10, y=20, width=200, height=100)
    first.update(
        kind="image",
        asset_id=digest,
        image_crop={"left": 0.1, "top": 0, "right": 0.4, "bottom": 0},
        object_fit="cover",
        rotation=15,
        opacity=0.5,
        border_width=4,
        border_color="rgba(10, 20, 30, 0.5)",
        radius=20,
    )
    second = {**first, "source_id": "image-two", "x": 300}
    output = tmp_path / "images.pptx"

    manifest = emit_scene_pptx(
        output,
        NormalizedScene(slides=((first, second),), assets={digest: asset}, diagnostics={}),
        {},
    )

    assert manifest["media"] == 1
    assert manifest["media_hashes"] == [digest]
    with zipfile.ZipFile(output) as archive:
        assert archive.read("ppt/media/image1.png") == PNG_1X1
        content_types = fromstring(archive.read("[Content_Types].xml"))
        png_default = next(
            entry for entry in content_types
            if entry.get("Extension") == "png"
        )
        assert png_default.get("ContentType") == "image/png"
        relationships = fromstring(archive.read("ppt/slides/_rels/slide1.xml.rels"))
        image_relationships = [entry for entry in relationships if entry.get("Type", "").endswith("/image")]
        assert [entry.get("Id") for entry in image_relationships] == ["rIdImage1", "rIdImage2"]
        assert {entry.get("Target") for entry in image_relationships} == {"../media/image1.png"}
        assert all(entry.get("TargetMode") is None for entry in image_relationships)
        slide = fromstring(archive.read("ppt/slides/slide1.xml"))
    pictures = list(slide.iter(f"{{{NS['p']}}}pic"))
    assert len(pictures) == 2
    for picture in pictures:
        crop = picture.find(f"{{{NS['p']}}}blipFill/{{{NS['a']}}}srcRect")
        assert crop is not None
        assert crop.attrib == {"l": "10000", "t": "0", "r": "40000", "b": "0"}
        assert picture.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}xfrm").get("rot") == "900000"
        alpha = picture.find(f"{{{NS['p']}}}blipFill/{{{NS['a']}}}blip/{{{NS['a']}}}alphaModFix")
        assert alpha is not None and alpha.get("amt") == "50000"
        geometry = picture.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}prstGeom")
        assert geometry is not None and geometry.get("prst") == "roundRect"
        adjustment = geometry.find(f"{{{NS['a']}}}avLst/{{{NS['a']}}}gd")
        assert adjustment is not None and adjustment.get("fmla") == "val 20000"
        line = picture.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}ln")
        assert line is not None and line.get("w") == "25400"
        line_alpha = line.find(f"{{{NS['a']}}}solidFill/{{{NS['a']}}}srgbClr/{{{NS['a']}}}alpha")
        assert line_alpha is not None and line_alpha.get("val") == "25000"


def test_scene_validation_rejects_run_redistribution_with_same_aggregate_text(tmp_path: Path):
    text_box = _item("runs", x=10, y=20, width=500, height=100)
    style = text_box["text_style"]
    text_box.update(
        kind="text",
        text="AB",
        paragraphs=[{
            "runs": [{"text": "A", "style": style}, {"text": "B", "style": style}],
            "alignment": "left",
            "line_height": "normal",
        }],
    )
    scene = NormalizedScene(slides=((text_box,),), assets={}, diagnostics={})
    clean = tmp_path / "clean.pptx"
    manifest = emit_scene_pptx(clean, scene, {})
    assert _scene_correspondence_gate(clean, scene, manifest)["outcome"] == "pass"

    with zipfile.ZipFile(clean) as archive:
        parts = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    slide = fromstring(parts["ppt/slides/slide1.xml"])
    text_nodes = list(slide.iter(f"{{{NS['a']}}}t"))
    assert [node.text for node in text_nodes] == ["A", "B"]
    text_nodes[0].text = "AB"
    text_nodes[1].text = ""
    parts["ppt/slides/slide1.xml"] = tostring(slide, encoding="UTF-8", xml_declaration=True)
    tampered = tmp_path / "tampered-runs.pptx"
    write_deterministic_zip(tampered, parts)

    assert _scene_correspondence_gate(tampered, scene, manifest)["outcome"] == "fail"


def test_scene_validation_rejects_picture_relationship_swap_with_same_media_set(tmp_path: Path):
    first_bytes = PNG_1X1
    second_bytes = PNG_1X1 + b"distinct"
    assets = {}
    items = []
    for index, payload in enumerate((first_bytes, second_bytes), 1):
        digest = hashlib.sha256(payload).hexdigest()
        asset_path = tmp_path / f"asset-{digest}.png"
        asset_path.write_bytes(payload)
        assets[digest] = {
            "id": digest,
            "filename": asset_path.name,
            "mime": "image/png",
            "bytes": len(payload),
            "width": 1,
            "height": 1,
            "purpose": "source-image",
            "path": asset_path,
        }
        item = _item(f"image-{index}", x=index * 100, y=20)
        item.update(kind="image", asset_id=digest)
        items.append(item)

    scene = NormalizedScene(slides=(tuple(items),), assets=assets, diagnostics={})
    clean = tmp_path / "clean-images.pptx"
    manifest = emit_scene_pptx(clean, scene, {})
    assert _scene_correspondence_gate(clean, scene, manifest)["outcome"] == "pass"

    with zipfile.ZipFile(clean) as archive:
        parts = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    slide = fromstring(parts["ppt/slides/slide1.xml"])
    blips = list(slide.iter(f"{{{NS['a']}}}blip"))
    embed_key = f"{{{NS['r']}}}embed"
    first_embed, second_embed = blips[0].get(embed_key), blips[1].get(embed_key)
    blips[0].set(embed_key, second_embed)
    blips[1].set(embed_key, first_embed)
    parts["ppt/slides/slide1.xml"] = tostring(slide, encoding="UTF-8", xml_declaration=True)
    tampered = tmp_path / "tampered-images.pptx"
    write_deterministic_zip(tampered, parts)

    assert _scene_correspondence_gate(tampered, scene, manifest)["outcome"] == "fail"


def _scene_correspondence_gate(
    path: Path,
    scene: NormalizedScene,
    manifest: dict[str, object],
) -> dict[str, object]:
    try:
        report = validate_scene_created(path, scene, manifest)
    except DocumentSkillsError as error:
        report = error.validation
    assert report is not None
    return next(
        gate
        for gate in report["gates"]
        if gate["id"] == "operation.scene-package-correspondence"
    )


def _item(
    source_id: str,
    *,
    x: float,
    y: float,
    width: float = 100,
    height: float = 50,
) -> dict[str, object]:
    style = {
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
    return {
        "source_id": source_id,
        "parent_source_id": None,
        "dom_ancestor_ids": [],
        "dom_index": 0,
        "z_index": 0,
        "paint_order": 0,
        "kind": "rectangle",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "rotation": 0,
        "opacity": 1,
        "fill": "rgb(255, 255, 255)",
        "border_color": "rgb(0, 0, 0)",
        "border_width": 0,
        "radius": 0,
        "text": "",
        "text_style": style,
        "text_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "paragraphs": [],
        "requested_font": "Arial",
        "font_evidence": {
            "requested_families": ["Arial"],
            "computed_family": "Arial",
            "platform_fonts": [],
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
        "outcome": "native",
        "outcome_reason": None,
    }


def _preset(shape) -> str | None:
    geometry = shape.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}prstGeom")
    return geometry.get("prst") if geometry is not None else None
