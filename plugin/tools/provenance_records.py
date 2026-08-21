"""Validation helpers for all-file provenance classifications."""

import hashlib
from pathlib import Path
from typing import Any


def mapping_digest(
    records: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
    data_records: list[dict[str, Any]],
    metadata_exclusions: list[dict[str, Any]],
) -> str:
    entries = [
        *(f"module:{record['module']}:{record['sha256']}" for record in records),
        *(
            f"excluded:{record['artifact']}:{record['sha256']}"
            for record in exclusions
        ),
        *(
            f"data:{record['artifact']}:{record['classification']}:{record['sha256']}"
            for record in data_records
        ),
        *(
            f"metadata:{record['artifact']}:{record['classification']}"
            for record in metadata_exclusions
        ),
    ]
    return hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()


def validate_exclusion(
    root: Path,
    record: dict[str, Any],
    reviewers: set[str],
) -> None:
    required = {
        "artifact", "sha256", "classification", "reason", "reviewer",
        "review_evidence",
    }
    artifact = record.get("artifact", "<unknown>")
    _require(required <= record.keys(), f"Incomplete executable exclusion: {artifact}")
    _require(
        record["classification"] == "non-executable-data",
        f"Executable exclusion has unsupported classification: {artifact}",
    )
    _require(len(record["reason"].strip()) >= 20, f"Executable exclusion reason is weak: {artifact}")
    _require(record["reviewer"] in reviewers, f"Exclusion reviewer is unattested: {artifact}")
    actual = hashlib.sha256((root / artifact).read_bytes()).hexdigest()
    _require(actual == record["sha256"], f"Excluded artifact hash drift: {artifact}")
    _validate_review_evidence(root, artifact, record["review_evidence"])
    _require(
        any(
            Path(evidence).as_posix().startswith("provenance/reviews/")
            for evidence in record["review_evidence"]
        ),
        f"Executable exclusion lacks actual review-report evidence: {artifact}",
    )


def validate_data_record(
    root: Path,
    record: dict[str, Any],
    reviewers: set[str],
    inventory: dict[str, Any],
) -> None:
    required = {
        "artifact", "sha256", "classification", "reason", "reviewer",
        "review_evidence",
    }
    artifact = record.get("artifact", "<unknown>")
    _require(required <= record.keys(), f"Incomplete data classification: {artifact}")
    classified = inventory.get(artifact)
    _require(classified is not None, f"Classified data is absent: {artifact}")
    _require(not classified.risky, f"Risky artifact is misclassified as data: {artifact}")
    _require(
        record["classification"] == classified.classification,
        f"Data classification differs from shared inventory: {artifact}",
    )
    _require(len(record["reason"].strip()) >= 20, f"Data classification reason is weak: {artifact}")
    _require(record["reviewer"] in reviewers, f"Data reviewer is unattested: {artifact}")
    actual = hashlib.sha256((root / artifact).read_bytes()).hexdigest()
    _require(actual == record["sha256"], f"Classified data hash drift: {artifact}")
    _validate_review_evidence(root, artifact, record["review_evidence"])


def validate_metadata_exclusion(
    root: Path,
    record: dict[str, Any],
    reviewers: set[str],
) -> None:
    required = {
        "artifact", "classification", "reason", "reviewer", "review_evidence",
    }
    artifact = record.get("artifact", "<unknown>")
    _require(required <= record.keys(), f"Incomplete metadata exclusion: {artifact}")
    _require(
        record["classification"] == "self-referential-audit-metadata",
        f"Unsupported metadata exclusion: {artifact}",
    )
    _require(
        artifact in {
            "provenance/audit-report.json",
            "provenance/modules.json",
            "provenance/reviews/clean-room-parity-and-hardening-review-cycle-round-1.md",
            "provenance/reviews/core-docx-review-cycle-round-1.md",
            "provenance/reviews/core-pdf-review-cycle-round-1.md",
            "provenance/reviews/core-pptx-review-cycle-round-1.md",
            "provenance/reviews/core-xlsx-review-cycle-round-1.md",
            "provenance/reviews/docx-create-optional-content-review-cycle-round-1.md",
            "provenance/reviews/document-skills-0.2.0-release.md",
            "provenance/reviews/document-skills-0.5.1-consumer-gates-implementation-audit.md",
            "provenance/reviews/document-skills-0.5.1-node20-process-review.md",
            "provenance/reviews/document-skills-0.5.2-ci-repair-and-version-bump-review.md",
            "provenance/reviews/document-skills-0.5.3-packaging-hygiene-review.md",
            "provenance/reviews/foundation-review-cycle-round-1.md",
            "provenance/reviews/html-to-editable-pptx-review-cycle-round-1.md",
            "provenance/reviews/libreoffice-enhancement-review-cycle-round-1.md",
            "provenance/reviews/openxml-dotnet-enhancement-review-cycle-round-1.md",
        },
        f"Metadata exclusion is outside the exact self-reference allowlist: {artifact}",
    )
    _require(len(record["reason"].strip()) >= 40, f"Metadata exclusion reason is weak: {artifact}")
    _require(record["reviewer"] in reviewers, f"Metadata reviewer is unattested: {artifact}")
    _validate_review_evidence(root, artifact, record["review_evidence"])


def _validate_review_evidence(
    root: Path,
    artifact: str,
    evidence_paths: list[str],
) -> None:
    _require(evidence_paths, f"Reviewed classification lacks evidence: {artifact}")
    for evidence in evidence_paths:
        _require(
            (root / evidence).is_file(),
            f"Missing classification evidence: {artifact}:{evidence}",
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
