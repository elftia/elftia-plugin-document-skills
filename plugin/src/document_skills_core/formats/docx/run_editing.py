"""Immutable text-match planning for bounded run formatting."""

from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


def plan_run_matches(
    mapped: Any,
    edit: dict[str, Any],
    *,
    paragraph_index: int,
) -> tuple[Element, ...]:
    needle = edit["match"]["text"]
    matches: list[tuple[Any, int, int]] = []
    for group in mapped.groups:
        cursor = 0
        while True:
            start = group.text.find(needle, cursor)
            if start < 0:
                break
            matches.append((group, start, start + len(needle)))
            cursor = start + len(needle)
    expected = edit["match"]["expected_matches"]
    if len(matches) != expected:
        _precondition_failed(
            paragraph_index,
            "run-style-match-count",
            expected_matches=expected,
            actual_matches=len(matches),
        )

    selected: list[Element] = []
    for group, start, end in matches:
        intervals: list[tuple[Element, int, int]] = []
        for reference in group.refs:
            existing = next(
                (item for item in intervals if item[0] is reference.run),
                None,
            )
            if existing is None:
                intervals.append((reference.run, reference.start, reference.end))
            else:
                intervals[intervals.index(existing)] = (
                    existing[0],
                    min(existing[1], reference.start),
                    max(existing[2], reference.end),
                )
        overlapping = [
            item for item in intervals if item[1] < end and item[2] > start
        ]
        if not overlapping or overlapping[0][1] != start or overlapping[-1][2] != end:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Run styling currently requires match boundaries to align with complete runs.",
                status="enhancement_required",
                details={"paragraph_index": paragraph_index, "match_text": needle},
            )
        selected.extend(item[0] for item in overlapping)
    return tuple(dict.fromkeys(selected))


def _precondition_failed(
    paragraph_index: int,
    reason: str,
    **details: Any,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX edit selector precondition did not match the immutable input.",
        details={"paragraph_index": paragraph_index, "reason": reason, **details},
    )
