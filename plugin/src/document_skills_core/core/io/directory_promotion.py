"""Atomic no-replace publication for validated directory artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import uuid

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .parent_anchor import DestinationParentAnchor
from .parent_anchor_types import FileIdentity, ParentSafetyError
from .paths import file_record
from .portable_paths import PORTABLE_PATH_POLICY
from .promotion_errors import parent_safety_error
from .promotion_models import ArtifactRecord, PromotionOutcome

_MAX_FILES = 4_096
_MAX_BYTES = 512 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def atomic_publish_directory(
    source: str | Path,
    destination: str | Path,
    *,
    manifest_relative_path: str = "manifest.json",
    expected_manifest_sha256: str | None = None,
) -> PromotionOutcome:
    """Copy a validated tree locally, then atomically install it if absent."""

    source_path = _source_directory(source)
    entries = _inventory(source_path)
    manifest_identity = PORTABLE_PATH_POLICY.parse_relative(manifest_relative_path)
    manifest_relative = Path(*manifest_identity.components)
    if manifest_relative.as_posix() not in {relative.as_posix() for relative, _ in entries}:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Directory artifact does not contain its declared manifest.",
        )
    source_manifest = file_record(source_path / manifest_relative, "output")
    if (
        expected_manifest_sha256 is not None
        and source_manifest.sha256 != expected_manifest_sha256
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Directory manifest differs from the validated candidate.",
            details={"candidate_identity_mismatch": True},
        )
    try:
        parent, destination_path = DestinationParentAnchor.capture(destination)
    except ParentSafetyError as error:
        raise parent_safety_error(error) from error
    with parent:
        if os.path.lexists(destination_path):
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Directory output already exists; no-replace publication requires an absent destination.",
                status="invalid_request",
            )
        stage_name = f".{destination_path.name}.elftia-dir-stage-{uuid.uuid4().hex}"
        stage_identity: FileIdentity | None = None

        def own_stage(identity: FileIdentity) -> None:
            nonlocal stage_identity
            stage_identity = identity

        stage_path: Path | None = None
        try:
            stage_path = parent.create_directory_exclusive(
                stage_name,
                on_created=own_stage,
            )
            _copy_inventory(source_path, stage_path, entries)
            _assert_tree_matches(source_path, stage_path, entries)
            parent.assert_bound("directory_publish_before")
            if os.path.lexists(destination_path):
                raise DocumentSkillsError(
                    ErrorCode.PATH_UNSAFE,
                    "Directory destination appeared during publication.",
                    status="invalid_request",
                )
            parent.rename_no_replace(
                stage_name,
                destination_path.name,
                source_is_directory=True,
            )
            stage_path = None
        except FileExistsError as error:
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "Directory destination or private stage is already occupied.",
                status="invalid_request",
            ) from error
        except ParentSafetyError as error:
            raise parent_safety_error(error) from error
        finally:
            if stage_path is not None and stage_identity is not None:
                _cleanup_owned_stage(parent, stage_path, stage_identity)
        final_manifest = file_record(destination_path / manifest_relative, "output")
        if (
            final_manifest.sha256 != source_manifest.sha256
            or final_manifest.bytes != source_manifest.bytes
        ):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Published directory manifest differs from the validated candidate.",
                details={"promotion_committed": True},
            )
        return PromotionOutcome(
            ArtifactRecord(
                "output",
                str(destination_path / manifest_relative),
                final_manifest.sha256,
                final_manifest.bytes,
            ),
            "committed_clean",
        )


def _source_directory(value: str | Path) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "Directory candidate does not exist.",
        ) from error
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or _redirected(metadata) or path.is_symlink():
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Directory candidate must be a plain directory.",
        )
    return path


def _inventory(root: Path) -> tuple[tuple[Path, int], ...]:
    records: list[tuple[Path, int]] = []
    folded: set[str] = set()
    total_bytes = 0
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in sorted(directory_names):
            _assert_plain_entry(current_path / name, directory=True)
        for name in sorted(file_names):
            path = current_path / name
            metadata = _assert_plain_entry(path, directory=False)
            relative = path.relative_to(root)
            identity = PORTABLE_PATH_POLICY.parse_relative(relative.as_posix())
            key = "/".join(identity.keys)
            if key in folded:
                raise DocumentSkillsError(
                    ErrorCode.PATH_UNSAFE,
                    "Directory artifact contains a portable path collision.",
                )
            folded.add(key)
            records.append((Path(*identity.components), metadata.st_size))
            total_bytes += metadata.st_size
            if len(records) > _MAX_FILES or total_bytes > _MAX_BYTES:
                raise DocumentSkillsError(
                    ErrorCode.RESOURCE_LIMIT,
                    "Directory artifact exceeds publication limits.",
                )
    return tuple(sorted(records, key=lambda item: item[0].as_posix()))


def _assert_plain_entry(path: Path, *, directory: bool) -> os.stat_result:
    metadata = path.lstat()
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected or _redirected(metadata) or path.is_symlink():
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Directory artifact contains a redirected or non-regular member.",
            details={"member": path.name},
        )
    return metadata


def _copy_inventory(
    source: Path,
    stage: Path,
    entries: tuple[tuple[Path, int], ...],
) -> None:
    for relative, expected_bytes in entries:
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest_bytes = 0
        with (source / relative).open("rb") as source_handle:
            with destination.open("xb") as destination_handle:
                for chunk in iter(lambda: source_handle.read(_COPY_CHUNK), b""):
                    destination_handle.write(chunk)
                    digest_bytes += len(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
        if digest_bytes != expected_bytes:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Directory member changed during destination-local staging.",
            )


def _assert_tree_matches(
    source: Path,
    stage: Path,
    entries: tuple[tuple[Path, int], ...],
) -> None:
    if _inventory(stage) != entries:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Destination-local directory stage does not match the candidate tree.",
        )
    for relative, _size in entries:
        if _sha256(source / relative) != _sha256(stage / relative):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Destination-local directory member differs from the candidate.",
            )


def _cleanup_owned_stage(
    parent: DestinationParentAnchor,
    stage: Path,
    expected_identity: FileIdentity,
) -> None:
    try:
        physical_parent = parent.current_path()
        parent_metadata = os.stat(physical_parent, follow_symlinks=False)
        if (
            (parent_metadata.st_dev, parent_metadata.st_ino) != parent.identity
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or _redirected(parent_metadata)
        ):
            return
        physical_stage = physical_parent / stage.name
        metadata = physical_stage.lstat()
        if (
            (metadata.st_dev, metadata.st_ino) == expected_identity
            and stat.S_ISDIR(metadata.st_mode)
            and not _redirected(metadata)
            and not physical_stage.is_symlink()
        ):
            shutil.rmtree(physical_stage)
    except (OSError, ParentSafetyError):
        return


def _redirected(metadata: os.stat_result) -> bool:
    if os.name != "nt":
        return False
    return bool(metadata.st_file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["atomic_publish_directory"]
