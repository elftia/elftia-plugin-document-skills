"""Public facade for exact PDF text-operator targeting and mutation."""

from dataclasses import dataclass, replace
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_streams import TextBlock
from .object_model import PdfObjectModel
from .page_tree import PageInfo
from .rewrite_layout import text_bbox_for_font
from .rewrite_operator_mutation import (
    apply_targeted_rewrites as apply_targeted_rewrites,
    replacement_fits_layout as replacement_fits_layout,
    verify_rewrite_candidate as verify_rewrite_candidate,
)
from .rewrite_operator_walker import OperatorLocator, page_operator_records


@dataclass(frozen=True)
class CandidateTextRun:
    text: str
    bbox: tuple[float, float, float, float]


def locate_block_selectors(
    model: PdfObjectModel,
    pages: list[PageInfo],
    blocks: list[dict[str, Any]],
) -> list[OperatorLocator]:
    """Resolve every caller selector to one content object and operator ordinal."""
    cached: dict[int, tuple[list[OperatorLocator], list[TextBlock]]] = {}
    located: list[OperatorLocator] = []
    for block_index, block in enumerate(blocks):
        page_number = block["page"]
        if not 1 <= page_number <= len(pages):
            _validation(
                "Rewrite block page precondition is outside the source document.",
                block_index=block_index,
                page=page_number,
            )
        if page_number not in cached:
            cached[page_number] = page_operator_records(
                model,
                pages[page_number - 1],
            )
        records, actual_blocks = cached[page_number]
        matches = [
            index
            for index, actual in enumerate(actual_blocks)
            if actual.text == block["text"]
            and _bbox_intersects(actual.bbox, block["bbox"])
        ]
        if len(matches) != 1:
            _validation(
                "Rewrite block text/bbox precondition is stale or ambiguous.",
                block_index=block_index,
                match_count=len(matches),
            )
        record = next(
            (item for item in records if item.page_block_index == matches[0]),
            None,
        )
        if record is None:
            _enhancement(
                "The selected visible block has no single editable text operand.",
                block_index=block_index,
            )
        if record.unsupported_text_state:
            _enhancement(
                "The selected text operator uses unsupported non-default text state.",
                capability="pdf.rewrite-text-state",
                block_index=block_index,
                operators=list(record.unsupported_text_state),
            )
        source_block = actual_blocks[matches[0]]
        located.append(
            replace(
                record,
                block_index=block_index,
                selector_bbox=tuple(float(value) for value in block["bbox"]),
                source_bbox=source_block.bbox,
            )
        )
    return located


def candidate_actual_text_runs(
    model: PdfObjectModel,
    page: PageInfo,
) -> list[CandidateTextRun] | None:
    """Recompute marked ActualText run bounds from candidate operators."""
    records, _blocks = page_operator_records(model, page)
    grouped: dict[int, tuple[str, list[tuple[float, float, float, float]]]] = {}
    for record in records:
        if record.marked_content_id is None or record.actual_text is None:
            continue
        if record.unsupported_text_state:
            return None
        bbox = text_bbox_for_font(
            model,
            page,
            record.font_name,
            record.source_bytes,
            record.font_size,
            record.text_matrix,
        )
        if bbox is None:
            return None
        text, boxes = grouped.setdefault(
            record.marked_content_id,
            (record.actual_text, []),
        )
        if text != record.actual_text:
            return None
        boxes.append(bbox)
    return [
        CandidateTextRun(
            text,
            (
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ),
        )
        for text, boxes in grouped.values()
        if boxes
    ]


def _bbox_intersects(
    actual: tuple[float, float, float, float],
    requested: list[float],
) -> bool:
    x0, y0, x1, y1 = (float(value) for value in requested)
    return not (actual[2] < x0 or actual[0] > x1 or actual[3] < y0 or actual[1] > y1)


def _validation(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.rewrite-exact-operator", **details},
    )
