"""Inert PPTM inventory and exact keep-VBA copy-through tests."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from xml.etree.ElementTree import SubElement

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.constants import CONTENT_TYPES_NS
from document_skills_core.formats.pptx.macro_policy import (
    MACRO_MAIN_TYPE,
    VBA_CONTENT_TYPE,
    VBA_PART,
    open_presentation_package,
    validate_vba_copy_through,
    validate_vba_package,
)
from document_skills_core.formats.pptx.mapping import map_slides
from document_skills_core.formats.pptx.mutation import MutablePptxPackage
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.scaffold import _to_xml_bytes
from document_skills_core.formats.pptx.service import PptxService

_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_VBA_REL = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"


def _deck() -> dict[str, object]:
    return {
        "metadata": {"title": "Macro deck", "creator": "Test", "subject": "VBA"},
        "slides": [
            {
                "layout": "content",
                "title": "Original",
                "shapes": [{"text": "Body", "runs": []}],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": None,
            },
            {
                "layout": "content",
                "title": "Second",
                "shapes": [],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": None,
            },
        ],
    }


def _request(source: Path, output: Path, *, keep_vba: bool | None) -> dict[str, object]:
    arguments: dict[str, object] = {
        "edits": [{"slide": 1, "type": "slide_text", "ref": "", "value": "Edited"}],
    }
    if keep_vba is not None:
        arguments["keep_vba"] = keep_vba
    return {
        "schema_version": "1.0",
        "operation": "pptx.edit",
        "input": str(source),
        "output": str(output),
        "arguments": arguments,
    }


def _make_pptm(
    service: PptxService,
    tmp_path: Path,
    *,
    name: str = "source.pptm",
) -> Path:
    pptx = tmp_path / f"{Path(name).stem}-base.pptx"
    result = service.execute("pptx.create", {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(pptx),
        "arguments": {"deck": _deck()},
    })
    assert result["status"] == "success", result
    source = OpcPackage.open(pptx)
    target = MutablePptxPackage(source)

    content_types = target.xml("[Content_Types].xml")
    main = [
        node
        for node in content_types
        if node.attrib.get("PartName") == "/ppt/presentation.xml"
    ]
    assert len(main) == 1
    main[0].set("ContentType", MACRO_MAIN_TYPE)
    SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": f"/{VBA_PART}", "ContentType": VBA_CONTENT_TYPE},
    )
    target.set_part("[Content_Types].xml", _to_xml_bytes(content_types))

    relationships = target.xml("ppt/_rels/presentation.xml.rels")
    SubElement(
        relationships,
        f"{{{_REL_NS}}}Relationship",
        {"Id": "rIdVba", "Type": _VBA_REL, "Target": "vbaProject.bin"},
    )
    target.set_part(
        "ppt/_rels/presentation.xml.rels",
        _to_xml_bytes(relationships),
    )
    target.set_part(VBA_PART, b"inert-vba-project-fixture")
    destination = tmp_path / name
    target.emit(destination)
    return destination


def _public(project_root: Path, request_path: Path) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pptx/scripts/run.py"),
            "run",
            "--request",
            str(request_path),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def test_pptm_inspection_is_inert_and_keep_vba_edit_is_exact_copy_through(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = PptxService(project_root)
    source = _make_pptm(service, tmp_path)
    source_hash = sha256(source.read_bytes()).hexdigest()
    source_package = OpcPackage.open(source, allow_dangerous_inventory=True)
    vba_hash = source_package.part_hashes[VBA_PART]

    inspection = service.execute("pptx.inspect.structure", {
        "schema_version": "1.0",
        "operation": "pptx.inspect.structure",
        "input": str(source),
        "arguments": {},
    })
    assert inspection["status"] == "success", inspection
    inspected = inspection["diagnostics"]["operation_result"]
    assert inspected["mutation_authorized"] is False
    assert inspected["dangerous_content"]["present"] is True
    assert len(inspected["dangerous_content"]["categories"]["vba"]) >= 3

    output = tmp_path / "edited.pptm"
    request = _request(source, output, keep_vba=True)
    request["arguments"]["edits"].append({
        "slide": 2,
        "type": "slide_duplicate",
        "position": 3,
    })
    result = service.execute("pptx.edit", request)

    assert result["status"] == "success", result
    assert sha256(source.read_bytes()).hexdigest() == source_hash
    candidate = OpcPackage.open(output, allow_dangerous_inventory=True)
    assert candidate.content_type_for("ppt/presentation.xml") == MACRO_MAIN_TYPE
    assert candidate.part_hashes[VBA_PART] == vba_hash
    assert len(map_slides(candidate)) == 3
    macro = result["diagnostics"]["operation_result"]["macro_copy_through"]
    assert macro["unchanged"] is True
    assert macro["copy_through"] == "exact-bytes"
    assert macro["source_sha256"] == vba_hash
    outcomes = {gate["id"]: gate["outcome"] for gate in result["validation"]["gates"]}
    assert outcomes["operation.pptx-deep-validation"] == "pass"
    assert outcomes["operation.mutation-semantics"] == "pass"


def test_pptm_contract_requires_explicit_keep_vba_and_matching_extensions(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = PptxService(project_root)
    source = _make_pptm(service, tmp_path)
    cases = [
        _request(source, tmp_path / "missing-flag.pptm", keep_vba=None),
        _request(source, tmp_path / "false-flag.pptm", keep_vba=False),
        _request(source, tmp_path / "wrong-output.pptx", keep_vba=True),
    ]
    normal = tmp_path / "normal.pptx"
    assert service.execute("pptx.create", {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(normal),
        "arguments": {"deck": _deck()},
    })["status"] == "success"
    cases.append(_request(normal, tmp_path / "normal-output.pptx", keep_vba=True))

    for request in cases:
        result = service.execute("pptx.edit", request)
        assert result["status"] == "invalid_request", result
        assert not Path(request["output"]).exists()


def test_public_keep_vba_edit_reopens_as_macro_enabled(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = PptxService(project_root)
    source = _make_pptm(service, tmp_path, name="public-source.pptm")
    output = tmp_path / "public-output.pptm"
    request_payload = _request(source, output, keep_vba=True)
    request_path = tmp_path / "public-request.json"
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, request_path)

    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    candidate = OpcPackage.open(output, allow_dangerous_inventory=True)
    assert candidate.content_type_for("ppt/presentation.xml") == MACRO_MAIN_TYPE
    assert result["diagnostics"]["operation_result"]["macro_copy_through"]["unchanged"] is True


def test_pptm_rejects_signatures_and_other_dangerous_inventory(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = PptxService(project_root)
    clean = _make_pptm(service, tmp_path)
    source = OpcPackage.open(clean, allow_dangerous_inventory=True)

    signed_target = MutablePptxPackage(source)
    signed_target.set_part("_xmlsignatures/sig1.xml", b"<Signature />")
    signed = tmp_path / "signed.pptm"
    signed_target.emit(signed)
    signed_output = tmp_path / "signed-output.pptm"
    signed_result = service.execute(
        "pptx.edit",
        _request(signed, signed_output, keep_vba=True),
    )
    assert signed_result["status"] == "invalid_request"
    assert signed_result["errors"][0]["details"]["signature_invalidation_required"] is True
    assert not signed_output.exists()

    active_target = MutablePptxPackage(source)
    active_target.set_part("ppt/activeX/activeX1.bin", b"inert-active-x")
    active = tmp_path / "active.pptm"
    active_target.emit(active)
    active_output = tmp_path / "active-output.pptm"
    active_result = service.execute(
        "pptx.edit",
        _request(active, active_output, keep_vba=True),
    )
    assert active_result["status"] == "invalid_request"
    assert not active_output.exists()


def test_vba_copy_through_validator_rejects_changed_project_bytes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = PptxService(project_root)
    source_path = _make_pptm(service, tmp_path)
    source = open_presentation_package(source_path, allow_vba=True)
    evidence = validate_vba_package(source, candidate=False)
    changed_target = MutablePptxPackage(source)
    changed_target.set_part(VBA_PART, b"changed-vba-project")
    changed = tmp_path / "changed.pptm"
    changed_target.emit(changed)

    with pytest.raises(DocumentSkillsError) as exc:
        validate_vba_copy_through(source, changed, evidence)
    assert exc.value.code.value == "DS_VALIDATION_FAILED"
