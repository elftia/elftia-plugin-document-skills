"""Audit the complete bounded revision annotation graph before merge."""

from typing import Iterable
from xml.etree.ElementTree import Element

from .merge_move_graph import audit_move_ranges
from .merge_revision_types import (
    MAX_REVISIONS,
    REVISION_TAGS,
    UNSUPPORTED_REVISION_TAGS,
    RevisionGraph,
    RevisionRecord,
    claim_annotation_id,
    context,
    unsupported,
    validate_revision,
)


def count_inline_revisions(root: Element) -> int:
    return count_revision_graph(root)[0]


def count_move_revision_ranges(root: Element) -> int:
    return count_revision_graph(root)[1]


def count_revision_graph(root: Element) -> tuple[int, int]:
    graph = audit_revision_graph(
        [root],
        document="candidate",
        source_index=None,
    )
    return len(graph.revisions), len(graph.move_ranges)


def audit_revision_graph(
    nodes: Iterable[Element],
    *,
    document: str,
    source_index: int | None,
) -> RevisionGraph:
    elements = [element for parent in nodes for element in parent.iter()]
    unsupported_tags = sorted(
        {
            element.tag.rsplit("}", 1)[-1]
            for element in elements
            if element.tag.rsplit("}", 1)[-1] in UNSUPPORTED_REVISION_TAGS
        }
    )
    if unsupported_tags:
        unsupported(
            "DOCX merge contains tracked-change structures outside the bounded graph slice.",
            structures=unsupported_tags,
            **context(document, source_index),
        )
    revisions: list[RevisionRecord] = []
    annotation_ids: set[int] = set()
    for position, element in enumerate(elements):
        revision_type = element.tag.rsplit("}", 1)[-1]
        if revision_type not in REVISION_TAGS:
            continue
        revision_id, author, date = validate_revision(
            element,
            revision_type=revision_type,
            document=document,
            source_index=source_index,
        )
        claim_annotation_id(
            annotation_ids,
            revision_id,
            document=document,
            revision_type=revision_type,
            source_index=source_index,
        )
        revisions.append(
            RevisionRecord(
                revision_type,
                element,
                revision_id,
                author,
                date,
                position,
            )
        )
    move_ranges = audit_move_ranges(
        elements,
        revisions,
        document=document,
        source_index=source_index,
    )
    for move_range in move_ranges:
        claim_annotation_id(
            annotation_ids,
            move_range.source_id,
            document=document,
            revision_type=f"{move_range.range_type}Range",
            source_index=source_index,
        )
    if len(annotation_ids) > MAX_REVISIONS:
        unsupported("DOCX merge revision count exceeds the supported bound.")
    return RevisionGraph(
        tuple(revisions),
        tuple(move_ranges),
        frozenset(annotation_ids),
    )
