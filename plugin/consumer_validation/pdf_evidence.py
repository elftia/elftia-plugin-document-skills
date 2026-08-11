"""Bounded, mutation-aware PDF byte evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Literal


EvidenceOutcome = Literal["exact", "resource-limit", "mutation"]


@dataclass(frozen=True)
class PdfArtifactEvidence:
    """One bounded observation; only ``exact`` binds content to the pathname."""

    outcome: EvidenceOutcome
    artifact_bytes: int | None
    sha256: str | None
    content: bytes | None = field(repr=False)
    evidence: dict[str, Any]


def read_bounded_pdf_evidence(
    artifact: Path,
    *,
    maximum_bytes: int,
    chunk_bytes: int,
) -> PdfArtifactEvidence:
    """Read at most ``maximum_bytes + 1`` and bind bytes to file identity."""

    if maximum_bytes <= 0 or chunk_bytes <= 0:
        raise ValueError("pdf-evidence-policy-invalid")
    initial_result = _stat_path(artifact)
    if isinstance(initial_result, PdfArtifactEvidence):
        return initial_result
    initial = initial_result
    if initial.st_size > maximum_bytes:
        return _resource_limit(initial.st_size, maximum_bytes, sentinel_bytes=0)

    try:
        handle = artifact.open("rb")
    except OSError as error:
        return _mutation(
            category="artifact-unavailable-before-open",
            initial=initial,
            error=error,
        )
    with handle:
        try:
            opened = os.fstat(handle.fileno())
        except OSError as error:
            return _mutation(
                category="artifact-handle-identity-unavailable",
                initial=initial,
                error=error,
            )
        if _file_identity(initial) != _file_identity(opened):
            return _mutation(
                category="artifact-replaced-before-evidence",
                initial=initial,
                opened=opened,
            )
        if opened.st_size > maximum_bytes:
            return _resource_limit(opened.st_size, maximum_bytes, sentinel_bytes=0)
        if not stat.S_ISREG(opened.st_mode):
            return _mutation(
                category="artifact-not-regular-before-evidence",
                initial=initial,
                opened=opened,
            )

        digest = hashlib.sha256()
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        try:
            while remaining > 0:
                chunk = handle.read(min(chunk_bytes, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        except OSError as error:
            return _mutation(
                category="artifact-read-failed",
                initial=initial,
                opened=opened,
                observed_bytes=sum(len(chunk) for chunk in chunks),
                observed_sha256=digest.hexdigest(),
                error=error,
            )
        observed = b"".join(chunks)
        try:
            final_handle = os.fstat(handle.fileno())
        except OSError as error:
            return _mutation(
                category="artifact-final-handle-identity-unavailable",
                initial=initial,
                opened=opened,
                observed_bytes=len(observed),
                observed_sha256=digest.hexdigest(),
                error=error,
            )

    try:
        final_path = artifact.stat()
    except OSError as error:
        return _mutation(
            category="artifact-missing-after-evidence",
            initial=initial,
            opened=opened,
            final_handle=final_handle,
            observed_bytes=len(observed),
            observed_sha256=digest.hexdigest(),
            error=error,
        )
    if not stat.S_ISREG(final_path.st_mode):
        return _mutation(
            category="artifact-not-regular-after-evidence",
            initial=initial,
            opened=opened,
            final_handle=final_handle,
            final_path=final_path,
            observed_bytes=len(observed),
            observed_sha256=digest.hexdigest(),
        )

    largest_size = max(
        initial.st_size,
        opened.st_size,
        final_handle.st_size,
        final_path.st_size,
        len(observed),
    )
    if largest_size > maximum_bytes or len(observed) > maximum_bytes:
        return _resource_limit(
            largest_size,
            maximum_bytes,
            sentinel_bytes=max(0, len(observed) - maximum_bytes),
        )

    changed = (
        _file_identity(initial) != _file_identity(final_path)
        or _file_identity(opened) != _file_identity(final_handle)
        or initial.st_size != opened.st_size
        or opened.st_size != final_handle.st_size
        or final_handle.st_size != final_path.st_size
        or len(observed) != final_handle.st_size
        or _modified_ns(initial) != _modified_ns(final_path)
        or _modified_ns(opened) != _modified_ns(final_handle)
    )
    if changed:
        return _mutation(
            category="artifact-mutated-during-evidence",
            initial=initial,
            opened=opened,
            final_handle=final_handle,
            final_path=final_path,
            observed_bytes=len(observed),
            observed_sha256=digest.hexdigest(),
        )

    return PdfArtifactEvidence(
        outcome="exact",
        artifact_bytes=len(observed),
        sha256=digest.hexdigest(),
        content=observed,
        evidence={
            "artifact_bytes": len(observed),
            "read_ceiling": maximum_bytes + 1,
        },
    )


def _stat_path(artifact: Path) -> os.stat_result | PdfArtifactEvidence:
    try:
        result = artifact.stat()
    except OSError as error:
        return _mutation(
            category="artifact-unavailable-before-evidence",
            error=error,
        )
    if not stat.S_ISREG(result.st_mode):
        return _mutation(
            category="artifact-not-regular-before-evidence",
            initial=result,
        )
    if result.st_size <= 0:
        return _mutation(
            category="artifact-empty-before-evidence",
            initial=result,
        )
    return result


def _resource_limit(
    actual: int,
    maximum: int,
    *,
    sentinel_bytes: int,
) -> PdfArtifactEvidence:
    return PdfArtifactEvidence(
        outcome="resource-limit",
        artifact_bytes=actual,
        sha256=None,
        content=None,
        evidence={
            "actual": actual,
            "category": "artifact-byte-limit",
            "maximum": maximum,
            "sentinel_bytes": sentinel_bytes,
        },
    )


def _mutation(
    *,
    category: str,
    initial: os.stat_result | None = None,
    opened: os.stat_result | None = None,
    final_handle: os.stat_result | None = None,
    final_path: os.stat_result | None = None,
    observed_bytes: int | None = None,
    observed_sha256: str | None = None,
    error: OSError | None = None,
) -> PdfArtifactEvidence:
    evidence: dict[str, Any] = {
        "category": category,
        "identity_status": "unavailable-non-exact-observation",
    }
    if initial is not None:
        evidence["initial_bytes"] = initial.st_size
    if opened is not None:
        evidence["opened_bytes"] = opened.st_size
    if final_handle is not None:
        evidence["final_handle_bytes"] = final_handle.st_size
    if final_path is not None:
        evidence["final_path_bytes"] = final_path.st_size
    if observed_bytes is not None:
        evidence["observed_stream_bytes"] = observed_bytes
    if observed_sha256 is not None:
        evidence["observed_stream_sha256"] = observed_sha256
    if error is not None:
        evidence["error_category"] = type(error).__name__
        if isinstance(error.errno, int):
            evidence["errno"] = error.errno
    return PdfArtifactEvidence(
        outcome="mutation",
        artifact_bytes=None,
        sha256=None,
        content=None,
        evidence=evidence,
    )


def _file_identity(result: os.stat_result) -> tuple[int, int]:
    return result.st_dev, result.st_ino


def _modified_ns(result: os.stat_result) -> int:
    return result.st_mtime_ns
