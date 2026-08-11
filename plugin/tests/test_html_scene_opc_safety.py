"""Generated HTML-scene PPTX packages must pass strict OPC safety gates."""

from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree.ElementTree import SubElement, tostring

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.constants import (
    CONTENT_TYPES_NS,
    NS,
    REL_HYPERLINK,
    REL_IMAGE,
    REL_VBA_PROJECT,
)
from document_skills_core.formats.pptx.package import write_deterministic_zip
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.scene_normalizer import NormalizedScene
from document_skills_core.formats.pptx.validation import validate_scene_created


def test_scene_validation_rejects_external_relationship(tmp_path: Path):
    candidate, scene, manifest = _candidate(tmp_path)
    parts = _parts(candidate)
    relationships = fromstring(parts["ppt/slides/_rels/slide1.xml.rels"])
    SubElement(
        relationships,
        f"{{{NS['rels']}}}Relationship",
        {
            "Id": "rIdExternal",
            "Type": REL_HYPERLINK,
            "Target": "https://example.invalid/leak",
            "TargetMode": "External",
        },
    )
    parts["ppt/slides/_rels/slide1.xml.rels"] = _xml(relationships)

    _assert_rejected(tmp_path, parts, scene, manifest, "external")


def test_scene_validation_rejects_active_content_part_and_relationship(tmp_path: Path):
    candidate, scene, manifest = _candidate(tmp_path)
    parts = _parts(candidate)
    content_types = fromstring(parts["[Content_Types].xml"])
    SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {
            "PartName": "/ppt/vbaProject.bin",
            "ContentType": "application/vnd.ms-office.vbaProject",
        },
    )
    parts["[Content_Types].xml"] = _xml(content_types)
    relationships = fromstring(parts["ppt/_rels/presentation.xml.rels"])
    SubElement(
        relationships,
        f"{{{NS['rels']}}}Relationship",
        {
            "Id": "rIdVba",
            "Type": REL_VBA_PROJECT,
            "Target": "vbaProject.bin",
        },
    )
    parts["ppt/_rels/presentation.xml.rels"] = _xml(relationships)
    parts["ppt/vbaProject.bin"] = b"ACTIVE"

    _assert_rejected(tmp_path, parts, scene, manifest, "active")


def test_scene_validation_rejects_invalid_part_content_type(tmp_path: Path):
    candidate, scene, manifest = _candidate(tmp_path)
    parts = _parts(candidate)
    content_types = fromstring(parts["[Content_Types].xml"])
    slide_override = next(
        node
        for node in content_types
        if node.get("PartName") == "/ppt/slides/slide1.xml"
    )
    slide_override.set("ContentType", "application/xml")
    parts["[Content_Types].xml"] = _xml(content_types)

    _assert_rejected(tmp_path, parts, scene, manifest, "content-type")


@pytest.mark.parametrize(
    ("target", "suffix"),
    [
        ("C:/Users/example/private.png", "drive-path"),
        ("../../../../private.png", "parent-traversal"),
        ("file:///C:/Users/example/private.png", "file-url"),
    ],
)
def test_scene_validation_rejects_relationship_path_leakage(
    tmp_path: Path,
    target: str,
    suffix: str,
):
    candidate, scene, manifest = _candidate(tmp_path)
    parts = _parts(candidate)
    relationships = fromstring(parts["ppt/slides/_rels/slide1.xml.rels"])
    SubElement(
        relationships,
        f"{{{NS['rels']}}}Relationship",
        {
            "Id": "rIdLeak",
            "Type": REL_IMAGE,
            "Target": target,
        },
    )
    parts["ppt/slides/_rels/slide1.xml.rels"] = _xml(relationships)

    _assert_rejected(tmp_path, parts, scene, manifest, suffix)


def test_scene_validation_rejects_unsafe_zip_member(tmp_path: Path):
    candidate, scene, manifest = _candidate(tmp_path)
    parts = _parts(candidate)
    parts["../escaped.xml"] = b"<escaped/>"

    _assert_rejected(tmp_path, parts, scene, manifest, "unsafe-zip")


def test_scene_validation_rejects_unsafe_xml(tmp_path: Path):
    candidate, scene, manifest = _candidate(tmp_path)
    parts = _parts(candidate)
    parts["ppt/slides/slide1.xml"] = (
        b'<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///private">]><x>&leak;</x>'
    )

    _assert_rejected(tmp_path, parts, scene, manifest, "unsafe-xml")


def _candidate(tmp_path: Path) -> tuple[Path, NormalizedScene, dict[str, object]]:
    scene = NormalizedScene(
        slides=((_item(),),),
        assets={},
        diagnostics={},
    )
    candidate = tmp_path / "candidate.pptx"
    manifest = emit_scene_pptx(candidate, scene, {})
    # After scaffold repair, the clean candidate passes both consumer-package
    # conformance and scene-package correspondence.  The safety tests below
    # tamper with the candidate and assert the tampered version is rejected.
    return candidate, scene, manifest


def _item() -> dict[str, object]:
    return {
        "source_id": "safe-item",
        "kind": "rectangle",
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 50,
        "rotation": 0,
        "opacity": 1,
        "fill": "rgb(255, 255, 255)",
        "border_color": "rgb(0, 0, 0)",
        "border_width": 0,
        "radius": 0,
        "text": "",
        "paragraphs": [],
        "outcome": "native",
        "asset_id": None,
    }


def _parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/")
        }


def _xml(root: object) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _assert_rejected(
    tmp_path: Path,
    parts: dict[str, bytes],
    scene: NormalizedScene,
    manifest: dict[str, object],
    suffix: str,
) -> None:
    tampered = tmp_path / f"tampered-{suffix}.pptx"
    write_deterministic_zip(tampered, parts)
    with pytest.raises(DocumentSkillsError) as captured:
        validate_scene_created(tampered, scene, manifest)
    validation = captured.value.validation
    assert validation is not None
    assert _outcome(validation, "operation.scene-package-correspondence") == "fail"


def _outcome(validation: dict[str, object], gate_id: str) -> str:
    gates = validation["gates"]
    assert isinstance(gates, list)
    return next(
        str(gate["outcome"])
        for gate in gates
        if isinstance(gate, dict) and gate.get("id") == gate_id
    )
