"""Bounded structural parsing for JPEG frame metadata."""

from dataclasses import dataclass
from typing import Any, NoReturn

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


@dataclass(frozen=True)
class JpegFrame:
    precision: int
    components: int


def validate_jpeg_frame(
    payload: bytes,
    *,
    bits_per_component: int,
    color_space: str,
    object_number: int,
) -> None:
    """Bind JPEG frame metadata to the PDF image dictionary."""
    frame = parse_jpeg_frame(payload, object_number=object_number)
    if frame.precision != bits_per_component:
        _unsafe(
            "JPEG SOF precision does not match the PDF image dictionary.",
            object=object_number,
            jpeg_precision=frame.precision,
            bits_per_component=bits_per_component,
        )
    expected_components = {"/DeviceGray": 1, "/DeviceRGB": 3}.get(color_space)
    if expected_components is not None and frame.components != expected_components:
        _unsafe(
            "JPEG SOF component count does not match the PDF image color space.",
            object=object_number,
            jpeg_components=frame.components,
            expected_components=expected_components,
            color_space=color_space,
        )


def parse_jpeg_frame(payload: bytes, *, object_number: int) -> JpegFrame:
    """Return the first JPEG SOF precision and component count."""
    if len(payload) < 4 or payload[:2] != b"\xff\xd8":
        _unsafe("JPEG codestream is missing its SOI marker.", object=object_number)
    offset = 2
    while offset < len(payload):
        if payload[offset] != 0xFF:
            _unsafe("JPEG marker sequence is malformed.", object=object_number)
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            _unsafe("JPEG marker sequence is truncated.", object=object_number)
        marker = payload[offset]
        offset += 1
        if marker == 0x00:
            _unsafe("JPEG marker sequence contains an unexpected stuffed byte.", object=object_number)
        if marker == 0xD9:
            break
        if marker == 0xD8:
            _unsafe("JPEG codestream contains a nested SOI marker.", object=object_number)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(payload):
            _unsafe("JPEG marker segment length is truncated.", object=object_number)
        segment_length = int.from_bytes(payload[offset : offset + 2], "big")
        if segment_length < 2:
            _unsafe("JPEG marker segment length is invalid.", object=object_number)
        segment_end = offset + segment_length
        if segment_end > len(payload):
            _unsafe("JPEG marker segment exceeds the codestream.", object=object_number)
        if _is_start_of_frame(marker):
            if segment_length < 8:
                _unsafe("JPEG SOF segment is truncated.", object=object_number)
            precision = payload[offset + 2]
            components = payload[offset + 7]
            if components == 0 or segment_length != 8 + (3 * components):
                _unsafe("JPEG SOF component table is malformed.", object=object_number)
            return JpegFrame(precision=precision, components=components)
        if marker == 0xDA:
            break
        offset = segment_end
    _unsafe("JPEG codestream has no frame header.", object=object_number)


def _is_start_of_frame(marker: int) -> bool:
    return 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}


def _unsafe(message: str, **details: Any) -> NoReturn:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
