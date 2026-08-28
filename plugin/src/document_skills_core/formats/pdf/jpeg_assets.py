"""Closed JPEG metadata parsing and bounded EXIF normalization."""

from dataclasses import dataclass
from io import BytesIO
import struct
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


_SOF_MARKERS = frozenset(
    {
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
)
_SUPPORTED_SOF_MARKERS = frozenset({0xC0, 0xC2})


@dataclass(frozen=True)
class JpegMetadata:
    width: int | None
    height: int | None
    components: int | None
    precision: int | None
    orientation: int
    adobe_transform: int | None


@dataclass(frozen=True)
class NormalizedJpeg:
    width: int
    height: int
    color_space: str
    pixels: bytes


class JpegParseError(ValueError):
    """The JPEG marker stream or Pillow decode is invalid."""


class JpegUnsupportedError(JpegParseError):
    """The JPEG is well-formed but uses an unsupported frame variant."""


def inspect_jpeg(raw: bytes) -> JpegMetadata:
    """Inspect bounded pre-SOS JPEG markers without decoding pixels."""
    width = height = components = precision = None
    orientation = 1
    exif_orientation = None
    adobe_transform = None
    frame_marker = None
    unsupported_frame_marker = None
    offset = 2
    while offset < len(raw):
        if raw[offset] != 0xFF:
            raise JpegParseError("JPEG marker stream is malformed.")
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            break
        marker = raw[offset]
        offset += 1
        if marker in {0x01, *range(0xD0, 0xDA)}:
            continue
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        if offset + 2 > len(raw):
            raise JpegParseError("JPEG contains a truncated segment.")
        length = struct.unpack(">H", raw[offset : offset + 2])[0]
        if length < 2 or offset + length > len(raw):
            raise JpegParseError("JPEG segment length is invalid.")
        segment = raw[offset + 2 : offset + length]
        if marker in _SOF_MARKERS:
            if frame_marker is not None:
                raise JpegParseError(
                    "JPEG contains duplicate or conflicting SOF frame headers."
                )
            frame_marker = marker
            if len(segment) < 6:
                raise JpegParseError("JPEG frame header is truncated.")
            if marker in _SUPPORTED_SOF_MARKERS:
                precision = segment[0]
                height, width = struct.unpack(">HH", segment[1:5])
                components = segment[5]
            else:
                unsupported_frame_marker = marker
        elif marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            candidate_orientation = _jpeg_orientation(segment[6:])
            if (
                exif_orientation is not None
                and candidate_orientation != exif_orientation
            ):
                raise JpegParseError("JPEG EXIF orientations conflict.")
            exif_orientation = candidate_orientation
            orientation = candidate_orientation
        elif marker == 0xEE and segment.startswith(b"Adobe"):
            if len(segment) < 12:
                raise JpegParseError("JPEG Adobe APP14 marker is truncated.")
            transform = segment[11]
            if adobe_transform is not None and adobe_transform != transform:
                raise JpegParseError("JPEG Adobe APP14 transforms conflict.")
            adobe_transform = transform
        offset += length
    if unsupported_frame_marker is not None:
        raise JpegUnsupportedError(
            f"JPEG SOF marker 0x{unsupported_frame_marker:02X} requires enhancement."
        )
    return JpegMetadata(
        width=width,
        height=height,
        components=components,
        precision=precision,
        orientation=orientation,
        adobe_transform=adobe_transform,
    )


def verify_direct_jpeg(raw: bytes, metadata: JpegMetadata) -> None:
    """Boundedly decode a direct-embed JPEG and bind it to parsed frame metadata."""
    if metadata.orientation != 1:
        raise JpegParseError("Direct JPEG decode proof requires orientation 1.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                _assert_decoded_frame(source, metadata)
                source.load()
                _assert_decoded_frame(source, metadata)
    except JpegParseError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        AttributeError,
    ) as error:
        raise JpegParseError("JPEG pixel decoding failed.") from error


def normalize_exif_jpeg(raw: bytes, metadata: JpegMetadata) -> NormalizedJpeg:
    """Decode and transpose an already size-bounded oriented JPEG."""
    if metadata.orientation not in range(2, 9):
        raise JpegParseError("JPEG EXIF orientation value is invalid.")
    expected_size = (
        (metadata.height, metadata.width)
        if metadata.orientation in {5, 6, 7, 8}
        else (metadata.width, metadata.height)
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format != "JPEG" or source.size != (
                    metadata.width,
                    metadata.height,
                ):
                    raise JpegParseError(
                        "Decoded JPEG dimensions do not match its frame header."
                    )
                normalized = ImageOps.exif_transpose(source)
                normalized.load()
                if normalized.size != expected_size:
                    raise JpegParseError("JPEG EXIF orientation normalization failed.")
                if normalized.mode == "L":
                    output = normalized
                    color_space = "/DeviceGray"
                else:
                    output = normalized.convert("RGB")
                    color_space = "/DeviceRGB"
                return NormalizedJpeg(
                    width=output.width,
                    height=output.height,
                    color_space=color_space,
                    pixels=output.tobytes(),
                )
    except JpegParseError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as error:
        raise JpegParseError("JPEG pixel decoding failed.") from error


def _assert_decoded_frame(source: Image.Image, metadata: JpegMetadata) -> None:
    expected_mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(metadata.components)
    if (
        source.format != "JPEG"
        or source.size != (metadata.width, metadata.height)
        or source.bits != metadata.precision
        or source.layers != metadata.components
    ):
        raise JpegParseError("Decoded JPEG frame metadata does not match its header.")
    if (
        expected_mode is None
        or source.mode != expected_mode
        or len(source.getbands()) != metadata.components
        or (
            metadata.adobe_transform is not None
            and source.info.get("adobe_transform") != metadata.adobe_transform
        )
    ):
        raise JpegParseError(
            "Decoded JPEG color components do not match its frame header."
        )


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
