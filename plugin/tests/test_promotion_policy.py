"""Shared validation-authoritative promotion policy tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.io.paths import atomic_promote, destination_snapshot
from document_skills_core.core.validation.promotion import assert_promotable


@pytest.mark.parametrize("outcome", ["fail", "unavailable", "not_run"])
def test_required_nonpass_gate_rejects_success_candidate(
    tmp_path: Path,
    outcome: str,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"candidate")
    report = _report(candidate, outcome=outcome)

    with pytest.raises(DocumentSkillsError) as captured:
        assert_promotable("success", report, candidate)

    assert captured.value.status == "failed"
    assert captured.value.validation == report


@pytest.mark.parametrize("status", ["enhancement_required", "invalid_request", "failed"])
def test_non_success_status_is_never_promotable(tmp_path: Path, status: str) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"candidate")

    with pytest.raises(DocumentSkillsError):
        assert_promotable(status, _report(candidate), candidate)


def test_candidate_hash_or_size_mismatch_rejects_before_promotion(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"candidate")
    report = _report(candidate)
    candidate.write_bytes(b"changed-after-validation")

    with pytest.raises(DocumentSkillsError) as captured:
        assert_promotable("success", report, candidate)

    assert captured.value.details["candidate_identity_mismatch"] is True


@pytest.mark.parametrize("status", ["success", "degraded"])
def test_pass_report_and_exact_identity_are_promotable(
    tmp_path: Path,
    status: str,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"candidate")

    identity = assert_promotable(status, _report(candidate), candidate)

    assert identity.sha256 == _sha256(candidate)
    assert identity.bytes == candidate.stat().st_size


def test_atomic_source_identity_mismatch_preserves_existing_destination(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"changed")
    destination = tmp_path / "destination.bin"
    destination.write_bytes(b"existing")
    before = _sha256(destination)
    snapshot = destination_snapshot(destination)

    with pytest.raises(DocumentSkillsError):
        atomic_promote(
            candidate,
            destination,
            expected_destination=snapshot,
            expected_source_sha256="0" * 64,
            expected_source_bytes=1,
        )

    assert _sha256(destination) == before


def _report(path: Path, *, outcome: str = "pass") -> dict[str, object]:
    required = gate_record(
        "artifact.identity",
        outcome,
        required=True,
        validator="test-independent",
        evidence={"sha256": _sha256(path), "bytes": path.stat().st_size},
    )
    return {
        "schema_version": "1.0",
        "status": "pass" if outcome == "pass" else "fail",
        "gates": [required],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
