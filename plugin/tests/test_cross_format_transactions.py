"""Cross-format validation-authoritative transaction behavior."""

from __future__ import annotations

import errno
import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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

    def inject_writer(path: Path, expected: Any) -> None:
        real_assert(path, expected)
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

    def inject_replace(path: Path, expected: Any) -> None:
        real_assert(path, expected)
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

    def inject_writer(path: Path, expected: Any) -> None:
        real_assert(path, expected)
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

    def inject_writer(path: Path, expected: Any) -> bool:
        nonlocal compared
        matched = real_matches(path, expected)
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

    def inject_after_final_check(path: Path, identity: Any, record: Any) -> bool:
        nonlocal injected_capture
        matched = real_matches(path, identity, record)
        captures = list(tmp_path.glob(".document-skills-capture-*"))
        if path == output and captures and injected_capture is None:
            injected_capture = captures[0]
            injected_capture.write_bytes(b"late-old-inode-writer")
        return matched

    monkeypatch.setattr(paths_module, "_matches_record", inject_after_final_check)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["promotion_committed"] is True
    assert captured.value.details["committed_with_cleanup_failure"] is True
    assert output.read_bytes() == b"validated"
    assert injected_capture is not None
    assert injected_capture.read_bytes() == b"late-old-inode-writer"
    assert _assert_exact_residue_inventory(captured.value, tmp_path) == [
        injected_capture
    ]


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

    def substitute_stage(source: Path, destination: Path) -> Any:
        stage = real_stage(source, destination)
        alien = tmp_path / "stage-writer.bin"
        alien.write_bytes(b"stage-path-writer")
        alien.replace(stage.path)
        return stage

    def inject_during_rollback(source: Path, destination: Path) -> None:
        real_rename(source, destination)
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


def test_existing_destination_commit_preserves_capture_and_reports_non_success(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")

    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(
            candidate,
            output,
            expected_destination=destination_snapshot(output),
        )

    assert captured.value.details["promotion_committed"] is True
    assert captured.value.details["committed_with_cleanup_failure"] is True
    assert captured.value.details["capture_cleanup_skipped"] is True
    assert output.read_bytes() == b"validated"
    capture = _only_residue(captured.value, tmp_path, "destination_capture")
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

    def unavailable_rename(_source: Path, _destination: Path) -> None:
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

    def fail_candidate_rename(source: Path, destination: Path) -> None:
        if source.name.startswith(".document-skills-stage-") and destination == output:
            raise OSError(errno.EIO, "injected candidate-rename failure")
        real_rename(source, destination)

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

    def inject_writer(path: Path, expected: Any) -> None:
        real_assert(path, expected)
        path.write_bytes(b"concurrent-old-inode")

    def fail_capture_restore(source: Path, destination: Path) -> None:
        if source.name.startswith(".document-skills-capture-"):
            raise OSError(errno.EIO, "injected capture-restore failure")
        real_rename(source, destination)

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

    def capture_denied(_source: Path, _destination: Path) -> None:
        raise PermissionError(errno.EACCES, "injected sharing violation")

    monkeypatch.setattr(paths_module, "_rename_no_replace", capture_denied)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["destination_transaction_unavailable"] is True
    assert output.read_bytes() == b"initial"
    residue = _only_residue(captured.value, tmp_path, "stage")
    assert residue.read_bytes() == b"validated"


def test_post_identity_observation_capture_substitution_is_never_unlinked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"validated")
    output = tmp_path / "output.bin"
    output.write_bytes(b"initial")
    snapshot = destination_snapshot(output)
    real_entry = paths_module._residue_entry
    unlink_calls: list[Path] = []

    def substitute_after_observation(reference: Any) -> Any:
        observed = real_entry(reference)
        if reference.role == "destination_capture" and not unlink_calls:
            alien = tmp_path / "alien.bin"
            alien.write_bytes(b"alien-capture-path")
            alien.replace(reference.path)
            unlink_calls.append(reference.path)
            # Re-observe so the committed inventory is exact after injection.
            return real_entry(reference)
        return observed

    def forbidden_unlink(_path: Path, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("promotion must not unlink mutable pathnames")

    monkeypatch.setattr(paths_module, "_residue_entry", substitute_after_observation)
    monkeypatch.setattr(Path, "unlink", forbidden_unlink)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_promote(candidate, output, expected_destination=snapshot)

    assert captured.value.details["promotion_committed"] is True
    assert captured.value.details["capture_cleanup_skipped"] is True
    assert output.read_bytes() == b"validated"
    capture = Path(captured.value.details["destination_capture_path"])
    assert capture.read_bytes() == b"alien-capture-path"
    assert unlink_calls == [capture]
    assert _assert_exact_residue_inventory(captured.value, tmp_path) == [capture]


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

    def substitute_stage(source: Path, destination: Path) -> Any:
        stage = real_stage(source, destination)
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

    def substitute_stage(source: Path, destination: Path) -> Any:
        stage = real_stage(source, destination)
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


def _transaction(format_id: str) -> Any:
    return importlib.import_module(
        f"document_skills_core.formats.{format_id}.transaction"
    )


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
    assert sorted(Path(item["path"]) for item in inventory) == actual
    for item in inventory:
        path = Path(item["path"])
        assert item["state"] == "regular_file"
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
