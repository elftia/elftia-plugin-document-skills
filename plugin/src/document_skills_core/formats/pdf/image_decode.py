"""Bounded PDF Image `/Decode` normalization and sample mapping."""

import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfObjectModel

_SUPPORTED_BITS = frozenset({1, 2, 4, 8, 16})


def normalized_decode(
    model: PdfObjectModel | None,
    value: Any,
    *,
    channels: int,
    object_number: int,
    capability: str = "pdf.image-decode-mapping",
) -> tuple[float, ...]:
    """Return a finite component-pair mapping, including PDF defaults."""
    default = tuple(component for _ in range(channels) for component in (0.0, 1.0))
    if value is None:
        return default
    if isinstance(value, IndirectReference):
        if model is None:
            _unsafe("PDF image Decode contains an indirect reference.", object=object_number)
        value = model.get_object(value).value
    if not isinstance(value, list):
        _unsafe("PDF image Decode entry is not an array.", object=object_number)
    if len(value) != channels * 2:
        _enhancement(
            "PDF image Decode length does not match its color components.",
            object=object_number,
            expected=channels * 2,
            actual=len(value),
            capability=capability,
        )
    output: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            _unsafe("PDF image Decode contains a non-numeric value.", object=object_number)
        number = float(item)
        if not math.isfinite(number):
            _unsafe("PDF image Decode contains a non-finite value.", object=object_number)
        output.append(number)
    return tuple(output)


def apply_decode(
    samples: bytes,
    *,
    width: int,
    height: int,
    channels: int,
    bits_per_component: int,
    decode: tuple[float, ...],
    object_number: int,
) -> bytes:
    """Unpack bounded samples and map component values into 8-bit color bytes."""
    if bits_per_component not in _SUPPORTED_BITS:
        _enhancement(
            "PDF image Decode uses an unsupported BitsPerComponent value.",
            object=object_number,
            bits_per_component=bits_per_component,
        )
    row_samples = width * channels
    row_bytes = (row_samples * bits_per_component + 7) // 8
    expected = row_bytes * height
    if len(samples) != expected:
        _unsafe(
            "Decoded PDF image sample bytes do not match the packed image layout.",
            object=object_number,
            expected=expected,
            actual=len(samples),
        )
    if bits_per_component == 8 and is_default_decode(decode, channels):
        return samples
    maximum = (1 << bits_per_component) - 1
    output = bytearray(width * height * channels)
    output_offset = 0
    for row_number in range(height):
        row = samples[row_number * row_bytes : (row_number + 1) * row_bytes]
        for sample_index in range(row_samples):
            sample = _packed_sample(row, sample_index, bits_per_component)
            component = sample_index % channels
            minimum = decode[component * 2]
            maximum_value = decode[component * 2 + 1]
            mapped = minimum + sample * (maximum_value - minimum) / maximum
            clipped = min(1.0, max(0.0, mapped))
            output[output_offset] = int(clipped * 255.0 + 0.5)
            output_offset += 1
    return bytes(output)


def is_default_decode(decode: tuple[float, ...], channels: int) -> bool:
    return decode == tuple(
        component for _ in range(channels) for component in (0.0, 1.0)
    )


def _packed_sample(row: bytes, index: int, bits: int) -> int:
    bit_offset = index * bits
    byte_offset = bit_offset // 8
    if bits == 16:
        return (row[byte_offset] << 8) | row[byte_offset + 1]
    shift = 8 - bits - (bit_offset % 8)
    return (row[byte_offset] >> shift) & ((1 << bits) - 1)


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(
    message: str,
    *,
    capability: str = "pdf.image-decode-mapping",
    **details: Any,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": capability, **details},
    )
