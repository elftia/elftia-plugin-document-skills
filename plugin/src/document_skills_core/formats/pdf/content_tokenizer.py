"""Bounded tokenization helpers for PDF page and Form content streams."""

import re
from typing import Any


def find_operator_token(
    content: bytes,
    operator: bytes,
    *,
    start: int = 0,
    limit: int | None = None,
) -> tuple[int, int] | None:
    """Locate a bare operator while skipping strings, comments, and compounds."""
    position = start
    stop = min(len(content), limit) if limit is not None else len(content)
    while position < stop:
        if content[position] in b"\x00\t\n\f\r ":
            position += 1
            continue
        if content[position] == ord("%"):
            position = _comment_end(content, position)
            continue
        if content[position] == ord("("):
            _text, position = _parse_content_string(content, position)
            continue
        if content[position:position + 2] == b"<<":
            position = _compound_token_end(content, position, b">>")
            continue
        if content[position] == ord("["):
            position = _compound_token_end(content, position, b"]")
            continue
        if content[position] == ord("<"):
            end = content.find(b">", position + 1)
            position = len(content) if end < 0 else end + 1
            continue
        if content[position] == ord("/"):
            position = _bare_token_end(content, position + 1)
            continue
        token_start = position
        position = _bare_token_end(content, position)
        if position == token_start:
            position += 1
            continue
        if content[token_start:position] == operator:
            return token_start, position
    return None


def tokenize_content_stream(content: bytes) -> list[tuple[str, list[Any]]]:
    """Tokenize a PDF content stream into ``(operator, operands)`` pairs."""
    operators: list[tuple[str, list[Any]]] = []
    pos = 0
    operands: list[Any] = []
    while pos < len(content):
        while pos < len(content) and content[pos] in b" \t\r\n\f":
            pos += 1
        if pos >= len(content):
            break
        ch = content[pos]
        if ch == ord("%"):
            while pos < len(content) and content[pos] != ord("\n"):
                pos += 1
            continue
        if ch == ord("("):
            text, pos = _parse_content_string(content, pos)
            operands.append(text)
            continue
        if ch == ord("<"):
            if pos + 1 < len(content) and content[pos + 1] == ord("<"):
                end = _content_dict_end(content, pos)
                operands.append(_parse_marked_content_dict(content[pos:end]))
                pos = end
                continue
            end = content.find(b">", pos)
            if end < 0:
                break
            operands.append(_decode_hex_bytes(content[pos + 1 : end]))
            pos = end + 1
            continue
        if ch == ord("["):
            array, pos = _parse_content_array(content, pos)
            operands.append(array)
            continue
        if ch == ord("/"):
            pos += 1
            start = pos
            while pos < len(content) and content[pos] not in b" \t\r\n\f/[]<>()":
                pos += 1
            operands.append("/" + content[start:pos].decode("utf-8", errors="replace"))
            continue
        start = pos
        while pos < len(content) and content[pos] not in b" \t\r\n\f/[]<>()":
            pos += 1
        token = content[start:pos].decode("ascii", errors="replace")
        if token in _OPERATORS:
            operators.append((token, operands))
            operands = []
            continue
        try:
            operands.append(float(token) if "." in token else int(token))
        except ValueError:
            operands.append(token)
    return operators


_OPERATORS = frozenset({
    "Tj", "TJ", "'", '"', "Tf", "Tm", "Td", "TD", "T*",
    "Tc", "Tw", "Tz", "TL", "Tr", "Ts",
    "rg", "RG", "g", "G", "sc", "SC", "scn", "SCN",
    "BT", "ET", "q", "Q", "cm", "w", "J", "j", "M", "d",
    "ri", "i", "gs", "CS", "cs", "sh", "re", "m", "l", "c",
    "v", "y", "h", "S", "s", "f", "F", "f*", "B", "b", "n",
    "W", "W*", "Mp", "DP", "BDC", "BMC", "EMC", "d0", "d1",
    "BI", "ID", "EI", "Do", "MP", "DP",
})


def _parse_content_string(content: bytes, pos: int) -> tuple[str, int]:
    depth = 1
    pos += 1
    result = bytearray()
    while pos < len(content) and depth > 0:
        ch = content[pos]
        if ch == ord("\\"):
            pos = _append_escape(content, pos + 1, result)
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


def _append_escape(content: bytes, pos: int, result: bytearray) -> int:
    if pos >= len(content):
        return pos
    escaped = content[pos]
    mapping = {
        ord("n"): 0x0A,
        ord("r"): 0x0D,
        ord("t"): 0x09,
        ord("b"): 0x08,
        ord("f"): 0x0C,
        ord("("): 0x28,
        ord(")"): 0x29,
        ord("\\"): 0x5C,
    }
    if escaped in mapping:
        result.append(mapping[escaped])
        return pos + 1
    if ord("0") <= escaped <= ord("7"):
        octal = chr(escaped)
        for _index in range(2):
            if (
                pos + 1 >= len(content)
                or not ord("0") <= content[pos + 1] <= ord("7")
            ):
                break
            pos += 1
            octal += chr(content[pos])
        result.append(int(octal, 8) & 0xFF)
        return pos + 1
    result.append(escaped)
    return pos + 1


def _parse_content_array(content: bytes, pos: int) -> tuple[list[Any], int]:
    pos += 1
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
            items.append(_decode_hex_bytes(content[pos + 1 : end]))
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
                items.append(float(token) if "." in token else int(token))
            except ValueError:
                items.append(token)
    if pos < len(content):
        pos += 1
    return items, pos


def _content_dict_end(content: bytes, pos: int) -> int:
    depth = 0
    while pos < len(content):
        if content[pos : pos + 2] == b"<<":
            depth += 1
            pos += 2
        elif content[pos : pos + 2] == b">>":
            depth -= 1
            pos += 2
            if depth == 0:
                return pos
        else:
            pos += 1
    return len(content)


def _parse_marked_content_dict(raw: bytes) -> dict[str, str]:
    match = re.search(rb"/ActualText\s*<([0-9A-Fa-f\s]+)>", raw)
    if match is None:
        return {}
    return {"/ActualText": _decode_pdf_text_bytes(_hex_bytes(match.group(1)))}


def _decode_hex_bytes(raw: bytes) -> str:
    return _hex_bytes(raw).decode("latin-1", errors="replace")


def _hex_bytes(raw: bytes) -> bytes:
    compact = re.sub(rb"\s+", b"", raw)
    if len(compact) % 2:
        compact += b"0"
    try:
        return bytes.fromhex(compact.decode("ascii"))
    except ValueError:
        return b""


def _decode_pdf_text_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    return raw.decode("latin-1", errors="replace")


def _bare_token_end(content: bytes, position: int) -> int:
    while position < len(content) and content[position] not in b"\x00\t\n\f\r ()<>[]{}/%":
        position += 1
    return position


def _comment_end(content: bytes, position: int) -> int:
    while position < len(content) and content[position] not in b"\r\n":
        position += 1
    return position


def _compound_token_end(content: bytes, position: int, closer: bytes) -> int:
    position += 2 if closer == b">>" else 1
    stack = [closer]
    while position < len(content) and stack:
        if content[position] == ord("("):
            _text, position = _parse_content_string(content, position)
        elif content[position] == ord("%"):
            position = _comment_end(content, position)
        elif content[position:position + 2] == b"<<":
            stack.append(b">>")
            position += 2
        elif content[position] == ord("["):
            stack.append(b"]")
            position += 1
        elif content[position:position + len(stack[-1])] == stack[-1]:
            position += len(stack.pop())
        elif content[position] == ord("<"):
            end = content.find(b">", position + 1)
            position = len(content) if end < 0 else end + 1
        else:
            position += 1
    return position
