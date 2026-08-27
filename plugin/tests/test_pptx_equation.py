"""Native OMML construction, readback, validation, and transactional edit tests."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring
import zipfile

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.constants import NS, local_name
from document_skills_core.formats.pptx.contracts import parse_deck, parse_pptx_request
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.edit import edit_pptx
from document_skills_core.formats.pptx.object_validation import validate_object_edits
from document_skills_core.formats.pptx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.formats.pptx.template_create import create_pptx_from_template
from document_skills_core.formats.pptx.validation import validate_created


def _equation(
    equation_id: str,
    latex: str,
    *,
    x: float = 0.5,
    y: float = 1.0,
) -> dict[str, Any]:
    return {
        "type": "equation",
        "id": equation_id,
        "bbox": {"x": x, "y": y, "w": 4.0, "h": 0.7},
        "source": {"kind": "latex", "value": latex},
        "fallback": "reject",
    }


def _deck(equations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "metadata": {
            "title": "Editable equations",
            "creator": "Elftia",
            "subject": "B6",
        },
        "slides": [
            {
                "layout": "content",
                "title": "Office Math",
                "shapes": equations,
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": None,
            }
        ],
    }


def _supported_deck() -> dict[str, Any]:
    sources = [
        ("eq-fraction", r"\frac{1}{2}", 0.7),
        ("eq-scripts", "x_i^2", 1.5),
        ("eq-sum", r"\sum_{i=1}^{n}i", 2.3),
        ("eq-root", r"\sqrt[3]{x}", 3.1),
        ("eq-matrix", r"\begin{matrix}a & b \\ c & d\end{matrix}", 3.9),
        ("eq-greek", r"\alpha+\beta=\Gamma", 4.7),
    ]
    return parse_deck(
        _deck([_equation(equation_id, latex, y=y) for equation_id, latex, y in sources])
    )


def _parsed_edits(
    source: Path,
    output: Path,
    edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return parse_pptx_request(
        {
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"edits": edits},
        }
    ).arguments["edits"]


def _mutate_slide(
    source: Path,
    output: Path,
    mutation: Any,
) -> Path:
    from defusedxml.ElementTree import fromstring

    with zipfile.ZipFile(source) as archive:
        parts = {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }
    root = fromstring(parts["ppt/slides/slide1.xml"])
    mutation(root)
    parts["ppt/slides/slide1.xml"] = tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
    )
    write_deterministic_zip(output, parts)
    return output


def _math_wrapper(root: Element) -> Element:
    return deepcopy(
        next(
            node
            for node in root.iter()
            if node.tag == f"{{{NS['a14']}}}m"
        )
    )


def _append_run(paragraph: Element, text: str) -> None:
    run = SubElement(paragraph, f"{{{NS['a']}}}r")
    SubElement(run, f"{{{NS['a']}}}t").text = text


def _mix_text_and_math(root: Element) -> None:
    tree = next(node for node in root.iter() if local_name(node.tag) == "spTree")
    alternate = next(
        child for child in tree if local_name(child.tag) == "AlternateContent"
    )
    math = _math_wrapper(alternate)
    shape = next(
        child
        for child in tree
        if local_name(child.tag) == "sp"
        and any(local_name(node.tag) == "t" for node in child.iter())
    )
    paragraph = next(
        node for node in shape.iter() if node.tag == f"{{{NS['a']}}}p"
    )
    for child in list(paragraph):
        paragraph.remove(child)
    _append_run(paragraph, "before")
    paragraph.append(deepcopy(math))
    _append_run(paragraph, "middle")
    paragraph.append(deepcopy(math))
    _append_run(paragraph, "after")
    tree.remove(alternate)


def _group_text_and_math(root: Element) -> None:
    tree = next(node for node in root.iter() if local_name(node.tag) == "spTree")
    alternate = next(
        child for child in tree if local_name(child.tag) == "AlternateContent"
    )
    choice = next(
        child for child in alternate if local_name(child.tag) == "Choice"
    )
    equation_shape = deepcopy(
        next(child for child in choice if local_name(child.tag) == "sp")
    )
    ordinary = next(
        child
        for child in tree
        if local_name(child.tag) == "sp"
        and any(local_name(node.tag) == "t" for node in child.iter())
    )
    tree.remove(ordinary)
    tree.remove(alternate)
    group = Element(f"{{{NS['p']}}}grpSp")
    non_visual = SubElement(group, f"{{{NS['p']}}}nvGrpSpPr")
    SubElement(
        non_visual,
        f"{{{NS['p']}}}cNvPr",
        {"id": "900", "name": "Mixed equation group"},
    )
    SubElement(non_visual, f"{{{NS['p']}}}cNvGrpSpPr")
    SubElement(non_visual, f"{{{NS['p']}}}nvPr")
    SubElement(group, f"{{{NS['p']}}}grpSpPr")
    group.append(ordinary)
    group.append(equation_shape)
    tree.append(group)


def test_create_emits_native_office_math_and_canonical_readback(
    tmp_path: Path,
) -> None:
    deck = _supported_deck()
    output = tmp_path / "equations.pptx"

    creation = create_pptx(output, deck)
    validation = validate_created(output, deck, creation)
    readback, warnings = read_pptx(output, {})

    assert validation["status"] == "pass"
    assert warnings == []
    assert creation["has_equation"] is True
    assert len(creation["equations"]) == 6
    equations = [
        shape["equation"]
        for shape in readback["slides"][0]["shapes"]
        if shape["type"] == "equation"
    ]
    assert [item["id"] for item in equations] == [
        "eq-fraction",
        "eq-scripts",
        "eq-sum",
        "eq-root",
        "eq-matrix",
        "eq-greek",
    ]
    assert all(item["editable"] is True for item in equations)
    assert all(item["readback"] == {"status": "pass"} for item in equations)

    slide = OpcPackage.open(output).xml("ppt/slides/slide1.xml")
    assert len(list(slide.iter(f"{{{NS['a14']}}}m"))) == 6
    assert len(list(slide.iter(f"{{{NS['m']}}}oMath"))) == 6
    assert not list(slide.iter(f"{{{NS['p']}}}oleObj"))
    assert not list(slide.iter(f"{{{NS['a']}}}blip"))

    missing_evidence = deepcopy(creation)
    missing_evidence["equations"] = []
    with pytest.raises(DocumentSkillsError) as captured:
        validate_created(output, deck, missing_evidence)
    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    rejected = captured.value.validation
    assert rejected is not None
    assert rejected["status"] == "fail"
    assert any(
        gate["id"] == "operation.native-object-correspondence"
        and gate["outcome"] == "fail"
        for gate in rejected["gates"]
    )


def test_equation_upsert_updates_by_stable_selector_and_adds_natively(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pptx"
    deck = parse_deck(_deck([_equation("eq-energy", "E=mc^2")]))
    create_pptx(source, deck)
    source_hash = sha256(source.read_bytes()).hexdigest()
    projected, _warnings = read_pptx(source, {})
    original = next(
        shape
        for shape in projected["slides"][0]["shapes"]
        if shape["type"] == "equation"
    )
    output = tmp_path / "updated.pptx"
    edits = _parsed_edits(
        source,
        output,
        [
            {
                "type": "equation_upsert",
                "slide": 1,
                "selector": original["selector"],
                "precondition_sha256": original["precondition_sha256"],
                "equation": _equation("eq-energy", r"E=\frac{mc^2}{2}"),
            },
            {
                "type": "equation_upsert",
                "slide": 1,
                "equation": _equation("eq-root", r"\sqrt{x}", x=5.0),
            },
        ],
    )

    operation, _manifest = edit_pptx(source, output, {"edits": edits})
    validation = validate_object_edits(
        output,
        edits=edits,
        operation_result=operation,
    )
    readback, _warnings = read_pptx(output, {})

    assert validation == {
        "edited_objects": 2,
        "notes_updates": 0,
        "object_graph_valid": True,
    }
    assert sha256(source.read_bytes()).hexdigest() == source_hash
    equations = [
        shape
        for shape in readback["slides"][0]["shapes"]
        if shape["type"] == "equation"
    ]
    assert len(equations) == 2
    assert equations[0]["id"] == original["id"]
    assert equations[0]["equation"]["canonical_latex"] == (r"E=\frac{mc^{2}}{2}")
    assert equations[1]["equation"]["canonical_latex"] == r"\sqrt{x}"


def test_equation_upsert_is_transactional_on_stale_selector(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pptx"
    create_pptx(
        source,
        parse_deck(_deck([_equation("eq-energy", "E=mc^2")])),
    )
    output = tmp_path / "must-not-exist.pptx"
    edits = _parsed_edits(
        source,
        output,
        [
            {
                "type": "equation_upsert",
                "slide": 1,
                "selector": {
                    "id": "999",
                    "name": "missing",
                    "type": "equation",
                },
                "equation": _equation("missing", "x=1"),
            }
        ],
    )

    with pytest.raises(DocumentSkillsError):
        edit_pptx(source, output, {"edits": edits})
    assert not output.exists()


def test_mixed_text_and_math_remains_a_shape_with_all_text_siblings(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated.pptx"
    create_pptx(
        generated,
        parse_deck(_deck([_equation("eq-inline", "x+1")])),
    )
    mixed = _mutate_slide(
        generated,
        tmp_path / "mixed-text-math.pptx",
        _mix_text_and_math,
    )

    projected, warnings = read_pptx(mixed, {})

    assert warnings == []
    assert not any(
        shape["type"] == "equation"
        for shape in projected["slides"][0]["shapes"]
    )
    text = [
        run["text"]
        for shape in projected["slides"][0]["shapes"]
        for frame in shape.get("text_frames", [])
        for paragraph in frame["paragraphs"]
        for run in paragraph["runs"]
    ]
    assert text == ["before", "middle", "after"]


def test_equation_upsert_cannot_replace_a_mixed_text_math_shape(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated.pptx"
    create_pptx(
        generated,
        parse_deck(_deck([_equation("eq-inline", "x+1")])),
    )
    mixed = _mutate_slide(
        generated,
        tmp_path / "mixed-text-math.pptx",
        _mix_text_and_math,
    )
    package = OpcPackage.open(mixed)
    shape = next(
        node
        for node in package.xml("ppt/slides/slide1.xml").iter()
        if local_name(node.tag) == "sp"
        and any((text.text or "") == "before" for text in node.iter())
    )
    properties = next(
        node for node in shape.iter() if local_name(node.tag) == "cNvPr"
    )
    output = tmp_path / "must-not-exist.pptx"
    edits = _parsed_edits(
        mixed,
        output,
        [
            {
                "type": "equation_upsert",
                "slide": 1,
                "selector": {
                    "id": properties.attrib["id"],
                    "name": properties.attrib["name"],
                    "type": "equation",
                },
                "equation": _equation("eq-replacement", "y+1"),
            }
        ],
    )

    with pytest.raises(DocumentSkillsError) as captured:
        edit_pptx(mixed, output, {"edits": edits})

    assert captured.value.code == ErrorCode.REQUEST_INVALID
    assert not output.exists()


def test_group_with_ordinary_and_math_children_is_not_an_equation_container(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated.pptx"
    create_pptx(
        generated,
        parse_deck(_deck([_equation("eq-grouped", "x+1")])),
    )
    grouped = _mutate_slide(
        generated,
        tmp_path / "grouped-equation.pptx",
        _group_text_and_math,
    )

    projected, warnings = read_pptx(grouped, {})

    assert warnings == []
    assert len(projected["slides"][0]["shapes"]) == 2
    assert {shape["type"] for shape in projected["slides"][0]["shapes"]} == {
        "shape"
    }
    assert any(
        run["text"] == "Office Math"
        for shape in projected["slides"][0]["shapes"]
        for frame in shape.get("text_frames", [])
        for paragraph in frame["paragraphs"]
        for run in paragraph["runs"]
    )

    output = tmp_path / "must-not-exist.pptx"
    edits = _parsed_edits(
        grouped,
        output,
        [
            {
                "type": "equation_upsert",
                "slide": 1,
                "selector": {
                    "id": "900",
                    "name": "Mixed equation group",
                    "type": "equation",
                },
                "equation": _equation("eq-replacement", "y+1"),
            }
        ],
    )
    with pytest.raises(DocumentSkillsError):
        edit_pptx(grouped, output, {"edits": edits})
    assert not output.exists()


def test_template_base_and_slide_add_preserve_native_equation_readback(
    tmp_path: Path,
) -> None:
    slide_size = {"cx": "12192000", "cy": "6858000", "type": "screen16x9"}
    template_deck = _deck([])
    template_deck["slide_size"] = slide_size
    template = tmp_path / "template.pptx"
    create_pptx(template, parse_deck(template_deck))

    target_deck = _deck([_equation("eq-template", r"\frac{a}{b}", x=8.0)])
    target_deck["slide_size"] = slide_size
    templated = tmp_path / "templated.pptx"
    create_pptx_from_template(templated, parse_deck(target_deck), template)

    source = tmp_path / "slide-add-source.pptx"
    create_pptx(source, parse_deck(_deck([])))
    added_slide = _deck([_equation("eq-slide-add", r"\sqrt{x}")])["slides"][0]
    added = tmp_path / "slide-added.pptx"
    edits = _parsed_edits(
        source,
        added,
        [{"type": "slide_add", "position": 2, "slide": added_slide}],
    )
    edit_pptx(source, added, {"edits": edits})

    for artifact, expected in (
        (templated, r"\frac{a}{b}"),
        (added, r"\sqrt{x}"),
    ):
        projected, warnings = read_pptx(artifact, {})
        equations = [
            shape["equation"]
            for slide in projected["slides"]
            for shape in slide["shapes"]
            if shape["type"] == "equation"
        ]
        assert warnings == []
        assert [equation["canonical_latex"] for equation in equations] == [expected]
        assert equations[0]["readback"] == {"status": "pass"}


def test_slide_add_revalidates_equation_bbox_against_target_size(
    tmp_path: Path,
) -> None:
    source_deck = _deck([])
    source_deck["slide_size"] = {
        "cx": "4572000",
        "cy": "4572000",
        "type": "custom",
    }
    source = tmp_path / "small-source.pptx"
    create_pptx(source, parse_deck(source_deck))
    added_slide = _deck([_equation("eq-outside", "x", x=5.0)])["slides"][0]
    output = tmp_path / "must-not-exist.pptx"
    edits = _parsed_edits(
        source,
        output,
        [{"type": "slide_add", "position": 2, "slide": added_slide}],
    )

    with pytest.raises(DocumentSkillsError):
        edit_pptx(source, output, {"edits": edits})

    assert not output.exists()
