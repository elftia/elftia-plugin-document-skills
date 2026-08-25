"""Decode bounded PDF Image XObjects into standalone JPEG or PNG bytes."""

from dataclasses import dataclass
import hashlib
from io import BytesIO
from typing import Any
import warnings

from PIL import Image

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .image_assets import MAX_IMAGE_PIXELS
from .image_decode import apply_decode, is_default_decode, normalized_decode
from .image_extraction_archive import encode_png
from .image_filter_parameters import filter_chain, reject_dct_decode_parameters
from .image_predictors import decode_image_predictor
from .jpeg_structure import validate_jpeg_frame
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel


@dataclass(frozen=True)
class ExtractedImage:
    format: str
    payload: bytes
    width: int
    height: int
    bits_per_component: int
    color_space: str
    filter_chain: list[str]
    soft_mask: bool
    decode: tuple[float, ...] | None = None
    source_object_sha256: str | None = None
    pixel_sha256: str | None = None


def extract_image(model: PdfObjectModel, obj: PdfObject) -> ExtractedImage:
    """Decode one already-bounded indirect Image XObject."""
    dictionary, stream = obj.value
    assert isinstance(dictionary, PdfDict)
    width = _positive_integer(dictionary.get("/Width"), "Width", obj.obj_num)
    height = _positive_integer(dictionary.get("/Height"), "Height", obj.obj_num)
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        _unsafe(
            "PDF image dimensions exceed the bounded pixel policy.",
            object=obj.obj_num,
            pixels=pixels,
            limit=MAX_IMAGE_PIXELS,
        )
    bits = _positive_integer(
        dictionary.get("/BitsPerComponent", 8),
        "BitsPerComponent",
        obj.obj_num,
    )
    color_space = _color_space(model, dictionary.get("/ColorSpace", "/DeviceRGB"))
    filters = filter_chain(
        model,
        dictionary.get("/Filter"),
        object_number=obj.obj_num,
    )
    reject_dct_decode_parameters(
        model,
        filters,
        dictionary.get("/DecodeParms"),
        object_number=obj.obj_num,
    )
    supported_color = color_space in {"/DeviceGray", "/DeviceRGB"}
    if dictionary.get("/Decode") is not None and not supported_color:
        _enhancement(
            "PDF image Decode requires a supported DeviceGray or DeviceRGB color space.",
            capability="pdf.image-decode-mapping",
            object=obj.obj_num,
            color_space=color_space,
        )
    color_channels = 1 if color_space == "/DeviceGray" else 3
    decode = (
        normalized_decode(
            model,
            dictionary.get("/Decode"),
            channels=color_channels,
            object_number=obj.obj_num,
        )
        if supported_color
        else None
    )
    if dictionary.get("/ImageMask") is True or dictionary.get("/Mask") is not None:
        _enhancement(
            "Image masks other than an 8-bit soft mask require an enhancement provider.",
            capability="pdf.image-mask-extraction",
            object=obj.obj_num,
        )
    if filters and filters[-1] == "/DCTDecode":
        return _extract_jpeg(
            model,
            obj,
            dictionary,
            stream,
            width,
            height,
            bits,
            color_space,
            filters,
            decode,
        )
    if filters and filters[-1] != "/FlateDecode":
        _enhancement(
            "The PDF image filter chain requires an enhancement provider.",
            capability="pdf.image-filter-extraction",
            object=obj.obj_num,
            filters=filters,
        )
    if not supported_color:
        _enhancement(
            "Core PNG reconstruction supports DeviceGray and DeviceRGB images.",
            capability="pdf.png-sample-reconstruction",
            object=obj.obj_num,
            bits_per_component=bits,
            color_space=color_space,
        )
    samples = decode_image_predictor(
        model,
        dictionary,
        stream,
        object_number=obj.obj_num,
        width=width,
        height=height,
        colors=color_channels,
        bits_per_component=bits,
    )
    assert decode is not None
    samples = apply_decode(
        samples,
        width=width,
        height=height,
        channels=color_channels,
        bits_per_component=bits,
        decode=decode,
        object_number=obj.obj_num,
    )
    alpha = _soft_mask_samples(model, dictionary.get("/SMask"), width, height)
    payload = encode_png(width, height, samples, color_channels, alpha)
    return ExtractedImage(
        "png",
        payload,
        width,
        height,
        bits,
        color_space,
        filters,
        alpha is not None,
        decode,
        obj.sha256,
        _sample_hash(samples),
    )


def _extract_jpeg(
    model: PdfObjectModel,
    obj: PdfObject,
    dictionary: PdfDict,
    payload: bytes,
    width: int,
    height: int,
    bits: int,
    color_space: str,
    filters: list[str],
    decode: tuple[float, ...] | None,
) -> ExtractedImage:
    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        _unsafe("DCTDecode image is not a complete JPEG codestream.", object=obj.obj_num)
    _verify_jpeg(payload, width, height, obj.obj_num)
    validate_jpeg_frame(
        payload,
        bits_per_component=bits,
        color_space=color_space,
        object_number=obj.obj_num,
    )
    if dictionary.get("/Decode") is not None and bits != 8:
        _enhancement(
            "JPEG Decode mapping requires an 8-bit image dictionary.",
            capability="pdf.image-decode-mapping",
            object=obj.obj_num,
            bits_per_component=bits,
        )
    has_mask = dictionary.get("/SMask") is not None
    if has_mask and (bits != 8 or decode is None):
        _enhancement(
            "JPEG soft-mask extraction requires 8-bit DeviceGray or DeviceRGB samples.",
            capability="pdf.jpeg-alpha-extraction",
            object=obj.obj_num,
        )
    samples, channels = _decode_jpeg_samples(
        payload,
        width,
        height,
        color_space,
        obj.obj_num,
    )
    if decode is not None:
        samples = apply_decode(
            samples,
            width=width,
            height=height,
            channels=channels,
            bits_per_component=8,
            decode=decode,
            object_number=obj.obj_num,
        )
    if not has_mask and (
        decode is None or is_default_decode(decode, channels)
    ):
        return ExtractedImage(
            "jpeg",
            payload,
            width,
            height,
            bits,
            color_space,
            filters,
            False,
            decode,
            obj.sha256,
            _sample_hash(samples),
        )
    alpha = _soft_mask_samples(model, dictionary.get("/SMask"), width, height)
    return ExtractedImage(
        "png",
        encode_png(width, height, samples, channels, alpha),
        width,
        height,
        bits,
        color_space,
        filters,
        alpha is not None,
        decode,
        obj.sha256,
        _sample_hash(samples),
    )


def _verify_jpeg(
    payload: bytes,
    width: int,
    height: int,
    object_number: int,
) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as image:
                if image.format != "JPEG":
                    _unsafe(
                        "DCTDecode image is not a JPEG codestream.",
                        object=object_number,
                    )
                if image.size != (width, height):
                    _unsafe(
                        "Decoded JPEG dimensions do not match the image dictionary.",
                        object=object_number,
                    )
                image.verify()
    except DocumentSkillsError:
        raise
    except Exception as error:
        _unsafe(
            "DCTDecode image could not be verified as a bounded JPEG.",
            object=object_number,
            reason=type(error).__name__,
        )


def _soft_mask_samples(
    model: PdfObjectModel,
    value: Any,
    width: int,
    height: int,
) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, IndirectReference):
        _enhancement(
            "Direct soft-mask streams require an enhancement provider.",
            capability="pdf.soft-mask-extraction",
        )
    obj = model.get_object(value)
    if not obj.is_stream or not isinstance(obj.value, tuple):
        _unsafe("Image soft mask is not a stream object.", object=obj.obj_num)
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        _unsafe("Image soft mask dictionary is malformed.", object=obj.obj_num)
    if (
        dictionary.get("/Width") != width
        or dictionary.get("/Height") != height
        or dictionary.get("/BitsPerComponent", 8) != 8
        or _color_space(model, dictionary.get("/ColorSpace", "/DeviceGray"))
        != "/DeviceGray"
    ):
        _enhancement(
            "Image soft mask dimensions or sample format are unsupported.",
            capability="pdf.soft-mask-extraction",
            object=obj.obj_num,
        )
    filters = filter_chain(
        model,
        dictionary.get("/Filter"),
        object_number=obj.obj_num,
    )
    if filters and filters[-1] != "/FlateDecode":
        _enhancement(
            "Image soft mask filter chain requires an enhancement provider.",
            capability="pdf.soft-mask-extraction",
            object=obj.obj_num,
        )
    samples = decode_image_predictor(
        model,
        dictionary,
        stream,
        object_number=obj.obj_num,
        width=width,
        height=height,
        colors=1,
        bits_per_component=8,
    )
    if len(samples) != width * height:
        _unsafe("Decoded image soft-mask byte count is invalid.", object=obj.obj_num)
    decode = normalized_decode(
        model,
        dictionary.get("/Decode"),
        channels=1,
        object_number=obj.obj_num,
    )
    return apply_decode(
        samples,
        width=width,
        height=height,
        channels=1,
        bits_per_component=8,
        decode=decode,
        object_number=obj.obj_num,
    )


def _decode_jpeg_samples(
    payload: bytes,
    width: int,
    height: int,
    color_space: str,
    object_number: int,
) -> tuple[bytes, int]:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            if image.size != (width, height):
                _unsafe(
                    "Decoded JPEG dimensions do not match the image dictionary.",
                    object=object_number,
                )
            mode = "L" if color_space == "/DeviceGray" else "RGB"
            decoded = image.convert(mode)
            return decoded.tobytes(), 1 if mode == "L" else 3
    except DocumentSkillsError:
        raise
    except Exception as error:
        _unsafe(
            "JPEG image could not be decoded for soft-mask extraction.",
            object=object_number,
            reason=type(error).__name__,
        )


def _color_space(model: PdfObjectModel, value: Any) -> str:
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    return value if isinstance(value, str) else "/Unsupported"


def _positive_integer(value: Any, field: str, obj_num: int) -> int:
    if type(value) is not int or type(value) is bool or value <= 0:
        _unsafe("PDF image dimension metadata is invalid.", object=obj_num, field=field)
    return value


def _sample_hash(samples: bytes) -> str:
    return hashlib.sha256(samples).hexdigest()


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
