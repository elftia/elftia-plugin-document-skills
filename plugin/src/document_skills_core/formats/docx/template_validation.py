"""Immutable template-plan semantic validation."""

from collections import Counter
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import (
    TextGroup,
    TextRef,
    document_stories,
    iter_paragraphs,
    map_paragraph,
    semantic_tree_digest,
)
from .package import OpcPackage
from .template import (
    TOKEN_PATTERN,
    TemplateExpectation,
    TemplatePlan,
    formatting_signature,
)

def assert_template_semantics(
    path: Path,
    plan: TemplatePlan,
) -> dict[str, Any]:
    """Verify the backend changed only the Python-planned story semantics."""
    package = OpcPackage.open(path)
    stories = {story.part: story for story in document_stories(package)}
    paragraphs = {
        part: list(iter_paragraphs(story.root))
        for part, story in stories.items()
    }
    expected_counts = Counter(
        item.variable
        for expectation in plan.expectations
        for item in expectation.occurrences
    )
    verified: Counter[str] = Counter()
    anchors = 0
    failures: list[dict[str, Any]] = []
    mutable_nodes: dict[str, set[int]] = {}

    for expectation in plan.expectations:
        part_paragraphs = paragraphs.get(expectation.part)
        if (
            part_paragraphs is None
            or expectation.paragraph_index >= len(part_paragraphs)
        ):
            failures.append(_template_failure(expectation, "missing-paragraph"))
            continue
        groups = map_paragraph(
            part_paragraphs[expectation.paragraph_index]
        ).groups
        if expectation.group_index >= len(groups):
            failures.append(_template_failure(expectation, "missing-text-group"))
            continue
        group = groups[expectation.group_index]
        mutable_nodes.setdefault(expectation.part, set()).update(
            id(reference.node) for reference in group.refs
        )
        if group.text != expectation.expected_text:
            failures.append(_template_failure(expectation, "rendered-text"))
            continue
        actual_node_texts = tuple(reference.node.text or "" for reference in group.refs)
        if actual_node_texts != expectation.expected_node_texts:
            failures.append(_template_failure(expectation, "text-node-plan"))
            continue
        for occurrence in expectation.occurrences:
            if (
                group.text[occurrence.output_start : occurrence.output_end]
                != occurrence.value
            ):
                failures.append(
                    _template_failure(
                        expectation,
                        "rendered-value",
                        variable=occurrence.variable,
                    )
                )
                continue
            anchor = _output_anchor(
                group,
                occurrence.output_start,
                occurrence.output_end,
            )
            if (
                anchor is None
                or formatting_signature(anchor.run)
                != occurrence.formatting_anchor
            ):
                failures.append(
                    _template_failure(
                        expectation,
                        "formatting-anchor",
                        variable=occurrence.variable,
                    )
                )
                continue
            verified[occurrence.variable] += 1
            anchors += 1

    expected_oracles = {oracle.part: oracle for oracle in plan.story_oracles}
    for part, oracle in expected_oracles.items():
        story = stories.get(part)
        actual_digest = (
            semantic_tree_digest(
                story.root,
                ignore_text_space_for=mutable_nodes.get(part, set()),
            )
            if story is not None
            else None
        )
        if actual_digest != oracle.semantic_sha256:
            failures.append(
                {
                    "reason": "story-semantic-oracle",
                    "part": part,
                    "expected_sha256": oracle.semantic_sha256,
                    "actual_sha256": actual_digest,
                }
            )

    expected_literals = Counter(
        match.group(1)
        for expectation in plan.expectations
        for match in TOKEN_PATTERN.finditer(expectation.expected_text)
        if match.group(1) in plan.used
    )
    actual_literals = Counter(
        match.group(1)
        for story in stories.values()
        for paragraph in iter_paragraphs(story.root)
        for group in map_paragraph(paragraph).groups
        for match in TOKEN_PATTERN.finditer(group.text)
        if match.group(1) in plan.used
    )
    if actual_literals != expected_literals:
        failures.append(
            {
                "reason": "unresolved-approved-tokens",
                "variables": sorted((actual_literals - expected_literals).keys()),
            }
        )
    if verified != expected_counts:
        failures.append(
            {
                "reason": "occurrence-counts",
                "expected": dict(sorted(expected_counts.items())),
                "actual": dict(sorted(verified.items())),
            }
        )
    if set(verified) != set(plan.used):
        failures.append(
            {
                "reason": "used-variables",
                "expected": list(plan.used),
                "actual": sorted(verified),
            }
        )
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template output does not satisfy the immutable semantic plan.",
            details={"mismatches": failures[:32]},
        )
    return {
        "verified_occurrences": sum(verified.values()),
        "counts_by_variable": dict(sorted(verified.items())),
        "used_variables": list(plan.used),
        "unused_variables": list(plan.unused),
        "unresolved_approved_tokens": 0,
        "formatting_anchors": anchors,
        "verified_story_parts": len(expected_oracles),
    }


def _output_anchor(group: TextGroup, start: int, end: int) -> TextRef | None:
    if end > start:
        for reference in group.refs:
            if reference.start <= start < reference.end:
                return reference
    return next(
        (
            reference
            for reference in group.refs
            if reference.start == start
            or reference.start <= start <= reference.end
        ),
        None,
    )


def _template_failure(
    expectation: TemplateExpectation,
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "part": expectation.part,
        "paragraph_index": expectation.paragraph_index,
        "group_index": expectation.group_index,
        **details,
    }
