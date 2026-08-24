"""Inert inventory for advanced PPTX objects that are not mutation primitives."""

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, register_namespace

from document_skills_core.formats.pptx.constants import CONTENT_TYPES_NS, NS
from document_skills_core.formats.pptx.mutation import MutablePptxPackage
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.scaffold import _to_xml_bytes
from document_skills_core.formats.pptx.service import PptxService

_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_DIAGRAM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram"

register_namespace("m", _MATH_NS)
register_namespace("dgm", _DIAGRAM_NS)


def test_inspect_classifies_advanced_objects_inertly(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _advanced_deck(project_root, tmp_path)
    result = PptxService(project_root).execute("pptx.inspect.structure", {
        "schema_version": "1.0",
        "operation": "pptx.inspect.structure",
        "input": str(source),
        "arguments": {},
    })

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    advanced = operation["advanced_objects"]
    assert advanced["inert_only"] is True
    assert advanced["mutation_supported"] is False
    assert advanced["smartart_diagrams"]["count"] == 5
    assert {item["kind"] for item in advanced["smartart_diagrams"]["parts"]} == {
        "colors", "data", "drawing", "layout", "style",
    }
    assert {item["type"] for item in advanced["smartart_diagrams"]["relationships"]} == {
        "diagramcolors", "diagramdata", "diagramdrawing", "diagramlayout",
        "diagramquickstyle",
    }
    assert advanced["equations"]["count"] == 1
    assert advanced["equations"]["parts"][0]["slide"] == 1
    assert advanced["audio"]["count"] == 1
    assert advanced["audio"]["playback_permitted"] is False
    assert advanced["video"]["count"] == 1
    assert advanced["video"]["playback_permitted"] is False
    assert advanced["ole"]["count"] == 1
    assert advanced["ole"]["activation_permitted"] is False
    assert advanced["animations"]["count"] == 1
    assert advanced["animations"]["execution_permitted"] is False
    assert advanced["transitions"]["slides"][0]["kind"] == "fade"
    assert advanced["transitions"]["execution_permitted"] is False
    assert advanced["comments"]["count"] == 3
    assert advanced["comments"]["mutation_supported"] is False
    assert operation["mutation_authorized"] is False
    assert operation["dangerous_content"]["present"] is True
    assert all(
        len(item["sha256"]) == 64
        for group in (
            advanced["smartart_diagrams"]["parts"],
            advanced["audio"]["parts"],
            advanced["video"]["parts"],
            advanced["comments"]["parts"],
        )
        for item in group
    )


def test_advanced_inventory_respects_inspect_hash_option(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _advanced_deck(project_root, tmp_path)
    result = PptxService(project_root).execute("pptx.inspect.structure", {
        "schema_version": "1.0",
        "operation": "pptx.inspect.structure",
        "input": str(source),
        "arguments": {"include_hashes": False},
    })

    assert result["status"] == "success", result
    advanced = result["diagnostics"]["operation_result"]["advanced_objects"]
    records = [
        *advanced["smartart_diagrams"]["parts"],
        *advanced["audio"]["parts"],
        *advanced["video"]["parts"],
        *advanced["comments"]["parts"],
        *advanced["ole"]["objects"],
    ]
    assert records
    assert all("sha256" not in item for item in records)


def _advanced_deck(project_root: Path, tmp_path: Path) -> Path:
    base = tmp_path / "base.pptx"
    service = PptxService(project_root)
    created = service.execute("pptx.create", {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(base),
        "arguments": {
            "deck": {
                "metadata": {"title": "Advanced inventory", "creator": "Test", "subject": ""},
                "slides": [{
                    "layout": "content",
                    "title": "Advanced objects",
                    "shapes": [],
                    "table": None,
                    "chart_reference": None,
                    "image_reference": None,
                    "notes": None,
                }],
            }
        },
    })
    assert created["status"] == "success", created

    package = OpcPackage.open(base)
    target = MutablePptxPackage(package)
    _add_content_types(target)
    _add_advanced_parts(target)
    _add_relationships(target)
    _add_slide_markup(target)
    output = tmp_path / "advanced.pptx"
    target.emit(output)
    return output


def _add_content_types(target: MutablePptxPackage) -> None:
    root = target.xml("[Content_Types].xml")
    declarations = {
        "ppt/diagrams/colors1.xml": "application/vnd.openxmlformats-officedocument.drawingml.diagramColors+xml",
        "ppt/diagrams/data1.xml": "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
        "ppt/diagrams/drawing1.xml": "application/vnd.ms-office.drawingml.diagramDrawing+xml",
        "ppt/diagrams/layout1.xml": "application/vnd.openxmlformats-officedocument.drawingml.diagramLayout+xml",
        "ppt/diagrams/quickStyle1.xml": "application/vnd.openxmlformats-officedocument.drawingml.diagramStyle+xml",
        "ppt/media/audio1.mp3": "audio/mpeg",
        "ppt/media/video1.mp4": "video/mp4",
        "ppt/embeddings/oleObject1.bin": "application/vnd.openxmlformats-officedocument.oleObject",
        "ppt/comments/comment1.xml": "application/vnd.openxmlformats-officedocument.presentationml.comments+xml",
        "ppt/threadedComments/threadedComment1.xml": "application/vnd.ms-powerpoint.threadedcomments+xml",
        "ppt/persons/person.xml": "application/vnd.ms-powerpoint.person+xml",
    }
    for part, content_type in declarations.items():
        SubElement(
            root,
            f"{{{CONTENT_TYPES_NS}}}Override",
            {"PartName": f"/{part}", "ContentType": content_type},
        )
    target.set_part("[Content_Types].xml", _to_xml_bytes(root))


def _add_advanced_parts(target: MutablePptxPackage) -> None:
    diagram_roots = {
        "colors1.xml": "colorsDef",
        "data1.xml": "dataModel",
        "drawing1.xml": "drawing",
        "layout1.xml": "layoutDef",
        "quickStyle1.xml": "styleDef",
    }
    for name, root_name in diagram_roots.items():
        target.set_part(
            f"ppt/diagrams/{name}",
            _to_xml_bytes(Element(f"{{{_DIAGRAM_NS}}}{root_name}")),
        )
    target.set_part("ppt/media/audio1.mp3", b"ID3\x04\x00\x00inert-audio")
    target.set_part("ppt/media/video1.mp4", b"\x00\x00\x00\x18ftypmp42inert-video")
    target.set_part("ppt/embeddings/oleObject1.bin", b"inert-ole-object")
    target.set_part(
        "ppt/comments/comment1.xml",
        _to_xml_bytes(Element(f"{{{NS['p']}}}cmLst")),
    )
    target.set_part(
        "ppt/threadedComments/threadedComment1.xml",
        b'<?xml version="1.0" encoding="UTF-8"?><p188:cmLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/8/main"/>',
    )
    target.set_part(
        "ppt/persons/person.xml",
        b'<?xml version="1.0" encoding="UTF-8"?><p188:personLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/8/main"/>',
    )


def _add_relationships(target: MutablePptxPackage) -> None:
    slide_rels = target.xml("ppt/slides/_rels/slide1.xml.rels")
    entries = (
        ("rIdDiagram", "diagramData", "../diagrams/data1.xml"),
        ("rIdDiagramDrawing", "diagramDrawing", "../diagrams/drawing1.xml"),
        ("rIdAudio", "audio", "../media/audio1.mp3"),
        ("rIdVideo", "video", "../media/video1.mp4"),
        ("rIdOle", "oleObject", "../embeddings/oleObject1.bin"),
        ("rIdComments", "comments", "../comments/comment1.xml"),
    )
    for relationship_id, kind, destination in entries:
        SubElement(
            slide_rels,
            f"{{{_REL_NS}}}Relationship",
            {
                "Id": relationship_id,
                "Type": f"{_OFFICE_REL}/{kind}",
                "Target": destination,
            },
        )
    target.set_part(
        "ppt/slides/_rels/slide1.xml.rels",
        _to_xml_bytes(slide_rels),
    )

    diagram_rels = Element(f"{{{_REL_NS}}}Relationships")
    for index, (kind, destination) in enumerate((
        ("diagramColors", "colors1.xml"),
        ("diagramLayout", "layout1.xml"),
        ("diagramQuickStyle", "quickStyle1.xml"),
    ), start=1):
        SubElement(
            diagram_rels,
            f"{{{_REL_NS}}}Relationship",
            {
                "Id": f"rId{index}",
                "Type": f"{_OFFICE_REL}/{kind}",
                "Target": destination,
            },
        )
    target.set_part(
        "ppt/diagrams/_rels/data1.xml.rels",
        _to_xml_bytes(diagram_rels),
    )


def _add_slide_markup(target: MutablePptxPackage) -> None:
    slide = target.xml("ppt/slides/slide1.xml")
    equation = SubElement(slide, f"{{{_MATH_NS}}}oMath")
    SubElement(equation, f"{{{_MATH_NS}}}r")
    transition = SubElement(slide, f"{{{NS['p']}}}transition", {"spd": "fast"})
    SubElement(transition, f"{{{NS['p']}}}fade")
    timing = SubElement(slide, f"{{{NS['p']}}}timing")
    SubElement(timing, f"{{{NS['p']}}}tnLst")
    target.set_part("ppt/slides/slide1.xml", _to_xml_bytes(slide))
