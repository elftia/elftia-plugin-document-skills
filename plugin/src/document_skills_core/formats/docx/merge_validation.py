"""Reopen assertions for compatible high-fidelity DOCX merge."""

from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import WORD_MAIN
from .merge_comments import count_comment_definitions
from .merge_content_controls import count_safe_merge_content_controls
from .merge_fields import count_safe_merge_fields
from .merge_graph import MergeGraphPlan
from .merge_revision_graph import count_revision_graph
from .note_editing import project_notes
from .package import OpcPackage


def assert_merge_candidate(path: Path, plan: MergeGraphPlan) -> dict[str, Any]:
    package = OpcPackage.open(path)
    if package.part_hashes.get(WORD_MAIN) != plan.expected_main_sha256:
        _failed("main-document")
    changed_failures = [
        name
        for name, expected in plan.expected_changed_hashes.items()
        if package.part_hashes.get(name) != expected
    ]
    if changed_failures:
        _failed("changed-parts", parts=sorted(changed_failures))
    failures = [
        name
        for name, payload in plan.added_parts.items()
        if package.part_hashes.get(name) != sha256(payload).hexdigest()
    ]
    if failures:
        _failed("copied-parts", parts=sorted(failures))
    actual_field_count = count_safe_merge_fields(
        package.xml(WORD_MAIN),
        source_index=None,
    )
    if actual_field_count != plan.expected_field_count:
        _failed(
            "fields",
            actual=actual_field_count,
            expected=plan.expected_field_count,
        )
    actual_content_control_count = count_safe_merge_content_controls(
        package.xml(WORD_MAIN),
        source_index=None,
    )
    if actual_content_control_count != plan.expected_content_control_count:
        _failed(
            "content-controls",
            actual=actual_content_control_count,
            expected=plan.expected_content_control_count,
        )
    notes, notes_truncated = project_notes(
        package,
        maximum=max(plan.expected_note_count + 1, 1),
    )
    if notes_truncated or len(notes) != plan.expected_note_count:
        _failed(
            "notes",
            actual=len(notes),
            expected=plan.expected_note_count,
            truncated=notes_truncated,
        )
    comment_count = count_comment_definitions(package)
    if comment_count != plan.expected_comment_count:
        _failed(
            "comments",
            actual=comment_count,
            expected=plan.expected_comment_count,
        )
    revision_count, move_range_count = count_revision_graph(package.xml(WORD_MAIN))
    if revision_count != plan.expected_revision_count:
        _failed(
            "revisions",
            actual=revision_count,
            expected=plan.expected_revision_count,
        )
    if move_range_count != plan.expected_move_range_count:
        _failed(
            "move-ranges",
            actual=move_range_count,
            expected=plan.expected_move_range_count,
        )
    return {
        "verified_copied_parts": len(plan.added_parts),
        "verified_body_blocks": plan.copied_body_blocks,
        "verified_fields": actual_field_count,
        "verified_content_controls": actual_content_control_count,
        "verified_notes": len(notes),
        "verified_comments": comment_count,
        "verified_revisions": revision_count,
        "verified_move_ranges": move_range_count,
    }


def _failed(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Merged DOCX does not match the immutable graph plan.",
        details={"reason": reason, **details},
    )
