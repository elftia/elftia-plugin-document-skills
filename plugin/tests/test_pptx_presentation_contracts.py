from __future__ import annotations

import json
from pathlib import Path
import shutil

from jsonschema import Draft202012Validator
import pytest
from tests.support.pptx_template_fixture import owner_contract_root

from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
    PresentationContractConsumer,
    PresentationContractConsumerError,
)


def _shallow_consumer(tmp_path: Path) -> PresentationContractConsumer:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["schemaVersion"],
        "properties": {"schemaVersion": {"const": "1.0.0"}},
    }
    validator = Draft202012Validator(schema)
    return PresentationContractConsumer(
        root=tmp_path,
        pin=PRESENTATION_CONTRACT_V1_PIN,
        manifest={},
        validators={
            "deck-ir": validator,
            "semantic-slots": validator,
            "template-contract": validator,
        },
    )


def _owner_contract_root(project_root: Path) -> Path | None:
    candidate = owner_contract_root(project_root)
    return candidate if candidate.is_dir() else None


def test_stable_ids_match_the_owner_vectors_and_reject_index_keys(tmp_path: Path) -> None:
    consumer = _shallow_consumer(tmp_path)
    deck_id = consumer.stable_deck_id(
        namespace="example.synthetic",
        source_template_id="quarterly-review",
        source_template_version="1.0.0",
    )
    slide_id = consumer.stable_slide_id(
        deck_id=deck_id,
        source_template_id="quarterly-review",
        semantic_key="executive-summary",
    )
    object_id = consumer.stable_object_id(slide_id=slide_id, semantic_key="headline")

    assert deck_id == "deck_2cf02b22247617a4c5665544b3fef3d9"
    assert slide_id == "slide_a7066570cd5835192671a268bd53f1b1"
    assert object_id == "object_4cd538da35f33d9b277fd4318218e98f"
    with pytest.raises(PresentationContractConsumerError, match="array index"):
        consumer.stable_slide_id(
            deck_id=deck_id,
            source_template_id="quarterly-review",
            semantic_key="0",
        )
    with pytest.raises(PresentationContractConsumerError, match="NFKC"):
        consumer.stable_object_id(slide_id=slide_id, semantic_key="ｈｅａｄｌｉｎｅ")


def test_unknown_versions_hash_drift_and_duplicate_slots_fail_closed(
    tmp_path: Path,
) -> None:
    consumer = _shallow_consumer(tmp_path)
    with pytest.raises(PresentationContractConsumerError) as unsupported:
        consumer.validate("deck-ir", {"schemaVersion": "2.0.0"})
    assert unsupported.value.code == "PRESENTATION_CONTRACT_UNSUPPORTED_VERSION"

    deck = {
        "schemaVersion": "1.0.0",
        "contentHash": "sha256:" + "0" * 64,
        "canvasProfiles": [{"id": "slides-16x9"}],
        "slides": [],
    }
    with pytest.raises(PresentationContractConsumerError) as hash_mismatch:
        consumer.validate("deck-ir", deck)
    assert hash_mismatch.value.code == "PRESENTATION_CONTRACT_HASH_MISMATCH"

    duplicate_slots = {
        "schemaVersion": "1.0.0",
        "slots": [
            {"slotId": "headline", "sourceObjectId": "object_" + "1" * 32},
            {"slotId": "headline", "sourceObjectId": "object_" + "2" * 32},
        ],
    }
    with pytest.raises(PresentationContractConsumerError, match="duplicate slot id"):
        consumer.validate("semantic-slots", duplicate_slots)


def test_owner_package_and_checked_snapshot_are_exact_when_available(
    project_root: Path,
    tmp_path: Path,
) -> None:
    owner_root = _owner_contract_root(project_root)
    if owner_root is None:
        pytest.skip("owner presentation-contract package is not installed in this checkout")

    consumer = PresentationContractConsumer.open(owner_root)
    snapshot_path = (
        project_root
        / "tests"
        / "fixtures"
        / "pptx"
        / "ecosystem_bc"
        / "expected"
        / "contract-pin.json"
    )
    assert consumer.summary() == json.loads(snapshot_path.read_text(encoding="utf-8"))

    copied = tmp_path / "contract"
    shutil.copytree(owner_root, copied)
    manifest_path = copied / "schemas" / "schema-manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    with pytest.raises(PresentationContractConsumerError) as pin_mismatch:
        PresentationContractConsumer.open(copied)
    assert pin_mismatch.value.code == "PRESENTATION_CONTRACT_PIN_MISMATCH"
