"""Exact module provenance and clean-room process evidence audits."""

import hashlib
import json
from pathlib import Path
from typing import Any

from .provenance_records import (
    mapping_digest,
    validate_data_record,
    validate_exclusion,
    validate_metadata_exclusion,
)
from .release_inventory import release_artifacts, release_inventory
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

_SOURCE_CLASSES = {"original", "adopted", "clean-room"}
_REVIEW_RUNTIMES = {"claude", "codex", "human"}


def audit_provenance(
    root: Path, inventory: list[str] | None = None
) -> dict[str, Any]:
    manifest = _load_json(root / "provenance" / "modules.json")
    records = manifest["modules"]
    exclusions = manifest.get("executable_exclusions", [])
    data_records = manifest.get("data_classifications", [])
    metadata_exclusions = manifest.get("metadata_exclusions", [])
    reviews = manifest.get("review_attestations", [])
    artifacts = release_artifacts(root, inventory)
    release_paths = [artifact.path for artifact in artifacts]
    release_keys = [
        PORTABLE_PATH_POLICY.require_release_safe(path).keys
        for path in release_paths
    ]
    _require(
        len(release_keys) == len(set(release_keys)),
        "Release inventory contains a portable path identity collision",
    )
    risky_paths = sorted(artifact.path for artifact in artifacts if artifact.risky)
    mappings = [record.get("module") for record in records]
    excluded = [record.get("artifact") for record in exclusions]
    classified = [record.get("artifact") for record in data_records]
    metadata = [record.get("artifact") for record in metadata_exclusions]
    _require(len(mappings) == len(set(mappings)), "Duplicate provenance module mapping")
    _require(len(excluded) == len(set(excluded)), "Duplicate executable exclusion")
    all_mappings = [*mappings, *excluded, *classified, *metadata]
    _require(
        len(all_mappings) == len(set(all_mappings)),
        "Release artifact has multiple provenance classifications",
    )
    _require(
        sorted(all_mappings) == release_paths,
        "All-file provenance mapping does not match the release inventory",
    )
    _require(
        sorted([*mappings, *excluded]) == risky_paths,
        "Risky artifact provenance does not match the shared release inventory",
    )
    digest = mapping_digest(
        records, exclusions, data_records, metadata_exclusions
    )
    # Exact inventory and byte hashes remain mandatory for every release. A
    # separate review is optional; a pending label must never impersonate one.
    reviewers = (
        _validate_review_attestations(root, reviews, digest)
        if reviews
        else {"PENDING independent review"}
    )
    required = {
        "module",
        "sha256",
        "source_class",
        "requirement_source",
        "implementation_source",
        "third_party_files",
        "license",
        "modifications",
        "reviewer",
        "review_evidence",
        "clean_room",
        "artifact_tests",
    }
    for record in records:
        module = record["module"]
        _require("*" not in module and "?" not in module, f"Glob provenance is forbidden: {module}")
        _require(required <= record.keys(), f"Incomplete provenance record: {module}")
        _require(record["source_class"] in _SOURCE_CLASSES, f"Invalid source class: {module}")
        _require(record["reviewer"] in reviewers, f"Reviewer attestation missing: {module}")
        actual = hashlib.sha256((root / module).read_bytes()).hexdigest()
        _require(actual == record["sha256"], f"Module hash drift: {module}")
        for evidence in [*record["review_evidence"], *record["artifact_tests"]]:
            _require((root / evidence).is_file(), f"Missing provenance evidence: {module}:{evidence}")
        if record["source_class"] == "adopted":
            _require(record["third_party_files"], f"Adopted source origin missing: {module}")
            _require(record["license"] != "NOASSERTION", f"Adopted license missing: {module}")
        else:
            _require(not record["third_party_files"], f"Unexpected third-party file: {module}")
    for record in exclusions:
        validate_exclusion(root, record, reviewers)
    by_path = {artifact.path: artifact for artifact in artifacts}
    for record in data_records:
        validate_data_record(root, record, reviewers, by_path)
    for record in metadata_exclusions:
        validate_metadata_exclusion(root, record, reviewers)
    return {
        "status": "pass",
        "module_count": len(risky_paths),
        "record_count": len(records),
        "exclusion_count": len(exclusions),
        "data_classification_count": len(data_records),
        "metadata_exclusion_count": len(metadata_exclusions),
        "release_file_count": len(release_paths),
        "review_attestations": len(reviews),
        "mapping_sha256": digest,
    }


def audit_clean_room(root: Path) -> dict[str, Any]:
    records = _load_json(root / "provenance" / "modules.json")["modules"]
    adopted = _load_json(root / "provenance" / "modules.json").get("adopted_sources", [])
    for record in records:
        _require(record["clean_room"] is True, f"Clean-room process evidence missing: {record['module']}")
        _require(record["review_evidence"], f"Review evidence missing: {record['module']}")
    for record in adopted:
        _require(record.get("exact_revision"), "Adopted source exact revision missing")
        _require(record.get("license_evidence"), "Adopted source license evidence missing")
    return {
        "status": "pass",
        "method": "exact-inventory-provenance",
        "expression_detection": "not_claimed",
        "module_records": len(records),
        "adopted_records": len(adopted),
    }


def provenance_modules(
    root: Path, inventory: list[str] | None = None
) -> list[str]:
    release_paths = inventory if inventory is not None else release_inventory(root)
    return sorted(
        artifact.path
        for artifact in release_artifacts(root, release_paths)
        if artifact.risky
    )


def _validate_review_attestations(
    root: Path,
    reviews: list[dict[str, Any]],
    mapping_digest: str,
) -> set[str]:
    _require(reviews, "Independent review attestation is missing")
    identities: set[str] = set()
    for review in reviews:
        required = {
            "id",
            "reviewer",
            "identity",
            "identity_assurance",
            "identity_limitations",
            "runtime",
            "role",
            "approval_claimed",
            "report_evidence",
            "report_name",
            "report_sha256",
            "reviewed_mapping_sha256",
            "scope",
            "status",
        }
        _require(required <= review.keys(), "Review attestation is incomplete")
        reviewer = review["reviewer"]
        _require(reviewer not in identities, f"Duplicate reviewer attestation: {reviewer}")
        _require(review["runtime"] in _REVIEW_RUNTIMES, f"Invalid reviewer runtime: {reviewer}")
        _require(
            review["identity"].startswith(f"{review['runtime']}-reviewer/"),
            f"Actual reviewer identity is missing: {reviewer}",
        )
        identity = review["identity"].lower()
        _require(
            not any(
                marker in identity
                for marker in ("placeholder", "unknown", "todo", "example")
            ),
            f"Reviewer identity is a placeholder: {reviewer}",
        )
        _require(review["role"] == "reviewer", f"Review role is not independent: {reviewer}")
        _require(
            review["scope"] == "all-release-artifacts",
            f"Review scope is incomplete: {reviewer}",
        )
        _require(
            review["identity_assurance"] in {"self-asserted", "cryptographically-verified"},
            f"Reviewer identity assurance is invalid: {reviewer}",
        )
        limitations = review["identity_limitations"].strip().lower()
        _require(
            len(limitations) >= 50
            and ("cannot" in limitations or "does not" in limitations),
            f"Reviewer identity limitations are not honest: {reviewer}",
        )
        _require(
            review["approval_claimed"] is False or review["status"] == "clean",
            f"Findings-bearing review claims approval: {reviewer}",
        )
        _require(
            len(review["report_sha256"]) == 64
            and all(character in "0123456789abcdef" for character in review["report_sha256"]),
            f"Review report hash missing: {reviewer}",
        )
        _require(
            len(set(review["report_sha256"])) > 4,
            f"Review report hash is a placeholder: {reviewer}",
        )
        evidence_relative = Path(review["report_evidence"])
        _require(
            not evidence_relative.is_absolute()
            and ".." not in evidence_relative.parts
            and evidence_relative.parts[:2] == ("provenance", "reviews")
            and evidence_relative.suffix.lower() == ".md",
            f"Review report is not canonical checked-in evidence: {reviewer}",
        )
        _require(
            review["report_name"] == evidence_relative.name,
            f"Review report name/path mismatch: {reviewer}",
        )
        _require(
            review["reviewed_mapping_sha256"] == mapping_digest,
            f"Review does not bind the executable mapping digest: {reviewer}",
        )
        evidence_path = root / evidence_relative
        _require(evidence_path.is_file(), f"Review report evidence missing: {reviewer}")
        _require(not evidence_path.is_symlink(), f"Review report evidence is a symlink: {reviewer}")
        actual_report_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        _require(
            actual_report_hash == review["report_sha256"],
            f"Review report hash does not match canonical bytes: {reviewer}",
        )
        evidence = evidence_path.read_text(encoding="utf-8")
        for expected in (
            review["identity"],
            review["reviewed_mapping_sha256"],
            review["status"],
        ):
            _require(
                expected in evidence,
                f"Review evidence does not bind the attestation: {reviewer}",
            )
        identities.add(reviewer)
    return identities


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
