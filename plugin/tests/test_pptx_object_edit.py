"""Public-contract and semantic tests for native PPTX object edits."""

from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import zipfile

from pptx import Presentation
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.contracts import parse_pptx_request
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.edit import edit_pptx
from document_skills_core.formats.pptx.object_validation import validate_object_edits
from document_skills_core.formats.pptx.object_xml import object_hash, select_object
from document_skills_core.formats.pptx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.formats.pptx.service import PptxService
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


def test_object_hash_is_independent_of_process_namespace_prefixes() -> None:
    script = """
import sys
from xml.etree.ElementTree import Element, register_namespace, SubElement

sys.path.insert(0, "src")
from document_skills_core.formats.pptx.object_xml import object_hash

namespace = "http://schemas.openxmlformats.org/drawingml/2006/main"
register_namespace(sys.argv[1], namespace)
element = Element(f"{{{namespace}}}root")
SubElement(element, f"{{{namespace}}}child", {f"{{{namespace}}}value": "x"})
print(object_hash(element))
"""
    project_root = Path(__file__).parents[1]

    def hash_from_process(prefix: str) -> str:
        return subprocess.run(
            [sys.executable, "-c", script, prefix],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    assert hash_from_process("first") == hash_from_process("second")


def _deck() -> dict[str, object]:
    return {
        "metadata": {"title": "Object edits", "creator": "Test", "subject": ""},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": [{
            "layout": "content",
            "title": "Object editing",
            "shapes": [{"text": "Existing body", "runs": []}],
            "table": None,
            "chart_reference": None,
            "image_reference": None,
            "notes": None,
        }],
    }


def _created(tmp_path: Path, name: str = "object-source.pptx") -> Path:
    source = tmp_path / name
    create_pptx(source, _deck())
    return source


def _shape(name: str) -> dict[str, object]:
    return {
        "name": name,
        "geometry": "roundRect",
        "frame": {"x": 500_000, "y": 2_000_000, "cx": 2_500_000, "cy": 900_000},
        "fill": "336699",
        "line": {"color": "112233", "width": 20_000},
        "opacity": 0.8,
        "rotation": 5,
        "shadow": {"color": "000000", "opacity": 0.25},
        "text": "Editable text",
        "z_order": 2,
    }


def _table(name: str) -> dict[str, object]:
    return {
        "name": name,
        "frame": {"x": 400_000, "y": 1_500_000, "cx": 4_000_000, "cy": 1_600_000},
        "rows": [["A", "B"], ["C", "D"]],
        "widths": [2_000_000, 2_000_000],
        "heights": [800_000, 800_000],
        "merges": [],
        "z_order": 3,
    }


def _chart(name: str, chart_type: str = "column") -> dict[str, object]:
    return {
        "name": name,
        "frame": {"x": 500_000, "y": 1_500_000, "cx": 5_000_000, "cy": 3_000_000},
        "title": f"{name} title",
        "chart_type": chart_type,
        "categories": ["One", "Two"],
        "series": [{"name": "Series", "values": [1, 2]}],
        "legend": {"show": True, "position": "right"},
        "axes": {"value": {"title": "Value", "number_format": "0"}},
        "data_labels": {"show_value": True},
        "colors": ["4472C4"],
        "z_order": 4,
    }


def _image(name: str, path: Path) -> dict[str, object]:
    return {
        "name": name,
        "path": str(path),
        "content_type": "image/png",
        "fit": "cover",
        "crop": {"left": 0.05, "top": 0, "right": 0, "bottom": 0},
        "opacity": 0.9,
        "rotation": 3,
        "alt_text": f"{name} alternative",
        "z_order": 5,
        "frame": {"x": 4_800_000, "y": 1_500_000, "cx": 2_000_000, "cy": 2_000_000},
    }


def _parsed_edits(
    source: Path,
    output: Path,
    edits: list[dict[str, object]],
) -> list[dict[str, object]]:
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"edits": edits},
    })
    return parsed.arguments["edits"]


def _all_object_edits(image_a: Path, image_b: Path) -> list[dict[str, object]]:
    selector = {"name": "Editable", "type": "shape"}
    return [
        {"type": "shape_add", "slide": 1, "object": _shape("Editable")},
        {
            "type": "shape_update",
            "slide": 1,
            "selector": selector,
            "properties": {
                "fill": {"color": "AA5500"},
                "opacity": 0.6,
                "rotation": 12,
                "shadow": {"color": "111111", "blur": 60_000},
                "z_order": 1,
            },
        },
        {
            "type": "text_update",
            "slide": 1,
            "selector": selector,
            "properties": {"paragraphs": ["First", "Second"]},
        },
        {
            "type": "text_style",
            "slide": 1,
            "selector": selector,
            "properties": {
                "alignment": "center",
                "autofit": True,
                "bold": True,
                "bullet": True,
                "color": "FFFFFF",
                "font": "Arial",
                "font_size": 20,
                "italic": True,
                "line_spacing": 1.2,
                "numbering": False,
                "underline": True,
            },
        },
        {"type": "action_add", "slide": 1, "selector": selector, "action": "next"},
        {"type": "action_update", "slide": 1, "selector": selector, "action": "last"},
        {"type": "action_remove", "slide": 1, "selector": selector},
        {"type": "hyperlink_add", "slide": 1, "selector": selector, "target_slide": 1},
        {"type": "hyperlink_update", "slide": 1, "selector": selector, "target_slide": 1},
        {"type": "hyperlink_remove", "slide": 1, "selector": selector},
        {"type": "shape_delete", "slide": 1, "selector": selector},
        {"type": "image_add", "slide": 1, "object": _image("Picture", image_a)},
        {
            "type": "image_crop",
            "slide": 1,
            "selector": {"name": "Picture", "type": "image"},
            "properties": {
                "fit": "contain",
                "crop": {"left": 0, "top": 0.1, "right": 0, "bottom": 0},
                "opacity": 0.7,
                "rotation": 8,
                "z_order": 2,
            },
        },
        {
            "type": "image_replace",
            "slide": 1,
            "selector": {"name": "Picture", "type": "image"},
            "object": _image("Replacement picture", image_b),
        },
        {
            "type": "image_delete",
            "slide": 1,
            "selector": {"name": "Replacement picture", "type": "image"},
        },
        {"type": "table_add", "slide": 1, "object": _table("Data table")},
        {
            "type": "table_update",
            "slide": 1,
            "selector": {"name": "Data table", "type": "table"},
            "properties": {
                "name": "Updated table",
                "rows": [["Merged", ""], ["Three", "Four"]],
                "merges": [{"row": 1, "column": 1, "row_span": 1, "column_span": 2}],
            },
        },
        {
            "type": "table_delete",
            "slide": 1,
            "selector": {"name": "Updated table", "type": "table"},
        },
        {"type": "chart_add", "slide": 1, "object": _chart("Sales chart")},
        {
            "type": "chart_update",
            "slide": 1,
            "selector": {"name": "Sales chart", "type": "chart"},
            "object": _chart("Updated chart", "line"),
        },
        {
            "type": "chart_delete",
            "slide": 1,
            "selector": {"name": "Updated chart", "type": "chart"},
        },
        {"type": "notes_update", "slide": 1, "value": "New speaker notes"},
    ]


def test_contract_accepts_every_object_primitive(tmp_path: Path) -> None:
    source = _created(tmp_path)
    image_a = tmp_path / "image-a.png"
    image_b = tmp_path / "image-b.png"
    image_a.write_bytes(PNG_1X1)
    image_b.write_bytes(PNG_1X1)
    edits = _parsed_edits(
        source,
        tmp_path / "contract-output.pptx",
        _all_object_edits(image_a, image_b),
    )
    assert {edit["type"] for edit in edits} == {
        "action_add", "action_remove", "action_update",
        "chart_add", "chart_delete", "chart_update",
        "hyperlink_add", "hyperlink_remove", "hyperlink_update",
        "image_add", "image_crop", "image_delete", "image_replace",
        "notes_update", "shape_add", "shape_delete", "shape_update",
        "table_add", "table_delete", "table_update", "text_style", "text_update",
    }


def test_all_object_primitives_are_transactional_and_consumer_reopen(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _created(tmp_path)
    source_hash = sha256(source.read_bytes()).hexdigest()
    image_a = tmp_path / "image-a.png"
    image_b = tmp_path / "image-b.png"
    image_a.write_bytes(PNG_1X1)
    image_b.write_bytes(PNG_1X1)
    output = tmp_path / "all-object-edits.pptx"
    edits = _all_object_edits(image_a, image_b)
    service = PptxService(project_root)
    result = service.execute("pptx.edit", {
        "schema_version": "1.0",
        "operation": "pptx.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"edits": edits},
    })

    assert result["status"] == "success", result
    assert sha256(source.read_bytes()).hexdigest() == source_hash
    assert len(Presentation(output).slides) == 1
    package = OpcPackage.open(output)
    assert len(package.media_parts()) == 0
    assert len(package.chart_parts()) == 0
    assert len(package.notes_slide_parts()) == 1
    evidence = result["diagnostics"]["operation_result"]["object_edits"]
    assert len(evidence) == len(edits)
    outcomes = {gate["id"]: gate["outcome"] for gate in result["validation"]["gates"]}
    assert outcomes["operation.mutation-semantics"] == "pass"


def test_object_precondition_uses_selected_object_hash(tmp_path: Path) -> None:
    source = _created(tmp_path)
    package = OpcPackage.open(source)
    selected = select_object(
        package.xml("ppt/slides/slide1.xml"),
        {"id": None, "name": "Shape3", "type": "shape"},
    )
    digest = object_hash(selected)
    projected, _warnings = read_pptx(source, {})
    projected_shape = next(
        item
        for item in projected["slides"][0]["shapes"]
        if item["name"] == "Shape3"
    )
    assert projected_shape["selector"] == {
        "id": "3",
        "name": "Shape3",
        "type": "shape",
    }
    assert projected_shape["precondition_sha256"] == digest
    output = tmp_path / "precondition-pass.pptx"
    edits = _parsed_edits(source, output, [{
        "type": "text_update",
        "slide": 1,
        "selector": {"name": "Shape3", "type": "shape"},
        "precondition_sha256": digest,
        "properties": {"text": "Precondition passed"},
    }])
    edit_pptx(source, output, {"edits": edits})
    assert output.is_file()

    rejected = tmp_path / "precondition-rejected.pptx"
    stale = [{**edits[0], "precondition_sha256": "0" * 64}]
    with pytest.raises(DocumentSkillsError) as captured:
        edit_pptx(source, rejected, {"edits": stale})
    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert captured.value.details["scope"] == "object"
    assert not rejected.exists()


def test_contract_rejects_external_action_and_object_type_mismatch(tmp_path: Path) -> None:
    source = _created(tmp_path)
    with pytest.raises(DocumentSkillsError) as external:
        _parsed_edits(source, tmp_path / "external.pptx", [{
            "type": "hyperlink_add",
            "slide": 1,
            "selector": {"name": "Shape3"},
            "target": "https://example.com",
        }])
    assert external.value.code == ErrorCode.REQUEST_INVALID

    output = tmp_path / "mismatch.pptx"
    edits = _parsed_edits(source, output, [{
        "type": "image_delete",
        "slide": 1,
        "selector": {"name": "Shape3"},
    }])
    with pytest.raises(DocumentSkillsError) as mismatch:
        edit_pptx(source, output, {"edits": edits})
    assert mismatch.value.code == ErrorCode.REQUEST_INVALID
    assert not output.exists()



def test_object_validator_rejects_tampered_object(tmp_path: Path) -> None:
    source = _created(tmp_path)
    output = tmp_path / "edited.pptx"
    edits = _parsed_edits(source, output, [{
        "type": "text_update",
        "slide": 1,
        "selector": {"name": "Shape3", "type": "shape"},
        "properties": {"text": "Validated text"},
    }])
    operation_result, _manifest = edit_pptx(source, output, {"edits": edits})
    parts: dict[str, bytes] = {}
    with zipfile.ZipFile(output) as archive:
        for info in archive.infolist():
            if not info.is_dir():
                parts[info.filename] = archive.read(info)
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        b"Validated text",
        b"Tampered text",
    )
    tampered = tmp_path / "tampered.pptx"
    write_deterministic_zip(tampered, parts)

    with pytest.raises(DocumentSkillsError) as captured:
        validate_object_edits(tampered, edits=edits, operation_result=operation_result)
    assert captured.value.code == ErrorCode.VALIDATION_FAILED
