"""Artifact identity, hashing, destination staging, and atomic promotion."""

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import uuid

from ..contracts.errors import DocumentSkillsError, ErrorCode


@dataclass(frozen=True)
class ArtifactRecord:
    role: str
    path: str
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True)
class DestinationSnapshot:
    path: Path
    exists: bool
    sha256: str | None
    device: int | None = None
    inode: int | None = None


FileIdentity = tuple[int, int]


def normalized_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def same_path(first: str | Path, second: str | Path) -> bool:
    left = normalized_path(first)
    right = normalized_path(second)
    if os.name == "nt":
        return os.path.normcase(str(left)) == os.path.normcase(str(right))
    return left == right


def assert_distinct_paths(
    input_path: str | Path, output_path: str | Path, *, in_place: bool = False
) -> None:
    if same_path(input_path, output_path):
        message = (
            "In-place output is not implemented by this operation."
            if in_place
            else "Output resolves to the input; explicit supported in-place mode is required."
        )
        raise DocumentSkillsError(ErrorCode.OUTPUT_EQUALS_INPUT, message)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: str | Path, role: str) -> ArtifactRecord:
    resolved = normalized_path(path)
    if not resolved.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            f"Artifact does not exist: {resolved.name}",
            details={"role": role},
        )
    return ArtifactRecord(role, str(resolved), sha256_file(resolved), resolved.stat().st_size)


def stage_for_destination(source: str | Path, destination: str | Path) -> Path:
    source_path = normalized_path(source)
    destination_path = normalized_path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    stage = destination_path.parent / f".document-skills-stage-{uuid.uuid4().hex}"
    stage_identity: FileIdentity | None = None
    try:
        with source_path.open("rb") as source_handle, stage.open("xb") as stage_handle:
            metadata = os.fstat(stage_handle.fileno())
            stage_identity = (metadata.st_dev, metadata.st_ino)
            shutil.copyfileobj(source_handle, stage_handle, length=1024 * 1024)
            stage_handle.flush()
            os.fsync(stage_handle.fileno())
    except Exception:
        if stage_identity is not None:
            _remove_owned_file(stage, stage_identity)
        raise
    return stage


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
) -> ArtifactRecord:
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
    destination_path = normalized_path(destination)
    effective_destination = expected_destination or destination_snapshot(destination_path)
    stage = stage_for_destination(staged_source, destination_path)
    promoted_record: ArtifactRecord | None = None
    stage_identity: FileIdentity | None = None
    operation_error: DocumentSkillsError | None = None
    try:
        staged_record = file_record(stage, "output")
        stage_identity = _regular_file_identity(stage)
        if (
            staged_record.sha256 != source_record.sha256
            or staged_record.bytes != source_record.bytes
        ):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Promotion staging copy differs from the candidate.",
                details={"candidate_identity_mismatch": True},
            )
        # This inexpensive preflight is deliberately followed by an atomic
        # capture/commit sequence.  It preserves the existing race diagnostic
        # hook, while the capture closes the check-to-commit window for writers
        # that do not cooperate with any lock file.
        _assert_destination_unchanged(destination_path, effective_destination)
        _conditional_promote(
            stage,
            destination_path,
            effective_destination,
            stage_identity,
            staged_record,
        )
        promoted_record = file_record(destination_path, "output")
        if (
            promoted_record.sha256 != staged_record.sha256
            or promoted_record.bytes != staged_record.bytes
        ):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Promoted output differs from the validated candidate.",
                details={"candidate_identity_mismatch": True},
            )
    except DocumentSkillsError as error:
        operation_error = error
        raise
    finally:
        if stage_identity is not None:
            cleanup_reason = _remove_owned_file(stage, stage_identity)
            if cleanup_reason is not None:
                details = {
                    "promotion_committed": promoted_record is not None,
                    "stage_cleanup_failed": True,
                    "stage_path": str(stage),
                    "stage_cleanup_reason": cleanup_reason,
                }
                if operation_error is not None:
                    operation_error.details.update(details)
                else:
                    raise DocumentSkillsError(
                        ErrorCode.VALIDATION_FAILED,
                        "Promotion stage cleanup failed after the destination transaction.",
                        details=details,
                    )
    if promoted_record is None:  # pragma: no cover - defensive invariant
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promotion did not produce an output record.",
        )
    return promoted_record


def _conditional_promote(
    stage: Path,
    destination: Path,
    expected: DestinationSnapshot,
    stage_identity: FileIdentity,
    staged_record: ArtifactRecord,
) -> None:
    """Conditionally install ``stage`` without overwriting an arbitrary writer.

    For an existing destination, an atomic same-directory rename first captures
    the current inode in a unique backup.  We compare that captured inode to the
    expected identity, then install the candidate with a no-replace hard link.
    A writer that appears after capture therefore makes the link fail and its
    bytes remain at the destination.  For an initially absent destination the
    no-replace link is the compare-and-commit operation itself.
    """

    _probe_no_replace_link(stage, destination.parent, stage_identity)
    if not expected.exists:
        try:
            os.link(stage, destination)
        except FileExistsError as error:
            raise _destination_transaction_busy() from error
        except OSError as error:
            raise _no_replace_unavailable(error) from error
        return

    if expected.device is None or expected.inode is None:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Existing destination snapshot lacks a stable file identity.",
            details={"destination_snapshot_identity_missing": True},
        )
    backup = destination.parent / f".document-skills-capture-{uuid.uuid4().hex}"
    try:
        # On Windows, an ordinary open handle commonly makes this fail before
        # any path change.  On POSIX the same-directory rename is atomic.
        os.replace(destination, backup)
    except FileNotFoundError as error:
        raise _destination_transaction_busy() from error
    except OSError as error:
        raise _destination_transaction_unavailable(error) from error

    try:
        backup_identity = _regular_file_identity(backup)
    except OSError as identity_error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Captured destination identity could not be established.",
            details={
                "destination_race": True,
                "rollback_complete": False,
                "destination_capture_path": str(backup),
                "capture_path_exists": backup.exists(),
                "capture_identity_unavailable": True,
                "reason": type(identity_error).__name__,
            },
        ) from identity_error
    if not _matches_snapshot(backup, expected):
        _raise_after_rollback(
            _destination_transaction_busy(), backup, backup_identity, destination
        )

    try:
        os.link(stage, destination)
    except FileExistsError as error:
        _raise_after_rollback(
            _destination_transaction_busy(), backup, backup_identity, destination
        )
    except OSError as error:
        unavailable = _no_replace_unavailable(error)
        _raise_after_rollback(unavailable, backup, backup_identity, destination)

    # A writer that already held the captured inode can mutate it after the
    # first comparison.  Recheck it after the candidate link and roll back the
    # still-unmodified candidate when that deterministic window is observed.
    if not _matches_snapshot(backup, expected):
        _raise_after_rollback(
            _destination_transaction_busy(),
            backup,
            backup_identity,
            destination,
            installed=(stage_identity, staged_record),
        )

    cleanup_reason = _remove_owned_file(backup, backup_identity)
    if cleanup_reason is not None:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Candidate committed, but the captured destination could not be cleaned.",
            details={
                "promotion_committed": True,
                "destination_capture_preserved": _owns_file(
                    backup, backup_identity
                ),
                "capture_path_exists": backup.exists(),
                "destination_capture_path": str(backup),
                "capture_cleanup_failed": True,
                "capture_cleanup_reason": cleanup_reason,
                "output_sha256": staged_record.sha256,
                "output_bytes": staged_record.bytes,
            },
        )


def _probe_no_replace_link(
    stage: Path, parent: Path, stage_identity: FileIdentity
) -> None:
    probe = parent / f".document-skills-link-probe-{uuid.uuid4().hex}"
    try:
        os.link(stage, probe)
    except OSError as error:
        raise _no_replace_unavailable(error) from error
    cleanup_reason = _remove_owned_file(probe, stage_identity)
    if cleanup_reason is not None:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Atomic no-replace promotion probe could not be cleaned.",
            details={
                "destination_race": True,
                "atomic_no_replace_unavailable": True,
                "link_probe_cleanup_failed": True,
                "link_probe_path": str(probe),
                "link_probe_cleanup_reason": cleanup_reason,
            },
        )


def _matches_snapshot(path: Path, expected: DestinationSnapshot) -> bool:
    try:
        identity = _regular_file_identity(path)
        return (
            identity == (expected.device, expected.inode)
            and sha256_file(path) == expected.sha256
        )
    except OSError:
        return False


def _raise_after_rollback(
    error: DocumentSkillsError,
    backup: Path,
    backup_identity: FileIdentity,
    destination: Path,
    *,
    installed: tuple[FileIdentity, ArtifactRecord] | None = None,
) -> None:
    if not _owns_file(backup, backup_identity):
        _raise_with_capture(
            error, backup, backup_identity, destination, "capture_identity_changed"
        )
    rollback_path: Path | None = None
    rollback_identity: FileIdentity | None = None
    if installed is not None:
        identity, record = installed
        rollback_path = destination.parent / (
            f".document-skills-rollback-{uuid.uuid4().hex}"
        )
        try:
            # Capture the current path atomically instead of checking and then
            # unlinking it.  A path writer is either captured here or wins the
            # following no-replace restore; rollback never replaces it.
            os.replace(destination, rollback_path)
        except FileNotFoundError:
            rollback_path = None
        except OSError as capture_error:
            _raise_with_capture(
                error,
                backup,
                backup_identity,
                destination,
                type(capture_error).__name__,
            )
        if rollback_path is not None:
            try:
                rollback_identity = _regular_file_identity(rollback_path)
            except OSError as identity_error:
                error.details.update(
                    {
                        "rollback_path": str(rollback_path),
                        "rollback_path_identity_unavailable": True,
                    }
                )
                _raise_with_capture(
                    error,
                    backup,
                    backup_identity,
                    destination,
                    type(identity_error).__name__,
                )
            if not _matches_record(rollback_path, identity, record):
                _restore_rollback_writer(
                    error,
                    rollback_path,
                    rollback_identity,
                    backup,
                    backup_identity,
                    destination,
                )
            error.details.update(
                {
                    "rollback_candidate_path": str(rollback_path),
                    "rollback_candidate_preserved": True,
                }
            )
    try:
        os.link(backup, destination)
    except FileExistsError:
        _raise_with_capture(
            error, backup, backup_identity, destination, "destination_occupied"
        )
    except OSError as restore_error:
        _raise_with_capture(
            error,
            backup,
            backup_identity,
            destination,
            type(restore_error).__name__,
        )
    error.details["rollback_complete"] = True
    if rollback_path is not None and rollback_identity is not None:
        rollback_cleanup = _remove_owned_file(rollback_path, rollback_identity)
        error.details["rollback_candidate_preserved"] = rollback_cleanup is not None
        if rollback_cleanup is not None:
            error.details["rollback_candidate_cleanup_reason"] = rollback_cleanup
    cleanup_reason = _remove_owned_file(backup, backup_identity)
    if cleanup_reason is not None:
        error.details.update(
            {
                "destination_capture_preserved": _owns_file(
                    backup, backup_identity
                ),
                "capture_path_exists": backup.exists(),
                "destination_capture_path": str(backup),
                "capture_cleanup_failed": True,
                "capture_cleanup_reason": cleanup_reason,
            }
        )
    raise error


def _restore_rollback_writer(
    error: DocumentSkillsError,
    rollback: Path,
    rollback_identity: FileIdentity,
    backup: Path,
    backup_identity: FileIdentity,
    destination: Path,
) -> None:
    error.details.update(
        {
            "concurrent_writer_captured_during_rollback": True,
            "rollback_writer_path": str(rollback),
            "rollback_writer_preserved": True,
        }
    )
    try:
        os.link(rollback, destination)
    except FileExistsError:
        _raise_with_capture(
            error, backup, backup_identity, destination, "destination_occupied"
        )
    except OSError as restore_error:
        _raise_with_capture(
            error,
            backup,
            backup_identity,
            destination,
            type(restore_error).__name__,
        )
    cleanup_reason = _remove_owned_file(rollback, rollback_identity)
    error.details.update(
        {
            "concurrent_writer_restored": True,
            "rollback_writer_preserved": cleanup_reason is not None,
        }
    )
    if cleanup_reason is not None:
        error.details["rollback_writer_cleanup_reason"] = cleanup_reason
    _raise_with_capture(error, backup, backup_identity, destination, "writer_won")


def _raise_with_capture(
    error: DocumentSkillsError,
    backup: Path,
    backup_identity: FileIdentity,
    destination: Path,
    reason: str,
) -> None:
    error.details.update(
        {
            "rollback_complete": False,
            "rollback_reason": reason,
            "destination_capture_preserved": _owns_file(backup, backup_identity),
            "destination_capture_path": str(backup),
            "destination_exists": destination.is_file(),
        }
    )
    raise error


def _matches_record(
    path: Path, identity: FileIdentity, record: ArtifactRecord
) -> bool:
    try:
        return (
            _regular_file_identity(path) == identity
            and path.stat().st_size == record.bytes
            and sha256_file(path) == record.sha256
        )
    except OSError:
        return False


def _regular_file_identity(path: Path) -> FileIdentity:
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError("Path is not a regular file")
    return metadata.st_dev, metadata.st_ino


def _owns_file(path: Path, identity: FileIdentity) -> bool:
    try:
        return _regular_file_identity(path) == identity
    except OSError:
        return False


def _remove_owned_file(path: Path, identity: FileIdentity) -> str | None:
    try:
        actual = _regular_file_identity(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        return type(error).__name__
    if actual != identity:
        return "identity_changed"
    try:
        path.unlink()
    except OSError as error:
        return type(error).__name__
    return None


def _destination_transaction_busy() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Destination is being modified by another transaction.",
        details={"destination_race": True, "destination_transaction_busy": True},
    )


def _destination_transaction_unavailable(error: OSError) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Exclusive destination transaction could not be established.",
        details={
            "destination_race": True,
            "destination_transaction_unavailable": True,
            "reason": type(error).__name__,
        },
    )


def _no_replace_unavailable(error: OSError) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Atomic no-replace promotion is unavailable for this destination.",
        details={
            "destination_race": True,
            "atomic_no_replace_unavailable": True,
            "reason": type(error).__name__,
            "errno": error.errno,
        },
    )


def _assert_destination_unchanged(
    path: Path,
    expected: DestinationSnapshot,
) -> None:
    if path != expected.path:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Destination snapshot does not match the promotion path.",
        )
    exists = path.is_file()
    actual_hash = sha256_file(path) if exists else None
    if exists != expected.exists or actual_hash != expected.sha256:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Destination changed while the DOCX operation was in progress.",
            details={"destination_race": True},
        )


def assert_source_preserved(path: str | Path, expected_sha256: str) -> None:
    try:
        actual = sha256_file(path)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Source artifact became unavailable during a non-destructive operation.",
            details={"reason": type(error).__name__},
        ) from error
    if actual != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Source artifact changed during a non-destructive operation.",
            details={"expected_sha256": expected_sha256, "actual_sha256": actual},
        )
