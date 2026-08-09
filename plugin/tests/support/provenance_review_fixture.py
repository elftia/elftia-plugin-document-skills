"""Deterministic review binding for provenance audit tests only."""

import json
from pathlib import Path

from tools.regenerate_provenance import regenerate


def bind_test_review(
    root: Path,
    *,
    report_name: str = "foundation-review-cycle-round-1.md",
) -> None:
    report_path = root / "provenance" / "reviews" / report_name
    if not report_path.exists():
        report_path.write_text("Pending deterministic test review.\n", encoding="utf-8")
    manifest, digest = regenerate(root)
    identity = "codex-reviewer/document-skills-foundation/test-fixture"
    report_path.write_text(
        f"Identity: `{identity}`\nMapping: `{digest}`\nStatus: `clean`\n",
        encoding="utf-8",
    )
    review = {
        "id": "strategy-2-test-review",
        "reviewer": "Strategy-2 independent test fixture reviewer",
        "identity": identity,
        "identity_assurance": "self-asserted",
        "identity_limitations": (
            "This deterministic test fixture cannot prove a human or service "
            "principal and does not represent release approval."
        ),
        "runtime": "codex",
        "role": "reviewer",
        "approval_claimed": True,
        "report_evidence": f"provenance/reviews/{report_name}",
        "report_name": report_name,
        "report_sha256": "pending",
        "reviewed_mapping_sha256": digest,
        "scope": "all-release-artifacts",
        "status": "clean",
    }
    manifest, rebound = regenerate(
        root,
        reviewer=review["reviewer"],
        review=review,
    )
    assert rebound == digest
    (root / "provenance" / "modules.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
