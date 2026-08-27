from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
)
from tests.support.pptx_ecosystem_fixture import (
    EcosystemFixtureWriter,
    FixtureMetadata,
)


def _metadata(**overrides: object) -> FixtureMetadata:
    values: dict[str, object] = {
        "fixture_id": "B0-TEST-01",
        "format": "json",
        "purpose": "Exercise the common B/C fixture writer.",
        "origin": "Elftia-authored synthetic test.",
        "recipe": "pytest",
        "license": "GPL-3.0",
        "expected_operation": "presentation-contract.conformance",
        "expected_consumers": ("document-skills",),
        "resource_limits": {"maxBytes": 1024},
        "invariants": ("payload hash remains exact",),
        "security_classification": "benign-generated-metadata",
    }
    values.update(overrides)
    return FixtureMetadata(**values)


def test_fixture_writer_is_deterministic_and_hash_binds_metadata(tmp_path: Path) -> None:
    roots = (tmp_path / "first", tmp_path / "second")
    results = [
        EcosystemFixtureWriter(root).write_json(
            "expected/sample.json",
            {"text": "中文", "value": 1},
            _metadata(),
        )
        for root in roots
    ]
    first_payload, first_manifest = results[0]
    second_payload, second_manifest = results[1]
    assert first_payload.read_bytes() == second_payload.read_bytes()
    assert first_manifest.read_bytes() == second_manifest.read_bytes()

    payload = first_payload.read_bytes()
    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert manifest["sha256"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert manifest["sizeBytes"] == len(payload)
    assert manifest["redistributable"] is True
    assert manifest["expected_consumers"] == ["document-skills"]


def test_fixture_writer_rejects_unsafe_or_unshippable_inputs(tmp_path: Path) -> None:
    writer = EcosystemFixtureWriter(tmp_path)
    with pytest.raises(ValueError, match="unsafe fixture path"):
        writer.write_bytes("../escape.bin", b"x", _metadata())
    with pytest.raises(ValueError, match="exceeds maxBytes"):
        writer.write_bytes(
            "large.bin",
            b"xx",
            _metadata(resource_limits={"maxBytes": 1}),
        )
    with pytest.raises(ValueError, match="non-redistributable"):
        writer.write_bytes(
            "restricted.bin",
            b"x",
            _metadata(redistributable=False),
        )

    writer.write_bytes("case/Item.bin", b"x", _metadata())
    with pytest.raises(ValueError, match="case-colliding"):
        writer.write_bytes("case/item.bin", b"x", _metadata())


def test_checked_contract_fixture_has_complete_adjacent_manifest(project_root: Path) -> None:
    expected_root = (
        project_root
        / "tests"
        / "fixtures"
        / "pptx"
        / "ecosystem_bc"
        / "expected"
    )
    payload_path = expected_root / "contract-pin.json"
    manifest_path = expected_root / "contract-pin.json.manifest.json"
    payload = payload_path.read_bytes()
    snapshot = json.loads(payload.decode("utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert snapshot["package"] == PRESENTATION_CONTRACT_V1_PIN.package
    assert snapshot["packageVersion"] == PRESENTATION_CONTRACT_V1_PIN.package_version
    assert snapshot["manifestSha256"] == PRESENTATION_CONTRACT_V1_PIN.manifest_sha256
    assert snapshot["licenseStatus"] == "not_evaluated"
    assert manifest["fixture_id"] == "B0-CONTRACT-01"
    assert manifest["sha256"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert manifest["sizeBytes"] == len(payload)
    assert manifest["invariants"]
    assert manifest["resource_limits"]["maxBytes"] >= len(payload)


def test_checked_b2_semantic_fixtures_keep_distinct_ids_and_allowed_roles(
    project_root: Path,
) -> None:
    templates = project_root / "tests" / "fixtures" / "pptx" / "ecosystem_bc" / "templates"
    semantic_ir = json.loads(
        (templates / "semantic-neutral.deck-ir.json").read_text(encoding="utf-8")
    )
    dependency_contract = json.loads(
        (templates / "dependency-heavy.template-contract.json").read_text(encoding="utf-8")
    )
    dependency_ir = json.loads(
        (templates / "dependency-heavy.deck-ir.json").read_text(encoding="utf-8")
    )

    assert [slide["role"] for slide in semantic_ir["slides"]] == [
        "cover",
        "content",
        "detail",
        "content",
        "summary",
        "appendix",
    ]
    assert dependency_contract["templateId"] == "dependency-heavy"
    assert dependency_contract["assetRef"]["assetId"] == "dependency-heavy"
    assert all(
        obj["slotBinding"]["templateId"] == "dependency-heavy"
        for slide in dependency_ir["slides"]
        for obj in slide["objects"]
    )
