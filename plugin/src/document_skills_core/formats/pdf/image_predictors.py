"""Bounded reversal of TIFF and PNG predictors for 8-bit PDF images."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObjectModel


def decode_image_predictor(
    model: PdfObjectModel,
    dictionary: PdfDict,
    samples: bytes,
    *,
    object_number: int,
    width: int,
    height: int,
    colors: int,
    bits_per_component: int,
) -> bytes:
    parameters = _decode_parameters(model, dictionary.get("/DecodeParms"))
    if parameters is None:
        return samples
    predictor = parameters.get("/Predictor", 1)
    if predictor == 1:
        return samples
    if type(predictor) is not int or predictor not in {2, 10, 11, 12, 13, 14, 15}:
        _enhancement(
            "The image predictor is not supported by the Core extractor.",
            object=object_number,
            predictor=predictor,
        )
    parameter_colors = parameters.get("/Colors", 1)
    parameter_bits = parameters.get("/BitsPerComponent", 8)
    parameter_columns = parameters.get("/Columns", 1)
    if (
        parameter_colors != colors
        or parameter_bits != bits_per_component
        or parameter_columns != width
        or bits_per_component != 8
    ):
        _enhancement(
            "Predictor parameters do not match the bounded 8-bit image layout.",
            object=object_number,
            predictor=predictor,
            colors=parameter_colors,
            bits_per_component=parameter_bits,
            columns=parameter_columns,
        )
    row_bytes = width * colors
    if predictor == 2:
        if len(samples) != row_bytes * height:
            _unsafe("TIFF predictor sample count is invalid.", object=object_number)
        output = bytearray(samples)
        for row_start in range(0, len(output), row_bytes):
            for index in range(colors, row_bytes):
                offset = row_start + index
                output[offset] = (output[offset] + output[offset - colors]) & 0xFF
        return bytes(output)
    return _decode_png_rows(
        samples,
        predictor=predictor,
        row_bytes=row_bytes,
        rows=height,
        bytes_per_pixel=colors,
        object_number=object_number,
    )


def _decode_parameters(model: PdfObjectModel, value: Any) -> PdfDict | None:
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    if isinstance(value, list):
        value = value[-1] if value else None
        if isinstance(value, IndirectReference):
            value = model.get_object(value).value
    if value is None:
        return None
    if not isinstance(value, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF image DecodeParms is malformed.",
        )
    return value


def _decode_png_rows(
    samples: bytes,
    *,
    predictor: int,
    row_bytes: int,
    rows: int,
    bytes_per_pixel: int,
    object_number: int,
) -> bytes:
    tagged_length = rows * (row_bytes + 1)
    fixed_length = rows * row_bytes
    tagged = len(samples) == tagged_length
    if not tagged and not (predictor in {10, 11, 12, 13, 14} and len(samples) == fixed_length):
        _unsafe("PNG predictor sample count is invalid.", object=object_number)
    output = bytearray()
    offset = 0
    previous = bytes(row_bytes)
    fixed_filter = predictor - 10
    for _row in range(rows):
        filter_type = samples[offset] if tagged else fixed_filter
        offset += 1 if tagged else 0
        if filter_type not in {0, 1, 2, 3, 4}:
            _unsafe(
                "PNG predictor row uses an unknown filter.",
                object=object_number,
                filter=filter_type,
            )
        raw = samples[offset:offset + row_bytes]
        offset += row_bytes
        row = bytearray(row_bytes)
        for index, value in enumerate(raw):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 1:
                value += left
            elif filter_type == 2:
                value += up
            elif filter_type == 3:
                value += (left + up) // 2
            elif filter_type == 4:
                value += _paeth(left, up, upper_left)
            row[index] = value & 0xFF
        output.extend(row)
        previous = bytes(row)
    return bytes(output)


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.image-predictor-extraction", **details},
    )
