"""Artifact identity, hashing, destination staging, and atomic promotion."""

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import shutil
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
    try:
        shutil.copyfile(source_path, stage)
        with stage.open("rb+") as handle:
            os.fsync(handle.fileno())
    except Exception:
        stage.unlink(missing_ok=True)
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
    return DestinationSnapshot(
        path,
        path.is_file(),
        sha256_file(path) if path.is_file() else None,
    )


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
    stage = stage_for_destination(staged_source, destination_path)
    try:
        staged_record = file_record(stage, "output")
        if (
            staged_record.sha256 != source_record.sha256
            or staged_record.bytes != source_record.bytes
        ):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Promotion staging copy differs from the candidate.",
                details={"candidate_identity_mismatch": True},
            )
        if expected_destination is not None:
            _assert_destination_unchanged(destination_path, expected_destination)
        os.replace(stage, destination_path)
    finally:
        stage.unlink(missing_ok=True)
    return file_record(destination_path, "output")


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
