"""Bounded parsing of raw or FlateDecode 8-bit inline PDF images."""

from dataclasses import dataclass
from typing import Any
import zlib

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .image_assets import MAX_IMAGE_PIXELS
from .image_decode import apply_decode, normalized_decode
from .image_extraction_limits import ImageExtractionBudget
from .content_tokenizer import find_operator_token
from .object_values import parse_array


@dataclass(frozen=True)
class InlineImage:
    width: int
    height: int
    bits_per_component: int
    color_space: str
    samples: bytes
    filter_chain: tuple[str, ...]
    decode: tuple[float, ...] | None


def parse_inline_images(
    content: bytes,
    *,
    budget: ImageExtractionBudget,
) -> tuple[list[InlineImage], bytes]:
    """Extract supported inline samples and remove their bytes for operator walking."""
    images: list[InlineImage] = []
    sanitized = bytearray()
    cursor = 0
    search_position = 0
    while True:
        match = find_operator_token(content, b"BI", start=search_position)
        if match is None:
            sanitized.extend(content[cursor:])
            break
        match_start, match_end = match
        id_match = find_operator_token(
            content,
            b"ID",
            start=match_end,
            limit=match_end + 65_537,
        )
        if id_match is None:
            _unsafe("Inline image dictionary is missing a bounded ID delimiter.")
        id_start, id_end = id_match
        header = content[match_end:id_start]
        values = _inline_dictionary(header)
        image = _image_layout(values)
        data_start = _skip_single_separator(content, id_end)
        sample_count = image.width * image.height * (
            1 if image.color_space == "/DeviceGray" else 3
        )
        budget.reserve_image(
            image.width,
            image.height,
            inline_sample_bytes=sample_count,
        )
        if image.filter_chain:
            samples, consumed = _flate_samples(content[data_start:], sample_count)
            data_end = data_start + consumed
        else:
            data_end = data_start + sample_count
            if data_end > len(content):
                _unsafe("Inline image sample bytes are truncated.")
            samples = content[data_start:data_end]
        if image.decode is not None:
            samples = apply_decode(
                samples,
                width=image.width,
                height=image.height,
                channels=1 if image.color_space == "/DeviceGray" else 3,
                bits_per_component=image.bits_per_component,
                decode=image.decode,
                object_number=0,
            )
        end_image = _end_image_position(content, data_end)
        images.append(InlineImage(
            width=image.width,
            height=image.height,
            bits_per_component=image.bits_per_component,
            color_space=image.color_space,
            samples=samples,
            filter_chain=image.filter_chain,
            decode=image.decode,
        ))
        sanitized.extend(content[cursor:match_start])
        sanitized.extend(b" BI ")
        cursor = end_image
        search_position = end_image
    return images, bytes(sanitized)


def _inline_dictionary(header: bytes) -> dict[str, Any]:
    try:
        tokens = header.decode("latin-1", errors="strict").split()
    except UnicodeDecodeError:
        _unsafe("Inline image dictionary is not byte-safe text.")
    values: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        key = tokens[index]
        index += 1
        if not key.startswith("/") or key in values:
            _unsafe("Inline image dictionary keys are malformed or duplicated.")
        if index >= len(tokens):
            _unsafe("Inline image dictionary must contain key/value pairs.")
        value = tokens[index]
        if value.startswith("["):
            parts: list[str] = []
            depth = 0
            while index < len(tokens):
                part = tokens[index]
                parts.append(part)
                depth += part.count("[") - part.count("]")
                index += 1
                if depth == 0:
                    break
            if depth != 0:
                _unsafe("Inline image dictionary array is not terminated.")
            raw_array = " ".join(parts).encode("latin-1")
            value, end = parse_array(raw_array, 0)
            if end != len(raw_array):
                _unsafe("Inline image dictionary array is malformed.")
        else:
            if "[" in value or "]" in value:
                _unsafe("Inline image dictionary array is malformed.")
            index += 1
        values[key] = value
    if any(key in values for key in ("/DP", "/DecodeParms")):
        _enhancement("Predictor-encoded inline images are not supported.")
    filter_name = values.get("/F", values.get("/Filter"))
    if filter_name is not None and filter_name not in ("/Fl", "/FlateDecode"):
        _enhancement("The inline image filter requires an enhancement provider.")
    if values.get("/IM", values.get("/ImageMask")) == "true":
        _enhancement("Inline image masks are not supported.")
    return values


def _image_layout(values: dict[str, Any]) -> InlineImage:
    width = _positive_integer(values.get("/W", values.get("/Width")), "Width")
    height = _positive_integer(values.get("/H", values.get("/Height")), "Height")
    bits = _positive_integer(
        values.get("/BPC", values.get("/BitsPerComponent", "8")),
        "BitsPerComponent",
    )
    color = values.get("/CS", values.get("/ColorSpace", "/RGB"))
    color_space = {
        "/G": "/DeviceGray",
        "/DeviceGray": "/DeviceGray",
        "/RGB": "/DeviceRGB",
        "/DeviceRGB": "/DeviceRGB",
    }.get(color)
    decode_value = values.get("/D", values.get("/Decode"))
    if bits != 8 or color_space is None:
        _enhancement(
            "Inline extraction supports only 8-bit DeviceGray and DeviceRGB images.",
            capability=(
                "pdf.inline-image-decode"
                if decode_value is not None
                else "pdf.inline-image-extraction"
            ),
        )
    if width * height > MAX_IMAGE_PIXELS:
        _unsafe("Inline image dimensions exceed the pixel limit.")
    filter_name = values.get("/F", values.get("/Filter"))
    filters = ("/FlateDecode",) if filter_name is not None else ()
    channels = 1 if color_space == "/DeviceGray" else 3
    decode = (
        normalized_decode(
            None,
            decode_value,
            channels=channels,
            object_number=0,
            capability="pdf.inline-image-decode",
        )
        if decode_value is not None
        else None
    )
    return InlineImage(width, height, bits, color_space, b"", filters, decode)


def _flate_samples(data: bytes, expected_count: int) -> tuple[bytes, int]:
    decoder = zlib.decompressobj()
    try:
        samples = decoder.decompress(data, expected_count + 1)
    except zlib.error:
        _unsafe("FlateDecode inline image data is malformed.")
    if len(samples) > expected_count or decoder.unconsumed_tail:
        _unsafe("FlateDecode inline image exceeds its declared sample bounds.")
    if not decoder.eof:
        _unsafe("FlateDecode inline image data is truncated.")
    if len(samples) != expected_count:
        _unsafe("Decoded inline image sample bytes do not match its dimensions.")
    consumed = len(data) - len(decoder.unused_data)
    if consumed <= 0:
        _unsafe("FlateDecode inline image has no bounded codestream.")
    return samples, consumed


def _skip_single_separator(content: bytes, position: int) -> int:
    if position >= len(content) or content[position] not in b" \t\r\n\f":
        _unsafe("Inline image ID is not followed by a whitespace separator.")
    if content[position:position + 2] == b"\r\n":
        return position + 2
    return position + 1


def _end_image_position(content: bytes, data_end: int) -> int:
    position = data_end
    while position < len(content) and content[position] in b" \t\r\n\f":
        position += 1
    if content[position:position + 2] != b"EI":
        _unsafe("Inline image samples are not followed by an EI delimiter.")
    after = position + 2
    if after < len(content) and content[after] not in b" \t\r\n\f":
        _unsafe("Inline image EI delimiter is not token-bounded.")
    return after


def _positive_integer(value: Any, field: str) -> int:
    try:
        number = int(value or "")
    except (TypeError, ValueError):
        _unsafe("Inline image dimension metadata is invalid.", field=field)
    if number <= 0:
        _unsafe("Inline image dimension metadata is invalid.", field=field)
    return number


def _unsafe(message: str, **details: object) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(
    message: str,
    *,
    capability: str = "pdf.inline-image-extraction",
) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": capability},
    )
