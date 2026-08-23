"""Bounded extraction of directly invoked PDF Image XObjects.

The Core path copies JPEG codestreams and reconstructs 8-bit grayscale/RGB
PNG files from lossless image samples, including a compatible soft mask.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
from .byte_preflight import PdfByteLimits, preflight_pdf
from .constants import MAX_CONTENT_STREAM_OPERATORS
from .content_streams import extract_content_stream
from .image_assets import MAX_IMAGE_PIXELS
from .image_extraction_archive import (
    encode_png,
    validate_image_archive,
    write_deterministic_image_zip,
)
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel, parse_pdf
from .page_tree import PageInfo, walk_pages
from .xobject_draws import walk_xobject_draws

_MAX_TOTAL_IMAGE_PIXELS = 100_000_000


@dataclass(frozen=True)
class _ExtractedImage:
    format: str
    payload: bytes
    width: int
    height: int
    bits_per_component: int
    color_space: str
    filter_chain: list[str]
    soft_mask: bool


def extract_pdf_images(
    source: Path,
    output: Path,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Extract selected, directly invoked Image XObjects to a deterministic ZIP."""
    limits = PdfByteLimits()
    preflight = preflight_pdf(source, limits)
    if preflight.encrypted:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF is encrypted; explicit decryption is required before image extraction.",
        )
    model = parse_pdf(source, limits)
    actions = classify_actions(model)
    if has_dangerous_actions(actions) or has_executable_embedded_files(model):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF contains active or executable content and cannot be extracted in normal mode.",
        )

    all_pages = walk_pages(model)
    selected = _select_pages(all_pages, arguments["pages"])
    payloads: dict[str, bytes] = {}
    images: list[dict[str, Any]] = []
    total_bytes = 0
    total_pixels = 0
    for page in selected:
        content = extract_content_stream(model, page.contents, page.page_number, limits)
        draws, has_inline_image = walk_xobject_draws(
            content,
            page.page_number,
            max_operators=MAX_CONTENT_STREAM_OPERATORS,
        )
        if has_inline_image:
            _enhancement(
                "Inline PDF images are not yet extractable by the Core provider.",
                capability="pdf.inline-image-extraction",
                page=page.page_number,
            )
        xobjects = _xobject_resources(model, page)
        for draw in draws:
            resource = xobjects.get(draw.resource_name)
            if resource is None:
                _unsafe(
                    "Page content invokes a missing XObject resource.",
                    page=page.page_number,
                    resource=draw.resource_name,
                )
            image_object = _image_object(model, resource)
            if image_object is None:
                continue
            if len(images) >= arguments["max_images"]:
                _unsafe(
                    "Extracted image count exceeds the caller-selected limit.",
                    limit=arguments["max_images"],
                )
            extracted = _extract_image(model, image_object)
            total_pixels += extracted.width * extracted.height
            if total_pixels > _MAX_TOTAL_IMAGE_PIXELS:
                _unsafe(
                    "Extracted image pixels exceed the aggregate safety limit.",
                    pixels=total_pixels,
                    limit=_MAX_TOTAL_IMAGE_PIXELS,
                )
            total_bytes += len(extracted.payload)
            if total_bytes > arguments["max_total_bytes"]:
                _unsafe(
                    "Extracted image bytes exceed the caller-selected limit.",
                    bytes=total_bytes,
                    limit=arguments["max_total_bytes"],
                )
            extension = "jpg" if extracted.format == "jpeg" else "png"
            archive_path = (
                f"page-{page.page_number:04d}-image-{len(images) + 1:04d}-"
                f"object-{image_object.obj_num:08d}.{extension}"
            )
            payloads[archive_path] = extracted.payload
            images.append({
                "archive_path": archive_path,
                "format": extracted.format,
                "page": page.page_number,
                "object": image_object.obj_num,
                "resource": draw.resource_name,
                "bbox": list(draw.bbox),
                "width": extracted.width,
                "height": extracted.height,
                "bits_per_component": extracted.bits_per_component,
                "color_space": extracted.color_space,
                "filter_chain": extracted.filter_chain,
                "soft_mask": extracted.soft_mask,
                "bytes": len(extracted.payload),
                "sha256": hashlib.sha256(extracted.payload).hexdigest(),
            })

    write_deterministic_image_zip(output, payloads)
    return {
        "image_count": len(images),
        "total_image_bytes": total_bytes,
        "total_image_pixels": total_pixels,
        "selected_pages": [page.page_number for page in selected],
        "images": images,
    }


def _select_pages(pages: list[PageInfo], requested: list[int] | None) -> list[PageInfo]:
    if requested is None:
        return pages
    by_number = {page.page_number: page for page in pages}
    missing = [page for page in requested if page not in by_number]
    if missing:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Requested image extraction page is outside the document.",
            status="invalid_request",
            details={"pages": missing, "page_count": len(pages)},
        )
    return [by_number[page] for page in requested]


def _xobject_resources(model: PdfObjectModel, page: PageInfo) -> dict[str, Any]:
    if page.resources is None:
        return {}
    xobjects = page.resources.get("/XObject")
    if isinstance(xobjects, IndirectReference):
        xobjects = model.get_object(xobjects).value
    if not isinstance(xobjects, PdfDict):
        return {}
    return xobjects.entries


def _image_object(model: PdfObjectModel, resource: Any) -> PdfObject | None:
    if not isinstance(resource, IndirectReference):
        _enhancement(
            "Direct Image XObject resources are not supported by the Core extractor.",
            capability="pdf.direct-image-xobject",
        )
    obj = model.get_object(resource)
    if not obj.is_stream or not isinstance(obj.value, tuple):
        return None
    dictionary = obj.value[0]
    if not isinstance(dictionary, PdfDict) or dictionary.get("/Subtype") != "/Image":
        return None
    return obj


def _extract_image(
    model: PdfObjectModel,
    obj: PdfObject,
) -> _ExtractedImage:
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
    filters = _filter_chain(dictionary.get("/Filter"))
    if dictionary.get("/ImageMask") is True or dictionary.get("/Mask") is not None:
        _enhancement(
            "Image masks other than an 8-bit soft mask require an enhancement provider.",
            capability="pdf.image-mask-extraction",
            object=obj.obj_num,
        )

    if filters and filters[-1] == "/DCTDecode":
        if dictionary.get("/SMask") is not None:
            _enhancement(
                "JPEG XObjects with a soft mask require a raster decode provider.",
                capability="pdf.jpeg-alpha-extraction",
                object=obj.obj_num,
            )
        # PdfObjectModel keeps the bounded, filter-decoded stream. DCTDecode is
        # intentionally a no-op there, so this remains the original JPEG.
        payload = stream
        if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            _unsafe("DCTDecode image is not a complete JPEG codestream.", object=obj.obj_num)
        return _ExtractedImage(
            "jpeg", payload, width, height, bits, color_space, filters, False,
        )

    if filters and filters[-1] != "/FlateDecode":
        _enhancement(
            "The PDF image filter chain requires an enhancement provider.",
            capability="pdf.image-filter-extraction",
            object=obj.obj_num,
            filters=filters,
        )
    _assert_no_predictor(model, dictionary, obj.obj_num)
    if bits != 8 or color_space not in {"/DeviceGray", "/DeviceRGB"}:
        _enhancement(
            "Core PNG reconstruction supports only 8-bit DeviceGray and DeviceRGB images.",
            capability="pdf.png-sample-reconstruction",
            object=obj.obj_num,
            bits_per_component=bits,
            color_space=color_space,
        )
    samples = stream
    color_channels = 1 if color_space == "/DeviceGray" else 3
    expected = width * height * color_channels
    if len(samples) != expected:
        _unsafe(
            "Decoded PDF image sample count does not match its dimensions.",
            object=obj.obj_num,
            expected=expected,
            actual=len(samples),
        )
    alpha = _soft_mask_samples(model, dictionary.get("/SMask"), width, height)
    payload = encode_png(width, height, samples, color_channels, alpha)
    return _ExtractedImage(
        "png", payload, width, height, bits, color_space, filters, alpha is not None,
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
    _assert_no_predictor(model, dictionary, obj.obj_num)
    filters = _filter_chain(dictionary.get("/Filter"))
    if filters and filters[-1] != "/FlateDecode":
        _enhancement(
            "Image soft mask filter chain requires an enhancement provider.",
            capability="pdf.soft-mask-extraction",
            object=obj.obj_num,
        )
    samples = stream
    if len(samples) != width * height:
        _unsafe("Decoded image soft-mask byte count is invalid.", object=obj.obj_num)
    return samples


def _assert_no_predictor(
    model: PdfObjectModel,
    dictionary: PdfDict,
    obj_num: int,
) -> None:
    decode_parameters = dictionary.get("/DecodeParms")
    if isinstance(decode_parameters, IndirectReference):
        decode_parameters = model.get_object(decode_parameters).value
    candidates = decode_parameters if isinstance(decode_parameters, list) else [decode_parameters]
    for candidate in candidates:
        if isinstance(candidate, IndirectReference):
            candidate = model.get_object(candidate).value
        if isinstance(candidate, PdfDict) and candidate.get("/Predictor", 1) != 1:
            _enhancement(
                "Predictor-encoded image samples require an enhancement provider.",
                capability="pdf.image-predictor-extraction",
                object=obj_num,
            )


def _color_space(model: PdfObjectModel, value: Any) -> str:
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    return value if isinstance(value, str) else "/Unsupported"


def _filter_chain(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    _unsafe("PDF image filter chain is malformed.")


def _positive_integer(value: Any, field: str, obj_num: int) -> int:
    if type(value) is not int or type(value) is bool or value <= 0:
        _unsafe("PDF image dimension metadata is invalid.", object=obj_num, field=field)
    return value


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
