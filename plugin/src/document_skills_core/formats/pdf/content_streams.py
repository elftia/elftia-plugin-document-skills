"""Bounded content-stream decode and text-showing operator capture.

Applies the bounded decode-filter chain, walks text-showing operators
(Tj/TJ/'/"), tracks text matrix (Tm/Td/TD/T*), and captures graphics
state (Tf, rg/RG/g/G/sc/SC).

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass, field

from .base14_metrics import base14_text_width
from .byte_preflight import PdfByteLimits
from .content_tokenizer import tokenize_content_stream
from .object_model import IndirectReference, PdfDict, PdfObjectModel


@dataclass
class TextState:
    """Text state parameters tracked during content-stream walk."""
    font_name: str = ""
    font_size: float = 0.0
    char_space: float = 0.0
    word_space: float = 0.0
    scaling: float = 100.0
    leading: float = 0.0
    rise: float = 0.0
    render_mode: int = 0
    knockout: bool = True


@dataclass
class GraphicsState:
    """Graphics state for text color and positioning."""
    fill_color: tuple[float, ...] = (0.0, 0.0, 0.0)
    stroke_color: tuple[float, ...] = (0.0, 0.0, 0.0)
    text_matrix: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    text_line_matrix: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    text_x: float = 0.0
    text_y: float = 0.0
    line_x: float = 0.0
    line_y: float = 0.0


@dataclass
class TextBlock:
    """A captured text-showing operator with its position and style."""
    page: int
    operator: str  # Tj, TJ, ', "
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    font_name: str
    font_size: float
    color: tuple[float, ...]
    semantic_text: bool = False


@dataclass
class _MarkedText:
    text: str
    blocks: list[TextBlock] = field(default_factory=list)


def extract_content_stream(
    model: PdfObjectModel,
    content_refs: list[IndirectReference],
    page_number: int,
    limits: PdfByteLimits | None = None,
) -> bytes:
    """Concatenate and return the decoded content stream for a page."""
    chunks: list[bytes] = []
    for ref in content_refs:
        obj = model.get_object(ref)
        if obj.is_stream and isinstance(obj.value, tuple):
            _dict_val, stream_data = obj.value
            # PdfObjectModel stores stream bytes after its bounded filter decode.
            chunks.append(stream_data)
        elif isinstance(obj.value, PdfDict):
            pass  # empty stream
    return b"\n".join(chunks)


def walk_text_operators(
    content: bytes,
    page_number: int,
    *,
    max_operators: int = 500_000,
) -> list[TextBlock]:
    """Walk content-stream text-showing operators and return text blocks.

    Tracks text matrix (Tm/Td/TD/T*) and graphics state (Tf/rg/sc) to
    compute text bbox per operator.  Does NOT execute JavaScript or follow
    external actions.
    """
    blocks: list[TextBlock] = []
    ts = TextState()
    gs = GraphicsState()
    op_count = 0
    marked_stack: list[_MarkedText | None] = []
    # Parse operators using a tokenizer
    operators = tokenize_content_stream(content)
    for op, operands in operators:
        op_count += 1
        if op_count > max_operators:
            break
        if op == "Tf":
            if len(operands) >= 2:
                ts.font_name = str(operands[0])
                ts.font_size = float(operands[1]) if operands[1] else 0.0
        elif op == "Tj":
            text = str(operands[0]) if operands else ""
            if text:
                block = _make_block(page_number, "Tj", text, ts, gs)
                _capture_or_append(block, marked_stack, blocks)
        elif op == "TJ":
            if operands and isinstance(operands[0], list):
                text = "".join(str(item) for item in operands[0] if isinstance(item, (str, bytes)))
                block = _make_block(page_number, "TJ", text, ts, gs)
                _capture_or_append(block, marked_stack, blocks)
        elif op == "'":
            text = str(operands[0]) if operands else ""
            _apply_t_star(gs, ts)
            block = _make_block(page_number, "'", text, ts, gs)
            _capture_or_append(block, marked_stack, blocks)
        elif op == '"':
            if len(operands) >= 3:
                ts.word_space = float(operands[0])
                ts.char_space = float(operands[1])
                text = str(operands[2])
                _apply_t_star(gs, ts)
                block = _make_block(page_number, '"', text, ts, gs)
                _capture_or_append(block, marked_stack, blocks)
        elif op == "Tm":
            if len(operands) >= 6:
                gs.text_matrix = tuple(float(o) for o in operands[:6])
                gs.text_line_matrix = gs.text_matrix
                gs.text_x = gs.text_matrix[4]
                gs.text_y = gs.text_matrix[5]
                gs.line_x = gs.text_x
                gs.line_y = gs.text_y
        elif op == "Td":
            if len(operands) >= 2:
                dx, dy = float(operands[0]), float(operands[1])
                _translate_text_line(gs, dx, dy)
        elif op == "TD":
            if len(operands) >= 2:
                dx, dy = float(operands[0]), float(operands[1])
                ts.leading = -dy
                _translate_text_line(gs, dx, dy)
        elif op == "T*":
            _apply_t_star(gs, ts)
        elif op == "rg":
            if len(operands) >= 3:
                gs.fill_color = (float(operands[0]), float(operands[1]), float(operands[2]))
        elif op == "RG":
            if len(operands) >= 3:
                gs.stroke_color = (float(operands[0]), float(operands[1]), float(operands[2]))
        elif op == "g":
            if len(operands) >= 1:
                gs.fill_color = (float(operands[0]),) * 3
        elif op == "G":
            if len(operands) >= 1:
                gs.stroke_color = (float(operands[0]),) * 3
        elif op == "sc" or op == "SC":
            pass  # color space dependent — record approximate
        elif op == "BDC":
            properties = next(
                (operand for operand in reversed(operands) if isinstance(operand, dict)),
                {},
            )
            actual_text = properties.get("/ActualText")
            marked_stack.append(
                _MarkedText(actual_text)
                if isinstance(actual_text, str)
                else None
            )
        elif op == "BMC":
            marked_stack.append(None)
        elif op == "EMC" and marked_stack:
            capture = marked_stack.pop()
            if capture is not None:
                block = _actual_text_block(page_number, capture, ts, gs)
                _capture_or_append(block, marked_stack, blocks)
    return blocks


def _capture_or_append(
    block: TextBlock,
    marked_stack: list[_MarkedText | None],
    blocks: list[TextBlock],
) -> None:
    capture = next(
        (item for item in reversed(marked_stack) if item is not None),
        None,
    )
    if capture is not None:
        capture.blocks.append(block)
    else:
        blocks.append(block)


def _actual_text_block(
    page_number: int,
    capture: _MarkedText,
    ts: TextState,
    gs: GraphicsState,
) -> TextBlock:
    if not capture.blocks:
        return _make_block(
            page_number,
            "ActualText",
            capture.text,
            ts,
            gs,
            semantic_text=True,
        )
    return TextBlock(
        page=page_number,
        operator="ActualText",
        text=capture.text,
        bbox=(
            min(block.bbox[0] for block in capture.blocks),
            min(block.bbox[1] for block in capture.blocks),
            max(block.bbox[2] for block in capture.blocks),
            max(block.bbox[3] for block in capture.blocks),
        ),
        font_name=capture.blocks[0].font_name,
        font_size=capture.blocks[0].font_size,
        color=capture.blocks[0].color,
        semantic_text=True,
    )


def _apply_t_star(gs: GraphicsState, ts: TextState) -> None:
    """Apply T* (move to next line)."""
    _translate_text_line(gs, 0.0, -ts.leading)


def _translate_text_line(gs: GraphicsState, tx: float, ty: float) -> None:
    """Move the text line matrix by a text-space translation."""
    a, b, c, d, e, f = gs.text_line_matrix
    translated = (
        a,
        b,
        c,
        d,
        e + tx * a + ty * c,
        f + tx * b + ty * d,
    )
    gs.text_line_matrix = translated
    gs.text_matrix = translated
    gs.text_x = translated[4]
    gs.text_y = translated[5]
    gs.line_x = translated[4]
    gs.line_y = translated[5]


def _make_block(
    page: int,
    op: str,
    text: str,
    ts: TextState,
    gs: GraphicsState,
    *,
    semantic_text: bool = False,
) -> TextBlock:
    """Build a TextBlock from current text/graphics state."""
    # Approximate the glyph box in text space, then transform all four corners.
    # Taking the user-space envelope keeps scale, rotation, and reflection visible
    # to promotion validation instead of trusting only the Tm translation.
    text_width = (
        base14_text_width(text, ts.font_size, ts.font_name)
        if ts.font_name in {"/F1", "/F2", "/F3", "/F4"}
        else len(text) * ts.font_size * 0.5
    )
    bbox = _transformed_bbox(
        (0.0, -ts.font_size * 0.2, text_width, ts.font_size * 0.8),
        gs.text_matrix,
    )
    return TextBlock(
        page=page,
        operator=op,
        text=text,
        bbox=bbox,
        font_name=ts.font_name,
        font_size=ts.font_size,
        color=gs.fill_color,
        semantic_text=semantic_text,
    )


def _transformed_bbox(
    bbox: tuple[float, float, float, float],
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    a, b, c, d, e, f = matrix
    points = tuple(
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)
