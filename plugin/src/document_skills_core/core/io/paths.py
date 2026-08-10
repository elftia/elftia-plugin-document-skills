"""Artifact identity, hashing, destination staging, and atomic promotion."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import BinaryIO
import uuid

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .path_identity import assert_distinct_paths, normalized_path, same_path
from .parent_anchor import (
    DestinationParentAnchor,
    FileIdentity,
    ParentSafetyError,
)
from .promotion_checks import (
    assert_destination_unchanged as _check_destination_unchanged,
    assert_source_preserved as _check_source_preserved,
    matches_record as _check_record,
    matches_snapshot as _check_snapshot,
)
from .promotion_errors import (
    destination_transaction_busy as _destination_transaction_busy,
    destination_transaction_unavailable as _destination_transaction_unavailable,
    internal_target_occupied as _internal_target_occupied,
    no_replace_unavailable as _no_replace_unavailable,
    parent_safety_error as _parent_safety_error,
)
from .promotion_models import (
    ArtifactRecord,
    DestinationSnapshot,
    PromotionOutcome,
    PromotionState as _PromotionState,
    ResidueReference as _ResidueReference,
    StagedArtifact,
)
from .promotion_observation import observe_entry


def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        return _sha256_open_file(handle)


def file_record(path: str | Path, role: str) -> ArtifactRecord:
    resolved = normalized_path(path)
    if not resolved.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            f"Artifact does not exist: {resolved.name}",
            details={"role": role},
        )
    return ArtifactRecord(role, str(resolved), sha256_file(resolved), resolved.stat().st_size)


def stage_for_destination(
    source: str | Path,
    destination: str | Path,
    *,
    parent: DestinationParentAnchor,
    state: _PromotionState,
) -> StagedArtifact:
    """Copy a candidate through an exclusive file in the captured parent."""

    source_path = normalized_path(source)
    stage_name = _internal_path(parent.original_path, "stage").name
    stage_path = parent.entry_path(
        stage_name,
        require_bound=True,
        phase="stage_path",
    )
    stage_identity: FileIdentity | None = None
    digest = hashlib.sha256()
    copied_bytes = 0
    try:
        with source_path.open("rb") as source_handle:
            try:
                stage_handle = parent.create_exclusive(stage_name)
            except FileExistsError as error:
                state.track("occupied_stage", stage_name, None)
                raise _internal_target_occupied("stage", stage_path) from error
            with stage_handle:
                metadata = os.fstat(stage_handle.fileno())
                stage_identity = (metadata.st_dev, metadata.st_ino)
                state.track("stage", stage_name, stage_identity)
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    stage_handle.write(chunk)
                    digest.update(chunk)
                    copied_bytes += len(chunk)
                stage_handle.flush()
                os.fsync(stage_handle.fileno())
                parent.assert_bound("stage_copy_complete")
    except (DocumentSkillsError, ParentSafetyError):
        raise
    except Exception as error:
        failed = DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promotion staging did not complete.",
            details={
                "stage_creation_failed": True,
                "stage_path": str(stage_path),
                "reason": type(error).__name__,
            },
        )
        if stage_identity is not None and not any(
            item.name == stage_name for item in state.references
        ):
            state.track("stage", stage_name, stage_identity)
        raise failed from error
    if stage_identity is None:  # pragma: no cover - creation invariant
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promotion stage identity was not captured at creation time.",
        )
    return StagedArtifact(
        stage_path,
        stage_name,
        stage_identity,
        ArtifactRecord("output", str(stage_path), digest.hexdigest(), copied_bytes),
    )


def destination_snapshot(destination: str | Path) -> DestinationSnapshot:
    path = normalized_path(destination)
    if path.exists() and not path.is_file():
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Output path exists but is not a regular file.",
            status="invalid_request",
        )
    if not path.is_file():
        return DestinationSnapshot(path, False, None)
    identity = _regular_file_identity(path)
    return DestinationSnapshot(path, True, sha256_file(path), *identity)


def atomic_promote(
    staged_source: str | Path,
    destination: str | Path,
    *,
    expected_destination: DestinationSnapshot | None = None,
    expected_source_sha256: str | None = None,
    expected_source_bytes: int | None = None,
) -> PromotionOutcome:
    source_record = file_record(staged_source, "output")
    if (
        expected_source_sha256 is not None
        and source_record.sha256 != expected_source_sha256
    ) or (
        expected_source_bytes is not None
        and source_record.bytes != expected_source_bytes
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promotion source differs from the validated candidate.",
            details={"candidate_identity_mismatch": True},
        )
    try:
        parent, destination_path = DestinationParentAnchor.capture(destination)
    except ParentSafetyError as error:
        raise _parent_safety_error(error) from error
    with parent:
        state = _PromotionState(parent)
        effective_destination = expected_destination or destination_snapshot(
            destination_path
        )
        try:
            stage = stage_for_destination(
                staged_source,
                destination_path,
                parent=parent,
                state=state,
            )
            if (
                stage.record.sha256 != source_record.sha256
                or stage.record.bytes != source_record.bytes
            ):
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Promotion staging copy differs from the candidate.",
                    details={"candidate_identity_mismatch": True},
                )
            _assert_destination_unchanged(
                destination_path,
                effective_destination,
                parent=parent,
            )
            promoted_record = _conditional_promote(
                stage,
                destination_path,
                effective_destination,
                state,
            )
            inventory = _residue_inventory(state)
            try:
                parent.assert_bound("committed_residue_observation")
            except ParentSafetyError:
                state.track(
                    "displaced_installed_output",
                    destination_path.name,
                    stage.identity,
                )
                raise
            outcome_state = (
                "committed_with_residue" if inventory else "committed_clean"
            )
            return PromotionOutcome(
                promoted_record,
                outcome_state,
                tuple(inventory),
            )
        except ParentSafetyError as error:
            failure = _parent_safety_error(error)
            _attach_residue_inventory(failure, state)
            raise failure from error
        except DocumentSkillsError as error:
            _attach_residue_inventory(error, state)
            raise


def _conditional_promote(
    stage: StagedArtifact,
    destination: Path,
    expected: DestinationSnapshot,
    state: _PromotionState,
) -> ArtifactRecord:
    """Install ``stage`` using identity-bound atomic no-replace renames."""

    if not expected.exists:
        try:
            _rename_no_replace(stage.path, destination, state=state)
        except ParentSafetyError:
            raise
        except FileExistsError as error:
            raise _destination_transaction_busy() from error
        except OSError as error:
            raise _no_replace_unavailable(error) from error
        if not _matches_record(
            destination,
            stage.identity,
            stage.record,
            parent=state.parent,
        ):
            mismatch = DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Installed output does not match the creation-time stage identity.",
                details={
                    "candidate_identity_mismatch": True,
                    "destination_changed_after_install": True,
                },
            )
            _preserve_installed_path(mismatch, stage, destination, state, None)
        return _promoted_record(stage.record, destination)

    if expected.device is None or expected.inode is None:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Existing destination snapshot lacks a stable file identity.",
            details={"destination_snapshot_identity_missing": True},
        )
    backup = _internal_path(state.parent.original_path, "capture")
    backup_identity = (expected.device, expected.inode)
    state.track("destination_capture", backup, backup_identity)
    try:
        _rename_no_replace(destination, backup, state=state)
    except ParentSafetyError:
        raise
    except FileExistsError as error:
        raise _internal_target_occupied("capture", backup) from error
    except FileNotFoundError as error:
        raise _destination_transaction_busy() from error
    except OSError as error:
        raise _destination_transaction_unavailable(error) from error
    if not _matches_snapshot(backup, expected, parent=state.parent):
        _restore_capture(
            _destination_transaction_busy(),
            backup,
            destination,
            state,
        )

    try:
        _rename_no_replace(stage.path, destination, state=state)
    except ParentSafetyError:
        raise
    except FileExistsError as error:
        _restore_capture(
            _destination_transaction_busy(),
            backup,
            destination,
            state,
        )
    except OSError as error:
        _restore_capture(
            _no_replace_unavailable(error),
            backup,
            destination,
            state,
        )

    if not _matches_record(
        destination,
        stage.identity,
        stage.record,
        parent=state.parent,
    ):
        mismatch = DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Installed output does not match the creation-time stage identity.",
            details={
                "candidate_identity_mismatch": True,
                "destination_changed_after_install": True,
            },
        )
        _preserve_installed_path(mismatch, stage, destination, state, backup)
    return _promoted_record(stage.record, destination)


def _restore_capture(
    error: DocumentSkillsError,
    backup: Path,
    destination: Path,
    state: _PromotionState,
) -> None:
    try:
        _rename_no_replace(backup, destination, state=state)
    except ParentSafetyError:
        raise
    except FileExistsError:
        error.details.update(
            {
                "rollback_complete": False,
                "rollback_reason": "destination_occupied",
                "destination_capture_path": str(backup),
                "destination_exists": _entry_exists(
                    state.parent, destination.name
                ),
            }
        )
        raise error
    except OSError as restore_error:
        error.details.update(
            {
                "rollback_complete": False,
                "rollback_reason": type(restore_error).__name__,
                "destination_capture_path": str(backup),
                "destination_exists": _entry_exists(
                    state.parent, destination.name
                ),
            }
        )
        raise error
    error.details["rollback_complete"] = True
    raise error


def _preserve_installed_path(
    error: DocumentSkillsError,
    stage: StagedArtifact,
    destination: Path,
    state: _PromotionState,
    backup: Path | None,
) -> None:
    rollback = _internal_path(state.parent.original_path, "rollback")
    state.track("rollback_candidate", rollback, stage.identity)
    error.details["rollback_candidate_path"] = str(rollback)
    error.details["destination_capture_path"] = (
        str(backup) if backup is not None else None
    )
    installed_path_preserved = False
    try:
        _rename_no_replace(destination, rollback, state=state)
        installed_path_preserved = True
    except ParentSafetyError:
        raise
    except FileExistsError as rollback_error:
        error.details.update(
            {
                "rollback_complete": False,
                "rollback_reason": "rollback_target_occupied",
                "internal_target_occupied": True,
                "internal_target_role": "rollback",
            }
        )
        raise error from rollback_error
    except FileNotFoundError:
        if backup is None:
            error.details["rollback_complete"] = True
            raise error
    except OSError as restore_error:
        error.details.update(
            {
                "rollback_complete": False,
                "rollback_reason": type(restore_error).__name__,
            }
        )
        raise error

    if installed_path_preserved:
        matches_stage = _matches_record(
            rollback,
            stage.identity,
            stage.record,
            parent=state.parent,
        )
        error.details["rollback_candidate_matches_stage"] = matches_stage
        if not matches_stage:
            error.details["concurrent_writer_captured_during_rollback"] = True
    if backup is not None:
        try:
            _rename_no_replace(backup, destination, state=state)
        except ParentSafetyError:
            raise
        except FileExistsError:
            error.details.update(
                {
                    "rollback_complete": False,
                    "rollback_reason": "destination_occupied",
                }
            )
            raise error
        except OSError as restore_error:
            error.details.update(
                {
                    "rollback_complete": False,
                    "rollback_reason": type(restore_error).__name__,
                }
            )
            raise error
    error.details["rollback_complete"] = True
    raise error


def _matches_snapshot(
    path: Path,
    expected: DestinationSnapshot,
    *,
    parent: DestinationParentAnchor,
) -> bool:
    return _check_snapshot(
        path,
        expected,
        parent=parent,
        observe=_observe_entry,
    )


def _matches_record(
    path: Path,
    identity: FileIdentity,
    record: ArtifactRecord,
    *,
    parent: DestinationParentAnchor,
) -> bool:
    return _check_record(
        path,
        identity,
        record,
        parent=parent,
        observe=_observe_entry,
    )


def _regular_file_identity(path: Path) -> FileIdentity:
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError("Path is not a regular file")
    return metadata.st_dev, metadata.st_ino


def _promoted_record(record: ArtifactRecord, destination: Path) -> ArtifactRecord:
    return ArtifactRecord("output", str(destination), record.sha256, record.bytes)


def _internal_path(parent: Path, role: str) -> Path:
    return parent / f".document-skills-{role}-{uuid.uuid4().hex}"


def _rename_no_replace(
    source: Path,
    destination: Path,
    *,
    state: _PromotionState,
) -> None:
    """Rename two entries inside the captured parent without replacement."""

    try:
        state.parent.rename_no_replace(source.name, destination.name)
    except ParentSafetyError:
        source_reference = next(
            (
                reference
                for reference in reversed(state.references)
                if reference.name == source.name
            ),
            None,
        )
        if (
            source_reference is not None
            and not _entry_exists(state.parent, source.name)
            and _entry_exists(state.parent, destination.name)
        ):
            state.track(
                f"displaced_{source_reference.role}",
                destination.name,
                source_reference.expected_identity,
            )
        raise


def _attach_residue_inventory(
    error: DocumentSkillsError,
    state: _PromotionState,
) -> None:
    inventory = _residue_inventory(state)
    error.details["transaction_residues"] = inventory
    error.details["transaction_residue_paths"] = [
        str(item["path"]) for item in inventory
    ]
    error.details["residue_observation_stable"] = all(
        item.get("stable") is True for item in inventory
    )
    capture = next(
        (item for item in inventory if item["role"] == "destination_capture"),
        None,
    )
    error.details["destination_capture_preserved"] = bool(
        capture is not None
        and capture.get("stable") is True
        and capture.get("identity_matches_expected") is True
    )


def _residue_inventory(state: _PromotionState) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for reference in state.references:
        key = (reference.role, reference.name)
        if key in seen:
            continue
        seen.add(key)
        entry = _residue_entry(reference, parent=state.parent)
        if entry is not None:
            inventory.append(entry)
    inventory.sort(key=lambda item: (str(item["path"]), str(item["role"])))
    return inventory


def _residue_entry(
    reference: _ResidueReference,
    *,
    parent: DestinationParentAnchor,
) -> dict[str, object] | None:
    return _observe_entry(parent, reference)


def _observe_entry(
    parent: DestinationParentAnchor,
    reference: _ResidueReference,
) -> dict[str, object] | None:
    return observe_entry(
        parent,
        reference,
        hash_open_file=_sha256_open_file,
    )


def _sha256_open_file(handle: BinaryIO) -> str:
    handle.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _entry_exists(parent: DestinationParentAnchor, name: str) -> bool:
    try:
        parent.entry_stat(name)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _assert_destination_unchanged(
    path: Path,
    expected: DestinationSnapshot,
    *,
    parent: DestinationParentAnchor,
) -> None:
    _check_destination_unchanged(
        path,
        expected,
        parent=parent,
        observe=_observe_entry,
    )


def assert_source_preserved(path: str | Path, expected_sha256: str) -> None:
    _check_source_preserved(
        path,
        expected_sha256,
        hash_file=sha256_file,
    )
