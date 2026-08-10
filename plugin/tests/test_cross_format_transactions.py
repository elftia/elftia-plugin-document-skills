"""Cross-format validation-authoritative transaction behavior."""

from __future__ import annotations

import errno
import hashlib
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import document_skills_core.core.io.parent_anchor as parent_anchor_module
import document_skills_core.core.io.paths as paths_module
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record, make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import atomic_promote, destination_snapshot
from document_skills_core.core.io.temp_roots import OperationTempRoot


_FORMATS = ("docx", "xlsx", "pptx", "pdf")


@pytest.mark.parametrize("format_id", _FORMATS)
def test_actual_report_is_preserved_and_exact_bytes_promote_atomically(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
) -> None:
    module = _transaction(format_id)
    candidate = tmp_path / f"candidate.{format_id}"
    candidate.write_bytes(f"validated-{format_id}".encode("ascii"))
    output = tmp_path / f"output.{format_id}"
    request = _request(format_id, output)
    report = _report(candidate)

    result = _write(module, SchemaCatalog(project_root), request, candidate, report)
    promoted = module.promote_candidate(
        request,
        candidate,
        result,
        source=None,
        destination=destination_snapshot(output),
    )

    assert promoted["validation"] == report
    assert promoted["artifacts"][-1]["sha256"] == _sha256(output)
    assert output.read_bytes() == candidate.read_bytes()


@pytest.mark.parametrize("format_id", _FORMATS)
@pytest.mark.parametrize("outcome", ["fail", "unavailable", "not_run"])
def test_required_nonpass_is_schema_valid_and_cleans_private_candidate(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
    outcome: str,
) -> None:
    module = _transaction(format_id)
    output = tmp_path / f"existing.{format_id}"
    output.write_bytes(b"existing")
    before = _sha256(output)
    request = _request(format_id, output)
    private_base = tmp_path / "document-skills-operations"

    with OperationTempRoot(base=private_base) as private_root:
        candidate = private_root / f"candidate.{format_id}"
        candidate.write_bytes(b"candidate")
        report = _report(candidate, outcome=outcome)
        with pytest.raises(DocumentSkillsError) as captured:
            _write(module, SchemaCatalog(project_root), request, candidate, report)
        error_result = make_error_result(request.operation, captured.value)

    SchemaCatalog(project_root).validate("operation-result", error_result)
    assert captured.value.validation == report
    assert error_result["validation"] == report
    assert not error_result["artifacts"]
    assert _sha256(output) == before
    assert list(private_base.iterdir()) == []


@pytest.mark.parametrize("format_id", _FORMATS)
def test_post_validation_mutation_is_rejected_before_destination_change(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
) -> None:
    module = _transaction(format_id)
    candidate = tmp_path / f"candidate.{format_id}"
    candidate.write_bytes(b"validated")
    output = tmp_path / f"output.{format_id}"
    output.write_bytes(b"existing")
    before = _sha256(output)
    request = _request(format_id, output)
    report = _report(candidate)
    result = _write(module, SchemaCatalog(project_root), request, candidate, report)
    candidate.write_bytes(b"changed-after-validation")

    with pytest.raises(DocumentSkillsError) as captured:
        module.promote_candidate(
            request,
            candidate,
            result,
            source=None,
            destination=destination_snapshot(output),
        )

    assert captured.value.details["candidate_identity_mismatch"] is True
    assert _sha256(output) == before


@pytest.mark.parametrize("format_id", _FORMATS)
def test_destination_race_is_detected_without_overwriting_concurrent_bytes(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_id: str,
) -> None:
    module = _transaction(format_id)
    candidate = tmp_path / f"candidate.{format_id}"
    candidate.write_bytes(b"validated")
    output = tmp_path / f"output.{format_id}"
    output.write_bytes(b"initial")
    request = _request(format_id, output)
    result = _write(module, SchemaCatalog(project_root), request, candidate, _report(candidate))
    snapshot = destination_snapshot(output)
    real_promote = module.atomic_promote

    def race(*args: Any, **kwargs: Any) -> Any:
        output.write_bytes(b"concurrent")
        return real_promote(*args, **kwargs)

    monkeypatch.setattr(module, "atomic_promote", race)
    with pytest.raises(DocumentSkillsError) as captured:
        module.promote_candidate(
            request,
            candidate,
            result,
            source=None,
            destination=snapshot,
        )

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert captured.value.details["destination_race"] is True
    assert output.read_bytes() == b"concurrent"


def test_noncooperating_writer_after_destination_comparison_survives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_assert = paths_module._assert_destination_unchanged

    def inject_writer(path: Path, expected: Any, *, parent: Any) -> None:
        real_assert(path, expected, parent=parent)
        # Deliberately bypass all transaction helpers: this models an
        # arbitrary writer using the ordinary filesystem API.
        path.write_bytes(b"concurrent")

    monkeypatch.setattr(paths_module, "_assert_destination_unchanged", inject_writer)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert captured.value.details["destination_race"] is True
    assert captured.value.details["destination_transaction_busy"] is True
    assert captured.value.details["rollback_complete"] is True
    assert output.read_bytes() == b"concurrent"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_noncooperating_atomic_replace_after_comparison_is_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_assert = paths_module._assert_destination_unchanged

    def inject_replace(path: Path, expected: Any, *, parent: Any) -> None:
        real_assert(path, expected, parent=parent)
        replacement = tmp_path / "writer-replacement.bin"
        replacement.write_bytes(b"concurrent-replacement")
        replacement.replace(path)

    monkeypatch.setattr(paths_module, "_assert_destination_unchanged", inject_replace)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["destination_transaction_busy"] is True
    assert captured.value.details["rollback_complete"] is True
    assert output.read_bytes() == b"concurrent-replacement"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_noncooperating_writer_created_after_absent_comparison_survives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    snapshot = destination_snapshot(output)
    real_assert = paths_module._assert_destination_unchanged

    def inject_writer(path: Path, expected: Any, *, parent: Any) -> None:
        real_assert(path, expected, parent=parent)
        path.write_bytes(b"concurrent")

    monkeypatch.setattr(paths_module, "_assert_destination_unchanged", inject_writer)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert captured.value.details["destination_race"] is True
    assert captured.value.details["destination_transaction_busy"] is True
    assert output.read_bytes() == b"concurrent"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_path_writer_after_captured_identity_comparison_wins_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_matches = paths_module._matches_snapshot
    compared = False

    def inject_writer(path: Path, expected: Any, *, parent: Any) -> bool:
        nonlocal compared
        matched = real_matches(path, expected, parent=parent)
        if not compared:
            compared = True
            output.write_bytes(b"concurrent")
        return matched

    monkeypatch.setattr(paths_module, "_matches_snapshot", inject_writer)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["destination_transaction_busy"] is True
    assert captured.value.details["rollback_complete"] is False
    assert captured.value.details["rollback_reason"] == "destination_occupied"
    assert output.read_bytes() == b"concurrent"
    capture = Path(captured.value.details["destination_capture_path"])
    assert capture.read_bytes() == b"initial"
    residues = _assert_exact_residue_inventory(captured.value, tmp_path)
    assert {path.read_bytes() for path in residues} == {b"initial", b"validated"}


def test_late_writer_to_captured_inode_remains_reachable_after_final_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_matches = paths_module._matches_record
    injected_capture: Path | None = None

    def inject_after_final_check(
        path: Path,
        identity: Any,
        record: Any,
        *,
        parent: Any,
    ) -> bool:
        nonlocal injected_capture
        matched = real_matches(path, identity, record, parent=parent)
        captures = list(tmp_path.glob(".document-skills-capture-*"))
        if path == output and captures and injected_capture is None:
            injected_capture = captures[0]
            injected_capture.write_bytes(b"late-old-inode-writer")
        return matched

    monkeypatch.setattr(paths_module, "_matches_record", inject_after_final_check)
    outcome = atomic_promote(candidate, output, expected_destination=snapshot)

    details = outcome.promotion_details()
    assert details["promotion_committed"] is True
    assert details["state"] == "committed_with_residue"
    assert output.read_bytes() == b"validated"
    assert injected_capture is not None
    assert injected_capture.read_bytes() == b"late-old-inode-writer"
    assert _assert_exact_outcome_inventory(outcome, tmp_path) == [injected_capture]


def test_path_writer_during_rollback_wins_and_all_captures_survive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_stage = paths_module.stage_for_destination
    real_rename = paths_module._rename_no_replace

    def substitute_stage(
        source: Path,
        destination: Path,
        **kwargs: Any,
    ) -> Any:
        stage = real_stage(source, destination, **kwargs)
        alien = tmp_path / "stage-writer.bin"
        alien.write_bytes(b"stage-path-writer")
        alien.replace(stage.path)
        return stage

    def inject_during_rollback(
        source: Path,
        destination: Path,
        *,
        state: Any,
    ) -> None:
        real_rename(source, destination, state=state)
        if destination.name.startswith(".document-skills-rollback-"):
            output.write_bytes(b"rollback-path-writer")

    monkeypatch.setattr(paths_module, "stage_for_destination", substitute_stage)
    monkeypatch.setattr(paths_module, "_rename_no_replace", inject_during_rollback)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["candidate_identity_mismatch"] is True
    assert captured.value.details["rollback_complete"] is False
    assert captured.value.details["rollback_reason"] == "destination_occupied"
    assert output.read_bytes() == b"rollback-path-writer"
    capture = Path(captured.value.details["destination_capture_path"])
    rollback = Path(captured.value.details["rollback_candidate_path"])
    assert capture.read_bytes() == b"initial"
    assert rollback.read_bytes() == b"stage-path-writer"
    assert _assert_exact_residue_inventory(captured.value, tmp_path) == sorted(
        [capture, rollback]
    )


def test_existing_destination_commit_preserves_capture_and_reports_committed_outcome(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")

    outcome = atomic_promote(
        candidate,
        output,
        expected_destination=destination_snapshot(output),
    )

    details = outcome.promotion_details()
    assert details["promotion_committed"] is True
    assert details["state"] == "committed_with_residue"
    assert details["destination_capture_preserved"] is True
    assert output.read_bytes() == b"validated"
    capture = _only_outcome_residue(outcome, tmp_path, "destination_capture")
    assert capture.read_bytes() == b"initial"


def test_absent_destination_success_consumes_stage_without_residue(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"

    promoted = atomic_promote(
        candidate,
        output,
        expected_destination=destination_snapshot(output),
    )

    assert promoted.sha256 == _sha256(output)
    assert output.read_bytes() == b"validated"
    assert _transaction_residue(tmp_path) == []


@pytest.mark.parametrize("destination_exists", [False, True])
@pytest.mark.parametrize("error_number", [errno.EPERM, errno.EXDEV])
def test_no_replace_rename_unavailable_preserves_destination_and_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination_exists: bool,
    error_number: int,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    if destination_exists:
        output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)

    def unavailable_rename(
        _source: Path,
        _destination: Path,
        *,
        state: Any,
    ) -> None:
        raise OSError(error_number, "injected no-replace failure")

    monkeypatch.setattr(paths_module, "_rename_no_replace", unavailable_rename)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    if destination_exists:
        assert captured.value.details["destination_transaction_unavailable"] is True
    else:
        assert captured.value.details["atomic_no_replace_unavailable"] is True
        assert captured.value.details["errno"] == error_number
    assert output.exists() is destination_exists
    if destination_exists:
        assert output.read_bytes() == b"initial"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_candidate_rename_failure_after_capture_restores_old_and_reports_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_rename = paths_module._rename_no_replace

    def fail_candidate_rename(
        source: Path,
        destination: Path,
        *,
        state: Any,
    ) -> None:
        if source.name.startswith(".document-skills-stage-") and destination == output:
            raise OSError(errno.EIO, "injected candidate-rename failure")
        real_rename(source, destination, state=state)

    monkeypatch.setattr(paths_module, "_rename_no_replace", fail_candidate_rename)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["atomic_no_replace_unavailable"] is True
    assert captured.value.details["rollback_complete"] is True
    assert output.read_bytes() == b"initial"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_restore_rename_failure_preserves_capture_and_stage_residues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_assert = paths_module._assert_destination_unchanged
    real_rename = paths_module._rename_no_replace

    def inject_writer(path: Path, expected: Any, *, parent: Any) -> None:
        real_assert(path, expected, parent=parent)
        path.write_bytes(b"concurrent-old-inode")

    def fail_capture_restore(
        source: Path,
        destination: Path,
        *,
        state: Any,
    ) -> None:
        if source.name.startswith(".document-skills-capture-"):
            raise OSError(errno.EIO, "injected capture-restore failure")
        real_rename(source, destination, state=state)

    monkeypatch.setattr(paths_module, "_assert_destination_unchanged", inject_writer)
    monkeypatch.setattr(paths_module, "_rename_no_replace", fail_capture_restore)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["rollback_complete"] is False
    assert captured.value.details["destination_capture_preserved"] is True
    assert not output.exists()
    capture = Path(captured.value.details["destination_capture_path"])
    assert capture.read_bytes() == b"concurrent-old-inode"
    residues = _assert_exact_residue_inventory(captured.value, tmp_path)
    assert {path.read_bytes() for path in residues} == {
        b"concurrent-old-inode",
        b"validated",
    }


def test_windows_style_open_handle_capture_failure_leaves_destination_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)

    def capture_denied(
        _source: Path,
        _destination: Path,
        *,
        state: Any,
    ) -> None:
        raise PermissionError(errno.EACCES, "injected sharing violation")

    monkeypatch.setattr(paths_module, "_rename_no_replace", capture_denied)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["destination_transaction_unavailable"] is True
    assert output.read_bytes() == b"initial"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_residue_substitution_inside_hash_window_is_marked_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_entry = paths_module._residue_entry
    real_hash = paths_module._sha256_open_file
    observing_capture = False
    substituted_path: Path | None = None

    def enter_real_observation(reference: Any, *, parent: Any) -> Any:
        nonlocal observing_capture
        observing_capture = reference.role == "destination_capture"
        try:
            return real_entry(reference, parent=parent)
        finally:
            observing_capture = False

    def substitute_during_handle_hash(handle: Any) -> str:
        nonlocal substituted_path
        if observing_capture and substituted_path is None:
            captures = list(tmp_path.glob(".document-skills-capture-*"))
            assert len(captures) == 1
            displaced = tmp_path / "writer-preserved-capture.bin"
            captures[0].rename(displaced)
            alien = tmp_path / "alien.bin"
            alien.write_bytes(b"alien-is-a-different-size")
            alien.rename(captures[0])
            substituted_path = captures[0]
        return real_hash(handle)

    monkeypatch.setattr(paths_module, "_residue_entry", enter_real_observation)
    monkeypatch.setattr(paths_module, "_sha256_open_file", substitute_during_handle_hash)
    outcome = atomic_promote(candidate, output, expected_destination=snapshot)

    details = outcome.promotion_details()
    assert details["promotion_committed"] is True
    assert details["destination_capture_preserved"] is False
    assert details["residue_observation_stable"] is False
    assert output.read_bytes() == b"validated"
    assert substituted_path is not None
    assert substituted_path.read_bytes() == b"alien-is-a-different-size"
    assert (tmp_path / "writer-preserved-capture.bin").read_bytes() == b"initial"
    entry = outcome.transaction_residues[0]
    assert entry["state"] == "changed_during_observation"
    assert entry["stable"] is False
    assert "path_identity_changed" in entry["change_reasons"]
    for claim in ("device", "inode", "bytes", "sha256", "identity_matches_expected"):
        assert claim not in entry


def test_stage_substitution_is_preserved_in_rollback_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_stage = paths_module.stage_for_destination

    def substitute_stage(
        source: Path,
        destination: Path,
        **kwargs: Any,
    ) -> Any:
        stage = real_stage(source, destination, **kwargs)
        alien = tmp_path / "alien-stage.bin"
        alien.write_bytes(b"concurrent-stage-bytes")
        alien.replace(stage.path)
        return stage

    monkeypatch.setattr(paths_module, "stage_for_destination", substitute_stage)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["candidate_identity_mismatch"] is True
    assert captured.value.details["rollback_complete"] is True
    assert captured.value.details["concurrent_writer_captured_during_rollback"] is True
    assert output.read_bytes() == b"initial"
    rollback = _only_residue(captured.value, tmp_path, "rollback_candidate")
    assert rollback.read_bytes() == b"concurrent-stage-bytes"


def test_occupied_capture_name_is_rejected_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    occupied = tmp_path / ".document-skills-capture-occupied"
    occupied.write_bytes(b"capture-name-writer")
    real_internal_path = paths_module._internal_path

    def choose_occupied(parent: Path, role: str) -> Path:
        if role == "capture":
            return occupied
        return real_internal_path(parent, role)

    monkeypatch.setattr(paths_module, "_internal_path", choose_occupied)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(
            candidate,
            output,
            expected_destination=destination_snapshot(output),
        )

    assert captured.value.details["internal_target_occupied"] is True
    assert captured.value.details["internal_target_role"] == "capture"
    assert output.read_bytes() == b"initial"
    assert occupied.read_bytes() == b"capture-name-writer"
    residues = _assert_exact_residue_inventory(captured.value, tmp_path)
    assert {path.read_bytes() for path in residues} == {
        b"capture-name-writer",
        b"validated",
    }


def test_occupied_stage_name_is_rejected_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    occupied = tmp_path / ".document-skills-stage-occupied"
    occupied.write_bytes(b"stage-name-writer")
    real_internal_path = paths_module._internal_path

    def choose_occupied(parent: Path, role: str) -> Path:
        if role == "stage":
            return occupied
        return real_internal_path(parent, role)

    monkeypatch.setattr(paths_module, "_internal_path", choose_occupied)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(
            candidate,
            output,
            expected_destination=destination_snapshot(output),
        )

    assert captured.value.details["internal_target_occupied"] is True
    assert captured.value.details["internal_target_role"] == "stage"
    assert output.read_bytes() == b"initial"
    assert occupied.read_bytes() == b"stage-name-writer"
    assert _only_residue(captured.value, tmp_path, "occupied_stage") == occupied


def test_occupied_rollback_name_is_rejected_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    occupied = tmp_path / ".document-skills-rollback-occupied"
    occupied.write_bytes(b"rollback-name-writer")
    real_stage = paths_module.stage_for_destination
    real_internal_path = paths_module._internal_path

    def substitute_stage(
        source: Path,
        destination: Path,
        **kwargs: Any,
    ) -> Any:
        stage = real_stage(source, destination, **kwargs)
        alien = tmp_path / "alien-stage.bin"
        alien.write_bytes(b"stage-path-writer")
        alien.replace(stage.path)
        return stage

    def choose_occupied(parent: Path, role: str) -> Path:
        if role == "rollback":
            return occupied
        return real_internal_path(parent, role)

    monkeypatch.setattr(paths_module, "stage_for_destination", substitute_stage)
    monkeypatch.setattr(paths_module, "_internal_path", choose_occupied)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(
            candidate,
            output,
            expected_destination=destination_snapshot(output),
        )

    assert captured.value.details["candidate_identity_mismatch"] is True
    assert captured.value.details["internal_target_occupied"] is True
    assert captured.value.details["internal_target_role"] == "rollback"
    assert captured.value.details["rollback_complete"] is False
    assert output.read_bytes() == b"stage-path-writer"
    capture = Path(captured.value.details["destination_capture_path"])
    assert capture.read_bytes() == b"initial"
    assert occupied.read_bytes() == b"rollback-name-writer"
    assert _assert_exact_residue_inventory(captured.value, tmp_path) == sorted(
        [capture, occupied]
    )


@pytest.mark.parametrize("destination_exists", [False, True])
def test_destination_parent_swap_during_install_is_blocked_or_reported_from_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination_exists: bool,
) -> None:
    parent = tmp_path / "destination-parent"
    parent.mkdir()
    displaced = tmp_path / "displaced-parent"
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = parent / "output.bin"
    if destination_exists:
        output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_assert = paths_module._assert_destination_unchanged
    event: dict[str, bool] = {}

    def swap_after_compare(path: Path, expected: Any, *, parent: Any) -> None:
        real_assert(path, expected, parent=parent)
        event.update(_attempt_parent_swap(path.parent, displaced))

    monkeypatch.setattr(paths_module, "_assert_destination_unchanged", swap_after_compare)
    outcome = None
    failure = None
    try:
        outcome = atomic_promote(candidate, output, expected_destination=snapshot)
    except DocumentSkillsError as error:
        failure = error
    if event == {"blocked": True}:
        assert outcome is not None
        assert failure is None
        assert output.read_bytes() == b"validated"
        if destination_exists:
            assert outcome.state == "committed_with_residue"
        else:
            assert outcome.state == "committed_clean"
    else:
        assert failure is not None
        assert outcome is None
        assert event == {"moved": True}
        assert failure.details["destination_parent_changed"] is True
        assert not output.exists()
        reported = {
            Path(path) for path in failure.details["transaction_residue_paths"]
        }
        assert reported == set(_transaction_residue(displaced))
        assert all(path.parent == displaced for path in reported)


def test_parent_swap_inside_raw_anchored_rename_reports_displaced_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "destination-parent"
    parent.mkdir()
    displaced = tmp_path / "displaced-parent"
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = parent / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    event: dict[str, bool] = {}

    if os.name == "nt":
        raw_rename_name = "_windows_rename_relative"
    elif sys.platform.startswith("linux"):
        raw_rename_name = "_linux_rename_no_replace"
    elif sys.platform == "darwin":
        raw_rename_name = "_darwin_rename_no_replace"
    else:  # pragma: no cover - unsupported promotion platform
        pytest.skip("anchored no-replace rename is unavailable")
    real_raw_rename = getattr(parent_anchor_module, raw_rename_name)

    def swap_inside_raw_rename(*args: Any) -> None:
        try:
            parent.rename(displaced)
        except PermissionError as error:  # pragma: no cover - platform policy
            pytest.skip(
                f"open destination parent cannot move: {type(error).__name__}"
            )
        parent.mkdir()
        guard = parent / "replacement-guard"
        guard.mkdir()
        (guard / "sentinel.bin").write_bytes(b"replacement-tree")
        event["moved"] = True
        real_raw_rename(*args)

    monkeypatch.setattr(
        parent_anchor_module,
        raw_rename_name,
        swap_inside_raw_rename,
    )
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert event == {"moved": True}
    assert captured.value.details["destination_parent_changed"] is True
    assert captured.value.details["parent_phase"] == "rename_after"
    assert not output.exists()
    assert sorted(
        path.relative_to(parent).as_posix() for path in parent.rglob("*")
    ) == ["replacement-guard", "replacement-guard/sentinel.bin"]
    assert (parent / "replacement-guard" / "sentinel.bin").read_bytes() == (
        b"replacement-tree"
    )
    reported = {
        Path(path) for path in captured.value.details["transaction_residue_paths"]
    }
    assert reported == set(_transaction_residue(displaced))
    assert all(path.parent == displaced for path in reported)
    assert {
        item["role"]: Path(item["path"]).read_bytes()
        for item in captured.value.details["transaction_residues"]
    } == {
        "destination_capture": b"initial",
        "stage": b"validated",
    }


def test_destination_parent_swap_during_rollback_is_blocked_or_displaced_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "destination-parent"
    parent.mkdir()
    displaced = tmp_path / "displaced-parent"
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = parent / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_stage = paths_module.stage_for_destination
    real_rename = paths_module._rename_no_replace
    event: dict[str, bool] = {}

    def substitute_stage(
        source: Path,
        destination: Path,
        **kwargs: Any,
    ) -> Any:
        stage = real_stage(source, destination, **kwargs)
        alien = parent / "stage-writer.bin"
        alien.write_bytes(b"stage-path-writer")
        alien.replace(stage.path)
        return stage

    def swap_after_rollback_capture(
        source: Path,
        destination: Path,
        *,
        state: Any,
    ) -> None:
        real_rename(source, destination, state=state)
        if destination.name.startswith(".document-skills-rollback-") and not event:
            event.update(_attempt_parent_swap(parent, displaced))

    monkeypatch.setattr(paths_module, "stage_for_destination", substitute_stage)
    monkeypatch.setattr(paths_module, "_rename_no_replace", swap_after_rollback_capture)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    if event == {"blocked": True}:
        assert event == {"blocked": True}
        assert output.read_bytes() == b"initial"
        assert {
            path.read_bytes() for path in _assert_exact_residue_inventory(
                captured.value,
                parent,
            )
        } == {b"stage-path-writer"}
    else:
        assert event == {"moved": True}
        assert captured.value.details["destination_parent_changed"] is True
        assert not output.exists()
        reported = {
            Path(path) for path in captured.value.details["transaction_residue_paths"]
        }
        assert reported == set(_transaction_residue(displaced))
        assert {path.read_bytes() for path in reported} == {
            b"initial",
            b"stage-path-writer",
        }


def test_destination_parent_swap_during_committed_residue_observation_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "destination-parent"
    parent.mkdir()
    displaced = tmp_path / "displaced-parent"
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = parent / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_entry = paths_module._residue_entry
    real_hash = paths_module._sha256_open_file
    observing_capture = False
    event: dict[str, bool] = {}

    def enter_capture_observation(reference: Any, *, parent: Any) -> Any:
        nonlocal observing_capture
        observing_capture = reference.role == "destination_capture"
        try:
            return real_entry(reference, parent=parent)
        finally:
            observing_capture = False

    def swap_during_hash(handle: Any) -> str:
        if observing_capture and not event:
            event.update(_attempt_parent_swap(parent, displaced))
        return real_hash(handle)

    monkeypatch.setattr(paths_module, "_residue_entry", enter_capture_observation)
    monkeypatch.setattr(paths_module, "_sha256_open_file", swap_during_hash)
    outcome = None
    failure = None
    try:
        outcome = atomic_promote(candidate, output, expected_destination=snapshot)
    except DocumentSkillsError as error:
        failure = error
    if event == {"blocked": True}:
        assert outcome is not None
        assert failure is None
        assert outcome.state == "committed_with_residue"
        assert output.read_bytes() == b"validated"
    else:
        assert failure is not None
        assert outcome is None
        assert event == {"moved": True}
        assert failure.details["destination_parent_changed"] is True
        assert not output.exists()
        reported = {
            Path(path) for path in failure.details["transaction_residue_paths"]
        }
        assert reported == set(_transaction_residue(displaced))
        assert {path.read_bytes() for path in reported} == {b"initial", b"validated"}


def test_symlinked_destination_parent_is_rejected_before_staging(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical"
    physical.mkdir()
    redirected = tmp_path / "redirected"
    try:
        redirected.symlink_to(physical, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {type(error).__name__}")
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")

    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, redirected / "output.bin")

    assert captured.value.code == ErrorCode.PATH_UNSAFE
    assert captured.value.details["destination_parent_safety_failure"] is True
    assert _transaction_residue(physical) == []


def _transaction(format_id: str) -> Any:
    return importlib.import_module(
        f"document_skills_core.formats.{format_id}.transaction"
    )


def _attempt_parent_swap(parent: Path, displaced: Path) -> dict[str, bool]:
    try:
        parent.rename(displaced)
    except PermissionError:
        return {"blocked": True}
    parent.mkdir()
    return {"moved": True}


def _request(format_id: str, output: Path) -> Any:
    return SimpleNamespace(
        operation=f"{format_id}.create",
        output_path=output,
        requested_fidelity="core",
    )


def _write(
    module: Any,
    schemas: SchemaCatalog,
    request: Any,
    candidate: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    return module.write_candidate_result(
        schemas,
        request,
        candidate,
        report,
        {"transaction_test": True},
        warnings=[],
        source=None,
    )


def _report(path: Path, *, outcome: str = "pass") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "pass" if outcome == "pass" else "fail",
        "gates": [
            gate_record(
                "artifact.identity",
                outcome,
                required=True,
                validator="cross-format-test",
                evidence={"sha256": _sha256(path), "bytes": path.stat().st_size},
            )
        ],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _transaction_residue(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.iterdir()
        if path.name.startswith(".document-skills-")
    )


def _assert_exact_residue_inventory(
    error: DocumentSkillsError,
    root: Path,
) -> list[Path]:
    actual = _transaction_residue(root)
    reported = sorted(Path(path) for path in error.details["transaction_residue_paths"])
    inventory = error.details["transaction_residues"]
    assert reported == actual
    return _assert_exact_inventory(inventory, actual)


def _assert_exact_outcome_inventory(
    outcome: Any,
    root: Path,
) -> list[Path]:
    actual = _transaction_residue(root)
    details = outcome.promotion_details()
    reported = sorted(Path(path) for path in details["transaction_residue_paths"])
    assert reported == actual
    return _assert_exact_inventory(list(outcome.transaction_residues), actual)


def _assert_exact_inventory(
    inventory: list[dict[str, Any]],
    actual: list[Path],
) -> list[Path]:
    assert sorted(Path(item["path"]) for item in inventory) == actual
    for item in inventory:
        path = Path(item["path"])
        assert item["state"] == "regular_file"
        assert item["stable"] is True
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == _sha256(path)
    return actual


def _only_residue(
    error: DocumentSkillsError,
    root: Path,
    role: str,
) -> Path:
    residues = _assert_exact_residue_inventory(error, root)
    assert len(residues) == 1
    inventory = error.details["transaction_residues"]
    assert len(inventory) == 1
    assert inventory[0]["role"] == role
    return residues[0]


def _only_outcome_residue(
    outcome: Any,
    root: Path,
    role: str,
) -> Path:
    residues = _assert_exact_outcome_inventory(outcome, root)
    assert len(residues) == 1
    inventory = list(outcome.transaction_residues)
    assert len(inventory) == 1
    assert inventory[0]["role"] == role
    return residues[0]
