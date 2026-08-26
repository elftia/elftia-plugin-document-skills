"""Deterministic dependency-free PNG contact-sheet composition."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any
import zlib

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_ENCODED_BYTES = 16 * 1024 * 1024
_MAX_PIXELS = 16_000_000
_MAX_TOTAL_PIXELS = 64_000_000
MAX_CONTACT_SHEET_SLIDES = 48
_FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


@dataclass(frozen=True)
class PngImage:
    width: int
    height: int
    rgba: bytes


def compose_contact_sheet(images: list[bytes]) -> tuple[bytes, dict[str, Any]]:
    if not images or len(images) > MAX_CONTACT_SHEET_SLIDES:
        _invalid("Contact sheets require between 1 and 48 rendered slides.")
    if sum(len(item) for item in images) > 64 * 1024 * 1024:
        _invalid("Contact-sheet provider output exceeds the encoded byte budget.")
    decoded: list[PngImage] = []
    total_pixels = 0
    for item in images:
        image = decode_png(item)
        total_pixels += image.width * image.height
        if total_pixels > _MAX_TOTAL_PIXELS:
            _invalid("Contact-sheet provider output exceeds the pixel budget.")
        decoded.append(image)
    columns = min(3, len(decoded))
    rows = math.ceil(len(decoded) / columns)
    thumb_width = 480
    thumb_height = 270
    padding = 20
    label_height = 30
    cell_width = thumb_width + padding * 2
    cell_height = thumb_height + label_height + padding * 2
    width = columns * cell_width
    height = rows * cell_height
    canvas = bytearray((28, 31, 38, 255) * (width * height))
    regions: list[dict[str, Any]] = []
    for index, source in enumerate(decoded):
        column = index % columns
        row = index // columns
        cell_x = column * cell_width
        cell_y = row * cell_height
        scale = min(thumb_width / source.width, thumb_height / source.height)
        rendered_width = max(1, round(source.width * scale))
        rendered_height = max(1, round(source.height * scale))
        x = cell_x + padding + (thumb_width - rendered_width) // 2
        y = cell_y + padding + (thumb_height - rendered_height) // 2
        _blit_scaled(canvas, width, source, x, y, rendered_width, rendered_height)
        _border(canvas, width, height, x, y, rendered_width, rendered_height)
        _draw_number(canvas, width, cell_x + padding, cell_y + padding + thumb_height + 9, index + 1)
        regions.append({
            "height": rendered_height,
            "label": str(index + 1),
            "slide": index + 1,
            "width": rendered_width,
            "x": x,
            "y": y,
        })
    return encode_png(PngImage(width, height, bytes(canvas))), {
        "columns": columns,
        "height": height,
        "regions": regions,
        "rows": rows,
        "slides": len(decoded),
        "width": width,
    }


def decode_png(data: bytes) -> PngImage:
    if not 0 < len(data) <= _MAX_ENCODED_BYTES or not data.startswith(_SIGNATURE):
        _invalid("Visual provider output is not a PNG image.")
    offset = len(_SIGNATURE)
    width = height = bit_depth = color_type = interlace = 0
    palette = b""
    transparency = b""
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if offset + 12 + length > len(data):
            _invalid("PNG chunk exceeds provider output bounds.")
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
        offset += 12 + length
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if (
        width <= 0
        or height <= 0
        or width * height > _MAX_PIXELS
        or bit_depth != 8
        or channels is None
        or interlace != 0
    ):
        _invalid("PNG uses an unsupported or excessive pixel format.")
    stride = width * channels
    expected_bytes = height * (stride + 1)
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(bytes(compressed), expected_bytes + 1)
    except zlib.error as error:
        _invalid("PNG pixel data could not be decompressed.", reason=type(error).__name__)
    if (
        len(raw) != expected_bytes
        or not decompressor.eof
        or decompressor.unconsumed_tail
        or decompressor.unused_data
    ):
        _invalid("PNG scanline size is inconsistent with its header.")
    previous = bytearray(stride)
    rgba = bytearray()
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        filtered = raw[cursor + 1:cursor + 1 + stride]
        cursor += stride + 1
        row = _unfilter(filtered, previous, channels, filter_type)
        rgba.extend(_rgba_row(row, color_type, palette, transparency))
        previous = row
    return PngImage(width, height, bytes(rgba))


def encode_png(image: PngImage) -> bytes:
    if len(image.rgba) != image.width * image.height * 4:
        _invalid("RGBA buffer size does not match PNG dimensions.")
    raw = bytearray()
    stride = image.width * 4
    for row in range(image.height):
        raw.append(0)
        raw.extend(image.rgba[row * stride:(row + 1) * stride])
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return _SIGNATURE + _chunk(b"IHDR", header) + _chunk(
        b"IDAT", zlib.compress(bytes(raw), level=9)
    ) + _chunk(b"IEND", b"")


def _unfilter(data: bytes, previous: bytearray, bpp: int, kind: int) -> bytearray:
    row = bytearray(len(data))
    for index, value in enumerate(data):
        left = row[index - bpp] if index >= bpp else 0
        up = previous[index]
        upper_left = previous[index - bpp] if index >= bpp else 0
        if kind == 0:
            predictor = 0
        elif kind == 1:
            predictor = left
        elif kind == 2:
            predictor = up
        elif kind == 3:
            predictor = (left + up) // 2
        elif kind == 4:
            predictor = _paeth(left, up, upper_left)
        else:
            _invalid("PNG uses an unknown scanline filter.", filter=kind)
        row[index] = (value + predictor) & 255
    return row


def _rgba_row(row: bytearray, color_type: int, palette: bytes, alpha: bytes) -> bytes:
    output = bytearray()
    step = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    for index in range(0, len(row), step):
        values = row[index:index + step]
        if color_type == 0:
            output.extend((values[0], values[0], values[0], 255))
        elif color_type == 2:
            output.extend((*values, 255))
        elif color_type == 3:
            palette_index = values[0]
            start = palette_index * 3
            if start + 3 > len(palette):
                _invalid("PNG palette index is outside the palette.")
            output.extend((*palette[start:start + 3], alpha[palette_index] if palette_index < len(alpha) else 255))
        elif color_type == 4:
            output.extend((values[0], values[0], values[0], values[1]))
        else:
            output.extend(values)
    return bytes(output)


def _blit_scaled(
    canvas: bytearray,
    canvas_width: int,
    source: PngImage,
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    for target_y in range(height):
        source_y = min(source.height - 1, target_y * source.height // height)
        for target_x in range(width):
            source_x = min(source.width - 1, target_x * source.width // width)
            source_offset = (source_y * source.width + source_x) * 4
            target_offset = ((y + target_y) * canvas_width + x + target_x) * 4
            canvas[target_offset:target_offset + 4] = source.rgba[source_offset:source_offset + 4]


def _border(canvas: bytearray, width: int, height: int, x: int, y: int, w: int, h: int) -> None:
    for px in range(max(0, x - 1), min(width, x + w + 1)):
        for py in (y - 1, y + h):
            if 0 <= py < height:
                canvas[(py * width + px) * 4:(py * width + px) * 4 + 4] = b"\xb4\xbc\xc8\xff"
    for py in range(max(0, y - 1), min(height, y + h + 1)):
        for px in (x - 1, x + w):
            if 0 <= px < width:
                canvas[(py * width + px) * 4:(py * width + px) * 4 + 4] = b"\xb4\xbc\xc8\xff"


def _draw_number(canvas: bytearray, width: int, x: int, y: int, number: int) -> None:
    cursor = x
    for digit in str(number):
        for row, pattern in enumerate(_FONT[digit]):
            for column, value in enumerate(pattern):
                if value == "1":
                    for dy in range(3):
                        for dx in range(3):
                            offset = ((y + row * 3 + dy) * width + cursor + column * 3 + dx) * 4
                            canvas[offset:offset + 4] = b"\xf4\xf6\xf8\xff"
        cursor += 12


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
    return (left, up, upper_left)[distances.index(min(distances))]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        status="failed",
        details=details,
    )
