"""Constrained SVG compiler and shared scene-emitter tests."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.svg_parser import compile_svg_scene
from document_skills_core.formats.pptx.validation import validate_scene_created
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


def _write_svg(path: Path, body: str, *, definitions: str = "") -> Path:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
        'viewBox="0 0 1920 1080">'
        f"<defs>{definitions}</defs>{body}</svg>",
        encoding="utf-8",
    )
    return path


def test_native_svg_profile_compiles_to_editable_grouped_scene(tmp_path: Path) -> None:
    source = _write_svg(
        tmp_path / "native.svg",
        """
        <g id="group-main" transform="translate(20 10) scale(0.9)">
          <rect id="rect-main" x="40" y="30" width="300" height="160" rx="18" fill="#2255AA"/>
          <line id="line-main" x1="380" y1="60" x2="620" y2="180" stroke="#112233" stroke-width="4"/>
          <ellipse id="ellipse-main" cx="780" cy="150" rx="120" ry="80" fill="#55AA88"/>
          <polygon id="polygon-main" points="980,60 1160,180 920,220" fill="#AA5522"/>
          <path id="path-main" d="M 1240 80 L 1450 80 Q 1530 160 1450 240 C 1360 300 1270 260 1240 180 Z" fill="#8844AA"/>
          <text id="text-main" x="80" y="360" textLength="700" font-size="44" fill="#111111">Hello <tspan font-weight="700">SVG</tspan></text>
        </g>
        """,
    )

    scene = compile_svg_scene(source, fallback_policy="reject")

    kinds = [item["kind"] for item in scene.slides[0]]
    assert kinds == [
        "group",
        "rounded-rectangle",
        "path",
        "ellipse",
        "polygon",
        "path",
        "text",
    ]
    assert scene.diagnostics["outcomes"] == {"native": 7}
    assert scene.diagnostics["svg"]["whole_slide_fallbacks"] == 0
    assert scene.slides[0][-1]["paragraphs"][0]["runs"][1]["text"] == "SVG"

    output = tmp_path / "native.pptx"
    manifest = emit_scene_pptx(
        output,
        scene,
        {"creator": "Elftia", "subject": "B5", "title": "Native SVG"},
    )
    report = validate_scene_created(output, scene, manifest)
    package = OpcPackage.open(output)
    slide_xml = package.parts["ppt/slides/slide1.xml"]

    assert report["status"] == "pass"
    assert manifest["objects"] == 7
    assert b"grpSp" in slide_xml
    assert b"custGeom" in slide_xml
    assert b"pathLst" in slide_xml
    assert b"<p:pic" not in slide_xml


def test_gradient_and_local_image_remain_element_level(tmp_path: Path) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(PNG_1X1)
    source = _write_svg(
        tmp_path / "gradient.svg",
        """
        <rect id="gradient-card" x="100" y="80" width="800" height="420" fill="url(#approved-gradient)" fill-opacity="0.5"/>
        <image id="local-image" x="980" y="100" width="400" height="300" href="pixel.png" opacity="0.6"/>
        """,
        definitions="""
        <linearGradient id="approved-gradient" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#112233"/>
          <stop offset="1" stop-color="#88AACC" stop-opacity="0.75"/>
        </linearGradient>
        """,
    )

    scene = compile_svg_scene(source, fallback_policy="reject")
    output = tmp_path / "gradient.pptx"
    manifest = emit_scene_pptx(
        output,
        scene,
        {"creator": "Elftia", "subject": "B5", "title": "Gradient"},
    )
    package = OpcPackage.open(output)

    assert scene.diagnostics["outcomes"] == {"native": 2}
    assert scene.slides[0][0]["gradient"]["stops"] == [
        {"color": "#112233", "offset": 0.0, "opacity": 0.5},
        {"color": "#88AACC", "offset": 1.0, "opacity": 0.375},
    ]
    assert manifest["media"] == 1
    assert b"gradFill" in package.parts["ppt/slides/slide1.xml"]
    assert len(package.media_parts()) == 1


def test_paint_specific_opacity_survives_scene_and_drawingml(
    tmp_path: Path,
) -> None:
    source = _write_svg(
        tmp_path / "paint-opacity.svg",
        '<rect id="paint" x="100" y="100" width="500" height="300" '
        'fill="#204060" fill-opacity="0.5" stroke="#102030" '
        'stroke-opacity="0.25" stroke-width="4" opacity="0.8"/>',
    )

    scene = compile_svg_scene(source, fallback_policy="reject")
    item = scene.slides[0][0]
    assert item["fill"] == "rgba(32, 64, 96, 0.500000)"
    assert item["border_color"] == "rgba(16, 32, 48, 0.250000)"
    assert item["opacity"] == 0.8

    output = tmp_path / "paint-opacity.pptx"
    emit_scene_pptx(
        output,
        scene,
        {"creator": "Elftia", "subject": "B5", "title": "Paint opacity"},
    )
    slide_xml = OpcPackage.open(output).parts["ppt/slides/slide1.xml"]
    assert b'<a:alpha val="40000"' in slide_xml
    assert b'<a:alpha val="20000"' in slide_xml


def test_element_fallback_requires_explicit_local_asset_and_stays_bounded(
    tmp_path: Path,
) -> None:
    fallback = tmp_path / "fallback.png"
    fallback.write_bytes(PNG_1X1)
    source = _write_svg(
        tmp_path / "fallback.svg",
        '<rect id="filtered" x="100" y="100" width="400" height="240" '
        'fill="#224466" filter="url(#shadow)" '
        'data-pptx-fallback-image="fallback.png"/>',
        definitions='<filter id="shadow"/>',
    )

    scene = compile_svg_scene(source, fallback_policy="element-rasterize")
    item = scene.slides[0][0]

    assert item["kind"] == "image"
    assert item["outcome"] == "rasterized"
    assert item["outcome_reason"] == "unsupported_filter"
    assert scene.diagnostics["outcomes"] == {"rasterized": 1}
    assert item["width"] * item["height"] < 1920 * 1080 * 0.8


@pytest.mark.parametrize(
    "body",
    [
        '<script id="bad">alert(1)</script>',
        '<foreignObject id="bad" x="1" y="1" width="10" height="10"/>',
        '<rect id="bad" x="1" y="1" width="10" height="10" onclick="bad()"/>',
        '<image id="bad" x="1" y="1" width="10" height="10" href="https://example.invalid/a.png"/>',
        '<animate id="bad" attributeName="x"/>',
    ],
)
def test_unsafe_svg_features_fail_closed(tmp_path: Path, body: str) -> None:
    source = _write_svg(tmp_path / "unsafe.svg", body)
    with pytest.raises(DocumentSkillsError):
        compile_svg_scene(source, fallback_policy="element-rasterize")


def test_path_bomb_and_near_whole_slide_fallback_fail_closed(tmp_path: Path) -> None:
    path_bomb = "M 0 0 " + " ".join(f"L {index} {index % 100}" for index in range(3000))
    source = _write_svg(
        tmp_path / "path-bomb.svg",
        f'<path id="bomb" d="{path_bomb}"/>',
    )
    with pytest.raises(DocumentSkillsError):
        compile_svg_scene(source, fallback_policy="reject")

    fallback = tmp_path / "fallback.png"
    fallback.write_bytes(PNG_1X1)
    source = _write_svg(
        tmp_path / "whole-slide.svg",
        '<rect id="filtered" x="0" y="0" width="1920" height="1080" '
        'filter="url(#shadow)" data-pptx-fallback-image="fallback.png"/>',
        definitions='<filter id="shadow"/>',
    )
    with pytest.raises(DocumentSkillsError):
        compile_svg_scene(source, fallback_policy="element-rasterize")


def test_deep_group_nesting_fails_with_resource_limit_before_recursion(
    tmp_path: Path,
) -> None:
    body = "".join(f'<g id="group-{index}">' for index in range(65))
    body += '<rect id="leaf" x="10" y="10" width="100" height="100"/>'
    body += "</g>" * 65
    source = _write_svg(tmp_path / "deep-groups.svg", body)

    with pytest.raises(DocumentSkillsError) as captured:
        compile_svg_scene(source, fallback_policy="reject")

    assert captured.value.code.value == "DS_RESOURCE_LIMIT"
    assert captured.value.details == {"limit": 64}
