"""Bounded, mutation-aware PDF byte evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from typing import Any, Literal


EvidenceOutcome = Literal["exact", "resource-limit", "mutation"]


@dataclass(frozen=True)
class PdfArtifactEvidence:
    """One bounded observation; only ``exact`` binds content to the pathname."""

    outcome: EvidenceOutcome
    artifact_bytes: int
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
    initial = _stat_path(artifact)
    if initial.st_size > maximum_bytes:
        return _resource_limit(initial.st_size, maximum_bytes, sentinel_bytes=0)

    with artifact.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if opened.st_size > maximum_bytes:
            return _resource_limit(opened.st_size, maximum_bytes, sentinel_bytes=0)
        if _file_identity(initial) != _file_identity(opened):
            return _mutation(
                artifact_bytes=initial.st_size,
                category="artifact-replaced-before-evidence",
                initial=initial,
                opened=opened,
            )

        digest = hashlib.sha256()
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = handle.read(min(chunk_bytes, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        observed = b"".join(chunks)
        final_handle = os.fstat(handle.fileno())

    try:
        final_path = artifact.stat()
    except OSError:
        return _mutation(
            artifact_bytes=len(observed),
            category="artifact-missing-after-evidence",
            initial=initial,
            opened=opened,
            final_handle=final_handle,
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
            artifact_bytes=len(observed),
            category="artifact-mutated-during-evidence",
            initial=initial,
            opened=opened,
            final_handle=final_handle,
            final_path=final_path,
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


def _stat_path(artifact: Path) -> os.stat_result:
    if not artifact.is_file():
        raise ValueError("artifact-missing")
    result = artifact.stat()
    if result.st_size <= 0:
        raise ValueError("artifact-empty")
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
    artifact_bytes: int,
    category: str,
    initial: os.stat_result,
    opened: os.stat_result,
    final_handle: os.stat_result | None = None,
    final_path: os.stat_result | None = None,
    observed_sha256: str | None = None,
) -> PdfArtifactEvidence:
    evidence: dict[str, Any] = {
        "category": category,
        "initial_bytes": initial.st_size,
        "opened_bytes": opened.st_size,
    }
    if final_handle is not None:
        evidence["final_handle_bytes"] = final_handle.st_size
    if final_path is not None:
        evidence["final_path_bytes"] = final_path.st_size
    if observed_sha256 is not None:
        evidence["observed_stream_sha256"] = observed_sha256
    return PdfArtifactEvidence(
        outcome="mutation",
        artifact_bytes=artifact_bytes,
        sha256=observed_sha256,
        content=None,
        evidence=evidence,
    )


def _file_identity(result: os.stat_result) -> tuple[int, int]:
    return result.st_dev, result.st_ino


def _modified_ns(result: os.stat_result) -> int:
    return result.st_mtime_ns
