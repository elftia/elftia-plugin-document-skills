"""Closed-world strict export coverage for native ChartML semantics."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from xml.etree.ElementTree import SubElement, tostring

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.formats.pptx.constants import qn
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
)
from document_skills_core.formats.pptx.service import PptxService

_MUTATIONS = (
    ("legend-position", "unsupported-chart-legendpos"),
    ("data-labels", "unsupported-chart-showval"),
    ("axis-property", "unsupported-chart-axpos"),
    ("grouping", "unsupported-chart-grouping"),
    ("gap-width", "unsupported-chart-gapwidth"),
    ("series-style", "unsupported-chart-sppr"),
)


def _contract_root(project_root: Path) -> Path:
    root = project_root.parents[1] / "elftia" / "packages" / "presentation-contracts"
    assert root.is_dir()
    return root


def _source(project_root: Path) -> Path:
    return (
        project_root
        / "tests"
        / "fixtures"
        / "pptx"
        / "ecosystem_bc"
        / "svg"
        / "roundtrip-source.pptx"
    )


def _request(source: Path, output: Path, contract_root: Path) -> dict[str, object]:
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
            "mode": "strict",
        },
    }


def _mutated_source(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
) -> Path:
    package = OpcPackage.open(_source(project_root))
    chart_part = package.chart_parts()[0]
    root = fromstring(package.parts[chart_part])
    if mutation == "legend-position":
        root.find(f".//{qn('c', 'legendPos')}").set("val", "l")
    elif mutation == "data-labels":
        root.find(f".//{qn('c', 'showVal')}").set("val", "1")
    elif mutation == "axis-property":
        root.find(f".//{qn('c', 'catAx')}/{qn('c', 'axPos')}").set(
            "val",
            "t",
        )
    elif mutation == "grouping":
        root.find(f".//{qn('c', 'grouping')}").set("val", "stacked")
    elif mutation == "gap-width":
        root.find(f".//{qn('c', 'gapWidth')}").set("val", "200")
    else:
        series = root.find(f".//{qn('c', 'ser')}")
        properties = SubElement(series, qn("c", "spPr"))
        solid = SubElement(properties, qn("a", "solidFill"))
        SubElement(solid, qn("a", "srgbClr"), {"val": "112233"})
    changed = tmp_path / f"{mutation}.pptx"
    package.write_copy(
        changed,
        changed_parts={
            chart_part: tostring(root, encoding="UTF-8", xml_declaration=True),
        },
    )
    return changed


def _assert_rejection(
    result: dict[str, object],
    output: Path,
    reason: str,
) -> None:
    assert result["status"] == "enhancement_required"
    errors = result["errors"]
    assert errors[0]["code"] == "DS_UNSUPPORTED_FEATURE"
    assert errors[0]["details"]["reason"] == reason
    assert not output.exists()


@pytest.mark.parametrize(("mutation", "reason"), _MUTATIONS)
def test_service_strict_export_rejects_unprojected_chart_semantics(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    source = _mutated_source(project_root, tmp_path, mutation)
    output = tmp_path / f"service-{mutation}-bundle"

    result = PptxService(project_root).execute(
        "pptx.scene.export",
        _request(source, output, _contract_root(project_root)),
    )

    _assert_rejection(result, output, reason)


@pytest.mark.parametrize(("mutation", "reason"), _MUTATIONS)
def test_public_strict_export_rejects_unprojected_chart_semantics(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    source = _mutated_source(project_root, tmp_path, mutation)
    output = tmp_path / f"public-{mutation}-bundle"
    request = tmp_path / f"public-{mutation}.json"
    request.write_text(
        json.dumps(
            _request(source, output, _contract_root(project_root)),
            ensure_ascii=False,
        ),
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

    assert process.returncode == 0
    assert process.stderr == b""
    _assert_rejection(result, output, reason)
