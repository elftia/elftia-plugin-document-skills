"""Candidate-derived image draw and asset-binding validation for PDF create."""

import hashlib
from pathlib import Path
import re
from typing import Any

from .byte_preflight import decode_stream
from .content_streams import extract_content_stream
from .content_tokenizer import tokenize_content_stream
from .create_image_structure import image_structure_mismatches
from .image_assets import ImageAsset, load_image_asset
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .xobject_draws import (
    AffineMatrix,
    concatenate_matrix,
    IDENTITY_MATRIX,
    unit_square_bbox,
)

_TOLERANCE = 0.02


def actual_image_draws(
    model: PdfObjectModel,
    pages: list[PageInfo],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in pages:
        resources = page.resources
        xobjects = resources.get("/XObject") if resources is not None else None
        if isinstance(xobjects, IndirectReference):
            xobjects = model.get_object(xobjects).value
        if not isinstance(xobjects, PdfDict):
            continue
        content = extract_content_stream(model, page.contents, page.page_number)
        draws = _visible_xobject_draws(content)
        for draw in draws:
            reference = xobjects.get(draw["resource"])
            if not isinstance(reference, IndirectReference):
                continue
            obj = model.get_object(reference)
            if not isinstance(obj.value, tuple):
                continue
            dictionary, stream = obj.value
            if not isinstance(dictionary, PdfDict) or dictionary.get("/Subtype") != "/Image":
                continue
            records.append({
                "page": page.page_number,
                "resource": draw["resource"],
                "object": obj.obj_num,
                "bbox": list(draw["bbox"]),
                "visible_bbox": list(draw["visible_bbox"]),
                "width": dictionary.get("/Width"),
                "height": dictionary.get("/Height"),
                "color_space": dictionary.get("/ColorSpace"),
                "stream": stream,
                "object_sha256": obj.sha256,
                "mcid": draw["mcid"],
                "soft_mask": _soft_mask_record(
                    model,
                    dictionary.get("/SMask"),
                ),
            })
    return records


def image_evidence_mismatches(
    document: dict[str, Any],
    creation: dict[str, Any] | None,
    actual: list[dict[str, Any]],
    model: PdfObjectModel,
    pages: list[PageInfo],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    image_records = (creation or {}).get("images")
    if not isinstance(image_records, list):
        return [], [_public_image_record(record) for record in actual]
    expected, binding_mismatches = _bind_structure_evidence(
        image_records,
        (creation or {}).get("image_structure"),
    )
    requested_assets = _requested_image_assets(document)
    structure_mismatches, structure_evidence = image_structure_mismatches(
        model,
        pages,
        expected,
        actual,
    )
    mismatches = binding_mismatches + structure_mismatches
    evidence: list[dict[str, Any]] = []
    for record in expected:
        identity = (
            str(Path(record["resolved_path"]).resolve()),
            record["asset_sha256"],
            record["content_type"],
            record.get("alt"),
        )
        if identity not in requested_assets:
            mismatches.append({"reason": "unbound-creation-image", "image": identity})
            continue
        asset = load_image_asset({
            "filename": record["resolved_path"],
            "sha256": record["asset_sha256"],
            "content_type": record["content_type"],
        })
        expected_stream = decode_stream(asset.image_data, [asset.filter_name])
        candidate = next(
            (
                item
                for item in actual
                if item["page"] == record["page"]
                and item["object"] == record["image_object"]
                and _bbox_matches(item["visible_bbox"], record["bbox"])
            ),
            None,
        )
        if candidate is None:
            mismatches.append({
                "reason": "missing-image-draw",
                "object": record["image_object"],
            })
            continue
        if (
            candidate["stream"] != expected_stream
            or candidate["width"] != asset.width
            or candidate["height"] != asset.height
            or candidate["color_space"] != asset.color_space
        ):
            mismatches.append({
                "reason": "image-object-mismatch",
                "object": record["image_object"],
            })
            continue
        soft_mask_mismatch, soft_mask_evidence = _soft_mask_mismatch(
            candidate.get("soft_mask"),
            asset,
        )
        if soft_mask_mismatch is not None:
            mismatches.append({
                "reason": soft_mask_mismatch,
                "object": record["image_object"],
            })
            continue
        image_evidence = {
            **_public_image_record(candidate),
            "asset_sha256": asset.sha256,
            "stream_sha256": hashlib.sha256(candidate["stream"]).hexdigest(),
            "visible_bbox": candidate["visible_bbox"],
            "alt": record.get("alt"),
            "mcid": candidate.get("mcid"),
            "struct_parent": record.get("struct_parent"),
            "structure_object": record.get("structure_object"),
        }
        association = structure_evidence.get(
            (candidate["page"], candidate.get("mcid"))
        )
        if association is not None:
            image_evidence.update(association)
        if soft_mask_evidence is not None:
            image_evidence.update(soft_mask_evidence)
        evidence.append(image_evidence)
    return mismatches, evidence


def _bind_structure_evidence(
    images: list[dict[str, Any]],
    associations: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(associations, list):
        return images, [{"reason": "missing-image-structure-evidence"}]
    index: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    valid = len(associations) == len(images)
    for record in associations:
        if not isinstance(record, dict):
            valid = False
            continue
        key = (record.get("page"), record.get("block_index"), record.get("image_object"))
        if key in index:
            valid = False
        index[key] = record
    enriched: list[dict[str, Any]] = []
    for image in images:
        key = (image.get("page"), image.get("block_index"), image.get("image_object"))
        association = index.get(key)
        if association is None or association.get("bbox") != image.get("bbox"):
            valid = False
            association = {}
        enriched.append({
            **image,
            **{
                field: association.get(field)
                for field in ("alt", "mcid", "struct_parent", "structure_object")
            },
        })
    return enriched, ([] if valid else [{"reason": "invalid-image-structure-evidence"}])


def _soft_mask_record(
    model: PdfObjectModel,
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, IndirectReference):
        return {"indirect": False}
    obj = model.get_object(value)
    if not isinstance(obj.value, tuple):
        return {"indirect": True, "object": obj.obj_num, "stream": None}
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        return {"indirect": True, "object": obj.obj_num, "stream": None}
    return {
        "indirect": True,
        "object": obj.obj_num,
        "object_sha256": obj.sha256,
        "type": dictionary.get("/Type"),
        "subtype": dictionary.get("/Subtype"),
        "width": dictionary.get("/Width"),
        "height": dictionary.get("/Height"),
        "color_space": dictionary.get("/ColorSpace"),
        "bits_per_component": dictionary.get("/BitsPerComponent"),
        "filter": dictionary.get("/Filter"),
        "stream": stream,
    }


def _soft_mask_mismatch(
    candidate: dict[str, Any] | None,
    asset: ImageAsset,
) -> tuple[str | None, dict[str, Any] | None]:
    if asset.alpha_data is None:
        return (
            ("unexpected-soft-mask" if candidate is not None else None),
            None,
        )
    if candidate is None:
        return "missing-soft-mask", None
    expected_alpha = decode_stream(asset.alpha_data, ["/FlateDecode"])
    if not candidate.get("indirect"):
        return "soft-mask-not-indirect", None
    if (
        candidate.get("type") != "/XObject"
        or candidate.get("subtype") != "/Image"
        or candidate.get("width") != asset.width
        or candidate.get("height") != asset.height
        or candidate.get("color_space") != "/DeviceGray"
        or candidate.get("bits_per_component") != 8
        or candidate.get("filter") != "/FlateDecode"
        or candidate.get("stream") != expected_alpha
    ):
        return "soft-mask-mismatch", None
    alpha_sha256 = hashlib.sha256(candidate["stream"]).hexdigest()
    return None, {
        "soft_mask_object": candidate["object"],
        "soft_mask_object_sha256": candidate["object_sha256"],
        "alpha_sha256": alpha_sha256,
    }


def _requested_image_assets(
    document: dict[str, Any],
) -> set[tuple[str, str, str, str | None]]:
    return {
        (
            str(Path(image["filename"]).resolve()),
            image["sha256"],
            image["content_type"],
            image.get("alt"),
        )
        for page in document.get("pages", [])
        for block in page.get("blocks", [])
        if block.get("type") == "image"
        for image in [block["image"]]
    }


def _public_image_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("page", "resource", "object", "bbox", "object_sha256")
    }


def _bbox_matches(actual: list[float], expected: list[float]) -> bool:
    return len(actual) == len(expected) == 4 and all(
        abs(float(left) - float(right)) <= _TOLERANCE
        for left, right in zip(actual, expected)
    )


def _visible_xobject_draws(content: bytes) -> list[dict[str, Any]]:
    """Return XObject draw boxes after candidate-derived rectangle clipping."""
    current = IDENTITY_MATRIX
    clip: tuple[float, float, float, float] | None = None
    stack: list[tuple[AffineMatrix, tuple[float, float, float, float] | None]] = []
    path_bbox: tuple[float, float, float, float] | None = None
    clip_pending = False
    marked_stack: list[tuple[str | None, int | None]] = []
    inline_properties = iter(_inline_marked_content_properties(content))
    draws: list[dict[str, Any]] = []
    for operator, operands in tokenize_content_stream(content):
        if operator == "BDC":
            tag = operands[-2] if len(operands) >= 2 else None
            properties = operands[-1] if operands else None
            mcid = (
                next(inline_properties, None)
                if isinstance(properties, dict)
                else None
            )
            marked_stack.append((tag if isinstance(tag, str) else None, mcid))
        elif operator == "BMC":
            tag = operands[-1] if operands else None
            marked_stack.append((tag if isinstance(tag, str) else None, None))
        elif operator == "EMC":
            if marked_stack:
                marked_stack.pop()
        elif operator == "q":
            stack.append((current, clip))
        elif operator == "Q":
            current, clip = stack.pop() if stack else (IDENTITY_MATRIX, None)
            path_bbox = None
            clip_pending = False
        elif operator == "cm" and len(operands) >= 6:
            try:
                matrix = tuple(float(value) for value in operands[-6:])
            except (TypeError, ValueError):
                continue
            current = concatenate_matrix(matrix, current)
        elif operator == "re" and len(operands) >= 4:
            try:
                x, y, width, height = (float(value) for value in operands[-4:])
            except (TypeError, ValueError):
                path_bbox = None
                continue
            rectangle = (width, 0.0, 0.0, height, x, y)
            path_bbox = unit_square_bbox(concatenate_matrix(rectangle, current))
        elif operator in {"W", "W*"}:
            clip_pending = True
        elif operator in {"n", "S", "s", "f", "F", "f*", "B", "b"}:
            if clip_pending and path_bbox is not None:
                clip = _intersect_bbox(clip, path_bbox)
            path_bbox = None
            clip_pending = False
        elif operator == "Do" and operands and isinstance(operands[-1], str):
            resource = operands[-1]
            if not resource.startswith("/"):
                continue
            bbox = unit_square_bbox(current)
            visible_bbox = _intersect_bbox(clip, bbox) if clip is not None else bbox
            if visible_bbox is not None:
                draws.append({
                    "resource": resource,
                    "bbox": bbox,
                    "visible_bbox": visible_bbox,
                    "mcid": next(
                        (
                            mcid
                            for tag, mcid in reversed(marked_stack)
                            if tag == "/Figure"
                        ),
                        None,
                    ),
                })
    return draws


def _inline_marked_content_properties(content: bytes) -> list[int | None]:
    properties: list[int | None] = []
    for match in re.finditer(rb"<<(.*?)>>\s*BDC", content, flags=re.DOTALL):
        mcid = re.search(rb"(?:^|\s)/MCID\s+([0-9]+)(?:\s|$)", match.group(1))
        properties.append(int(mcid.group(1)) if mcid is not None else None)
    return properties


def _intersect_bbox(
    left: tuple[float, float, float, float] | None,
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    if left is None:
        return right
    intersection = (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )
    if intersection[0] >= intersection[2] or intersection[1] >= intersection[3]:
        return None
    return intersection
