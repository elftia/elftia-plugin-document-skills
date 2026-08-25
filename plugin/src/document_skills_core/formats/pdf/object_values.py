"""PDF dictionary/value types and bounded recursive value parsing."""

from dataclasses import dataclass, field
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_OBJECT_GRAPH_DEPTH


_PDF_WHITESPACE = b"\x00\t\n\f\r "
_PDF_DELIMITERS = b"()<>[]{}/%"
_PDF_TOKEN_BOUNDARIES = _PDF_WHITESPACE + _PDF_DELIMITERS
_MAX_PARSED_VALUE_NODES = 1_000_000


@dataclass
class _ValueParseBudget:
    nodes: int = 0

    def consume(self, depth: int) -> None:
        if depth > MAX_OBJECT_GRAPH_DEPTH:
            _unsafe("PDF value graph exceeds the maximum depth.")
        self.nodes += 1
        if self.nodes > _MAX_PARSED_VALUE_NODES:
            _unsafe("PDF value graph exceeds the maximum node count.")


@dataclass(frozen=True)
class IndirectReference:
    """A PDF indirect object reference."""

    obj_num: int
    gen_num: int

    def __repr__(self) -> str:
        return f"{self.obj_num} {self.gen_num} R"


@dataclass
class PdfDict:
    """A parsed PDF dictionary."""

    entries: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.entries.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __getitem__(self, key: str) -> Any:
        return self.entries[key]


def parse_dict(
    raw: bytes | bytearray,
    start: int,
    *,
    _budget: _ValueParseBudget | None = None,
    _depth: int = 0,
) -> tuple[PdfDict, int]:
    """Parse a PDF dictionary starting at a ``<<`` token."""
    budget = _budget or _ValueParseBudget()
    budget.consume(_depth)
    if raw[start : start + 2] != b"<<":
        _unsafe("PDF dictionary does not start with <<.")
    pos = start + 2
    entries: dict[str, Any] = {}
    while pos < len(raw):
        pos = _skip_whitespace_and_comments(raw, pos)
        if pos >= len(raw):
            break
        if raw[pos : pos + 2] == b">>":
            return PdfDict(entries), pos + 2
        if raw[pos] != ord("/"):
            pos += 1
            continue
        key, pos = _parse_name(raw, pos)
        pos = _skip_whitespace_and_comments(raw, pos)
        value, pos = _parse_value(raw, pos, budget, _depth + 1)
        entries[key] = value
    _unsafe("PDF dictionary is not properly terminated with >>.")


def parse_array(
    raw: bytes | bytearray,
    start: int,
    *,
    _budget: _ValueParseBudget | None = None,
    _depth: int = 0,
) -> tuple[list[Any], int]:
    """Parse a PDF array starting at a ``[`` token."""
    budget = _budget or _ValueParseBudget()
    budget.consume(_depth)
    if raw[start] != ord("["):
        _unsafe("PDF array does not start with [.")
    pos = start + 1
    items: list[Any] = []
    while pos < len(raw):
        pos = _skip_whitespace_and_comments(raw, pos)
        if pos >= len(raw):
            break
        if raw[pos] == ord("]"):
            return items, pos + 1
        value, pos = _parse_value(raw, pos, budget, _depth + 1)
        items.append(value)
    _unsafe("PDF array is not properly terminated with ].")


def parse_simple_value(raw: bytes) -> Any:
    """Parse a simple non-dictionary, non-array value."""
    raw_str = raw.strip()
    if not raw_str:
        return None
    try:
        if b"." in raw_str:
            return float(raw_str)
        return int(raw_str)
    except ValueError:
        return raw_str.decode("latin-1", errors="replace")


def _parse_value(
    raw: bytes | bytearray,
    pos: int,
    budget: _ValueParseBudget,
    depth: int,
) -> tuple[Any, int]:
    if pos >= len(raw):
        budget.consume(depth)
        return None, pos
    ch = raw[pos]
    if ch == ord("<") and pos + 1 < len(raw) and raw[pos + 1] == ord("<"):
        return parse_dict(raw, pos, _budget=budget, _depth=depth)
    if ch == ord("["):
        return parse_array(raw, pos, _budget=budget, _depth=depth)
    budget.consume(depth)
    if ch == ord("/"):
        return _parse_name(raw, pos)
    if ch == ord("("):
        return _parse_literal_string(raw, pos)
    if ch == ord("<"):
        return _parse_hex_string(raw, pos)
    if ch == ord("t") and raw[pos : pos + 4] == b"true":
        return True, pos + 4
    if ch == ord("f") and raw[pos : pos + 5] == b"false":
        return False, pos + 5
    if ch == ord("n") and raw[pos : pos + 4] == b"null":
        return None, pos + 4
    return _parse_number_or_ref(raw, pos)


def _parse_name(raw: bytes | bytearray, pos: int) -> tuple[str, int]:
    if raw[pos] != ord("/"):
        _unsafe("PDF name does not start with /.")
    pos += 1
    start = pos
    while pos < len(raw) and raw[pos] not in _PDF_TOKEN_BOUNDARIES:
        pos += 1
    return decode_pdf_name(raw[start:pos]), pos


def _skip_whitespace_and_comments(raw: bytes | bytearray, pos: int) -> int:
    while pos < len(raw):
        while pos < len(raw) and raw[pos] in _PDF_WHITESPACE:
            pos += 1
        if pos >= len(raw) or raw[pos] != ord("%"):
            return pos
        while pos < len(raw) and raw[pos] not in b"\r\n":
            pos += 1
    return pos


def decode_pdf_name(raw_name: bytes | bytearray) -> str:
    """Decode ``#xx`` escapes in one PDF name and preserve its leading slash."""
    decoded = bytearray()
    pos = 0
    while pos < len(raw_name):
        if (
            raw_name[pos] == ord("#")
            and pos + 2 < len(raw_name)
            and _is_hex_byte(raw_name[pos + 1])
            and _is_hex_byte(raw_name[pos + 2])
        ):
            decoded.append(int(bytes(raw_name[pos + 1 : pos + 3]), 16))
            pos += 3
            continue
        decoded.append(raw_name[pos])
        pos += 1
    try:
        name = decoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        name = decoded.decode("latin-1")
    return "/" + name


def _is_hex_byte(value: int) -> bool:
    return (
        ord("0") <= value <= ord("9")
        or ord("A") <= value <= ord("F")
        or ord("a") <= value <= ord("f")
    )


def _parse_literal_string(raw: bytes | bytearray, pos: int) -> tuple[str, int]:
    if raw[pos] != ord("("):
        _unsafe("PDF literal string does not start with (.")
    pos += 1
    depth = 1
    result = bytearray()
    while pos < len(raw) and depth > 0:
        ch = raw[pos]
        if ch == ord("\\"):
            pos = _append_literal_escape(raw, pos + 1, result)
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
    return _decode_pdf_text_bytes(bytes(result)), pos


def _append_literal_escape(
    raw: bytes | bytearray,
    pos: int,
    result: bytearray,
) -> int:
    if pos >= len(raw):
        return pos
    escaped = raw[pos]
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
            if pos + 1 >= len(raw) or not ord("0") <= raw[pos + 1] <= ord("7"):
                break
            pos += 1
            octal += chr(raw[pos])
        result.append(int(octal, 8) & 0xFF)
        return pos + 1
    result.append(escaped)
    return pos + 1


def _parse_hex_string(raw: bytes | bytearray, pos: int) -> tuple[str, int]:
    if raw[pos] != ord("<"):
        _unsafe("PDF hex string does not start with <.")
    pos += 1
    hex_chars = bytearray()
    while pos < len(raw) and raw[pos] != ord(">"):
        if raw[pos] not in b" \t\r\n\f":
            hex_chars.append(raw[pos])
        pos += 1
    pos += 1
    if len(hex_chars) % 2 == 1:
        hex_chars.append(ord("0"))
    try:
        decoded = bytes.fromhex(hex_chars.decode("ascii"))
    except ValueError as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF hex string contains invalid characters.",
        ) from error
    return _decode_pdf_text_bytes(decoded), pos


def _decode_pdf_text_bytes(value: bytes) -> str:
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", errors="replace")
    if value.startswith(b"\xff\xfe"):
        return value[2:].decode("utf-16-le", errors="replace")
    return value.decode("latin-1", errors="replace")


def _parse_number_or_ref(raw: bytes | bytearray, pos: int) -> tuple[Any, int]:
    start = pos
    while pos < len(raw) and raw[pos] not in _PDF_TOKEN_BOUNDARIES:
        pos += 1
    token = raw[start:pos]
    token_str = token.decode("ascii", errors="replace")
    if pos < len(raw) and (
        raw[pos] in _PDF_WHITESPACE or raw[pos] == ord("%")
    ):
        save_pos = pos
        pos = _skip_whitespace_and_comments(raw, pos)
        gen_start = pos
        while pos < len(raw) and raw[pos] not in _PDF_TOKEN_BOUNDARIES:
            pos += 1
        gen_str = raw[gen_start:pos].decode("ascii", errors="replace")
        pos = _skip_whitespace_and_comments(raw, pos)
        if pos < len(raw) and raw[pos] == ord("R"):
            after_r = pos + 1
            if after_r >= len(raw) or raw[after_r] in _PDF_TOKEN_BOUNDARIES:
                try:
                    return IndirectReference(int(token_str), int(gen_str)), after_r
                except ValueError:
                    pass
        pos = save_pos
    try:
        if b"." in token:
            return float(token_str), pos
        return int(token_str), pos
    except ValueError:
        return token_str, pos


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
