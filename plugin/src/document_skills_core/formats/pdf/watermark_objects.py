"""Dedicated PDF objects and evidence for watermark mutations."""

import hashlib
from typing import Any

from .image_assets import ImageAsset, image_xobject_dictionary, soft_mask_dictionary
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import walk_pages
from .watermark_resource_scan import font_resource_record, strict_indirect_object


def allocate_watermark_content_objects(
    model: PdfObjectModel,
    additions: dict[int, bytes],
    added_objects: dict[int, bytes],
) -> dict[int, int]:
    """Allocate one new content stream for every targeted page object."""
    objects: dict[int, int] = {}
    for page_object, operators in additions.items():
        object_number = _next_object_number(model, added_objects)
        added_objects[object_number] = stream_object_payload(
            object_number,
            f"<< /Length {len(operators)} >>".encode("ascii"),
            operators,
        )
        objects[page_object] = object_number
    return objects


def watermark_image_objects(
    model: PdfObjectModel,
    asset: ImageAsset,
    alt: str | None,
) -> tuple[int, dict[int, bytes]]:
    """Allocate a closed image XObject and its optional alpha mask."""
    next_object = max(max(model.objects), model.trailer.size - 1) + 1
    objects: dict[int, bytes] = {}
    soft_mask_object = None
    if asset.alpha_data is not None:
        soft_mask_object = next_object
        objects[soft_mask_object] = watermark_soft_mask_object_payload(
            soft_mask_object,
            asset,
        )
        next_object += 1
    image_object = next_object
    objects[image_object] = watermark_image_object_payload(
        image_object,
        asset,
        alt,
        soft_mask_object,
    )
    return image_object, objects


def watermark_image_object_payload(
    object_number: int,
    asset: ImageAsset,
    alt: str | None,
    soft_mask_object: int | None,
) -> bytes:
    """Build the exact main image object payload for one watermark asset."""
    image_dictionary = image_xobject_dictionary(
        asset,
        stream_length=len(asset.image_data),
        soft_mask_object=soft_mask_object,
        alt=alt,
    )
    image_dictionary = (
        image_dictionary[:-2]
        + f" /DSAssetSHA256 ({asset.sha256}) >>".encode("ascii")
    )
    return stream_object_payload(
        object_number,
        image_dictionary,
        asset.image_data,
    )


def watermark_soft_mask_object_payload(
    object_number: int,
    asset: ImageAsset,
) -> bytes:
    """Build the exact grayscale soft-mask object payload."""
    if asset.alpha_data is None:
        raise ValueError("The image asset has no alpha channel.")
    return stream_object_payload(
        object_number,
        soft_mask_dictionary(asset),
        asset.alpha_data,
    )


def reopened_use_evidence(
    model: PdfObjectModel,
    uses: list[dict[str, Any]],
    content_objects: dict[int, int],
    *,
    graphics_state_resource: str,
    image_resource: str | None,
    image_object: int | None,
    font_resource: str | None,
) -> list[dict[str, Any]]:
    """Bind writer evidence to hashes reopened from the staged candidate."""
    image = model.objects.get(image_object) if image_object is not None else None
    stream = image.value[1] if image is not None and isinstance(image.value, tuple) else None
    pages = walk_pages(model)
    records: list[dict[str, Any]] = []
    for use in uses:
        content_object = content_objects[use["page_object"]]
        content = model.objects[content_object]
        content_stream = (
            content.value[1] if isinstance(content.value, tuple) else None
        )
        content_dictionary = (
            content.value[0] if isinstance(content.value, tuple) else None
        )
        if content_stream is None or not isinstance(content_dictionary, PdfDict):
            raise ValueError("Watermark content object is not a stream.")
        font = font_resource_record(
            model,
            pages[use["page"] - 1],
            f"/{font_resource}" if font_resource is not None else None,
        )
        record = {
            **use,
            "content_object": content_object,
            "content_object_generation": content.gen_num,
            "content_object_sha256": content.sha256,
            "content_stream_sha256": hashlib.sha256(content_stream).hexdigest(),
            "content_keys": sorted(content_dictionary.entries),
            "content_length": content_dictionary.get("/Length"),
            "content_filter": content_dictionary.get("/Filter"),
            "content_decode_parms": _decode_parms_evidence(
                content_dictionary.get("/DecodeParms")
            ),
            "graphics_state": f"/{graphics_state_resource}",
            "font_resource": f"/{font_resource}" if font_resource is not None else None,
            "font_object": font.object_number if font is not None else None,
            "font_object_generation": (
                font.object_generation if font is not None else None
            ),
            "font_object_sha256": font.object_sha256 if font is not None else None,
            "image_resource": f"/{image_resource}" if image_resource is not None else None,
            "image_object": image_object,
        }
        record.pop("page_object")
        if stream is not None:
            record["stream_sha256"] = hashlib.sha256(stream).hexdigest()
        records.append(record)
    return records


def reopened_image_evidence(
    model: PdfObjectModel,
    image_object: int,
) -> dict[str, Any]:
    """Return JSON-safe dictionary semantics reopened from the staged image."""
    obj = model.objects[image_object]
    if not isinstance(obj.value, tuple):
        raise ValueError("Watermark image object is not a stream.")
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        raise ValueError("Watermark image stream has no dictionary.")
    return {
        "image_object": image_object,
        "image_object_generation": obj.gen_num,
        "image_object_sha256": obj.sha256,
        "keys": sorted(dictionary.entries),
        "type": dictionary.get("/Type"),
        "subtype": dictionary.get("/Subtype"),
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
        "width": dictionary.get("/Width"),
        "height": dictionary.get("/Height"),
        "color_space": dictionary.get("/ColorSpace"),
        "bits_per_component": dictionary.get("/BitsPerComponent"),
        "filter": dictionary.get("/Filter"),
        "decode": dictionary.get("/Decode"),
        "decode_parms": _decode_parms_evidence(dictionary.get("/DecodeParms")),
        "length": dictionary.get("/Length"),
        "alt": dictionary.get("/Alt"),
        "soft_mask": _soft_mask_evidence(model, dictionary.get("/SMask")),
    }


def stream_object_payload(
    obj_num: int,
    dictionary: bytes,
    stream_data: bytes,
) -> bytes:
    return (
        f"{obj_num} 0 obj\n".encode("ascii")
        + dictionary
        + b"\nstream\n"
        + stream_data
        + b"\nendstream\nendobj"
    )


def _next_object_number(
    model: PdfObjectModel,
    added_objects: dict[int, bytes],
) -> int:
    occupied = set(model.objects) | set(added_objects) | {model.trailer.size - 1}
    return max(occupied) + 1


def _soft_mask_evidence(model: PdfObjectModel, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, IndirectReference):
        return {"indirect": False}
    obj = strict_indirect_object(model, value)
    if obj is None:
        return {"indirect": False}
    if not isinstance(obj.value, tuple):
        return {
            "indirect": True,
            "object": obj.obj_num,
            "object_generation": obj.gen_num,
        }
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        return {
            "indirect": True,
            "object": obj.obj_num,
            "object_generation": obj.gen_num,
        }
    return {
        "indirect": True,
        "object": obj.obj_num,
        "object_generation": obj.gen_num,
        "object_sha256": obj.sha256,
        "keys": sorted(dictionary.entries),
        "type": dictionary.get("/Type"),
        "subtype": dictionary.get("/Subtype"),
        "width": dictionary.get("/Width"),
        "height": dictionary.get("/Height"),
        "color_space": dictionary.get("/ColorSpace"),
        "bits_per_component": dictionary.get("/BitsPerComponent"),
        "filter": dictionary.get("/Filter"),
        "decode": dictionary.get("/Decode"),
        "decode_parms": _decode_parms_evidence(dictionary.get("/DecodeParms")),
        "length": dictionary.get("/Length"),
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
    }


def _decode_parms_evidence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, PdfDict):
        raise ValueError("Watermark DecodeParms is not a dictionary.")
    return dict(value.entries)
