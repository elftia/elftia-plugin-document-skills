"""Public-truth tests for typed native PPTX images and charts."""

from pathlib import Path
import struct
from typing import Any
import zlib

from PIL import Image
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.contracts import parse_pptx_request
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.image import load_pptx_image
from document_skills_core.formats.pptx.inspect import inspect_pptx
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.formats.pptx.validation import validate_created

_GIF_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def _png(width: int = 2, height: int = 1) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x33\x66\x99\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _oversized_png_header(width: int, height: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    tag = b"IHDR"
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(header))
        + tag
        + header
        + struct.pack(">I", zlib.crc32(tag + header) & 0xFFFFFFFF)
    )


def _slide(**overrides: Any) -> dict[str, Any]:
    slide: dict[str, Any] = {
        "layout": "content",
        "title": "Native object",
        "shapes": [{"text": "Editable text", "runs": []}],
        "table": None,
        "chart_reference": None,
        "image_reference": None,
        "notes": None,
    }
    slide.update(overrides)
    return slide


def _deck(slides: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "metadata": {"title": "Typed truth", "creator": "Test", "subject": ""},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": slides,
    }


def _chart(kind: str) -> dict[str, Any]:
    common: dict[str, Any] = {
        "title": f"{kind.title()} chart",
        "chart_type": kind,
        "legend": {"show": True, "position": "bottom"},
        "data_labels": {
            "show_category_name": kind == "pie",
            "show_series_name": False,
            "show_value": True,
        },
        "colors": ["3366CC", "DC3912"],
    }
    if kind == "scatter":
        return {
            **common,
            "categories": ["ignored"],
            "series": [
                {"name": "Trend", "x_values": [1.0, 2.0, 3.0], "y_values": [2.0, 4.0, 8.0]}
            ],
            "axes": {
                "x": {"title": "X", "number_format": "0.0"},
                "y": {"title": "Y", "number_format": "0.0"},
            },
        }
    return {
        **common,
        "categories": ["A", "B", "C"],
        "series": [
            {"name": "Actual", "values": [3.0, 5.0, 8.0]},
            {"name": "Plan", "values": [4.0, 6.0, 7.0]},
        ],
        "axes": {
            "category": {"title": "Category", "number_format": "General"},
            "value": {"title": "Units", "number_format": "0"},
        },
    }


def test_contract_accepts_real_image_and_chart_properties(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(_png())
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(tmp_path / "out.pptx"),
        "arguments": {
            "deck": _deck([
                _slide(
                    image_reference={
                        "path": str(image),
                        "content_type": "image/png",
                        "fit": "cover",
                        "crop": {"left": 0.1, "top": 0.0, "right": 0.0, "bottom": 0.0},
                        "opacity": 0.75,
                        "rotation": 15,
                        "alt_text": "Evidence image",
                        "z_order": 20,
                        "frame": {"x": 10, "y": 20, "cx": 300, "cy": 200},
                    },
                    chart_reference=_chart("line"),
                )
            ]),
        },
    })
    image_request = parsed.arguments["deck"]["slides"][0]["image_reference"]
    chart_request = parsed.arguments["deck"]["slides"][0]["chart_reference"]
    assert image_request["path"] == image.resolve()
    assert image_request["fit"] == "cover"
    assert image_request["opacity"] == 0.75
    assert chart_request["chart_type"] == "line"
    assert chart_request["series"][0]["values"] == [3.0, 5.0, 8.0]


@pytest.mark.parametrize(
    "image_reference",
    [
        {"path": "https://example.invalid/image.png"},
        {"path": "image.png", "fit": "placeholder"},
        {"path": "image.png", "crop": {"left": 0.8, "right": 0.3}},
        {"path": "image.png", "content_type": "image/svg+xml"},
    ],
)
def test_contract_rejects_unsafe_or_unsupported_image_requests(
    tmp_path: Path,
    image_reference: dict[str, Any],
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.create",
            "output": str(tmp_path / "out.pptx"),
            "arguments": {"deck": _deck([_slide(image_reference=image_reference)])},
        })
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_create_embeds_distinct_png_jpeg_and_static_gif_bytes(tmp_path: Path) -> None:
    png = tmp_path / "asset.png"
    png.write_bytes(_png(3, 2))
    jpeg = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (4, 2), (12, 34, 56)).save(jpeg, "JPEG", exif=exif)
    gif = tmp_path / "asset.gif"
    gif.write_bytes(_GIF_1X1)
    assets = [
        (png, "image/png", "PNG"),
        (jpeg, "image/jpeg", "JPEG"),
        (gif, "image/gif", "GIF"),
    ]
    deck = _deck([
        _slide(image_reference={
            "path": path,
            "content_type": content_type,
            "alt_text": alt,
            "fit": "contain",
        })
        for path, content_type, alt in assets
    ])
    output = tmp_path / "images.pptx"
    creation = create_pptx(output, deck)
    report = validate_created(output, deck, creation)
    package = OpcPackage.open(output)

    assert report["status"] == "pass"
    assert [item["embedded_media_part"] for item in creation["images"]] == [
        "ppt/media/image1.png",
        "ppt/media/image2.jpg",
        "ppt/media/image3.gif",
    ]
    for record, (source, content_type, _alt) in zip(creation["images"], assets, strict=True):
        assert package.parts[record["embedded_media_part"]] == source.read_bytes()
        assert record["content_type"] == content_type
        assert record["fallback"] == "native"
    assert creation["images"][1]["exif_orientation"] == 6
    second_slide = package.xml("ppt/slides/slide2.xml")
    transform = next(
        node
        for node in second_slide.iter(f"{{{NS['a']}}}xfrm")
        if "rot" in node.attrib
    )
    assert transform.attrib["rot"] == "5400000"


def test_image_loader_rejects_content_type_mismatch_and_pixel_bomb(tmp_path: Path) -> None:
    png = tmp_path / "asset.png"
    png.write_bytes(_png())
    mismatch = _deck([_slide(image_reference={"path": png, "content_type": "image/jpeg"})])
    with pytest.raises(DocumentSkillsError) as captured:
        create_pptx(tmp_path / "mismatch.pptx", mismatch)
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_image_fit_crop_opacity_rotation_alt_text_and_z_order_are_native(tmp_path: Path) -> None:
    image_path = tmp_path / "styled.png"
    image_path.write_bytes(_png(4, 2))
    deck = _deck([
        _slide(
            chart_reference=_chart("column"),
            image_reference={
                "path": image_path,
                "content_type": "image/png",
                "fit": "cover",
                "crop": {"left": 0.1, "top": 0.0, "right": 0.0, "bottom": 0.0},
                "opacity": 0.25,
                "rotation": 15.0,
                "alt_text": "Styled native image",
                "z_order": 50,
                "frame": {"x": 100, "y": 200, "cx": 1_000, "cy": 1_000},
            },
        )
    ])
    output = tmp_path / "styled.pptx"
    creation = create_pptx(output, deck)
    validate_created(output, deck, creation)
    slide = OpcPackage.open(output).xml("ppt/slides/slide1.xml")

    picture = next(slide.iter(f"{{{NS['p']}}}pic"))
    alt = next(picture.iter(f"{{{NS['p']}}}cNvPr"))
    assert alt.attrib["descr"] == "Styled native image"
    alpha = next(picture.iter(f"{{{NS['a']}}}alphaModFix"))
    assert alpha.attrib["amt"] == "25000"
    crop = next(picture.iter(f"{{{NS['a']}}}srcRect"))
    assert int(crop.attrib["l"]) > 25_000
    transform = next(picture.iter(f"{{{NS['a']}}}xfrm"))
    assert transform.attrib["rot"] == "900000"
    shape_tree = next(slide.iter(f"{{{NS['p']}}}spTree"))
    drawable_types = [node.tag.rsplit("}", 1)[-1] for node in list(shape_tree)[2:]]
    assert drawable_types == ["pic", "sp", "graphicFrame", "sp"]


@pytest.mark.parametrize(
    ("fit", "expected_frame", "cropped"),
    [
        ("contain", {"x": 0, "y": 250, "cx": 1_000, "cy": 500}, False),
        ("cover", {"x": 0, "y": 0, "cx": 1_000, "cy": 1_000}, True),
        ("stretch", {"x": 0, "y": 0, "cx": 1_000, "cy": 1_000}, False),
    ],
)
def test_image_fit_modes_map_to_expected_native_geometry(
    tmp_path: Path,
    fit: str,
    expected_frame: dict[str, int],
    cropped: bool,
) -> None:
    image_path = tmp_path / f"{fit}.png"
    image_path.write_bytes(_png(4, 2))
    loaded = load_pptx_image({
        "path": image_path,
        "content_type": "image/png",
        "fit": fit,
        "frame": {"x": 0, "y": 0, "cx": 1_000, "cy": 1_000},
    }, 1)
    assert loaded["frame"] == expected_frame
    assert any(loaded["crop"].values()) is cropped


def test_image_loader_rejects_animated_gif(tmp_path: Path) -> None:
    animated = tmp_path / "animated.gif"
    first = Image.new("RGB", (1, 1), (0, 0, 0))
    second = Image.new("RGB", (1, 1), (255, 255, 255))
    first.save(animated, "GIF", save_all=True, append_images=[second], duration=100, loop=0)
    with pytest.raises(DocumentSkillsError) as captured:
        create_pptx(
            tmp_path / "animated.pptx",
            _deck([_slide(image_reference={"path": animated, "content_type": "image/gif"})]),
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID

    bomb = tmp_path / "bomb.png"
    bomb.write_bytes(_oversized_png_header(10_000, 10_000))
    with pytest.raises(DocumentSkillsError) as captured:
        create_pptx(
            tmp_path / "bomb.pptx",
            _deck([_slide(image_reference={"path": bomb, "content_type": "image/png"})]),
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_create_emits_all_required_native_chart_types_and_reopens(tmp_path: Path) -> None:
    from pptx import Presentation

    kinds = ["bar", "column", "line", "pie", "scatter"]
    deck = _deck([_slide(chart_reference=_chart(kind)) for kind in kinds])
    output = tmp_path / "charts.pptx"
    creation = create_pptx(output, deck)
    validation = validate_created(output, deck, creation)
    operation_result, _warnings = read_pptx(output, {})
    inspection, _warnings = inspect_pptx(output, {})

    assert validation["status"] == "pass"
    assert [item["chart_type"] for item in operation_result["charts"]] == kinds
    assert all(item["series"] for item in operation_result["charts"])
    assert [len(item["axes"]) for item in operation_result["charts"]] == [2, 2, 2, 0, 2]
    assert operation_result["charts"][4]["series"][0]["x_values"] == [1.0, 2.0, 3.0]
    assert operation_result["charts"][4]["series"][0]["y_values"] == [2.0, 4.0, 8.0]
    assert inspection["charts"] == operation_result["charts"]
    first_chart = OpcPackage.open(output).xml("ppt/charts/chart1.xml")
    assert next(first_chart.iter(f"{{{NS['c']}}}legendPos")).attrib["val"] == "b"
    assert next(first_chart.iter(f"{{{NS['c']}}}showVal")).attrib["val"] == "1"
    assert next(first_chart.iter(f"{{{NS['a']}}}srgbClr")).attrib["val"] == "3366CC"
    number_formats = [node.attrib["formatCode"] for node in first_chart.iter(f"{{{NS['c']}}}numFmt")]
    assert number_formats == ["General", "0"]
    presentation = Presentation(output)
    assert sum(
        1
        for slide in presentation.slides
        for shape in slide.shapes
        if getattr(shape, "has_chart", False)
    ) == 5


def test_validator_rejects_chart_cache_tampering(tmp_path: Path) -> None:
    deck = _deck([_slide(chart_reference=_chart("line"))])
    output = tmp_path / "chart.pptx"
    creation = create_pptx(output, deck)
    package = OpcPackage.open(output)
    chart = package.xml("ppt/charts/chart1.xml")
    numeric_cache = next(chart.iter(f"{{{NS['c']}}}numLit"))
    first_value = next(numeric_cache.iter(f"{{{NS['c']}}}v"))
    first_value.text = "tampered"
    from document_skills_core.formats.pptx.scaffold import _to_xml_bytes

    doctored = tmp_path / "doctored.pptx"
    package.write_copy(
        doctored,
        changed_parts={"ppt/charts/chart1.xml": _to_xml_bytes(chart)},
    )
    with pytest.raises(DocumentSkillsError) as captured:
        validate_created(doctored, deck, creation)
    assert captured.value.code == ErrorCode.VALIDATION_FAILED
