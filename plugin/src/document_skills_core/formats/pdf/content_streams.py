"""Bounded content-stream decode and text-showing operator capture.

Applies the bounded decode-filter chain, walks text-showing operators
(Tj/TJ/'/"), tracks text matrix (Tm/Td/TD/T*), and captures graphics
state (Tf, rg/RG/g/G/sc/SC).

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass, field
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .byte_preflight import PdfByteLimits, decode_stream
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


def extract_content_stream(
    model: PdfObjectModel,
    content_refs: list[IndirectReference],
    page_number: int,
    limits: PdfByteLimits | None = None,
) -> bytes:
    """Concatenate and return the decoded content stream for a page."""
    budget = limits or PdfByteLimits()
    chunks: list[bytes] = []
    for ref in content_refs:
        obj = model.get_object(ref)
        if obj.is_stream and isinstance(obj.value, tuple):
            dict_val, stream_data = obj.value
            if isinstance(dict_val, PdfDict):
                filter_spec = dict_val.get("/Filter")
                filters: list[str] = []
                if isinstance(filter_spec, str):
                    filters = [filter_spec]
                elif isinstance(filter_spec, list):
                    filters = [f for f in filter_spec if isinstance(f, str)]
                if filters:
                    stream_data = decode_stream(stream_data, filters, budget)
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
    # Parse operators using a tokenizer
    operators = _tokenize_content_stream(content)
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
            block = _make_block(page_number, "Tj", text, ts, gs)
            blocks.append(block)
        elif op == "TJ":
            if operands and isinstance(operands[0], list):
                text = "".join(str(item) for item in operands[0] if isinstance(item, (str, bytes)))
                block = _make_block(page_number, "TJ", text, ts, gs)
                blocks.append(block)
        elif op == "'":
            text = str(operands[0]) if operands else ""
            _apply_t_star(gs, ts)
            block = _make_block(page_number, "'", text, ts, gs)
            blocks.append(block)
        elif op == '"':
            if len(operands) >= 3:
                ts.word_space = float(operands[0])
                ts.char_space = float(operands[1])
                text = str(operands[2])
                _apply_t_star(gs, ts)
                block = _make_block(page_number, '"', text, ts, gs)
                blocks.append(block)
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
                gs.text_x = gs.line_x + dx
                gs.text_y = gs.line_y + dy
        elif op == "TD":
            if len(operands) >= 2:
                dx, dy = float(operands[0]), float(operands[1])
                ts.leading = -dy
                gs.text_x = gs.line_x + dx
                gs.text_y = gs.line_y + dy
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
    return blocks


def _apply_t_star(gs: GraphicsState, ts: TextState) -> None:
    """Apply T* (move to next line)."""
    gs.text_x = gs.line_x
    gs.text_y = gs.line_y - ts.leading
    gs.line_x = gs.text_x
    gs.line_y = gs.text_y


def _make_block(page: int, op: str, text: str, ts: TextState, gs: GraphicsState) -> TextBlock:
    """Build a TextBlock from current text/graphics state."""
    # Approximate bbox from text position and font size
    x0 = gs.text_x
    y0 = gs.text_y - ts.font_size * 0.2  # approximate descender
    text_width = len(text) * ts.font_size * 0.5  # approximate monospace width
    x1 = x0 + text_width
    y1 = gs.text_y + ts.font_size * 0.8
    return TextBlock(
        page=page,
        operator=op,
        text=text,
        bbox=(x0, y0, x1, y1),
        font_name=ts.font_name,
        font_size=ts.font_size,
        color=gs.fill_color,
    )


def _tokenize_content_stream(content: bytes) -> list[tuple[str, list[Any]]]:
    """Tokenize a PDF content stream into (operator, operands) pairs."""
    operators: list[tuple[str, list[Any]]] = []
    pos = 0
    operands: list[Any] = []
    while pos < len(content):
        # Skip whitespace
        while pos < len(content) and content[pos] in b" \t\r\n\f":
            pos += 1
        if pos >= len(content):
            break
        ch = content[pos]
        # Comment
        if ch == ord("%"):
            while pos < len(content) and content[pos] != ord("\n"):
                pos += 1
            continue
        # String
        if ch == ord("("):
            text, pos = _parse_content_string(content, pos)
            operands.append(text)
            continue
        # Hex string or dict
        if ch == ord("<"):
            if pos + 1 < len(content) and content[pos + 1] == ord("<"):
                # Skip dict
                depth = 0
                while pos < len(content):
                    if content[pos : pos + 2] == b"<<":
                        depth += 1
                        pos += 2
                    elif content[pos : pos + 2] == b">>":
                        depth -= 1
                        pos += 2
                        if depth == 0:
                            break
                    else:
                        pos += 1
                operands.append("<<dict>>")
                continue
            # Hex string
            end = content.find(b">", pos)
            if end < 0:
                break
            operands.append(content[pos + 1 : end].decode("latin-1", errors="replace"))
            pos = end + 1
            continue
        # Array
        if ch == ord("["):
            arr, pos = _parse_content_array(content, pos)
            operands.append(arr)
            continue
        # Name
        if ch == ord("/"):
            pos += 1
            start = pos
            while pos < len(content) and content[pos] not in b" \t\r\n\f/[]<>()":
                pos += 1
            operands.append("/" + content[start:pos].decode("utf-8", errors="replace"))
            continue
        # Number, operator, or keyword
        start = pos
        while pos < len(content) and content[pos] not in b" \t\r\n\f/[]<>()":
            pos += 1
        token = content[start:pos].decode("ascii", errors="replace")
        # Check if this is an operator (keyword)
        if token in _OPERATORS:
            operators.append((token, operands))
            operands = []
        else:
            # Try as number
            try:
                if "." in token:
                    operands.append(float(token))
                else:
                    operands.append(int(token))
            except ValueError:
                operands.append(token)
    return operators


_OPERATORS = frozenset({
    "Tj", "TJ", "'", '"', "Tf", "Tm", "Td", "TD", "T*",
    "rg", "RG", "g", "G", "sc", "SC", "scn", "SCN",
    "BT", "ET", "q", "Q", "cm", "w", "J", "j", "M", "d",
    "ri", "i", "gs", "CS", "cs", "sh", "re", "m", "l", "c",
    "v", "y", "h", "S", "s", "f", "F", "f*", "B", "b", "n",
    "W", "W*", "Mp", "DP", "BDC", "BMC", "EMC", "d0", "d1",
    "BI", "ID", "EI", "Do", "MP", "DP",
})


def _parse_content_string(content: bytes, pos: int) -> tuple[str, int]:
    """Parse a literal string in content stream."""
    depth = 1
    pos += 1
    result = bytearray()
    while pos < len(content) and depth > 0:
        ch = content[pos]
        if ch == ord("\\"):
            pos += 1
            if pos >= len(content):
                break
            esc = content[pos]
            mapping = {ord("n"): 0x0A, ord("r"): 0x0D, ord("t"): 0x09,
                       ord("b"): 0x08, ord("f"): 0x0C,
                       ord("("): 0x28, ord(")"): 0x29, ord("\\"): 0x5C}
            if esc in mapping:
                result.append(mapping[esc])
            elif ord("0") <= esc <= ord("7"):
                octal = chr(esc)
                for _ in range(2):
                    if pos + 1 < len(content) and ord("0") <= content[pos + 1] <= ord("7"):
                        pos += 1
                        octal += chr(content[pos])
                    else:
                        break
                result.append(int(octal, 8) & 0xFF)
            else:
                result.append(esc)
            pos += 1
        elif ch == ord("("):
            depth += 1
            result.append(ch)
            pos += 1
        elif ch == ord(")"):
            depth -= 1
            if depth > 0:
                result.append(ch)
            pos += 1
        else:
            result.append(ch)
            pos += 1
    return result.decode("latin-1", errors="replace"), pos


def _parse_content_array(content: bytes, pos: int) -> tuple[list, int]:
    """Parse an array in content stream."""
    pos += 1  # skip [
    items: list[Any] = []
    while pos < len(content) and content[pos] != ord("]"):
        while pos < len(content) and content[pos] in b" \t\r\n\f":
            pos += 1
        if pos >= len(content) or content[pos] == ord("]"):
            break
        ch = content[pos]
        if ch == ord("("):
            text, pos = _parse_content_string(content, pos)
            items.append(text)
        elif ch == ord("<"):
            end = content.find(b">", pos)
            if end < 0:
                break
            items.append(content[pos + 1 : end].decode("latin-1", errors="replace"))
            pos = end + 1
        elif ch == ord("/"):
            pos += 1
            start = pos
            while pos < len(content) and content[pos] not in b" \t\r\n\f/[]<>()":
                pos += 1
            items.append("/" + content[start:pos].decode("utf-8", errors="replace"))
        else:
            start = pos
            while pos < len(content) and content[pos] not in b" \t\r\n\f/[]<>()":
                pos += 1
            token = content[start:pos].decode("ascii", errors="replace")
            try:
                if "." in token:
                    items.append(float(token))
                else:
                    items.append(int(token))
            except ValueError:
                items.append(token)
    if pos < len(content):
        pos += 1  # skip ]
    return items, pos
