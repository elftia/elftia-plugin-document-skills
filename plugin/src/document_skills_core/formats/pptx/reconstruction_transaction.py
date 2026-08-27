"""Identity-aware output and optional audit-asset publication."""

import hashlib
import os
from pathlib import Path
import stat
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.parent_anchor import DestinationParentAnchor
from document_skills_core.core.io.paths import (
    ArtifactRecord,
    DestinationSnapshot,
    atomic_promote,
    file_record,
)
from document_skills_core.core.io.path_identity import same_path
from document_skills_core.core.io.parent_anchor_types import FileIdentity, ParentSafetyError

from .contracts import ParsedPptxRequest
from .reconstruction_models import RasterEvidence
from .transaction import promote_candidate


def audit_asset_path(
    output: Path,
    source: Path,
    raster: RasterEvidence,
) -> Path:
    extension = ".png" if raster.media_type == "image/png" else ".jpg"
    base = f"{output.name}.source-audit-{raster.sha256}{extension}"
    candidate = output.with_name(base)
    index = 1
    while same_path(candidate, source) or same_path(candidate, output):
        candidate = output.with_name(f"{base}.{index}")
        index += 1
    return candidate


def audit_artifact_record(path: Path, raster: RasterEvidence) -> ArtifactRecord:
    return ArtifactRecord("report", str(path), raster.sha256, raster.byte_count)


def promote_reconstruction_candidate(
    request: ParsedPptxRequest,
    staged_pptx: Path,
    staged_audit: Path,
    result: dict[str, Any],
    *,
    source: ArtifactRecord,
    destination: DestinationSnapshot,
    audit_record: ArtifactRecord | None,
    audit_destination: DestinationSnapshot | None,
) -> dict[str, Any]:
    created_identity: FileIdentity | None = None
    candidate = file_record(staged_pptx, "output")
    try:
        if audit_record is not None:
            if audit_destination is None:
                raise RuntimeError("Retained audit publication requires a destination snapshot.")
            created_identity = _ensure_audit_asset(
                staged_audit,
                audit_record,
                audit_destination,
            )
        promoted = promote_candidate(
            request,
            staged_pptx,
            result,
            source=source,
            destination=destination,
        )
    except Exception as error:
        if (
            created_identity is not None
            and audit_record is not None
            and not _matches(Path(request.output_path), candidate)
            and not _cleanup_owned_audit(
                Path(audit_record.path),
                created_identity,
                audit_record.sha256,
                audit_record.bytes,
            )
            and isinstance(error, DocumentSkillsError)
        ):
            error.details["audit_cleanup_failed"] = True
        raise
    if audit_record is not None and not _matches(Path(audit_record.path), audit_record):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Retained audit asset changed after output publication.",
            details={"promotion_committed": True, "audit_asset_invalid": True},
        )
    return promoted


def _ensure_audit_asset(
    staged: Path,
    expected: ArtifactRecord,
    destination: DestinationSnapshot,
) -> FileIdentity | None:
    path = Path(expected.path)
    if destination.exists:
        if not _matches(path, expected):
            raise DocumentSkillsError(
                ErrorCode.STALE_PRECONDITION,
                "Retained audit destination is occupied by different content.",
                status="invalid_request",
                details={"audit_destination_occupied": True},
            )
        return None
    promoted = atomic_promote(
        staged,
        path,
        expected_destination=destination,
        expected_source_sha256=expected.sha256,
        expected_source_bytes=expected.bytes,
    )
    if promoted.sha256 != expected.sha256 or promoted.bytes != expected.bytes:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Retained audit asset differs from the screened source.",
        )
    metadata = path.stat(follow_symlinks=False)
    return metadata.st_dev, metadata.st_ino


def _matches(path: Path, expected: ArtifactRecord) -> bool:
    try:
        record = file_record(path, expected.role)
    except (DocumentSkillsError, OSError):
        return False
    return record.sha256 == expected.sha256 and record.bytes == expected.bytes


def _cleanup_owned_audit(
    path: Path,
    expected_identity: FileIdentity,
    expected_sha256: str,
    expected_bytes: int,
) -> bool:
    try:
        parent, physical_path = DestinationParentAnchor.capture(path)
        with parent:
            metadata = parent.entry_stat(physical_path.name)
            if (
                (metadata.st_dev, metadata.st_ino) != expected_identity
                or not stat.S_ISREG(metadata.st_mode)
            ):
                return False
            with parent.open_entry(physical_path.name) as handle:
                digest = hashlib.sha256()
                observed = 0
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    observed += len(chunk)
            parent.assert_bound("audit_cleanup")
            metadata = parent.entry_stat(physical_path.name)
            if (
                (metadata.st_dev, metadata.st_ino) != expected_identity
                or digest.hexdigest() != expected_sha256
                or observed != expected_bytes
            ):
                return False
            os.unlink(parent.entry_path(physical_path.name, require_bound=True, phase="audit_unlink"))
            return True
    except (OSError, ParentSafetyError):
        return False


__all__ = [
    "audit_artifact_record",
    "audit_asset_path",
    "promote_reconstruction_candidate",
]
