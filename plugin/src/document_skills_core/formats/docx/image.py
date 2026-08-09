"""Bounded local raster validation for styled DOCX creation."""

from pathlib import Path
import struct
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_MAX_IMAGE_BYTES = 16 * 1024 * 1024
_MAX_DIMENSION = 100_000
_JPEG_SOF = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def load_image(value: dict[str, Any]) -> dict[str, Any]:
    path: Path = value["path"]
    if (
        not path.is_file()
        or path.stat().st_size <= 0
        or path.stat().st_size > _MAX_IMAGE_BYTES
    ):
        _invalid("The report image must be a local bounded file.")
    payload = path.read_bytes()
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _png_dimensions(payload)
        extension, content_type = "png", "image/png"
    elif payload.startswith(b"\xff\xd8\xff"):
        width, height = _jpeg_dimensions(payload)
        extension, content_type = "jpg", "image/jpeg"
    elif payload.startswith((b"GIF87a", b"GIF89a")):
        width, height = _gif_dimensions(payload)
        extension, content_type = "gif", "image/gif"
    else:
        _invalid("The report image format is not PNG, JPEG, or GIF.")
    if (
        width <= 0
        or height <= 0
        or width > _MAX_DIMENSION
        or height > _MAX_DIMENSION
    ):
        _invalid("The report image dimensions are invalid.")
    return {
        "bytes": payload,
        "extension": extension,
        "content_type": content_type,
        "width_px": width,
        "height_px": height,
        "alt_text": value["alt_text"],
        "width_inches": value["width_inches"],
    }


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 33 or payload[12:16] != b"IHDR":
        _invalid("The PNG image is truncated or lacks IHDR.")
    width, height = struct.unpack(">II", payload[16:24])
    return width, height


def _gif_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 10:
        _invalid("The GIF image is truncated.")
    return struct.unpack("<HH", payload[6:10])


def _jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    cursor = 2
    while cursor < len(payload):
        while cursor < len(payload) and payload[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(payload):
            break
        marker = payload[cursor]
        cursor += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(payload):
            break
        segment_length = int.from_bytes(payload[cursor : cursor + 2], "big")
        if segment_length < 2 or cursor + segment_length > len(payload):
            break
        if marker in _JPEG_SOF:
            if segment_length < 7:
                break
            height = int.from_bytes(payload[cursor + 3 : cursor + 5], "big")
            width = int.from_bytes(payload[cursor + 5 : cursor + 7], "big")
            return width, height
        cursor += segment_length
    _invalid("The JPEG image is truncated or lacks a supported frame header.")


def _invalid(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
    )
