"""Bounded pairing checks for Word move revision ranges."""

from xml.etree.ElementTree import Element

from .constants import qn
from .merge_revision_types import (
    MOVE_TYPES,
    MoveRange,
    RevisionRecord,
    context,
    unsafe,
    unsupported,
    validate_annotation_id,
    validate_move_start,
)


def audit_move_ranges(
    elements: list[Element],
    revisions: list[RevisionRecord],
    *,
    document: str,
    source_index: int | None,
) -> list[MoveRange]:
    move_revisions = [
        revision
        for revision in revisions
        if revision.revision_type in MOVE_TYPES
    ]
    marker_names = {
        f"{move_type}Range{boundary}"
        for move_type in MOVE_TYPES
        for boundary in ("Start", "End")
    }
    present_markers = sorted(
        {
            element.tag.rsplit("}", 1)[-1]
            for element in elements
            if element.tag.rsplit("}", 1)[-1] in marker_names
        }
    )
    if not move_revisions and not present_markers:
        return []
    if move_revisions and not present_markers:
        unsupported(
            "DOCX merge move revision graph is incomplete.",
            structures=sorted({item.revision_type for item in move_revisions}),
            **context(document, source_index),
        )
    ranges = [
        move_range
        for move_type in MOVE_TYPES
        for move_range in _audit_move_type_ranges(
            elements,
            move_revisions,
            move_type=move_type,
            document=document,
            source_index=source_index,
        )
    ]
    assigned = {id(move_range.wrapper) for move_range in ranges}
    if assigned != {id(revision.element) for revision in move_revisions}:
        unsupported(
            "DOCX merge move revision graph does not bind every move wrapper.",
            structures=sorted({item.revision_type for item in move_revisions}),
            **context(document, source_index),
        )
    _assert_non_overlapping_ranges(ranges, document, source_index)
    _assert_move_pairs(ranges, document, source_index)
    return sorted(ranges, key=lambda item: item.start_position)


def _audit_move_type_ranges(
    elements: list[Element],
    move_revisions: list[RevisionRecord],
    *,
    move_type: str,
    document: str,
    source_index: int | None,
) -> list[MoveRange]:
    start_name = f"{move_type}RangeStart"
    end_name = f"{move_type}RangeEnd"
    starts: dict[int, tuple[int, Element, str, str, str]] = {}
    ends: dict[int, tuple[int, Element]] = {}
    for position, element in enumerate(elements):
        local = element.tag.rsplit("}", 1)[-1]
        if local == start_name:
            range_id, name, author, date = validate_move_start(
                element,
                range_type=move_type,
                document=document,
                source_index=source_index,
            )
            numeric_id = int(range_id)
            if numeric_id in starts:
                unsafe(
                    "DOCX move range contains duplicate start ids.",
                    range_id=range_id,
                    range_type=move_type,
                    **context(document, source_index),
                )
            starts[numeric_id] = (position, element, name, author, date)
        elif local == end_name:
            range_id = validate_annotation_id(
                element.attrib.get(qn("w", "id"), ""),
                label="move range end",
                document=document,
                source_index=source_index,
            )
            numeric_id = int(range_id)
            if numeric_id in ends:
                unsafe(
                    "DOCX move range contains duplicate end ids.",
                    range_id=range_id,
                    range_type=move_type,
                    **context(document, source_index),
                )
            ends[numeric_id] = (position, element)
    if set(starts) != set(ends):
        unsupported(
            "DOCX merge move range start/end ids are incomplete.",
            structures=sorted({start_name, end_name}),
            **context(document, source_index),
        )
    result: list[MoveRange] = []
    for numeric_id, start_record in sorted(
        starts.items(),
        key=lambda item: item[1][0],
    ):
        start_position, start, name, author, date = start_record
        end_position, end = ends[numeric_id]
        if start_position >= end_position:
            unsafe(
                "DOCX move range end precedes its start.",
                range_id=str(numeric_id),
                range_type=move_type,
                **context(document, source_index),
            )
        contained = [
            revision
            for revision in move_revisions
            if revision.revision_type == move_type
            and start_position < revision.position < end_position
        ]
        if len(contained) != 1:
            unsupported(
                "DOCX merge move range must contain exactly one matching wrapper.",
                range_id=str(numeric_id),
                range_type=move_type,
                wrapper_count=len(contained),
                **context(document, source_index),
            )
        wrapper = contained[0]
        if wrapper.author != author or wrapper.date != date:
            unsafe(
                "DOCX move range metadata does not match its wrapper.",
                range_id=str(numeric_id),
                range_type=move_type,
                **context(document, source_index),
            )
        result.append(
            MoveRange(
                move_type,
                str(numeric_id),
                start,
                end,
                wrapper.element,
                name,
                author,
                date,
                start_position,
                end_position,
            )
        )
    return result


def _assert_non_overlapping_ranges(
    ranges: list[MoveRange],
    document: str,
    source_index: int | None,
) -> None:
    ordered = sorted(ranges, key=lambda item: item.start_position)
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_position < previous.end_position:
            unsupported(
                "DOCX merge move ranges overlap or nest ambiguously.",
                structures=[
                    f"{previous.range_type}Range",
                    f"{current.range_type}Range",
                ],
                **context(document, source_index),
            )


def _assert_move_pairs(
    ranges: list[MoveRange],
    document: str,
    source_index: int | None,
) -> None:
    by_type: dict[str, dict[str, MoveRange]] = {}
    for move_type in MOVE_TYPES:
        named: dict[str, MoveRange] = {}
        for move_range in ranges:
            if move_range.range_type != move_type:
                continue
            if move_range.name in named:
                unsafe(
                    "DOCX move range name is not unique.",
                    name=move_range.name,
                    range_type=move_type,
                    **context(document, source_index),
                )
            named[move_range.name] = move_range
        by_type[move_type] = named
    if set(by_type["moveFrom"]) != set(by_type["moveTo"]):
        unsupported(
            "DOCX merge move-from and move-to ranges are not paired by name.",
            structures=["moveFromRange", "moveToRange"],
            **context(document, source_index),
        )
    for name, move_from in by_type["moveFrom"].items():
        move_to = by_type["moveTo"][name]
        if move_from.author != move_to.author or move_from.date != move_to.date:
            unsafe(
                "DOCX paired move ranges have inconsistent metadata.",
                name=name,
                **context(document, source_index),
            )
