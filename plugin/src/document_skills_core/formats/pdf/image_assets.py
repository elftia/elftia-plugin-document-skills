"""Bounded local PNG/JPEG decoding for PDF Image XObjects.

Module provenance: original Elftia-authored clean-room implementation. Only
Python's standard library is used; no system image command or optional provider
is invoked.
"""

from dataclasses import dataclass
import binascii
import hashlib
from pathlib import Path
import struct
from typing import Any
import zlib

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"
MAX_IMAGE_FILE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_DECODED_BYTES = 160 * 1024 * 1024


@dataclass(frozen=True)
class ImageAsset:
    path: Path
    content_type: str
    width: int
    height: int
    bits_per_component: int
    color_space: str
    filter_name: str
    image_data: bytes
    alpha_data: bytes | None
    sha256: str
    byte_count: int
    transcoded: bool = False


def load_image_asset(spec: dict[str, Any]) -> ImageAsset:
    """Load and validate one bounded local PNG or JPEG asset."""
    path = Path(spec["filename"]).expanduser().resolve(strict=False)
    try:
        stat = path.stat()
    except OSError as error:
        _invalid_image("Image asset does not exist or is not readable.", path, error)
    if not path.is_file():
        _invalid_image("Image asset must be a regular file.", path)
    if stat.st_size <= 0 or stat.st_size > MAX_IMAGE_FILE_BYTES:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Image asset exceeds the bounded file-size policy.",
            details={"path": str(path), "bytes": stat.st_size},
        )
    raw = path.read_bytes()
    if len(raw) != stat.st_size:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Image asset changed while it was being read.",
            details={"path": str(path)},
        )
    content_type = spec["content_type"]
    if content_type == "image/png":
        asset = _load_png(path, raw)
    elif content_type == "image/jpeg":
        asset = _load_jpeg(path, raw)
    else:
        _invalid_image("Only image/png and image/jpeg are supported.", path)
    return asset


def image_xobject_dictionary(
    asset: ImageAsset,
    *,
    stream_length: int,
    soft_mask_object: int | None,
    alt: str | None,
) -> bytes:
    """Build a closed Image XObject dictionary for the validated asset."""
    parts = [
        "/Type /XObject",
        "/Subtype /Image",
        f"/Width {asset.width}",
        f"/Height {asset.height}",
        f"/ColorSpace {asset.color_space}",
        f"/BitsPerComponent {asset.bits_per_component}",
        f"/Filter {asset.filter_name}",
        f"/Length {stream_length}",
    ]
    if soft_mask_object is not None:
        parts.append(f"/SMask {soft_mask_object} 0 R")
    if alt:
        parts.append(f"/Alt ({_escape_pdf_string(alt)})")
    return f"<< {' '.join(parts)} >>".encode("ascii")


def soft_mask_dictionary(asset: ImageAsset) -> bytes:
    """Build the grayscale soft-mask dictionary for an alpha-bearing PNG."""
    if asset.alpha_data is None:
        raise ValueError("The image asset has no alpha channel.")
    return (
        f"<< /Type /XObject /Subtype /Image /Width {asset.width} "
        f"/Height {asset.height} /ColorSpace /DeviceGray /BitsPerComponent 8 "
        f"/Filter /FlateDecode /Length {len(asset.alpha_data)} >>"
    ).encode("ascii")


def _load_png(path: Path, raw: bytes) -> ImageAsset:
    if not raw.startswith(PNG_SIGNATURE):
        _invalid_image("PNG content type does not match the file magic.", path)
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    seen_iend = False
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(raw):
            _invalid_image("PNG contains a truncated chunk.", path)
        chunk_data = raw[data_start:data_end]
        expected_crc = struct.unpack(">I", raw[data_end:crc_end])[0]
        actual_crc = binascii.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            _invalid_image("PNG chunk CRC validation failed.", path)
        if chunk_type == b"IHDR":
            if length != 13 or width is not None:
                _invalid_image("PNG IHDR is malformed or duplicated.", path)
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if compression != 0 or filter_method != 0:
                _invalid_image("PNG uses an unsupported compression or filter method.", path)
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            seen_iend = True
            offset = crc_end
            break
        offset = crc_end
    if width is None or height is None or not idat or not seen_iend or offset != len(raw):
        _invalid_image("PNG is missing required chunks or has trailing bytes.", path)
    if bit_depth != 8 or color_type not in {0, 2, 4, 6} or interlace != 0:
        _enhancement(
            "PNG requires unsupported bit depth, palette, or interlace handling.",
            path,
            capability="pdf.png-variant",
        )
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    _check_pixel_budget(path, width, height, channels)
    row_bytes = width * channels
    expected_bytes = (row_bytes + 1) * height
    decoded = _bounded_decompress(path, bytes(idat), expected_bytes)
    pixels = _unfilter_png(path, decoded, width, height, channels)
    color, alpha = _split_png_channels(pixels, color_type)
    color_space = "/DeviceGray" if color_type in {0, 4} else "/DeviceRGB"
    return ImageAsset(
        path=path,
        content_type="image/png",
        width=width,
        height=height,
        bits_per_component=8,
        color_space=color_space,
        filter_name="/FlateDecode",
        image_data=zlib.compress(color, level=9),
        alpha_data=zlib.compress(alpha, level=9) if alpha is not None else None,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
    )


def _load_jpeg(path: Path, raw: bytes) -> ImageAsset:
    if not raw.startswith(JPEG_SIGNATURE) or not raw.endswith(b"\xff\xd9"):
        _invalid_image("JPEG content type does not match a complete JPEG file.", path)
    width = height = components = precision = None
    orientation = 1
    offset = 2
    while offset < len(raw):
        if raw[offset] != 0xFF:
            _invalid_image("JPEG marker stream is malformed.", path)
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            break
        marker = raw[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        if offset + 2 > len(raw):
            _invalid_image("JPEG contains a truncated segment.", path)
        length = struct.unpack(">H", raw[offset : offset + 2])[0]
        if length < 2 or offset + length > len(raw):
            _invalid_image("JPEG segment length is invalid.", path)
        segment = raw[offset + 2 : offset + length]
        if marker in {0xC0, 0xC2}:
            if len(segment) < 6:
                _invalid_image("JPEG frame header is truncated.", path)
            precision = segment[0]
            height, width = struct.unpack(">HH", segment[1:5])
            components = segment[5]
        elif marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            orientation = _jpeg_orientation(segment[6:])
        offset += length
    if width is None or height is None or components not in {1, 3, 4} or precision != 8:
        _enhancement(
            "JPEG frame precision or color components are unsupported.",
            path,
            capability="pdf.jpeg-variant",
        )
    if orientation != 1:
        _enhancement(
            "JPEG EXIF orientation requires a caller-authorized transform provider.",
            path,
            capability="pdf.image-exif-orientation",
        )
    _check_pixel_budget(path, width, height, components)
    color_space = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[components]
    return ImageAsset(
        path=path,
        content_type="image/jpeg",
        width=width,
        height=height,
        bits_per_component=8,
        color_space=color_space,
        filter_name="/DCTDecode",
        image_data=raw,
        alpha_data=None,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
    )


def _bounded_decompress(path: Path, compressed: bytes, expected_bytes: int) -> bytes:
    if expected_bytes > MAX_IMAGE_DECODED_BYTES:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PNG decoded bytes exceed the bounded image policy.",
            details={"path": str(path), "decoded_bytes": expected_bytes},
        )
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(compressed, expected_bytes + 1)
    except zlib.error as error:
        _invalid_image("PNG IDAT decompression failed.", path, error)
    if (
        len(decoded) != expected_bytes
        or not decoder.eof
        or decoder.unconsumed_tail
        or decoder.unused_data
    ):
        _invalid_image("PNG decoded byte count does not match IHDR.", path)
    return decoded


def _unfilter_png(
    path: Path,
    decoded: bytes,
    width: int,
    height: int,
    channels: int,
) -> bytes:
    row_bytes = width * channels
    previous = bytearray(row_bytes)
    output = bytearray()
    offset = 0
    for _row in range(height):
        filter_type = decoded[offset]
        current = bytearray(decoded[offset + 1 : offset + 1 + row_bytes])
        offset += row_bytes + 1
        if filter_type > 4:
            _invalid_image("PNG uses an invalid row filter.", path)
        for index in range(row_bytes):
            left = current[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 0xFF
            elif filter_type == 2:
                current[index] = (current[index] + above) & 0xFF
            elif filter_type == 3:
                current[index] = (current[index] + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                current[index] = (
                    current[index] + _paeth(left, above, upper_left)
                ) & 0xFF
        output.extend(current)
        previous = current
    return bytes(output)


def _split_png_channels(pixels: bytes, color_type: int) -> tuple[bytes, bytes | None]:
    if color_type in {0, 2}:
        return pixels, None
    color_channels = 1 if color_type == 4 else 3
    stride = color_channels + 1
    color = bytearray()
    alpha = bytearray()
    for offset in range(0, len(pixels), stride):
        color.extend(pixels[offset : offset + color_channels])
        alpha.append(pixels[offset + color_channels])
    return bytes(color), bytes(alpha)


def _jpeg_orientation(tiff: bytes) -> int:
    if len(tiff) < 8 or tiff[:2] not in {b"II", b"MM"}:
        return 1
    endian = "<" if tiff[:2] == b"II" else ">"
    if struct.unpack(f"{endian}H", tiff[2:4])[0] != 42:
        return 1
    ifd_offset = struct.unpack(f"{endian}I", tiff[4:8])[0]
    if ifd_offset + 2 > len(tiff):
        return 1
    count = struct.unpack(f"{endian}H", tiff[ifd_offset : ifd_offset + 2])[0]
    for index in range(count):
        start = ifd_offset + 2 + index * 12
        entry = tiff[start : start + 12]
        if len(entry) < 12:
            return 1
        tag, value_type, value_count = struct.unpack(f"{endian}HHI", entry[:8])
        if tag == 0x0112 and value_type == 3 and value_count == 1:
            return struct.unpack(f"{endian}H", entry[8:10])[0]
    return 1


def _check_pixel_budget(path: Path, width: int, height: int, channels: int) -> None:
    pixels = width * height
    if width <= 0 or height <= 0 or pixels > MAX_IMAGE_PIXELS:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Image dimensions exceed the bounded pixel policy.",
            details={"path": str(path), "width": width, "height": height},
        )
    if pixels * channels > MAX_IMAGE_DECODED_BYTES:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Image decoded bytes exceed the bounded image policy.",
            details={"path": str(path)},
        )


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _escape_pdf_string(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _invalid_image(message: str, path: Path, error: Exception | None = None) -> None:
    details: dict[str, Any] = {"path": str(path)}
    if error is not None:
        details["reason"] = type(error).__name__
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _enhancement(message: str, path: Path, *, capability: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"path": str(path), "capability": capability},
    )
