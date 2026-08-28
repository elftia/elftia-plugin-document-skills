"""Rebind extracted image occurrences to their source PDF semantics."""

from dataclasses import dataclass
import hashlib
from typing import Any

from .byte_preflight import PdfByteLimits
from .content_streams import extract_content_stream
from .extract_contracts import MAX_EXTRACTED_IMAGES, MAX_EXTRACTED_TOTAL_BYTES
from .image_extraction_limits import ImageExtractionBudget, MAX_TOTAL_IMAGE_PIXELS
from .image_xobject_extract import ExtractedImage
from .object_model import PdfObjectModel
from .page_tree import walk_pages

_SourceIdentity = tuple[int, int, int | None, str | None]


@dataclass(frozen=True)
class _SourceOccurrence:
    identity: _SourceIdentity
    source_kind: str
    object_number: int | None
    extracted: ExtractedImage
    bbox: list[float]


def verify_source_manifest_semantics(
    model: PdfObjectModel,
    operation_result: dict[str, Any],
) -> dict[str, int]:
    """Require a one-to-one manifest replay before binding inline payloads."""
    images = operation_result.get("images")
    selected_pages = operation_result.get("selected_pages")
    if not isinstance(images, list) or not isinstance(selected_pages, list):
        raise ValueError("Extracted image source manifest is malformed.")
    if any(type(page) is not int or page <= 0 for page in selected_pages):
        raise ValueError("Extracted image selected-page identity is malformed.")
    if len(selected_pages) != len(set(selected_pages)):
        raise ValueError("Extracted image selected pages are not unique.")

    manifest_identities: list[_SourceIdentity] = []
    page_ordinals: set[tuple[int, int]] = set()
    for item in images:
        if not isinstance(item, dict):
            raise ValueError("Extracted image source manifest is malformed.")
        identity = _manifest_identity(item)
        page_ordinal = identity[:2]
        if page_ordinal in page_ordinals:
            raise ValueError("Extracted image page traversal identity is not unique.")
        page_ordinals.add(page_ordinal)
        manifest_identities.append(identity)

    occurrences = _fresh_source_occurrences(model, selected_pages)
    if manifest_identities != [occurrence.identity for occurrence in occurrences]:
        raise ValueError("Extracted image identities do not cover the source traversal.")

    inline_count = 0
    for item, occurrence in zip(images, occurrences):
        if (
            item.get("source") != occurrence.source_kind
            or item.get("object") != occurrence.object_number
        ):
            raise ValueError("Extracted image source occurrence differs from its manifest.")
        if occurrence.source_kind == "inline":
            _verify_inline_occurrence(item, occurrence)
            inline_count += 1
    return {"images": len(occurrences), "inline_images": inline_count}


def verify_inline_source_semantics(
    model: PdfObjectModel,
    item: dict[str, Any],
) -> None:
    """Locate one inline image and bind its manifest to fresh source decoding."""
    identity = _manifest_identity(item)
    if item.get("source") != "inline":
        raise ValueError("Extracted inline image source identity is malformed.")
    occurrences = _fresh_source_occurrences(model, [identity[0]])
    candidates = [
        occurrence
        for occurrence in occurrences
        if occurrence.identity == identity and occurrence.source_kind == "inline"
    ]
    if len(candidates) != 1:
        raise ValueError("Extracted inline image source identity is not unique.")
    _verify_inline_occurrence(item, candidates[0])


def _manifest_identity(item: dict[str, Any]) -> _SourceIdentity:
    page_number = item.get("page")
    page_image_index = item.get("page_image_index")
    inline_index = item.get("inline_index")
    resource = item.get("resource")
    source_kind = item.get("source")
    object_number = item.get("object")
    if (
        type(page_number) is not int
        or page_number <= 0
        or type(page_image_index) is not int
        or page_image_index <= 0
        or (resource is not None and not isinstance(resource, str))
        or source_kind not in {"inline", "xobject"}
    ):
        raise ValueError("Extracted image source identity is malformed.")
    if source_kind == "inline":
        if (
            type(inline_index) is not int
            or inline_index <= 0
            or object_number is not None
        ):
            raise ValueError("Extracted inline image source identity is malformed.")
    elif inline_index is not None or type(object_number) is not int or object_number <= 0:
        raise ValueError("Extracted XObject image source identity is malformed.")
    return page_number, page_image_index, inline_index, resource


def _fresh_source_occurrences(
    model: PdfObjectModel,
    selected_pages: list[int],
) -> list[_SourceOccurrence]:
    pages = {page.page_number: page for page in walk_pages(model)}
    missing = [page_number for page_number in selected_pages if page_number not in pages]
    if missing:
        raise ValueError("Extracted image source page is missing.")

    limits = PdfByteLimits()
    image_budget = ImageExtractionBudget(
        max_images=MAX_EXTRACTED_IMAGES,
        max_output_bytes=MAX_EXTRACTED_TOTAL_BYTES,
        max_pixels=MAX_TOTAL_IMAGE_PIXELS,
    )
    occurrences: list[_SourceOccurrence] = []
    page_image_counts: dict[int, int] = {}

    def add_extracted(extracted: ExtractedImage, **metadata: Any) -> None:
        if not metadata.get("pre_reserved", False):
            image_budget.reserve_image(extracted.width, extracted.height)
        image_budget.add_output_bytes(len(extracted.payload))
        page_number = metadata["page_number"]
        page_image_index = page_image_counts.get(page_number, 0) + 1
        page_image_counts[page_number] = page_image_index
        source_kind = metadata["source_kind"]
        inline_index = metadata.get("inline_index") if source_kind == "inline" else None
        occurrences.append(_SourceOccurrence(
            identity=(
                page_number,
                page_image_index,
                inline_index,
                metadata.get("resource"),
            ),
            source_kind=source_kind,
            object_number=metadata.get("object_number"),
            extracted=extracted,
            bbox=list(metadata["bbox"]),
        ))

    from .images_extract import _TraversalBudget, _walk_content_images

    for page_number in selected_pages:
        page = pages[page_number]
        content = extract_content_stream(model, page.contents, page_number, limits)
        _walk_content_images(
            model,
            content,
            page=page,
            resources=page.resources,
            add_extracted=add_extracted,
            budget=_TraversalBudget(),
            image_budget=image_budget,
        )
    return occurrences


def _verify_inline_occurrence(
    item: dict[str, Any],
    occurrence: _SourceOccurrence,
) -> None:
    expected = occurrence.extracted
    expected_decode = list(expected.decode) if expected.decode is not None else None
    expected_fields = {
        "format": expected.format,
        "object": None,
        "bbox": occurrence.bbox,
        "width": expected.width,
        "height": expected.height,
        "bits_per_component": expected.bits_per_component,
        "color_space": expected.color_space,
        "filter_chain": expected.filter_chain,
        "soft_mask": expected.soft_mask,
        "decode": expected_decode,
        "source_object_sha256": None,
        "pixel_sha256": expected.pixel_sha256,
        "sha256": hashlib.sha256(expected.payload).hexdigest(),
    }
    if any(item.get(key) != value for key, value in expected_fields.items()):
        raise ValueError("Extracted inline image differs from its source semantics.")
