"""Identity-bound private XLSX input snapshots for provider operations."""

from __future__ import annotations

import hashlib
from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io import ArtifactRecord


def stage_source_snapshot(source: ArtifactRecord, private_root: Path) -> Path:
    """Copy exactly the recorded source bytes once and verify the bound identity."""

    source_path = Path(source.path)
    staged = private_root / f"provider-source{source_path.suffix.casefold()}"
    digest = hashlib.sha256()
    copied = 0
    try:
        with source_path.open("rb") as input_handle, staged.open("xb") as output_handle:
            for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                output_handle.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
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
