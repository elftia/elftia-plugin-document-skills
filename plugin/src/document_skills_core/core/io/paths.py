"""Artifact identity, hashing, destination staging, and atomic promotion."""

import ctypes
from dataclasses import asdict, dataclass, field
import hashlib
import os
from pathlib import Path
import stat
import sys
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


@dataclass(frozen=True)
class StagedArtifact:
    path: Path
    identity: FileIdentity
    record: ArtifactRecord


@dataclass(frozen=True)
class _ResidueReference:
    role: str
    path: Path
    expected_identity: FileIdentity | None


@dataclass
class _PromotionState:
    references: list[_ResidueReference] = field(default_factory=list)

    def track(
        self,
        role: str,
        path: Path,
        expected_identity: FileIdentity | None,
    ) -> None:
        self.references.append(_ResidueReference(role, path, expected_identity))


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


def stage_for_destination(
    source: str | Path, destination: str | Path
) -> StagedArtifact:
    """Copy a candidate into its destination directory and retain creation identity.

    The public stage name is never deleted by pathname. If creation or copying fails,
    any reachable residue is reported for explicit recovery rather than being removed
    after a racy identity check.
    """

    source_path = normalized_path(source)
    destination_path = normalized_path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    stage = _internal_path(destination_path.parent, "stage")
    stage_identity: FileIdentity | None = None
    digest = hashlib.sha256()
    copied_bytes = 0
    try:
        with source_path.open("rb") as source_handle:
            try:
                stage_handle = stage.open("xb")
            except FileExistsError as error:
                occupied = DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "The selected promotion stage name is occupied.",
                    details={
                        "destination_race": True,
                        "internal_target_occupied": True,
                        "internal_target_role": "stage",
                        "stage_path": str(stage),
                    },
                )
                _attach_residue_inventory(
                    occupied, [_ResidueReference("occupied_stage", stage, None)]
                )
                raise occupied from error
            with stage_handle:
                metadata = os.fstat(stage_handle.fileno())
                stage_identity = (metadata.st_dev, metadata.st_ino)
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    stage_handle.write(chunk)
                    digest.update(chunk)
                    copied_bytes += len(chunk)
                stage_handle.flush()
                os.fsync(stage_handle.fileno())
    except DocumentSkillsError:
        raise
    except Exception as error:
        details: dict[str, object] = {
            "stage_creation_failed": True,
            "stage_path": str(stage),
            "reason": type(error).__name__,
        }
        failed = DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promotion staging did not complete.",
            details=details,
        )
        if stage_identity is not None:
            _attach_residue_inventory(
                failed,
                [_ResidueReference("stage", stage, stage_identity)],
            )
        raise failed from error
    if stage_identity is None:  # pragma: no cover - creation invariant
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Promotion stage identity was not captured at creation time.",
        )
    return StagedArtifact(
        stage,
        stage_identity,
        ArtifactRecord("output", str(stage), digest.hexdigest(), copied_bytes),
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
    state = _PromotionState()
    state.track("stage", stage.path, stage.identity)
    try:
        if (
            stage.record.sha256 != source_record.sha256
            or stage.record.bytes != source_record.bytes
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
        promoted_record = _conditional_promote(
            stage,
            destination_path,
            effective_destination,
            state,
        )
    except DocumentSkillsError as error:
        _attach_residue_inventory(error, state.references)
        raise
    return promoted_record


def _conditional_promote(
    stage: StagedArtifact,
    destination: Path,
    expected: DestinationSnapshot,
    state: _PromotionState,
) -> ArtifactRecord:
    """Install ``stage`` using only atomic no-replace renames.

    No internal path is ever overwritten or unlinked. An existing destination is
    retained at an exact capture path; because portable identity-bound deletion
    is unavailable, a committed replacement is reported as committed-with-
    cleanup-failure instead of silently discarding the captured inode.
    """

    if not expected.exists:
        try:
            _rename_no_replace(stage.path, destination)
        except FileExistsError as error:
            raise _destination_transaction_busy() from error
        except OSError as error:
            raise _no_replace_unavailable(error) from error
        if not _matches_record(destination, stage.identity, stage.record):
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
    backup = _internal_path(destination.parent, "capture")
    backup_identity = (expected.device, expected.inode)
    state.track("destination_capture", backup, backup_identity)
    try:
        _rename_no_replace(destination, backup)
    except FileExistsError as error:
        occupied = _internal_target_occupied("capture", backup)
        raise occupied from error
    except FileNotFoundError as error:
        raise _destination_transaction_busy() from error
    except OSError as error:
        raise _destination_transaction_unavailable(error) from error
    if not _matches_snapshot(backup, expected):
        _restore_capture(_destination_transaction_busy(), backup, destination)

    try:
        _rename_no_replace(stage.path, destination)
    except FileExistsError as error:
        _restore_capture(_destination_transaction_busy(), backup, destination)
    except OSError as error:
        _restore_capture(_no_replace_unavailable(error), backup, destination)

    if not _matches_record(destination, stage.identity, stage.record):
        mismatch = DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Installed output does not match the creation-time stage identity.",
            details={
                "candidate_identity_mismatch": True,
                "destination_changed_after_install": True,
            },
        )
        _preserve_installed_path(
            mismatch, stage, destination, state, backup
        )

    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Candidate committed, but identity-bound capture deletion is unavailable.",
        details={
            "promotion_committed": True,
            "committed_with_cleanup_failure": True,
            "destination_capture_preserved": True,
            "destination_capture_path": str(backup),
            "capture_cleanup_skipped": True,
            "capture_cleanup_reason": "identity_bound_deletion_unavailable",
            "output_sha256": stage.record.sha256,
            "output_bytes": stage.record.bytes,
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


def _restore_capture(
    error: DocumentSkillsError,
    backup: Path,
    destination: Path,
) -> None:
    try:
        _rename_no_replace(backup, destination)
    except FileExistsError:
        error.details.update(
            {
                "rollback_complete": False,
                "rollback_reason": "destination_occupied",
                "destination_capture_preserved": True,
                "destination_capture_path": str(backup),
                "destination_exists": destination.is_file(),
            }
        )
        raise error
    except OSError as restore_error:
        error.details.update(
            {
                "rollback_complete": False,
                "rollback_reason": type(restore_error).__name__,
                "destination_capture_preserved": True,
                "destination_capture_path": str(backup),
                "destination_exists": destination.is_file(),
            }
        )
        raise error
    error.details["rollback_complete"] = True
    error.details["destination_capture_preserved"] = False
    raise error


def _preserve_installed_path(
    error: DocumentSkillsError,
    stage: StagedArtifact,
    destination: Path,
    state: _PromotionState,
    backup: Path | None,
) -> None:
    rollback = _internal_path(destination.parent, "rollback")
    state.track("rollback_candidate", rollback, stage.identity)
    error.details["rollback_candidate_path"] = str(rollback)
    error.details.update(
        {
            "rollback_candidate_preserved": False,
            "destination_capture_path": str(backup) if backup is not None else None,
        }
    )
    installed_path_preserved = False
    try:
        _rename_no_replace(destination, rollback)
        installed_path_preserved = True
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
        error.details.update(
            {
                "rollback_candidate_preserved": True,
                "rollback_candidate_matches_stage": _matches_record(
                    rollback, stage.identity, stage.record
                ),
            }
        )
        if not error.details["rollback_candidate_matches_stage"]:
            error.details["concurrent_writer_captured_during_rollback"] = True
    if backup is not None:
        try:
            _rename_no_replace(backup, destination)
        except FileExistsError:
            error.details.update(
                {
                    "rollback_complete": False,
                    "rollback_reason": "destination_occupied",
                    "destination_capture_preserved": True,
                }
            )
            raise error
        except OSError as restore_error:
            error.details.update(
                {
                    "rollback_complete": False,
                    "rollback_reason": type(restore_error).__name__,
                    "destination_capture_preserved": True,
                }
            )
            raise error
        error.details["destination_capture_preserved"] = False
    error.details["rollback_complete"] = True
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


def _promoted_record(record: ArtifactRecord, destination: Path) -> ArtifactRecord:
    return ArtifactRecord("output", str(destination), record.sha256, record.bytes)


def _internal_path(parent: Path, role: str) -> Path:
    return parent / f".document-skills-{role}-{uuid.uuid4().hex}"


def _internal_target_occupied(role: str, path: Path) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        f"The selected internal {role} target is occupied.",
        details={
            "destination_race": True,
            "internal_target_occupied": True,
            "internal_target_role": role,
            "internal_target_path": str(path),
        },
    )


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename while rejecting an occupied target, or fail closed."""

    if os.name == "nt":
        # CPython maps os.rename to a non-replacing Windows rename. Unlike
        # os.replace, an occupied target raises FileExistsError.
        os.rename(source, destination)
        return
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        try:
            renameat2 = library.renameat2
        except AttributeError:
            raise OSError("renameat2 is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, source_bytes, -100, destination_bytes, 1)
    elif sys.platform == "darwin":
        try:
            renamex_np = library.renamex_np
        except AttributeError:
            raise OSError("renamex_np is unavailable")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source_bytes, destination_bytes, 4)
    else:
        raise OSError("atomic no-replace rename is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            str(destination),
        )


def _attach_residue_inventory(
    error: DocumentSkillsError,
    references: list[_ResidueReference],
) -> None:
    inventory: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for reference in references:
        key = (reference.role, str(reference.path))
        if key in seen:
            continue
        seen.add(key)
        entry = _residue_entry(reference)
        if entry is not None:
            inventory.append(entry)
    inventory.sort(key=lambda item: (str(item["path"]), str(item["role"])))
    error.details["transaction_residues"] = inventory
    error.details["transaction_residue_paths"] = [
        str(item["path"]) for item in inventory
    ]


def _residue_entry(
    reference: _ResidueReference,
) -> dict[str, object] | None:
    try:
        metadata = os.stat(reference.path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        return {
            "role": reference.role,
            "path": str(reference.path),
            "state": "identity_unavailable",
            "reason": type(error).__name__,
        }
    actual_identity = (metadata.st_dev, metadata.st_ino)
    entry: dict[str, object] = {
        "role": reference.role,
        "path": str(reference.path),
        "state": "regular_file" if stat.S_ISREG(metadata.st_mode) else "non_regular",
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
    }
    if reference.expected_identity is not None:
        entry["identity_matches_expected"] = (
            actual_identity == reference.expected_identity
        )
    if stat.S_ISREG(metadata.st_mode):
        entry["bytes"] = metadata.st_size
        try:
            entry["sha256"] = sha256_file(reference.path)
        except OSError as error:
            entry["sha256_unavailable"] = type(error).__name__
    return entry


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
