"""Identity-bound private XLSX input snapshots for provider operations."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io import ArtifactRecord


class _ByteLimitExceeded(Exception):
    def __init__(self, observed_bytes: int) -> None:
        self.observed_bytes = observed_bytes


def bounded_source_record(
    path: str | Path,
    role: str,
    *,
    byte_limit: int,
) -> ArtifactRecord:
    """Record one regular input without hashing beyond its byte ceiling."""

    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            f"Artifact does not exist: {resolved.name}",
            details={"role": role},
        )
    input_bytes = resolved.stat().st_size
    if input_bytes > byte_limit:
        _raise_input_too_large(input_bytes, byte_limit)
    try:
        with resolved.open("rb") as handle:
            digest, hashed_bytes = _bounded_hash(handle, byte_limit)
    except _ByteLimitExceeded as error:
        _raise_input_too_large(error.observed_bytes, byte_limit)
    final_bytes = resolved.stat().st_size
    if final_bytes > byte_limit:
        _raise_input_too_large(final_bytes, byte_limit)
    if hashed_bytes != input_bytes or final_bytes != hashed_bytes:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The input changed while its identity record was created.",
            details={
                "source_changed_during_record": True,
                "recorded_bytes": input_bytes,
                "hashed_bytes": hashed_bytes,
                "final_bytes": final_bytes,
            },
        )
    return ArtifactRecord(role, str(resolved), digest, hashed_bytes)


def assert_bounded_source_preserved(
    source: ArtifactRecord,
    *,
    byte_limit: int,
) -> None:
    """Verify source preservation without reading beyond the input ceiling."""

    path = Path(source.path)
    try:
        if not path.is_file():
            raise OSError("source is no longer a regular file")
        actual_bytes = path.stat().st_size
        if actual_bytes > byte_limit:
            _raise_source_growth(actual_bytes, byte_limit)
        with path.open("rb") as handle:
            actual_sha256, hashed_bytes = _bounded_hash(handle, byte_limit)
        final_bytes = path.stat().st_size
        if final_bytes > byte_limit:
            _raise_source_growth(final_bytes, byte_limit)
    except _ByteLimitExceeded as error:
        _raise_source_growth(error.observed_bytes, byte_limit)
    except DocumentSkillsError:
        raise
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Source artifact became unavailable during a non-destructive operation.",
            details={"reason": type(error).__name__},
        ) from error
    if (
        actual_sha256 != source.sha256
        or hashed_bytes != source.bytes
        or final_bytes != hashed_bytes
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Source artifact changed during a non-destructive operation.",
            details={
                "expected_sha256": source.sha256,
                "actual_sha256": actual_sha256,
                "expected_bytes": source.bytes,
                "actual_bytes": final_bytes,
                "hashed_bytes": hashed_bytes,
            },
        )


def merge_bounded_source_preservation_failure(
    primary_error: BaseException,
    source: ArtifactRecord,
    *,
    byte_limit: int,
) -> None:
    """Keep a primary failure while attaching one bounded preservation check."""

    try:
        assert_bounded_source_preserved(source, byte_limit=byte_limit)
    except Exception as check_error:
        if isinstance(check_error, DocumentSkillsError):
            source_error = check_error
        else:
            source_error = DocumentSkillsError(
                ErrorCode.INTERNAL_ERROR,
                "Source preservation could not be checked while another failure was active.",
                details={"reason": type(check_error).__name__},
            )
        record = {"status": "fail", "error": source_error.record()}
        if isinstance(primary_error, DocumentSkillsError):
            primary_error.details = {
                **primary_error.details,
                "source_preservation": record,
            }
        else:
            primary_error.add_note(
                f"Source preservation also failed: {source_error.code.value}"
            )


def stage_source_snapshot(
    source: ArtifactRecord,
    private_root: Path,
    *,
    byte_limit: int,
) -> Path:
    """Copy exactly the recorded source bytes once and verify the bound identity."""

    source_path = Path(source.path)
    staged = private_root / f"provider-source{source_path.suffix.casefold()}"
    if source.bytes > byte_limit:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "The provider input exceeds its byte ceiling.",
            details={"input_bytes": source.bytes, "input_limit": byte_limit},
        )
    digest = hashlib.sha256()
    copied = 0
    try:
        with source_path.open("rb") as input_handle, staged.open("xb") as output_handle:
            copy_boundary = min(source.bytes, byte_limit)
            while True:
                chunk = input_handle.read(min(1024 * 1024, copy_boundary - copied + 1))
                if not chunk:
                    break
                next_copied = copied + len(chunk)
                if next_copied > byte_limit:
                    raise DocumentSkillsError(
                        ErrorCode.ARCHIVE_UNSAFE,
                        "The provider input grew beyond its byte ceiling while being copied.",
                        details={
                            "input_bytes": next_copied,
                            "input_limit": byte_limit,
                        },
                    )
                if next_copied > source.bytes:
                    raise DocumentSkillsError(
                        ErrorCode.VALIDATION_FAILED,
                        "The input changed while the provider snapshot was created.",
                        details={
                            "source_changed_during_snapshot": True,
                            "expected_sha256": source.sha256,
                            "expected_bytes": source.bytes,
                            "copied_bytes": next_copied,
                        },
                    )
                output_handle.write(chunk)
                digest.update(chunk)
                copied = next_copied
    except DocumentSkillsError:
        raise
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The provider input snapshot could not be created.",
            details={"reason": type(error).__name__},
        ) from error
    if digest.hexdigest() != source.sha256 or copied != source.bytes:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The input changed while the provider snapshot was created.",
            details={
                "source_changed_during_snapshot": True,
                "expected_sha256": source.sha256,
                "expected_bytes": source.bytes,
                "copied_bytes": copied,
            },
        )
    return staged


def _bounded_hash(handle: BinaryIO, byte_limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    hashed_bytes = 0
    while True:
        chunk = handle.read(min(1024 * 1024, byte_limit - hashed_bytes + 1))
        if not chunk:
            break
        hashed_bytes += len(chunk)
        if hashed_bytes > byte_limit:
            raise _ByteLimitExceeded(hashed_bytes)
        digest.update(chunk)
    return digest.hexdigest(), hashed_bytes


def _raise_input_too_large(input_bytes: int, byte_limit: int) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "The provider input exceeds its byte ceiling.",
        details={"input_bytes": input_bytes, "input_limit": byte_limit},
    )


def _raise_source_growth(actual_bytes: int, byte_limit: int) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Source artifact grew beyond its byte ceiling during a non-destructive operation.",
        details={
            "source_growth_exceeds_limit": True,
            "actual_bytes": actual_bytes,
            "input_limit": byte_limit,
        },
    )
