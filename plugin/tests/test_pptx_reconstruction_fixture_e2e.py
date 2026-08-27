"""Fixture-backed end-to-end tests for layered raster reconstruction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from document_skills_core.core.capabilities import ProviderCatalog
from document_skills_core.providers.ocr_vision import build_ocr_vision_provider
from tests.support.pptx_reconstruction_adapter import fixture_adapter


def _fixture_root(project_root: Path) -> Path:
    return project_root / "tests/fixtures/pptx/ecosystem_bc/reconstruction"


def _request(source: Path, output: Path, audit_policy: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.reconstruct.from-image",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": audit_policy,
        },
        "options": {"fidelity": "core"},
    }


def _registry(project_root: Path, adapter: object) -> ProviderCatalog:
    registry = ProviderCatalog()
    registry.register_provider(build_ocr_vision_provider(project_root, adapter=adapter))
    return registry


def test_b_rec_01_emits_stable_editable_layers_and_retained_audit_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    source = tmp_path / "synthetic-cards.png"
    source.write_bytes((fixture_root / source.name).read_bytes())
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    observations = json.loads(
        (fixture_root / "synthetic-cards.observations.json").read_text(encoding="utf-8")
    )
    adapter = fixture_adapter(fixture_root, "synthetic-cards")
    output = tmp_path / "synthetic-cards.pptx"

    result = _registry(project_root, adapter).execute(_request(source, output, "retain"))

    assert result["status"] == "success", json.dumps(result, indent=2)
    assert result["provider_chain"] == ["ocr-vision"]
    reconstruction = result["diagnostics"]["operation_result"]["reconstruction"]
    assert reconstruction["ocr_text"] == ["PLAN", "BUILD", "SHIP"]
    assert reconstruction["whole_slide_raster"] is False
    assert reconstruction["editable_coverage"]["by_object_count"] == {
        "editable": 5,
        "ratio": 1.0,
        "total": 5,
    }
    assert [item["id"] for item in reconstruction["elements"]] == [
        item["id"] for item in observations["elements"]
    ]
    assert [item["reading_order"] for item in reconstruction["elements"]] == list(range(5))
    assert all(item["outcome"] == "editable" for item in reconstruction["elements"])
    for actual, expected in zip(reconstruction["elements"], observations["elements"]):
        assert actual["confidence"] == expected["confidence"]
        assert actual["geometry"] == expected["geometry"]
        assert actual["source_region"] == expected["source_region"]
        assert actual["text"] == expected["text"]

    audit = result["diagnostics"]["operation_result"]["audit_asset"]
    audit_path = Path(audit["path"])
    assert audit["policy"] == "retain"
    assert audit["retained"] is True
    assert audit["sha256"] == source_digest
    assert audit["bytes"] == source.stat().st_size
    assert audit_path.read_bytes() == source.read_bytes()
    assert source.read_bytes() == (fixture_root / source.name).read_bytes()

    assert adapter.observed_source is not None
    assert adapter.observed_source != source
    assert not adapter.observed_source.exists()
    with zipfile.ZipFile(output) as archive:
        slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        assert not any(name.startswith("ppt/media/") for name in archive.namelist())
    object_names = [item["id"] for item in observations["elements"]]
    positions = [slide.index(f'name="{identity}"') for identity in object_names]
    assert positions == sorted(positions)


@pytest.mark.parametrize("audit_policy", ["retain", "discard"])
def test_b_rec_02_rasterizes_only_the_isolated_low_confidence_region(
    project_root: Path,
    tmp_path: Path,
    audit_policy: str,
) -> None:
    fixture_root = _fixture_root(project_root)
    source = tmp_path / "low-confidence.png"
    expected_source = (fixture_root / source.name).read_bytes()
    source.write_bytes(expected_source)
    adapter = fixture_adapter(fixture_root, "low-confidence")
    output = tmp_path / f"low-confidence-{audit_policy}.pptx"

    result = _registry(project_root, adapter).execute(
        _request(source, output, audit_policy)
    )

    assert result["status"] == "degraded", json.dumps(result, indent=2)
    reconstruction = result["diagnostics"]["operation_result"]["reconstruction"]
    assert [item["outcome"] for item in reconstruction["elements"]] == [
        "editable",
        "editable",
        "editable",
        "editable",
        "rasterized",
    ]
    assert reconstruction["elements"][-1]["id"] == "text-low"
    area = reconstruction["editable_coverage"]["by_area"]
    count = reconstruction["editable_coverage"]["by_object_count"]
    assert area == {
        "editable": 31_500.0,
        "ratio": pytest.approx(31_500 / 34_800),
        "total": 34_800.0,
    }
    assert count == {"editable": 4, "ratio": 0.8, "total": 5}
    assert 0 <= area["ratio"] <= 1
    assert 0 <= count["ratio"] <= 1
    assert area["ratio"] != count["ratio"]

    with zipfile.ZipFile(output) as archive:
        slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("ppt/media/")]
    assert slide.count("<p:pic>") == 1
    assert 'name="text-low"' in slide
    assert '<a:srcRect l="57500" t="64444" r="15000" b="22222"' in slide
    assert len(media) == 1

    audit = result["diagnostics"]["operation_result"]["audit_asset"]
    assert audit["policy"] == audit_policy
    assert audit["retained"] is (audit_policy == "retain")
    if audit_policy == "retain":
        audit_path = Path(audit["path"])
        assert audit_path.read_bytes() == expected_source
        assert audit["sha256"] == hashlib.sha256(expected_source).hexdigest()
    else:
        assert set(audit) == {"policy", "retained"}
        assert not list(tmp_path.glob("*.source-audit-*"))
    assert source.read_bytes() == expected_source
    assert adapter.observed_source is not None
    assert not adapter.observed_source.exists()
