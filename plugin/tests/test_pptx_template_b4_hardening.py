from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.formats.pptx.constants import NS, local_name
from document_skills_core.formats.pptx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.pptx.service import PptxService
from document_skills_core.formats.pptx.template_content_analysis import (
    inspect_template_content,
)
from document_skills_core.formats.pptx.template_content_metrics import contains_cjk
from document_skills_core.formats.pptx.template_descriptor import (
    load_template_descriptor,
)
from tests.support.pptx_template_fixture import build_semantic_template

_A = f"{{{NS['a']}}}"
_P = f"{{{NS['p']}}}"


def test_postflight_preserves_semantic_capacity_after_output_id_assignment(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    service = PptxService(project_root)
    inspect_request = _inspect_request(fixture.source)
    inspect_request["arguments"].update({
        "catalog_ref": fixture.catalog_ref,
        "descriptor": fixture.descriptor,
    })
    inspection = service.execute("pptx.template.inspect", inspect_request)
    slot = inspection["diagnostics"]["operation_result"]["pages"][0][
        "semantic_slots"
    ][0]
    output = tmp_path / "semantic-capacity.pptx"
    result = service.execute(
        "pptx.create.from-template",
        {
            "arguments": {
                "catalog_ref": fixture.catalog_ref,
                "delivery_profile": "development",
                "descriptor": fixture.descriptor,
                "expected_input_sha256": sha256(fixture.source.read_bytes()).hexdigest(),
                "pages": [{
                    "bindings": [{
                        "expected_hash": slot["expected_hash"],
                        "slot_id": slot["slot_id"],
                        "value": {"text": "\u4e2d" * 22, "type": "text"},
                    }],
                    "output_slide_id": "slide_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "source_slide_id": fixture.slide_ids[0],
                }],
                "unbound_required_slot": "reject",
                "unselected_content": "physical_purge",
            },
            "input": str(fixture.source),
            "operation": "pptx.create.from-template",
            "output": str(output),
            "schema_version": "1.0",
        },
    )

    assert result["status"] == "success", result
    postflight = result["diagnostics"]["operation_result"]["content_lint"][
        "postflight"
    ]
    assert postflight["status"] == "passed"
    assert output.is_file()


def test_cjk_classification_includes_han_kana_and_hangul() -> None:
    assert contains_cjk("\u4e2d\u6587") is True
    assert contains_cjk("\u304b\u306a\u30ab\u30ca") is True
    assert contains_cjk("\ud55c\uae00") is True
    assert contains_cjk("Latin only") is False


def test_styled_run_splits_and_notes_runs_do_not_evade_markers(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    package = OpcPackage.open(fixture.source)
    parts = dict(package.parts)
    slide_part = package.slide_parts()[0]
    slide_root = package.xml(slide_part)
    _split_text_run(slide_root, "Template page 1", "[PLACE", "HOLDER]")
    parts[slide_part] = tostring(slide_root, encoding="UTF-8", xml_declaration=True)
    notes_part = next(
        item.resolved_target
        for item in package.part_rels(slide_part)
        if item.relationship_type.endswith("/notesSlide")
    )
    notes_root = package.xml(notes_part)
    _split_text_run(notes_root, "Approved notes 1", "DO NOT ", "SHARE")
    parts[notes_part] = tostring(notes_root, encoding="UTF-8", xml_declaration=True)
    candidate = tmp_path / "split-runs.pptx"
    write_deterministic_zip(candidate, parts)

    report = inspect_template_content(candidate)

    assert report["summary"]["placeholder-content"] == 1
    assert report["summary"]["speaker-notes-leak"] == 1


def test_inherited_master_type_scale_and_grouped_shapes_are_linted(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    package = OpcPackage.open(fixture.source)
    parts = dict(package.parts)
    slide_part = package.slide_parts()[0]
    slide_root = package.xml(slide_part)
    title_shape = _shape_with_text(slide_root, "Template page 1")
    body_shape = _shape_with_text(slide_root, "Body 1")
    _remove_inline_sizes(title_shape)
    _remove_inline_sizes(body_shape)
    tree = next(node for node in slide_root.iter() if local_name(node.tag) == "spTree")
    group = _group(title_shape, body_shape)
    tree.remove(title_shape)
    tree.remove(body_shape)
    tree.append(group)
    parts[slide_part] = tostring(slide_root, encoding="UTF-8", xml_declaration=True)
    layout_part = next(
        item.resolved_target
        for item in package.part_rels(slide_part)
        if item.relationship_type.endswith("/slideLayout")
    )
    master_part = next(
        item.resolved_target
        for item in package.part_rels(layout_part)
        if item.relationship_type.endswith("/slideMaster")
    )
    master_root = package.xml(master_part)
    _set_master_style_size(master_root, "titleStyle", 3000)
    _set_master_style_size(master_root, "otherStyle", 3600)
    parts[master_part] = tostring(master_root, encoding="UTF-8", xml_declaration=True)
    candidate = tmp_path / "grouped-inherited-scale.pptx"
    write_deterministic_zip(candidate, parts)

    report = inspect_template_content(
        candidate,
        descriptor=_load_descriptor(fixture.descriptor),
    )

    assert report["summary"]["type-scale-hierarchy"] == 1
    finding = next(
        item for item in report["findings"] if item["code"] == "type-scale-hierarchy"
    )
    assert finding["title_maximum_pt"] == 30
    assert finding["body_maximum_pt"] == 36


def _inspect_request(source: Path) -> dict[str, Any]:
    return {
        "arguments": {
            "catalog_ref": None,
            "contact_sheet": False,
            "descriptor": None,
            "expected_input_sha256": sha256(source.read_bytes()).hexdigest(),
            "mode": "strict",
        },
        "input": str(source),
        "operation": "pptx.template.inspect",
        "schema_version": "1.0",
    }


def _split_text_run(root: Element, expected: str, left: str, right: str) -> None:
    for paragraph in root.iter(f"{_A}p"):
        for index, run in enumerate(list(paragraph)):
            texts = list(run.iter(f"{_A}t"))
            if not texts or "".join(item.text or "" for item in texts) != expected:
                continue
            texts[0].text = left
            for item in texts[1:]:
                item.text = ""
            second = deepcopy(run)
            second_texts = list(second.iter(f"{_A}t"))
            second_texts[0].text = right
            for item in second_texts[1:]:
                item.text = ""
            paragraph.insert(index + 1, second)
            return
    raise AssertionError(f"text run not found: {expected}")


def _load_descriptor(value: dict[str, Any]):
    reference = deepcopy(value)
    reference["contract_root"] = Path(reference["contract_root"])
    for field in ("deck_ir", "semantic_slots", "template_contract"):
        reference[field]["path"] = Path(reference[field]["path"])
    return load_template_descriptor(reference)


def _shape_with_text(root: Element, expected: str) -> Element:
    return next(
        shape
        for shape in root.iter(f"{_P}sp")
        if any(node.text == expected for node in shape.iter(f"{_A}t"))
    )


def _remove_inline_sizes(shape: Element) -> None:
    for node in shape.iter():
        if local_name(node.tag) in {"endParaRPr", "rPr"}:
            node.attrib.pop("sz", None)


def _set_master_style_size(root: Element, style_name: str, size: int) -> None:
    style = next(node for node in root.iter() if local_name(node.tag) == style_name)
    properties = next(
        node for node in style.iter() if local_name(node.tag) == "defRPr"
    )
    properties.set("sz", str(size))


def _group(*shapes: Element) -> Element:
    group = Element(f"{_P}grpSp")
    non_visual = SubElement(group, f"{_P}nvGrpSpPr")
    SubElement(non_visual, f"{_P}cNvPr", {"id": "900", "name": "Lint Group"})
    SubElement(non_visual, f"{_P}cNvGrpSpPr")
    SubElement(non_visual, f"{_P}nvPr")
    properties = SubElement(group, f"{_P}grpSpPr")
    transform = SubElement(properties, f"{_A}xfrm")
    SubElement(transform, f"{_A}off", {"x": "0", "y": "0"})
    SubElement(transform, f"{_A}ext", {"cx": "9144000", "cy": "6858000"})
    SubElement(transform, f"{_A}chOff", {"x": "0", "y": "0"})
    SubElement(transform, f"{_A}chExt", {"cx": "9144000", "cy": "6858000"})
    group.extend(shapes)
    return group
