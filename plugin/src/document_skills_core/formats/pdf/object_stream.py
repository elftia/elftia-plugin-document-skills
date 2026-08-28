"""Bounded stream extraction shared by PDF objects and xref streams."""

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .byte_preflight import PdfByteLimits, decode_stream
from .object_values import PdfDict


def extract_stream(
    raw: bytes,
    pos: int,
    dictionary: PdfDict,
    budget: PdfByteLimits,
) -> tuple[bytes, int]:
    """Extract and decode a stream payload from complete PDF bytes."""
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    if raw[pos : pos + 6] != b"stream":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF stream object is missing 'stream' keyword.",
        )
    pos = _skip_stream_eol(raw, pos + 6)
    length = dictionary.get("/Length")
    if isinstance(length, int):
        stream_raw = raw[pos : pos + length]
        pos += length
    else:
        endstream = raw.find(b"endstream", pos)
        if endstream < 0:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF stream is missing 'endstream'.",
            )
        stream_raw = raw[pos:endstream]
        pos = endstream + 9
    return _decode_filters(stream_raw, dictionary, budget), pos


def extract_stream_from_value(
    value_text: bytes,
    stream_pos: int,
    dictionary: PdfDict,
    budget: PdfByteLimits,
) -> tuple[bytes, int]:
    """Extract a stream from within one indirect object's value bytes."""
    pos = _skip_stream_eol(value_text, stream_pos + 6)
    length = dictionary.get("/Length")
    if isinstance(length, int):
        stream_raw = value_text[pos : pos + length]
    else:
        endstream = value_text.find(b"endstream", pos)
        if endstream < 0:
            return b"", pos
        stream_raw = value_text[pos:endstream]
    decoded = _decode_filters(stream_raw, dictionary, budget)
    return decoded, pos + len(decoded)


def _skip_stream_eol(value: bytes, pos: int) -> int:
    if pos < len(value) and value[pos] == ord("\r"):
        pos += 1
    if pos < len(value) and value[pos] == ord("\n"):
        pos += 1
    return pos


def _decode_filters(
    stream_raw: bytes,
    dictionary: PdfDict,
    budget: PdfByteLimits,
) -> bytes:
    filter_spec = dictionary.get("/Filter")
    filters: list[str] = []
    if isinstance(filter_spec, str):
        filters = [filter_spec]
    elif isinstance(filter_spec, list):
        filters = [item for item in filter_spec if isinstance(item, str)]
    return decode_stream(stream_raw, filters, budget) if filters else stream_raw
