"""Shared bounded revision-graph records, validation, and errors."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn

REVISION_TAGS = ("ins", "del", "moveFrom", "moveTo")
MOVE_TYPES = ("moveFrom", "moveTo")
UNSUPPORTED_REVISION_TAGS = frozenset(
    {
        "cellDel",
        "cellIns",
        "cellMerge",
        "conflictDel",
        "conflictIns",
        "customXmlDelRangeEnd",
        "customXmlDelRangeStart",
        "customXmlInsRangeEnd",
        "customXmlInsRangeStart",
        "customXmlMoveFromRangeStart",
        "customXmlMoveFromRangeEnd",
        "customXmlMoveToRangeStart",
        "customXmlMoveToRangeEnd",
        "numberingChange",
        "pPrChange",
        "rPrChange",
        "sectPrChange",
        "tblGridChange",
        "tblPrChange",
        "tcPrChange",
        "trPrChange",
    }
)
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MAX_REVISIONS = 10_000


@dataclass(frozen=True)
class RevisionRecord:
    revision_type: str
    element: Element
    source_id: str
    author: str
    date: str
    position: int


@dataclass(frozen=True)
class MoveRange:
    range_type: str
    source_id: str
    start: Element
    end: Element
    wrapper: Element
    name: str
    author: str
    date: str
    start_position: int
    end_position: int


@dataclass(frozen=True)
class RevisionGraph:
    revisions: tuple[RevisionRecord, ...]
    move_ranges: tuple[MoveRange, ...]
    annotation_ids: frozenset[int]


def validate_revision(
    revision: Element,
    *,
    revision_type: str,
    document: str,
    source_index: int | None,
) -> tuple[str, str, str]:
    revision_id = validate_annotation_id(
        revision.attrib.get(qn("w", "id"), ""),
        label="inline revision",
        document=document,
        source_index=source_index,
    )
    author, date = validate_track_metadata(
        revision,
        label="inline revision",
        document=document,
        source_index=source_index,
        revision_type=revision_type,
        revision_id=revision_id,
    )
    return revision_id, author, date


def validate_move_start(
    start: Element,
    *,
    range_type: str,
    document: str,
    source_index: int | None,
) -> tuple[str, str, str, str]:
    range_id = validate_annotation_id(
        start.attrib.get(qn("w", "id"), ""),
        label="move range start",
        document=document,
        source_index=source_index,
    )
    name = start.attrib.get(qn("w", "name"), "")
    if not name or len(name.encode("utf-8", errors="strict")) > 1_024:
        unsafe(
            "DOCX move range name is invalid.",
            range_id=range_id,
            range_type=range_type,
            **context(document, source_index),
        )
    author, date = validate_track_metadata(
        start,
        label="move range start",
        document=document,
        source_index=source_index,
        range_type=range_type,
        range_id=range_id,
    )
    return range_id, name, author, date


def validate_track_metadata(
    element: Element,
    *,
    label: str,
    document: str,
    source_index: int | None,
    **details: Any,
) -> tuple[str, str]:
    author = element.attrib.get(qn("w", "author"), "")
    date = element.attrib.get(qn("w", "date"), "")
    error_details = {"document": document, "structure": label, **details}
    if source_index is not None:
        error_details["source_index"] = source_index
    if not author or len(author.encode("utf-8", errors="strict")) > 1_024:
        unsafe("DOCX tracked-change author is invalid.", **error_details)
    try:
        datetime.strptime(date, DATE_FORMAT)
    except ValueError:
        unsafe("DOCX tracked-change date is invalid.", **error_details)
    return author, date


def validate_annotation_id(
    value: str,
    *,
    label: str,
    document: str,
    source_index: int | None,
) -> str:
    if not value.isdigit() or int(value) > 2_147_483_647:
        unsafe(
            f"DOCX {label} id is invalid.",
            annotation_id=value,
            **context(document, source_index),
        )
    return value


def claim_annotation_id(
    used: set[int],
    value: str,
    *,
    document: str,
    revision_type: str,
    source_index: int | None,
) -> None:
    numeric_id = int(value)
    if numeric_id in used:
        unsafe(
            "DOCX contains duplicate tracked-change annotation ids.",
            annotation_id=value,
            revision_type=revision_type,
            **context(document, source_index),
        )
    used.add(numeric_id)


def context(document: str, source_index: int | None) -> dict[str, Any]:
    details: dict[str, Any] = {"document": document}
    if source_index is not None:
        details["source_index"] = source_index
    return details


def unsupported(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )


def unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
