"""Checked B-SVG-01 through B-SVG-04 fixture acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

import pytest
from tests.support.pptx_template_fixture import owner_contract_root

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.svg_parser import compile_svg_scene
from tests.support.pptx_ecosystem_fixture import EcosystemFixtureWriter
from tests.support.pptx_svg_fixture import write_svg_fixtures
from tools.capture_pptx_powerpoint_evidence import _build_evidence


def _root(project_root: Path) -> Path:
    return project_root / "tests" / "fixtures" / "pptx" / "ecosystem_bc"


def test_b5_fixture_manifests_bind_every_svg_scene_payload(
    project_root: Path,
) -> None:
    root = _root(project_root)
    manifest_paths = sorted((root / "svg").rglob("*.manifest.json"))

    assert len(manifest_paths) == 11
    observed_ids = set()
    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = root / Path(manifest["path"])
        observed_ids.add(manifest["fixture_id"])
        assert payload.is_file()
        assert manifest["origin"] == "Elftia-authored deterministic synthetic fixture."
        assert manifest["license"] == "GPL-3.0"
        assert manifest["redistributable"] is True
        assert manifest["sha256"] == (
            "sha256:" + hashlib.sha256(payload.read_bytes()).hexdigest()
        )
        assert manifest["sizeBytes"] == payload.stat().st_size
        assert manifest["resource_limits"]["maxBytes"] >= payload.stat().st_size
        assert manifest["invariants"]
    assert observed_ids == {"B-SVG-01", "B-SVG-02", "B-SVG-03", "B-SVG-04"}


def test_checked_native_svg_fixtures_emit_editable_objects(
    project_root: Path,
    tmp_path: Path,
) -> None:
    root = _root(project_root) / "svg"
    native = compile_svg_scene(
        root / "native-basic" / "native-basic.svg",
        fallback_policy="reject",
    )
    gradient = compile_svg_scene(
        root / "native-gradient-image" / "gradient-image.svg",
        fallback_policy="reject",
    )
    native_output = tmp_path / "native.pptx"
    gradient_output = tmp_path / "gradient.pptx"
    native_manifest = emit_scene_pptx(
        native_output,
        native,
        {"creator": "Elftia", "subject": "B5", "title": "Native"},
    )
    gradient_manifest = emit_scene_pptx(
        gradient_output,
        gradient,
        {"creator": "Elftia", "subject": "B5", "title": "Gradient"},
    )

    assert native.diagnostics["outcomes"] == {"native": 7}
    assert native_manifest["objects"] == 7
    assert gradient.diagnostics["outcomes"] == {"native": 2}
    assert gradient_manifest["media"] == 1
    assert b"grpSp" in OpcPackage.open(native_output).parts["ppt/slides/slide1.xml"]
    assert b"gradFill" in OpcPackage.open(gradient_output).parts["ppt/slides/slide1.xml"]


def test_checked_unsupported_svg_fixtures_all_fail_closed(
    project_root: Path,
) -> None:
    root = _root(project_root) / "svg" / "unsupported"

    for source in sorted(root.glob("*.svg")):
        with pytest.raises(DocumentSkillsError) as captured:
            compile_svg_scene(source, fallback_policy="element-rasterize")
        assert captured.value.code.value in {
            "DS_ARCHIVE_UNSAFE",
            "DS_REQUEST_INVALID",
        }, source.name


def test_checked_roundtrip_source_matches_semantic_oracle(
    project_root: Path,
) -> None:
    root = _root(project_root)
    source = root / "svg" / "roundtrip-source.pptx"
    expected = json.loads(
        (root / "expected" / "scene" / "b5-roundtrip.json").read_text(
            encoding="utf-8"
        )
    )
    package = OpcPackage.open(source)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected["sourcePptxSha256"]
    assert expected["unsupported"] == []
    assert expected["wholeSlideRaster"] is False
    assert expected["emission"] == {
        "charts": 1,
        "media": 1,
        "objects": 6,
        "slides": 1,
    }
    assert expected["objectTypes"] == [
        "shape",
        "shape",
        "text",
        "table",
        "chart",
        "image",
    ]
    assert len(package.chart_parts()) == 1
    assert len(package.media_parts()) == 1


def test_checked_powerpoint_consumer_evidence_is_native_and_honest(
    project_root: Path,
) -> None:
    root = _root(project_root)
    evidence_path = root / "expected" / "visual" / "b5-powerpoint-consumer.json"
    manifest_path = evidence_path.with_suffix(".json.manifest.json")
    payload = evidence_path.read_bytes()
    evidence = json.loads(payload.decode("utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["fixture_id"] == "B-SVG-04"
    assert manifest["sha256"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert manifest["sizeBytes"] == len(payload)
    assert (
        "then run uv run --project plugin --frozen python -m "
        "tools.capture_pptx_powerpoint_evidence"
    ) in manifest["recipe"]
    capture = evidence["capture"]
    uuid.UUID(capture["runId"])
    assert capture["capturedAt"].endswith("Z")
    tool = project_root / capture["tool"]["path"]
    assert tool == project_root / "tools" / "capture_pptx_powerpoint_evidence.py"
    assert capture["tool"]["sha256"] == hashlib.sha256(tool.read_bytes()).hexdigest()
    assert evidence["schemaVersion"] == 2
    assert evidence["consumer"] == {
        "application": "Microsoft PowerPoint",
        "method": "COM read-only open, native object readback, and PNG export",
        "outcome": "pass",
        "platform": "windows-x64",
        "version": "16.0",
    }
    source = root / "svg" / "roundtrip-source.pptx"
    assert evidence["source"]["artifact"] == {
        "bytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    assert evidence["source"]["tableCells"] == evidence["roundtrip"]["tableCells"]
    assert evidence["source"]["chartType"] == evidence["roundtrip"]["chartType"] == 57
    assert [shape["msoType"] for shape in evidence["source"]["topLevelShapes"]] == [
        6,
        19,
        3,
        13,
    ]
    assert [
        shape["msoType"] for shape in evidence["roundtrip"]["topLevelShapes"]
    ] == [6, 19, 3, 13]
    assert all(
        outcome == "pass"
        for key, outcome in evidence["assertions"].items()
        if key != "topLevelObjectTypesEqual"
    )
    assert evidence["assertions"]["topLevelObjectTypesEqual"] is True
    comparison = evidence["renderComparison"]
    assert comparison["metrics"]["within_thresholds"] is True
    assert comparison["metrics"]["mean_absolute_error"] <= comparison["thresholds"][
        "mean_absolute_error_max"
    ]
    assert comparison["metrics"]["changed_pixel_ratio"] <= comparison["thresholds"][
        "changed_pixel_ratio_max"
    ]
    assert evidence["releaseBytePolicy"]["renderBytesIncluded"] is False

    registry = json.loads(
        (project_root / "tests" / "fixtures" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    record = next(
        item
        for item in registry["fixtures"]
        if item["path"].endswith("b5-powerpoint-consumer.json")
    )
    assert record["recipe"] == "tools/capture_pptx_powerpoint_evidence.py"
    assert record["recipe_dependencies"] == [
        "src/document_skills_core/formats/pptx/png_compare.py",
        "tools/prepare_pptx_svg_roundtrip.py",
    ]


def test_unavailable_capture_cannot_claim_powerpoint_pass(
    project_root: Path,
) -> None:
    source = _root(project_root) / "svg" / "roundtrip-source.pptx"

    evidence = _build_evidence(
        source,
        source,
        {"available": False, "reason": "PowerPoint COM is unavailable."},
        b"",
        b"",
    )

    assert evidence["consumer"]["outcome"] == "not_run"
    assert evidence["consumer"]["reason"] == "PowerPoint COM is unavailable."
    assert "assertions" not in evidence
    assert "renderComparison" not in evidence


def test_deterministic_svg_recipe_cannot_emit_powerpoint_pass(
    project_root: Path,
    tmp_path: Path,
) -> None:
    contract_root = owner_contract_root(project_root)
    if not contract_root.is_dir():
        pytest.skip("owner presentation-contract package is not installed")

    write_svg_fixtures(EcosystemFixtureWriter(tmp_path), contract_root)

    assert not (
        tmp_path
        / "expected"
        / "visual"
        / "b5-powerpoint-consumer.json"
    ).exists()
