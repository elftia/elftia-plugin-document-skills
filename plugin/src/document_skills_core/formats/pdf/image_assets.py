"""Bounded local PNG/JPEG decoding for PDF Image XObjects.

Module provenance: original Elftia-authored clean-room implementation. No
system image command or optional provider is invoked.
"""

from dataclasses import dataclass
import binascii
import hashlib
from pathlib import Path
import struct
from typing import Any
import zlib

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_text_utils import pdf_text_string
from .jpeg_assets import (
    inspect_jpeg,
    JpegParseError,
    JpegUnsupportedError,
    normalize_exif_jpeg,
    verify_direct_jpeg,
)

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
    decode: tuple[int, ...] | None = None
    decode_parms: tuple[tuple[str, int], ...] | None = None
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
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != spec["sha256"]:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Image asset does not match sha256.",
            status="invalid_request",
            details={"capability": "pdf.image-source-precondition"},
        )
    content_type = spec["content_type"]
    if content_type == "image/png":
        asset = _load_png(path, raw)
    elif content_type == "image/jpeg":
        asset = _load_jpeg(path, raw)
    else:
        _invalid_image("Only image/png and image/jpeg are supported.", path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != actual_sha256:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Image asset changed while it was being read.",
            status="invalid_request",
            details={"capability": "pdf.image-source-precondition"},
        )
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
    if asset.decode is not None:
        parts.append(f"/Decode [{' '.join(str(value) for value in asset.decode)}]")
    if asset.decode_parms is not None:
        parameters = " ".join(f"{key} {value}" for key, value in asset.decode_parms)
        parts.append(f"/DecodeParms << {parameters} >>")
    if soft_mask_object is not None:
        parts.append(f"/SMask {soft_mask_object} 0 R")
    if alt:
        parts.append(f"/Alt {pdf_text_string(alt)}")
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
    try:
        metadata = inspect_jpeg(raw)
    except JpegUnsupportedError as error:
        _enhancement(str(error), path, capability="pdf.jpeg-variant")
    except JpegParseError as error:
        _invalid_image(str(error), path, error)
    if (
        metadata.width is None
        or metadata.height is None
        or metadata.components not in {1, 3, 4}
        or metadata.precision != 8
    ):
        _enhancement(
            "JPEG frame precision or color components are unsupported.",
            path,
            capability="pdf.jpeg-variant",
        )
    width = metadata.width
    height = metadata.height
    components = metadata.components
    _check_pixel_budget(path, width, height, components)
    if metadata.orientation != 1:
        try:
            normalized = normalize_exif_jpeg(raw, metadata)
        except JpegParseError as error:
            _invalid_image(str(error), path, error)
        channels = 1 if normalized.color_space == "/DeviceGray" else 3
        _check_pixel_budget(path, normalized.width, normalized.height, channels)
        return ImageAsset(
            path=path,
            content_type="image/jpeg",
            width=normalized.width,
            height=normalized.height,
            bits_per_component=8,
            color_space=normalized.color_space,
            filter_name="/FlateDecode",
            image_data=zlib.compress(normalized.pixels, level=9),
            alpha_data=None,
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_count=len(raw),
            transcoded=True,
        )
    if components == 4 and metadata.adobe_transform not in {None, 0, 2}:
        _enhancement(
            "JPEG uses an unsupported Adobe APP14 color transform.",
            path,
            capability="pdf.jpeg-adobe-transform",
        )
    try:
        verify_direct_jpeg(raw, metadata)
    except JpegParseError as error:
        _invalid_image(str(error), path, error)
    color_space = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[components]
    decode = (
        (1, 0, 1, 0, 1, 0, 1, 0)
        if components == 4 and metadata.adobe_transform in {0, 2}
        else None
    )
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
        decode=decode,
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
