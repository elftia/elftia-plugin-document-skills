"""Immutable planning and run-aware Word text replacement."""

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import Story, TextGroup, iter_paragraphs, map_paragraph
from .xml_utils import set_text, xml_bytes


@dataclass(frozen=True)
class PlannedMatch:
    group: TextGroup
    start: int
    end: int
    rule_index: int
    replacement: str
    story_kind: str
    part: str


@dataclass
class ReplacementPlan:
    matches: list[PlannedMatch]
    counts: list[int]
    counts_by_story: dict[str, list[int]]
    protected: list[dict[str, Any]]


def plan_replacements(
    stories: list[Story],
    rules: list[dict[str, Any]],
    *,
    case_sensitive: bool,
    protected_comment_text: str = "",
) -> ReplacementPlan:
    matches: list[PlannedMatch] = []
    counts = [0 for _ in rules]
    counts_by_story: dict[str, list[int]] = {}
    protected = []
    for rule_index, rule in enumerate(rules):
        if _contains(
            protected_comment_text,
            rule["search"],
            case_sensitive=case_sensitive,
        ):
            protected.append(
                {
                    "part": "word/comments*.xml",
                    "story": "comments",
                    "paragraph": None,
                    "rule_index": rule_index,
                }
            )
    for story in stories:
        story_counts = counts_by_story.setdefault(
            f"{story.kind}:{story.part}", [0 for _ in rules]
        )
        for paragraph_index, paragraph in enumerate(iter_paragraphs(story.root)):
            mapped = map_paragraph(paragraph)
            for rule_index, rule in enumerate(rules):
                if _contains(
                    mapped.protected_text,
                    rule["search"],
                    case_sensitive=case_sensitive,
                ):
                    protected.append(
                        {
                            "part": story.part,
                            "story": story.kind,
                            "paragraph": paragraph_index,
                            "rule_index": rule_index,
                        }
                    )
            paragraph_matches = []
            for group in mapped.groups:
                for rule_index, rule in enumerate(rules):
                    for start, end in _find_spans(
                        group.text,
                        rule["search"],
                        case_sensitive=case_sensitive,
                    ):
                        paragraph_matches.append(
                            PlannedMatch(
                                group,
                                start,
                                end,
                                rule_index,
                                rule["replace"],
                                story.kind,
                                story.part,
                            )
                        )
            _assert_no_overlap(paragraph_matches)
            for match in paragraph_matches:
                matches.append(match)
                counts[match.rule_index] += 1
                story_counts[match.rule_index] += 1
    if protected:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Requested text occurs in a protected field, revision, comment, or content boundary.",
            status="enhancement_required",
            details={
                "protected_spans": protected,
                "recommended_providers": ["dotnet-openxml"],
            },
        )
    mismatches = []
    for index, rule in enumerate(rules):
        expected = rule["expected_matches"]
        if expected is not None and counts[index] != expected:
            mismatches.append(
                {"rule_index": index, "expected": expected, "actual": counts[index]}
            )
    if mismatches:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Replacement match counts do not satisfy the request.",
            details={"match_count_mismatches": mismatches},
        )
    return ReplacementPlan(matches, counts, counts_by_story, protected)


def apply_replacement_plan(plan: ReplacementPlan) -> None:
    grouped: dict[int, list[PlannedMatch]] = {}
    for match in plan.matches:
        grouped.setdefault(id(match.group), []).append(match)
    for matches in grouped.values():
        for match in sorted(matches, key=lambda item: item.start, reverse=True):
            _apply_match(match)


def changed_story_parts(stories: list[Story], plan: ReplacementPlan) -> dict[str, bytes]:
    changed = {match.part for match in plan.matches}
    return {
        story.part: xml_bytes(story.root)
        for story in stories
        if story.part in changed
    }


def plan_diagnostics(plan: ReplacementPlan, rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "formatting_anchor": "first-affected-run",
        "rule_counts": [
            {
                "rule_index": index,
                "search": rule["search"],
                "matches": plan.counts[index],
            }
            for index, rule in enumerate(rules)
        ],
        "counts_by_story": {
            key: value for key, value in sorted(plan.counts_by_story.items())
        },
        "protected_spans": plan.protected,
    }


def _find_spans(text: str, needle: str, *, case_sensitive: bool) -> list[tuple[int, int]]:
    if case_sensitive:
        haystack, target = text, needle
    else:
        if any(len(character.casefold()) != 1 for character in f"{text}{needle}"):
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Case-insensitive matching is ambiguous for length-changing Unicode folds.",
                status="invalid_request",
            )
        haystack, target = text.casefold(), needle.casefold()
    spans = []
    cursor = 0
    while True:
        start = haystack.find(target, cursor)
        if start < 0:
            return spans
        end = start + len(target)
        spans.append((start, end))
        cursor = end


def _contains(text: str, needle: str, *, case_sensitive: bool) -> bool:
    if not text:
        return False
    return bool(_find_spans(text, needle, case_sensitive=case_sensitive))


def _assert_no_overlap(matches: list[PlannedMatch]) -> None:
    ordered = sorted(matches, key=lambda item: (id(item.group), item.start, item.end))
    previous: PlannedMatch | None = None
    for match in ordered:
        if previous is not None and match.group is previous.group and match.start < previous.end:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Replacement rules overlap in the immutable source stream.",
                status="invalid_request",
                details={
                    "first_rule": previous.rule_index,
                    "second_rule": match.rule_index,
                },
            )
        previous = match


def _apply_match(match: PlannedMatch) -> None:
    affected = [
        reference
        for reference in match.group.refs
        if reference.end > match.start and reference.start < match.end
    ]
    if not affected:
        raise RuntimeError("planned DOCX match has no text nodes")
    first, last = affected[0], affected[-1]
    first_start = match.start - first.start
    last_end = match.end - last.start
    if first is last:
        current = first.node.text or ""
        set_text(
            first.node,
            current[:first_start] + match.replacement + current[last_end:],
        )
        return
    first_current = first.node.text or ""
    set_text(first.node, first_current[:first_start] + match.replacement)
    for reference in affected[1:-1]:
        set_text(reference.node, "")
    last_current = last.node.text or ""
    set_text(last.node, last_current[last_end:])
