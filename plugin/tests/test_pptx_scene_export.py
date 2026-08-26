"""PPTX scene bundle export and semantic round-trip acceptance."""

import hashlib
import html
import json
from pathlib import Path
from xml.etree.ElementTree import SubElement, tostring

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.formats.pptx.constants import qn
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
    PresentationContractConsumer,
)
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.service import PptxService
from document_skills_core.formats.pptx.svg_parser import compile_svg_scene
from document_skills_core.formats.pptx.validation import validate_scene_created
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


def _owner_contract_root(project_root: Path) -> Path:
    root = project_root.parents[1] / "elftia" / "packages" / "presentation-contracts"
    assert root.is_dir()
    return root


def _source_deck(tmp_path: Path) -> Path:
    image = tmp_path / "pixel.png"
    image.write_bytes(PNG_1X1)
    table = html.escape(json.dumps({
        "header_rows": 1,
        "rows": [["Quarter", "Revenue"], ["Q1", "42"]],
    }, sort_keys=True, separators=(",", ":")), quote=True)
    chart = html.escape(json.dumps({
        "categories": ["Q1", "Q2"],
        "chart_type": "bar",
        "series": [{"name": "Revenue", "values": [42, 55]}],
    }, sort_keys=True, separators=(",", ":")), quote=True)
    svg = tmp_path / "roundtrip-source.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
        'viewBox="0 0 1920 1080">'
        '<g id="source-group">'
        '<rect id="source-shape" x="80" y="70" width="420" height="220" fill="#225588"/>'
        '<text id="source-text" x="110" y="180" textLength="340" font-size="36" fill="#FFFFFF">Round trip</text>'
        '</g>'
        f'<g id="source-table" data-elftia-kind="table" data-elftia-bounds="80,360,700,300" data-elftia-model="{table}">'
        '<rect x="80" y="360" width="700" height="300" fill="#FFFFFF"/>'
        '</g>'
        f'<g id="source-chart" data-elftia-kind="chart" data-elftia-bounds="860,90,880,570" data-elftia-model="{chart}">'
        '<rect x="860" y="90" width="880" height="570" fill="#FFFFFF"/>'
        '</g>'
        '<image id="source-image" x="80" y="740" width="220" height="180" href="pixel.png"/>'
        '</svg>',
        encoding="utf-8",
    )
    scene = compile_svg_scene(svg, fallback_policy="reject")
    source = tmp_path / "roundtrip-source.pptx"
    emit_scene_pptx(
        source,
        scene,
        {"creator": "Elftia", "subject": "B5", "title": "Round trip"},
    )
    return source


def _request(source: Path, output: Path, contract_root: Path, mode: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.scene.export",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "contract": {
                "manifest_sha256": PRESENTATION_CONTRACT_V1_PIN.manifest_sha256,
                "root": str(contract_root),
            },
            "identity": {
                "namespace": "example.synthetic",
                "source_template_id": "svg-roundtrip",
                "source_template_version": "1.0.0",
            },
            "mode": mode,
        },
    }


def test_scene_export_publishes_hash_bound_a_contract_bundle_and_roundtrips(
    project_root: Path,
    tmp_path: Path,
) -> None:
    contract_root = _owner_contract_root(project_root)
    source = _source_deck(tmp_path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "scene-bundle"

    result = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(source, output, contract_root, "strict"),
    )

    assert result["status"] == "success"
    assert result["validation"]["status"] == "pass"
    assert result["diagnostics"]["operation_result"]["unsupported"] == []
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    deck_ir = json.loads((output / "deck-ir.json").read_text(encoding="utf-8"))
    PresentationContractConsumer.open(contract_root).validate("deck-ir", deck_ir)
    assert {item["type"] for item in deck_ir["slides"][0]["objects"]} == {
        "chart",
        "image",
        "shape",
        "table",
        "text",
    }
    for member in manifest["members"]:
        payload = (output / Path(member["path"])).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == member["sha256"]
        assert len(payload) == member["bytes"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash

    exported_svg = next(output.glob("slide-*.svg"))
    scene = compile_svg_scene(exported_svg, fallback_policy="reject")
    roundtrip = tmp_path / "roundtrip.pptx"
    emission = emit_scene_pptx(
        roundtrip,
        scene,
        {"creator": "Elftia", "subject": "B5", "title": "Round trip output"},
    )
    validation = validate_scene_created(roundtrip, scene, emission)
    package = OpcPackage.open(roundtrip)

    assert validation["status"] == "pass"
    assert emission["objects"] == len(scene.slides[0])
    assert len(package.chart_parts()) == 1
    assert len(package.media_parts()) == 1
    assert b"graphicFrame" in package.parts["ppt/slides/slide1.xml"]


def test_scene_export_existing_directory_is_preserved(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _source_deck(tmp_path)
    output = tmp_path / "scene-bundle"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(source, output, _owner_contract_root(project_root), "strict"),
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_PATH_UNSAFE"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (output / "manifest.json").exists()


def test_scene_export_strict_rejects_and_tolerant_inventories_opaque_objects(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _source_deck(tmp_path)
    package = OpcPackage.open(source)
    slide_part = package.slide_parts()[0]
    payload = package.parts[slide_part]
    assert b'prst="rect"' in payload
    unsupported = tmp_path / "unsupported.pptx"
    package.write_copy(
        unsupported,
        changed_parts={
            slide_part: payload.replace(b'prst="rect"', b'prst="star5"', 1),
        },
    )
    contract_root = _owner_contract_root(project_root)

    strict_output = tmp_path / "strict-bundle"
    strict = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(unsupported, strict_output, contract_root, "strict"),
    )
    assert strict["status"] == "enhancement_required"
    assert strict["errors"][0]["code"] == "DS_UNSUPPORTED_FEATURE"
    assert not strict_output.exists()

    tolerant_output = tmp_path / "tolerant-bundle"
    tolerant = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(unsupported, tolerant_output, contract_root, "tolerant"),
    )
    assert tolerant["status"] == "degraded"
    assert tolerant["degraded"] is True
    assert tolerant["diagnostics"]["operation_result"]["unsupported"][0]["reason"] == (
        "unsupported-preset-star5"
    )
    deck_ir = json.loads((tolerant_output / "deck-ir.json").read_text(encoding="utf-8"))
    opaque = next(item for item in deck_ir["slides"][0]["objects"] if item["content"].get("shapeKind") == "opaque")
    assert opaque["editability"] == "none"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("mixed-runs", "unsupported-text-run-structure"),
        ("mixed-paragraphs", "unsupported-text-paragraph-structure"),
        ("rotation", "unsupported-rotation"),
        ("flip", "unsupported-flip"),
        ("visible-line", "unsupported-visible-line-style"),
        ("text-alignment", "unsupported-text-alignment"),
        ("text-insets", "unsupported-text-insets"),
        ("inherited-shape-style", "unsupported-inherited-shape-style"),
        ("placeholder", "unsupported-placeholder-inheritance"),
        ("inherited-text-style", "unsupported-inherited-text-style"),
    ],
)
def test_scene_export_strict_rejects_unrepresented_drawingml_semantics(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    source = _source_deck(tmp_path)
    package = OpcPackage.open(source)
    slide_part = package.slide_parts()[0]
    root = fromstring(package.parts[slide_part])
    shapes = {
        shape.find(f"{qn('p', 'nvSpPr')}/{qn('p', 'cNvPr')}").attrib["name"]: shape
        for shape in root.iter(qn("p", "sp"))
    }
    if mutation == "mixed-runs":
        paragraph = shapes["source-text"].find(
            f"{qn('p', 'txBody')}/{qn('a', 'p')}"
        )
        run = SubElement(paragraph, qn("a", "r"))
        SubElement(run, qn("a", "t")).text = "Second run"
    elif mutation == "mixed-paragraphs":
        body = shapes["source-text"].find(qn("p", "txBody"))
        SubElement(body, qn("a", "p"))
    elif mutation == "rotation":
        transform = shapes["source-shape"].find(
            f"{qn('p', 'spPr')}/{qn('a', 'xfrm')}"
        )
        transform.set("rot", "60000")
    elif mutation == "flip":
        transform = shapes["source-shape"].find(
            f"{qn('p', 'spPr')}/{qn('a', 'xfrm')}"
        )
        transform.set("flipH", "1")
    elif mutation == "visible-line":
        line = shapes["source-shape"].find(
            f"{qn('p', 'spPr')}/{qn('a', 'ln')}"
        )
        line.remove(line.find(qn("a", "noFill")))
        fill = SubElement(line, qn("a", "solidFill"))
        SubElement(fill, qn("a", "srgbClr"), {"val": "112233"})
    elif mutation == "text-alignment":
        paragraph_properties = shapes["source-text"].find(
            f"{qn('p', 'txBody')}/{qn('a', 'p')}/{qn('a', 'pPr')}"
        )
        paragraph_properties.set("algn", "ctr")
    elif mutation == "text-insets":
        body_properties = shapes["source-text"].find(
            f"{qn('p', 'txBody')}/{qn('a', 'bodyPr')}"
        )
        body_properties.set("lIns", "91440")
    elif mutation == "inherited-shape-style":
        SubElement(shapes["source-shape"], qn("p", "style"))
    elif mutation == "placeholder":
        non_visual = shapes["source-text"].find(
            f"{qn('p', 'nvSpPr')}/{qn('p', 'nvPr')}"
        )
        SubElement(non_visual, qn("p", "ph"), {"type": "body"})
    else:
        run = shapes["source-text"].find(
            f"{qn('p', 'txBody')}/{qn('a', 'p')}/{qn('a', 'r')}"
        )
        run.remove(run.find(qn("a", "rPr")))
    changed = tmp_path / f"{mutation}.pptx"
    package.write_copy(
        changed,
        changed_parts={
            slide_part: tostring(root, encoding="UTF-8", xml_declaration=True),
        },
    )

    output = tmp_path / f"{mutation}-bundle"
    result = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(changed, output, _owner_contract_root(project_root), "strict"),
    )

    assert result["status"] == "enhancement_required"
    assert result["errors"][0]["code"] == "DS_UNSUPPORTED_FEATURE"
    assert result["errors"][0]["details"]["reason"] == reason
    assert not output.exists()
