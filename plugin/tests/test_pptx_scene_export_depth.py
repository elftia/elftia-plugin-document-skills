"""Resource containment for deeply nested PresentationML groups."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.formats.pptx.constants import local_name, qn
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
)
from document_skills_core.formats.pptx.scene_export_objects import MAX_GROUP_DEPTH
from document_skills_core.formats.pptx.service import PptxService


def _contract_root(project_root: Path) -> Path:
    root = project_root.parents[1] / "elftia" / "packages" / "presentation-contracts"
    assert root.is_dir()
    return root


def _fixture(project_root: Path) -> Path:
    return (
        project_root
        / "tests"
        / "fixtures"
        / "pptx"
        / "ecosystem_bc"
        / "svg"
        / "roundtrip-source.pptx"
    )


def _group(index: int, child: Element) -> Element:
    group = Element(qn("p", "grpSp"))
    non_visual = SubElement(group, qn("p", "nvGrpSpPr"))
    SubElement(
        non_visual,
        qn("p", "cNvPr"),
        {"id": str(10_000 + index), "name": f"depth-group-{index}"},
    )
    SubElement(non_visual, qn("p", "cNvGrpSpPr"))
    SubElement(non_visual, qn("p", "nvPr"))
    properties = SubElement(group, qn("p", "grpSpPr"))
    transform = SubElement(properties, qn("a", "xfrm"))
    for tag, attributes in (
        ("off", {"x": "0", "y": "0"}),
        ("ext", {"cx": "9144000", "cy": "6858000"}),
        ("chOff", {"x": "0", "y": "0"}),
        ("chExt", {"cx": "9144000", "cy": "6858000"}),
    ):
        SubElement(transform, qn("a", tag), attributes)
    group.append(child)
    return group


def _deep_source(project_root: Path, tmp_path: Path) -> Path:
    package = OpcPackage.open(_fixture(project_root))
    slide_part = package.slide_parts()[0]
    root = fromstring(package.parts[slide_part])
    tree = root.find(f"{qn('p', 'cSld')}/{qn('p', 'spTree')}")
    assert tree is not None
    leaf = deepcopy(next(root.iter(qn("p", "sp"))))
    for child in list(tree):
        if local_name(child.tag) in {"cxnSp", "graphicFrame", "grpSp", "pic", "sp"}:
            tree.remove(child)
    nested = leaf
    for index in reversed(range(MAX_GROUP_DEPTH + 1)):
        nested = _group(index, nested)
    tree.append(nested)
    source = tmp_path / "deep-groups.pptx"
    package.write_copy(
        source,
        changed_parts={
            slide_part: tostring(root, encoding="UTF-8", xml_declaration=True),
        },
    )
    return source


def _request(
    source: Path,
    output: Path,
    contract_root: Path,
    mode: str,
) -> dict[str, object]:
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
                "source_template_id": "deep-groups",
                "source_template_version": "1.0.0",
            },
            "mode": mode,
        },
    }


def _assert_resource_limit(
    result: dict[str, object],
    source: Path,
    source_hash: str,
    output: Path,
) -> None:
    assert result["status"] == "failed"
    errors = result["errors"]
    assert errors[0]["code"] == "DS_RESOURCE_LIMIT"
    assert errors[0]["details"] == {"limit": MAX_GROUP_DEPTH}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert not output.exists()


@pytest.mark.parametrize("mode", ["strict", "tolerant"])
def test_service_scene_export_rejects_excessive_group_depth(
    project_root: Path,
    tmp_path: Path,
    mode: str,
) -> None:
    source = _deep_source(project_root, tmp_path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / f"service-{mode}-bundle"

    result = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(source, output, _contract_root(project_root), mode),
    )

    _assert_resource_limit(result, source, source_hash, output)


@pytest.mark.parametrize("mode", ["strict", "tolerant"])
def test_public_scene_export_rejects_excessive_group_depth(
    project_root: Path,
    tmp_path: Path,
    mode: str,
) -> None:
    source = _deep_source(project_root, tmp_path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / f"public-{mode}-bundle"
    request = tmp_path / f"public-{mode}.json"
    request.write_text(
        json.dumps(_request(source, output, _contract_root(project_root), mode)),
        encoding="utf-8",
        newline="\n",
    )

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
            str(request),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=100,
    )
    result = json.loads(process.stdout.decode("utf-8", errors="strict"))

    assert process.returncode == 2
    assert process.stderr == b""
    _assert_resource_limit(result, source, source_hash, output)
