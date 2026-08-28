"""Bounded extraction of PDF images, including nested Form XObjects."""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
from .byte_preflight import PdfByteLimits, preflight_pdf
from .constants import MAX_CONTENT_STREAM_OPERATORS
from .content_streams import extract_content_stream, tokenize_content_stream
from .image_extraction_archive import (
    encode_png,
    write_deterministic_image_zip,
)
from .image_extraction_limits import ImageExtractionBudget, MAX_TOTAL_IMAGE_PIXELS
from .image_xobject_extract import ExtractedImage, extract_image
from .inline_images import parse_inline_images
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel, parse_pdf
from .page_tree import PageInfo, walk_pages
from .xobject_draws import (
    AffineMatrix,
    concatenate_matrix,
    IDENTITY_MATRIX,
    walk_xobject_draws,
)

_MAX_TOTAL_IMAGE_PIXELS = MAX_TOTAL_IMAGE_PIXELS
_MAX_FORM_DEPTH = 32


@dataclass
class _TraversalBudget:
    remaining_operators: int = MAX_CONTENT_STREAM_OPERATORS


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
    page_image_counts: dict[int, int] = {}
    image_budget = ImageExtractionBudget(
        max_images=arguments["max_images"],
        max_output_bytes=arguments["max_total_bytes"],
        max_pixels=_MAX_TOTAL_IMAGE_PIXELS,
    )

    def add_extracted(
        extracted: ExtractedImage,
        *,
        page_number: int,
        object_number: int | None,
        resource: str | None,
        bbox: tuple[float, float, float, float],
        source_kind: str,
        inline_index: int | None = None,
        pre_reserved: bool = False,
    ) -> None:
        if not pre_reserved:
            image_budget.reserve_image(extracted.width, extracted.height)
        image_budget.add_output_bytes(len(extracted.payload))
        page_image_index = page_image_counts.get(page_number, 0) + 1
        page_image_counts[page_number] = page_image_index
        extension = "jpg" if extracted.format == "jpeg" else "png"
        identity = (
            f"object-{object_number:08d}"
            if object_number is not None
            else f"inline-{inline_index or 0:04d}"
        )
        archive_path = (
            f"page-{page_number:04d}-image-{len(images) + 1:04d}-"
            f"{identity}.{extension}"
        )
        payloads[archive_path] = extracted.payload
        images.append({
            "archive_path": archive_path,
            "format": extracted.format,
            "source": source_kind,
            "page": page_number,
            "page_image_index": page_image_index,
            "object": object_number,
            "inline_index": inline_index,
            "resource": resource,
            "bbox": list(bbox),
            "width": extracted.width,
            "height": extracted.height,
            "bits_per_component": extracted.bits_per_component,
            "color_space": extracted.color_space,
            "filter_chain": extracted.filter_chain,
            "soft_mask": extracted.soft_mask,
            "decode": list(extracted.decode) if extracted.decode is not None else None,
            "source_object_sha256": extracted.source_object_sha256,
            "pixel_sha256": extracted.pixel_sha256,
            "bytes": len(extracted.payload),
            "sha256": hashlib.sha256(extracted.payload).hexdigest(),
        })

    for page in selected:
        content = extract_content_stream(model, page.contents, page.page_number, limits)
        _walk_content_images(
            model,
            content,
            page=page,
            resources=page.resources,
            add_extracted=add_extracted,
            budget=_TraversalBudget(),
            image_budget=image_budget,
        )

    write_deterministic_image_zip(output, payloads)
    return {
        "image_count": len(images),
        "total_image_bytes": image_budget.total_output_bytes,
        "total_image_pixels": image_budget.total_pixels,
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


def _walk_content_images(
    model: PdfObjectModel,
    content: bytes,
    *,
    page: PageInfo,
    resources: PdfDict | None,
    add_extracted: Callable[..., None],
    budget: _TraversalBudget,
    image_budget: ImageExtractionBudget,
    initial_matrix: AffineMatrix = IDENTITY_MATRIX,
    resource_path: tuple[str, ...] = (),
    active_forms: frozenset[int] = frozenset(),
) -> None:
    inline_images, sanitized_content = parse_inline_images(
        content,
        budget=image_budget,
    )
    operator_count = len(tokenize_content_stream(sanitized_content))
    if operator_count > budget.remaining_operators:
        _unsafe(
            "Nested PDF content exceeds the image-operator budget.",
            page=page.page_number,
            limit=MAX_CONTENT_STREAM_OPERATORS,
        )
    budget.remaining_operators -= operator_count
    draws, inline_draws = walk_xobject_draws(
        sanitized_content,
        page.page_number,
        max_operators=operator_count,
        initial_matrix=initial_matrix,
    )
    if len(inline_images) != len(inline_draws):
        _unsafe(
            "Inline image parsing and graphics-state tracking disagree.",
            page=page.page_number,
        )

    xobjects = _xobject_resources(model, resources)
    for draw in draws:
        resource = xobjects.get(draw.resource_name)
        if resource is None:
            _unsafe(
                "PDF content invokes a missing XObject resource.",
                page=page.page_number,
                resource=_resource_name(resource_path + (draw.resource_name,)),
            )
        xobject = _xobject_object(model, resource)
        if xobject is None:
            continue
        dictionary, stream = xobject.value
        assert isinstance(dictionary, PdfDict)
        nested_path = resource_path + (draw.resource_name,)
        subtype = dictionary.get("/Subtype")
        if subtype == "/Image":
            width = dictionary.get("/Width")
            height = dictionary.get("/Height")
            reserved = (
                type(width) is int
                and type(height) is int
                and width > 0
                and height > 0
            )
            if reserved:
                image_budget.reserve_image(width, height)
            add_extracted(
                extract_image(model, xobject),
                page_number=page.page_number,
                object_number=xobject.obj_num,
                resource=_resource_name(nested_path),
                bbox=draw.bbox,
                source_kind="xobject",
                pre_reserved=reserved,
            )
        elif subtype == "/Form":
            if xobject.obj_num in active_forms:
                _unsafe(
                    "Form XObject graph contains a recursive invocation.",
                    page=page.page_number,
                    object=xobject.obj_num,
                )
            if len(active_forms) >= _MAX_FORM_DEPTH:
                _unsafe(
                    "Form XObject nesting exceeds the safety limit.",
                    page=page.page_number,
                    limit=_MAX_FORM_DEPTH,
                )
            _validate_form_bbox(dictionary.get("/BBox"), xobject.obj_num)
            form_resources = _form_resources(
                model,
                dictionary.get("/Resources"),
                inherited=resources,
                object_number=xobject.obj_num,
            )
            _walk_content_images(
                model,
                stream,
                page=page,
                resources=form_resources,
                add_extracted=add_extracted,
                budget=budget,
                image_budget=image_budget,
                initial_matrix=concatenate_matrix(
                    _form_matrix(dictionary.get("/Matrix"), xobject.obj_num),
                    draw.matrix,
                ),
                resource_path=nested_path,
                active_forms=active_forms | {xobject.obj_num},
            )

    for inline_index, (inline_image, inline_draw) in enumerate(
        zip(inline_images, inline_draws),
        start=1,
    ):
        channels = 1 if inline_image.color_space == "/DeviceGray" else 3
        add_extracted(
            ExtractedImage(
                "png",
                encode_png(
                    inline_image.width,
                    inline_image.height,
                    inline_image.samples,
                    channels,
                    None,
                ),
                inline_image.width,
                inline_image.height,
                inline_image.bits_per_component,
                inline_image.color_space,
                list(inline_image.filter_chain),
                False,
                inline_image.decode,
                None,
                hashlib.sha256(inline_image.samples).hexdigest(),
            ),
            page_number=page.page_number,
            object_number=None,
            resource=_resource_name(resource_path) if resource_path else None,
            bbox=inline_draw.bbox,
            source_kind="inline",
            inline_index=inline_index,
            pre_reserved=True,
        )


def _xobject_resources(
    model: PdfObjectModel,
    resources: PdfDict | None,
) -> dict[str, Any]:
    if resources is None:
        return {}
    xobjects = resources.get("/XObject")
    if isinstance(xobjects, IndirectReference):
        xobjects = model.get_object(xobjects).value
    if not isinstance(xobjects, PdfDict):
        return {}
    return xobjects.entries


def _xobject_object(model: PdfObjectModel, resource: Any) -> PdfObject | None:
    if not isinstance(resource, IndirectReference):
        _enhancement(
            "Direct XObject resources are not supported by the Core extractor.",
            capability="pdf.direct-xobject",
        )
    obj = model.get_object(resource)
    if not obj.is_stream or not isinstance(obj.value, tuple):
        return None
    dictionary = obj.value[0]
    if not isinstance(dictionary, PdfDict):
        return None
    return obj


def _form_resources(
    model: PdfObjectModel,
    value: Any,
    *,
    inherited: PdfDict | None,
    object_number: int,
) -> PdfDict | None:
    if value is None:
        return inherited
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    if not isinstance(value, PdfDict):
        _unsafe("Form XObject resources are malformed.", object=object_number)
    return value


def _form_matrix(value: Any, object_number: int) -> AffineMatrix:
    if value is None:
        return IDENTITY_MATRIX
    if not isinstance(value, list) or len(value) != 6:
        _unsafe("Form XObject matrix is malformed.", object=object_number)
    numbers: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            _unsafe("Form XObject matrix is malformed.", object=object_number)
        number = float(item)
        if not math.isfinite(number):
            _unsafe("Form XObject matrix is non-finite.", object=object_number)
        numbers.append(number)
    return (
        numbers[0],
        numbers[1],
        numbers[2],
        numbers[3],
        numbers[4],
        numbers[5],
    )


def _validate_form_bbox(value: Any, object_number: int) -> None:
    if not isinstance(value, list) or len(value) != 4:
        _unsafe("Form XObject BBox is malformed.", object=object_number)
    for item in value:
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
        ):
            _unsafe("Form XObject BBox is malformed.", object=object_number)


def _resource_name(path: tuple[str, ...]) -> str:
    return "/" + "/".join(item.lstrip("/") for item in path)


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
