"""Regenerate exact all-file provenance from final release bytes."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .html_pptx_provenance import (
    HTML_PPTX_REQUIREMENT,
    html_pptx_data_profile,
    html_pptx_module_profile,
)
from .provenance_records import mapping_digest
from .release_inventory import release_artifacts

PENDING_REVIEWER = "PENDING independent review"


def regenerate(
    root: Path,
    *,
    reviewer: str = PENDING_REVIEWER,
    review: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    artifacts = release_artifacts(root)
    modules = []
    data = []
    metadata = []
    for artifact in artifacts:
        if _is_metadata(artifact.path):
            metadata.append(
                {
                    "artifact": artifact.path,
                    "classification": "self-referential-audit-metadata",
                    "reason": (
                        "This audit metadata contains or reports the mapping digest, so "
                        "raw self-hashing would be circular; exact scope and "
                        "classification require independent review."
                    ),
                    "reviewer": reviewer,
                    "review_evidence": ["PROVENANCE.md"],
                }
            )
        elif artifact.risky:
            modules.append(_module_record(artifact, reviewer))
        else:
            data.append(_data_record(artifact, reviewer))
    digest = mapping_digest(modules, [], data, metadata)
    reviews = []
    if review is not None:
        if review["reviewed_mapping_sha256"] != digest:
            raise ValueError("review does not bind the regenerated mapping")
        report = root / review["report_evidence"]
        review["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
        reviews.append(review)
        evidence = [review["report_evidence"]]
        for record in [*modules, *data, *metadata]:
            record["review_evidence"] = evidence
    manifest = {
        "schema_version": "1.0",
        "modules": modules,
        "adopted_sources": [],
        "executable_exclusions": [],
        "data_classifications": data,
        "metadata_exclusions": metadata,
        "review_attestations": reviews,
    }
    return manifest, digest


def _module_record(artifact: Any, reviewer: str) -> dict[str, Any]:
    html_profile = html_pptx_module_profile(artifact.path)
    is_docx = (
        "/docx/" in artifact.path
        or "document-docx" in artifact.path
        or "docx_" in artifact.path
        or "docx-" in artifact.path
    )
    tests = html_profile[1] if html_profile else (
        [
            "tests/test_docx_contracts.py",
            "tests/test_docx_operations.py",
            "tests/test_docx_public.py",
            "tests/test_supply_chain.py",
        ]
        if is_docx
        else
        [
            "tests/test_strategy2.py",
            "tests/test_strategy3.py",
            "tests/test_runtime.py",
        ]
        if artifact.path.startswith(("src/", "runtime/", "skills/"))
        else [
            "tests/test_strategy2.py",
            "tests/test_strategy3.py",
            "tests/test_supply_chain.py",
        ]
    )
    return {
        "module": artifact.path,
        "sha256": artifact.sha256,
        "source_class": "original",
        "requirement_source": (
            HTML_PPTX_REQUIREMENT
            if html_profile
            else "Rasen document-skills-core-docx"
            if is_docx
            else "Rasen document-skills-foundation strategy-attempt-3"
        ),
        "implementation_source": "Original Elftia project code",
        "third_party_files": [],
        "license": "GPL-3.0",
        "modifications": (
            html_profile[0]
            if html_profile
            else
            (
                "Original Core DOCX contract, package, projection, mutation, "
                "validation, Skill guidance, tests, or release evidence."
            )
            if is_docx
            else (
                "Strategy-attempt-3 semantic loader/reflection, command discovery, "
                "portable release inventory, tests, or release evidence."
            )
        ),
        "reviewer": reviewer,
        "review_evidence": ["PROVENANCE.md"],
        "clean_room": True,
        "artifact_tests": tests,
    }


def _data_record(artifact: Any, reviewer: str) -> dict[str, Any]:
    profile = html_pptx_data_profile(artifact.path)
    record = {
        "artifact": artifact.path,
        "sha256": artifact.sha256,
        "classification": artifact.classification,
        "reason": (
            profile[0]
            if profile
            else (
                "Exact non-execution release bytes are classified by the shared "
                "release inventory and require independent review."
            )
        ),
        "reviewer": reviewer,
        "review_evidence": ["PROVENANCE.md"],
    }
    if profile:
        record.update({
            "requirement_source": HTML_PPTX_REQUIREMENT,
            "modifications": profile[0],
            "artifact_tests": profile[1],
        })
    return record


def _is_metadata(path: str) -> bool:
    return path in {
        "provenance/audit-report.json",
        "provenance/modules.json",
        "provenance/reviews/clean-room-parity-and-hardening-review-cycle-round-1.md",
        "provenance/reviews/core-docx-review-cycle-round-1.md",
        "provenance/reviews/core-pdf-review-cycle-round-1.md",
        "provenance/reviews/core-pptx-review-cycle-round-1.md",
        "provenance/reviews/core-xlsx-review-cycle-round-1.md",
        "provenance/reviews/docx-create-optional-content-review-cycle-round-1.md",
        "provenance/reviews/document-skills-0.2.0-release.md",
        "provenance/reviews/foundation-review-cycle-round-1.md",
        "provenance/reviews/html-to-editable-pptx-review-cycle-round-1.md",
        "provenance/reviews/libreoffice-enhancement-review-cycle-round-1.md",
        "provenance/reviews/openxml-dotnet-enhancement-review-cycle-round-1.md",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest, digest = regenerate(args.project_root.resolve())
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
