"""Bounded PDF byte-format preflight — NOT inspect_ooxml; PDF is not ZIP.

Validates header (%PDF-), EOF marker (%%EOF), byte size, decompression-stream
budget, decompression ratio, stream count, object-graph depth, and decode-filter
chain depth against the foundation's ArchiveLimits *concept* (reused, not the
ZIP-specific implementation).

Module provenance: original Elftia-authored clean-room implementation of ISO
32000-1/2 structural requirements.  No pypdf/PyMuPDF/fpdf2/reportlab code.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import zlib
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    MAX_DECODE_FILTER_CHAIN_DEPTH,
    MAX_EXPANSION_RATIO,
    MAX_OBJECTS,
    MAX_OBJECT_GRAPH_DEPTH,
    MAX_PDF_BYTES,
    MAX_STREAM_BYTES,
    MAX_STREAM_COUNT,
    MAX_UNCOMPRESSED_STREAM_BYTES,
    PDF_EOF_MARKER,
    PDF_HEADER_MAGIC,
    SUPPORTED_FILTERS,
)
from .trailer_preflight import trailer_has_encrypt


@dataclass(frozen=True)
class PdfByteLimits:
    """PDF byte-format limits (mirrors ArchiveLimits structure for byte formats)."""
    max_bytes: int = MAX_PDF_BYTES
    max_uncompressed_bytes: int = MAX_UNCOMPRESSED_STREAM_BYTES
    max_expansion_ratio: float = MAX_EXPANSION_RATIO
    max_stream_bytes: int = MAX_STREAM_BYTES
    max_streams: int = MAX_STREAM_COUNT
    max_objects: int = MAX_OBJECTS
    max_object_graph_depth: int = MAX_OBJECT_GRAPH_DEPTH
    max_decode_filter_depth: int = MAX_DECODE_FILTER_CHAIN_DEPTH


@dataclass(frozen=True)
class PreflightResult:
    """Result of PDF byte-format preflight."""
    version_major: int
    version_minor: int
    total_bytes: int
    sha256: str
    has_eof: bool
    object_count: int
    stream_count: int
    encrypted: bool


def preflight_pdf(
    path: str | Path,
    limits: PdfByteLimits | None = None,
) -> PreflightResult:
    """Validate PDF byte-format structure and return basic info.

    Raises DocumentSkillsError(ARCHIVE_UNSAFE) on any structural violation.
    """
    budget = limits or PdfByteLimits()
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            f"PDF input does not exist: {resolved.name}",
        )
    total_bytes = resolved.stat().st_size
    if total_bytes > budget.max_bytes:
        _unsafe("byte_count", total_bytes, budget.max_bytes)
    raw = resolved.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    # Header check
    if not raw[:5] == PDF_HEADER_MAGIC:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF header magic (%PDF-) is missing.",
        )
    version_match = re.match(rb"%PDF-(\d+)\.(\d+)", raw[:20])
    if version_match is None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF version string is malformed.",
        )
    version_major = int(version_match.group(1))
    version_minor = int(version_match.group(2))

    # EOF marker check (search from the end)
    tail = raw[-1024:] if len(raw) > 1024 else raw
    if PDF_EOF_MARKER not in tail:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF EOF marker (%%EOF) is missing.",
        )

    # Count objects and streams using bounded scanning
    object_count = _count_objects(raw, budget)
    stream_count = _count_streams(raw, budget)

    # Check for encryption
    encrypted = trailer_has_encrypt(
        raw,
        max_depth=budget.max_object_graph_depth,
    )

    return PreflightResult(
        version_major=version_major,
        version_minor=version_minor,
        total_bytes=total_bytes,
        sha256=sha256,
        has_eof=True,
        object_count=object_count,
        stream_count=stream_count,
        encrypted=encrypted,
    )


def _count_objects(raw: bytes, budget: PdfByteLimits) -> int:
    """Bounded count of 'obj' keywords."""
    count = 0
    pos = 0
    while True:
        pos = raw.find(b" obj", pos)
        if pos < 0:
            break
        count += 1
        if count > budget.max_objects:
            _unsafe("object_count", count, budget.max_objects)
        pos += 4
    return count


def _count_streams(raw: bytes, budget: PdfByteLimits) -> int:
    """Bounded count of 'stream' keywords."""
    count = 0
    pos = 0
    while True:
        pos = raw.find(b"stream\r\n", pos)
        if pos < 0:
            pos = raw.find(b"stream\n", pos)
        if pos < 0:
            break
        count += 1
        if count > budget.max_streams:
            _unsafe("stream_count", count, budget.max_streams)
        pos += 8
    return count


def decode_stream(
    raw_stream: bytes,
    filters: list[str],
    limits: PdfByteLimits | None = None,
) -> bytes:
    """Apply a bounded decode-filter chain to a stream payload.

    Supported filters: FlateDecode, ASCIIHexDecode, ASCII85Decode (bounded).
    Each filter application is bounded by max_stream_bytes; total chain depth
    bounded by max_decode_filter_depth.
    """
    budget = limits or PdfByteLimits()
    if len(filters) > budget.max_decode_filter_depth:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Decode-filter chain exceeds the maximum depth.",
            details={"depth": len(filters), "limit": budget.max_decode_filter_depth},
        )
    decoded = raw_stream
    for filter_name in filters:
        filter_name = filter_name.removeprefix("/")
        if filter_name not in SUPPORTED_FILTERS:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                f"Unsupported decode filter: {filter_name}",
                details={"filter": filter_name},
            )
        if len(decoded) > budget.max_stream_bytes:
            _unsafe("stream_bytes", len(decoded), budget.max_stream_bytes)
        decoded = _apply_filter(decoded, filter_name, budget)
        if len(decoded) > budget.max_uncompressed_bytes:
            _unsafe(
                "uncompressed_bytes",
                len(decoded),
                budget.max_uncompressed_bytes,
            )
    return decoded


def _apply_filter(data: bytes, filter_name: str, budget: PdfByteLimits) -> bytes:
    if filter_name == "FlateDecode":
        return _decode_flate(data, budget)
    if filter_name == "ASCIIHexDecode":
        return _decode_ascii_hex(data)
    if filter_name == "ASCII85Decode":
        return _decode_ascii85(data)
    if filter_name == "LZWDecode":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "LZWDecode is not supported in Core (license-restricted algorithm).",
            details={"filter": filter_name},
        )
    if filter_name == "RunLengthDecode":
        return _decode_run_length(data, budget, _effective_output_cap(data, budget))
    if filter_name == "DCTDecode":
        # JPEG codestreams remain compressed. Their marker/dimension policy is
        # validated before embedding; the PDF parser inventories the stream
        # without treating a non-lossless codec as a text/content decoder.
        return data
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        f"Unsupported decode filter: {filter_name}",
        details={"filter": filter_name},
    )


def _decode_flate(data: bytes, budget: PdfByteLimits) -> bytes:
    absolute_cap = max(0, budget.max_uncompressed_bytes)
    ratio_cap = absolute_cap
    if data:
        candidate = len(data) * budget.max_expansion_ratio
        if candidate < absolute_cap:
            ratio_cap = max(0, int(candidate))
    output_cap = min(absolute_cap, ratio_cap)
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, output_cap + 1)
        if len(result) > output_cap:
            _flate_limit_exceeded(data, budget, absolute_cap, ratio_cap)
        if not decoder.eof and decoder.unconsumed_tail:
            extra = decoder.decompress(decoder.unconsumed_tail, 1)
            if extra:
                _flate_limit_exceeded(data, budget, absolute_cap, ratio_cap)
        if not decoder.eof:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "FlateDecode decompression failed.",
                details={"reason": "compressed stream did not reach its end marker"},
            )
    except zlib.error as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "FlateDecode decompression failed.",
            details={"reason": str(error)[:128]},
        ) from error
    return result


def _flate_limit_exceeded(
    data: bytes,
    budget: PdfByteLimits,
    absolute_cap: int,
    ratio_cap: int,
) -> None:
    if absolute_cap <= ratio_cap:
        _unsafe("uncompressed_bytes", absolute_cap + 1, budget.max_uncompressed_bytes)
    observed_ratio = (ratio_cap + 1) / len(data) if data else float("inf")
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "Decompression ratio exceeds the maximum (decompression bomb).",
        details={"ratio": observed_ratio, "limit": budget.max_expansion_ratio},
    )


def _decode_ascii_hex(data: bytes) -> bytes:
    result = bytearray()
    high_nibble = None
    for byte in data:
        if byte in b" \t\r\n\f":
            continue
        if byte == ord(">"):
            break
        if byte == ord("<"):
            continue
        nibble = _hex_nibble(byte)
        if nibble < 0:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "ASCIIHexDecode encountered an invalid character.",
            )
        if high_nibble is None:
            high_nibble = nibble
        else:
            result.append((high_nibble << 4) | nibble)
            high_nibble = None
    if high_nibble is not None:
        result.append(high_nibble << 4)
    return bytes(result)


def _hex_nibble(byte: int) -> int:
    if ord("0") <= byte <= ord("9"):
        return byte - ord("0")
    if ord("a") <= byte <= ord("f"):
        return byte - ord("a") + 10
    if ord("A") <= byte <= ord("F"):
        return byte - ord("A") + 10
    return -1


def _decode_ascii85(data: bytes) -> bytes:
    result = bytearray()
    group: list[int] = []
    for byte in data:
        if byte in b" \t\r\n\f":
            continue
        if byte == ord("~"):
            break
        if byte == ord("z") and not group:
            result.extend(b"\x00\x00\x00\x00")
            continue
        if byte < ord("!") or byte > ord("u"):
            continue
        group.append(byte - ord("!"))
        if len(group) == 5:
            value = (
                group[0] * 85 ** 4
                + group[1] * 85 ** 3
                + group[2] * 85 ** 2
                + group[3] * 85
                + group[4]
            )
            result.extend(value.to_bytes(4, "big"))
            group = []
    if group:
        padding = 5 - len(group)
        for _ in range(padding):
            group.append(84)
        value = (
            group[0] * 85 ** 4
            + group[1] * 85 ** 3
            + group[2] * 85 ** 2
            + group[3] * 85
            + group[4]
        )
        result.extend(value.to_bytes(4, "big")[: 4 - padding])
    return bytes(result)


def _effective_output_cap(data: bytes, budget: PdfByteLimits) -> int:
    output_cap = max(0, budget.max_uncompressed_bytes)
    if data:
        ratio_candidate = len(data) * budget.max_expansion_ratio
        if ratio_candidate < output_cap:
            output_cap = max(0, int(ratio_candidate))
    return output_cap


def _decode_run_length(
    data: bytes, budget: PdfByteLimits, output_cap: int
) -> bytes:
    result = bytearray()
    pos = 0
    while pos < len(data):
        length = data[pos]
        pos += 1
        if length == 128:
            break
        if length < 128:
            count = length + 1
            if pos + count > len(data):
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "RunLengthDecode stream is truncated.",
                )
            _guard_run_length_allocation(result, count, data, budget, output_cap)
            result.extend(data[pos : pos + count])
            pos += count
        else:
            count = 257 - length
            if pos >= len(data):
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "RunLengthDecode stream is truncated.",
                )
            _guard_run_length_allocation(result, count, data, budget, output_cap)
            result.extend(bytes([data[pos]]) * count)
            pos += 1
    return bytes(result)


def _guard_run_length_allocation(
    result: bytearray,
    count: int,
    data: bytes,
    budget: PdfByteLimits,
    output_cap: int,
) -> None:
    prospective = len(result) + count
    if prospective <= output_cap:
        return
    if output_cap == max(0, budget.max_uncompressed_bytes):
        _unsafe("uncompressed_bytes", prospective, budget.max_uncompressed_bytes)
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "Decompression ratio exceeds the maximum (decompression bomb).",
        details={"ratio": prospective / len(data), "limit": budget.max_expansion_ratio},
    )


def _unsafe(metric: str, value: Any, limit: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        f"PDF exceeds the {metric.replace('_', ' ')} budget.",
        details={metric: value, "limit": limit},
    )
