"""Stateful page-content traversal for exact PDF operator rewrites."""

from dataclasses import dataclass, replace
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_streams import extract_content_stream, TextBlock, walk_text_operators
from .content_tokenizer import tokenize_content_stream
from .object_model import PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .rewrite_operator_state import (
    concatenate_matrix,
    IDENTITY_MATRIX,
    numeric_operands,
    OperatorGraphicsState,
    OperatorTraversalState,
    text_show_advance,
    translate_matrix,
    unsupported_text_state,
)
from .rewrite_operator_tokens import operator_bytes, operator_text, raw_operations

TEXT_OPERATORS = {"Tj", "TJ", "'", '"'}


@dataclass(frozen=True)
class OperatorLocator:
    """Stable identity and operand span for one text-showing operator."""

    block_index: int
    page_number: int
    page_block_index: int
    content_object: int
    content_operator_index: int
    operator: str
    operand_start: int
    operand_end: int
    operand_kind: str
    original_operand: bytes
    source_text: str
    source_bytes: bytes
    font_name: str
    font_size: float
    text_matrix: tuple[float, float, float, float, float, float]
    unsupported_text_state: tuple[str, ...]
    selector_bbox: tuple[float, float, float, float]
    source_bbox: tuple[float, float, float, float]
    actual_text: str | None
    marked_content_id: int | None


def page_operator_records(
    model: PdfObjectModel,
    page: PageInfo,
) -> tuple[list[OperatorLocator], list[TextBlock]]:
    state = OperatorTraversalState()
    records: list[OperatorLocator] = []
    for reference in page.contents:
        records.extend(_stream_operator_records(model, page, reference.obj_num, state))
    content = extract_content_stream(model, page.contents, page.page_number)
    blocks = walk_text_operators(content, page.page_number)
    direct_blocks = [
        (index, block)
        for index, block in enumerate(blocks)
        if block.operator in TEXT_OPERATORS
    ]
    visible_records = [record for record in records if record.page_block_index == 0]
    if len(visible_records) != len(direct_blocks) or any(
        record.operator != block.operator or record.source_text != block.text
        for record, (_index, block) in zip(visible_records, direct_blocks)
    ):
        _enhancement(
            "Text operator locations cannot be mapped safely on the selected page.",
            page=page.page_number,
        )
    visible_blocks = iter(direct_blocks)
    located: list[OperatorLocator] = []
    for record in records:
        if record.page_block_index != 0:
            located.append(record)
            continue
        index, block = next(visible_blocks)
        located.append(
            replace(
                record,
                page_block_index=index,
                font_name=record.font_name or block.font_name,
            )
        )
    return located, blocks


def _stream_operator_records(
    model: PdfObjectModel,
    page: PageInfo,
    object_number: int,
    state: OperatorTraversalState,
) -> list[OperatorLocator]:
    content = _editable_stream(model, object_number)
    parsed = tokenize_content_stream(content)
    raw = raw_operations(content)
    if [item[0] for item in parsed] != [item[0] for item in raw]:
        _enhancement(
            "Content stream tokens cannot be mapped to stable source spans.",
            content_object=object_number,
        )
    records: list[OperatorLocator] = []
    marked_stack = state.marked_stack
    next_marked_content = state.next_marked_content
    operator_index = 0
    graphics = state.graphics
    graphics_stack = state.graphics_stack
    text_matrix = state.text_matrix
    text_line_matrix = state.text_line_matrix
    text_position_supported = state.text_position_supported
    for (operator, operands), (_raw_operator, raw_operands) in zip(parsed, raw):
        if operator == "q":
            graphics_stack.append(replace(graphics))
            continue
        if operator == "Q":
            graphics = (
                graphics_stack.pop() if graphics_stack else OperatorGraphicsState()
            )
            continue
        if operator == "cm":
            matrix = numeric_operands(operands, 6)
            if matrix is None:
                _enhancement(
                    "Rewrite content has a malformed transformation matrix.",
                    content_object=object_number,
                )
            graphics.ctm = concatenate_matrix(matrix, graphics.ctm)
            continue
        if operator == "BT":
            text_matrix = IDENTITY_MATRIX
            text_line_matrix = text_matrix
            text_position_supported = True
            continue
        if operator == "Tf":
            font_size = numeric_operands(operands, 1)
            if (
                font_size is None
                or len(operands) < 2
                or not isinstance(operands[-2], str)
            ):
                _enhancement(
                    "Rewrite content has a malformed font selection.",
                    content_object=object_number,
                )
            graphics.font_name = operands[-2]
            graphics.font_size = font_size[0]
            continue
        if operator in {"Tc", "Tw", "Tz", "Tr", "Ts"}:
            value = numeric_operands(operands, 1)
            resolved = None if value is None else value[0]
            if operator == "Tc":
                graphics.character_spacing = resolved
            elif operator == "Tw":
                graphics.word_spacing = resolved
            elif operator == "Tz":
                graphics.horizontal_scaling = resolved
            elif operator == "Tr":
                graphics.rendering_mode = resolved
            else:
                graphics.text_rise = resolved
            continue
        if operator == "TL":
            value = numeric_operands(operands, 1)
            graphics.leading = 0.0 if value is None else value[0]
            if value is None:
                text_position_supported = False
            continue
        if operator == "gs":
            graphics.external_graphics_state = True
            continue
        if operator == "Tm" and len(operands) >= 6:
            matrix = numeric_operands(operands, 6)
            if matrix is None:
                _enhancement(
                    "Rewrite content has a malformed text matrix.",
                    content_object=object_number,
                )
            text_matrix = matrix
            text_line_matrix = text_matrix
            text_position_supported = True
            continue
        if operator in {"Td", "TD"} and len(operands) >= 2:
            translation = numeric_operands(operands, 2)
            if translation is None:
                _enhancement(
                    "Rewrite content has a malformed text translation.",
                    content_object=object_number,
                )
            dx, dy = translation
            if operator == "TD":
                graphics.leading = -dy
            text_line_matrix = translate_matrix(text_line_matrix, dx, dy)
            text_matrix = text_line_matrix
            text_position_supported = True
            continue
        if operator == "T*":
            text_line_matrix = translate_matrix(
                text_line_matrix,
                0.0,
                -graphics.leading,
            )
            text_matrix = text_line_matrix
            text_position_supported = True
            continue
        if operator == "BDC":
            dictionaries = (
                item for item in reversed(operands) if isinstance(item, dict)
            )
            properties = next(dictionaries, {})
            actual_text = properties.get("/ActualText")
            if isinstance(actual_text, str):
                marked_stack.append((next_marked_content, actual_text))
                next_marked_content += 1
            else:
                marked_stack.append((None, None))
            continue
        if operator == "BMC":
            marked_stack.append((None, None))
            continue
        if operator == "EMC":
            if marked_stack:
                marked_stack.pop()
            continue
        if operator not in TEXT_OPERATORS:
            continue
        records.append(
            _text_record(
                content,
                page,
                object_number,
                operator_index,
                operator,
                operands,
                raw_operands,
                graphics,
                text_matrix,
                text_position_supported,
                marked_stack,
            )
        )
        operator_index += 1
        advance = text_show_advance(model, page, operator, operands, graphics)
        if advance is None:
            text_position_supported = False
        else:
            text_matrix = translate_matrix(text_matrix, advance, 0.0)
    state.graphics = graphics
    state.text_matrix = text_matrix
    state.text_line_matrix = text_line_matrix
    state.text_position_supported = text_position_supported
    state.next_marked_content = next_marked_content
    return records


def _text_record(
    content: bytes,
    page: PageInfo,
    object_number: int,
    operator_index: int,
    operator: str,
    operands: list[Any],
    raw_operands: tuple[Any, ...],
    graphics: OperatorGraphicsState,
    text_matrix: tuple[float, float, float, float, float, float],
    text_position_supported: bool,
    marked_stack: list[tuple[int | None, str | None]],
) -> OperatorLocator:
    if not raw_operands:
        _validation("Text-showing operator has no source operand.")
    operand = raw_operands[-1]
    valid_kind = (
        operand.kind == "array"
        if operator == "TJ"
        else operand.kind in {"literal", "hex"}
    )
    if not valid_kind:
        _validation("Text-showing operator has an invalid source operand.")
    source_text = operator_text(operator, operands)
    marked_content_id, actual_text = next(
        (item for item in reversed(marked_stack) if item[1] is not None),
        (None, None),
    )
    visible = actual_text is None and (operator != "Tj" or bool(source_text))
    unsupported = unsupported_text_state(graphics)
    if not text_position_supported:
        unsupported += ("text-position",)
    return OperatorLocator(
        -1,
        page.page_number,
        0 if visible else -1,
        object_number,
        operator_index,
        operator,
        operand.start,
        operand.end,
        operand.kind,
        content[operand.start : operand.end],
        source_text,
        operator_bytes(operator, operands),
        graphics.font_name,
        graphics.font_size,
        concatenate_matrix(text_matrix, graphics.ctm),
        unsupported,
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        actual_text,
        marked_content_id,
    )


def _editable_stream(model: PdfObjectModel, object_number: int) -> bytes:
    obj = model.objects[object_number]
    if not obj.is_stream or not isinstance(obj.value, tuple):
        _validation(
            "Rewrite target is not a content stream.",
            content_object=object_number,
        )
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        _validation(
            "Rewrite stream dictionary is malformed.",
            content_object=object_number,
        )
    return stream


def _validation(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.rewrite-exact-operator", **details},
    )
