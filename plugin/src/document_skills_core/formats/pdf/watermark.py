"""Text watermark emission with an effective ExtGState opacity resource.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
import math
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .create import _image_placement
from .image_assets import (
    ImageAsset,
    image_xobject_dictionary,
    load_image_asset,
    soft_mask_dictionary,
)
from .object_model import PdfObjectModel, parse_pdf
from .page_tree import walk_pages
from .trailer import trailer_bytes
from .watermark_layout import (
    image_box_origin,
    image_matrix,
    rgb_operator,
    transformed_unit_bbox,
    watermark_origin,
    watermark_rotation,
)
from .watermark_resources import WatermarkResourceRewriter


def apply_text_watermark(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a text watermark while preserving untargeted objects."""
    pages = walk_pages(model)
    target_pages = set(primitive["pages"])
    selected_pages = [page for page in pages if page.page_number in target_pages]
    if len(selected_pages) != len(target_pages):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Watermark page selection is outside the document.",
            status="invalid_request",
            details={"pages": sorted(target_pages), "page_count": len(pages)},
        )
    if any(not page.contents for page in selected_pages):
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Watermarking a page without a content stream is not implemented.",
            status="enhancement_required",
            details={"capability": "pdf.watermark-empty-page"},
        )
    page_objects = {page.obj_num for page in selected_pages}
    changed: set[int] = set()
    added_objects: dict[int, bytes] = {}
    image_asset = None
    image_object = None
    image_request = primitive.get("image")
    if image_request is not None:
        image_asset = load_image_asset(image_request)
        image_object, added_objects = _watermark_image_objects(
            model,
            image_asset,
            image_request.get("alt"),
        )
    content_additions, image_evidence = _content_additions(
        selected_pages,
        primitive,
        image_asset=image_asset,
    )
    output_bytes = _copy_with_watermark(
        model,
        content_additions,
        page_objects,
        primitive["opacity"],
        image_object,
        added_objects,
        changed,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)

    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=changed,
        added=set(added_objects),
        removed=set(),
    )
    result = {
        "primitive": "watermark",
        "text": primitive["text"],
        "pages": sorted(target_pages),
        "opacity": primitive["opacity"],
        "graphics_state": "/DSWMGS",
        "rotation": watermark_rotation(primitive, image_asset is not None),
        "font": primitive.get("font", "Helvetica") if image_asset is None else None,
        "size": primitive.get("size", 48.0) if image_asset is None else None,
        "color": primitive.get("color", [0.7, 0.7, 0.7]) if image_asset is None else None,
        "position": primitive.get("position", "center"),
        "preservation": manifest,
    }
    if image_asset is not None:
        result["image"] = {
            "resolved_path": str(image_asset.path),
            "asset_sha256": image_asset.sha256,
            "asset_bytes": image_asset.byte_count,
            "content_type": image_asset.content_type,
            "source_width": image_asset.width,
            "source_height": image_asset.height,
            "image_object": image_object,
            "bbox": image_evidence[0]["bbox"],
            "page_bboxes": image_evidence,
            "transcoded": image_asset.transcoded,
        }
    return result, manifest


def _content_additions(
    pages: list[Any],
    primitive: dict[str, Any],
    *,
    image_asset: ImageAsset | None,
) -> tuple[dict[int, bytes], list[dict[str, Any]]]:
    additions: dict[int, bytes] = {}
    image_evidence: list[dict[str, Any]] = []
    for page in pages:
        if image_asset is None:
            escaped_text = _escape_pdf_string(primitive["text"])
            font_resource = _watermark_font_resource(
                page,
                primitive.get("font", "Helvetica"),
            )
            size = primitive.get("size", 48.0)
            color = primitive.get("color", [0.7, 0.7, 0.7])
            x, y = watermark_origin(
                page,
                primitive.get("position", "center"),
                text=primitive["text"],
                size=size,
            )
            radians = math.radians(watermark_rotation(primitive, False))
            cosine = pdf_number(math.cos(radians))
            sine = pdf_number(math.sin(radians))
            negative_sine = pdf_number(-math.sin(radians))
            operators = (
                f"\nq\n/DSWMGS gs\n{rgb_operator(color)}\nBT\n"
                f"/{font_resource} {pdf_number(size)} Tf\n"
                f"{cosine} {sine} {negative_sine} {cosine} "
                f"{pdf_number(x)} {pdf_number(y)} Tm\n"
                f"({escaped_text}) Tj\nET\nQ\n"
            )
        else:
            image = primitive["image"]
            box_left, box_bottom = image_box_origin(
                page,
                primitive.get("position", "center"),
                width=image["width"],
                height=image["height"],
            )
            placement = _image_placement(
                image,
                image_asset,
                left=box_left,
                top=box_bottom + image["height"],
            )
            drawing = placement["draw"]
            rotation = watermark_rotation(primitive, True)
            if image["fit"] == "cover" and rotation != 0.0:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Rotated cover image watermarks require rotated clipping support.",
                    status="enhancement_required",
                    details={"capability": "pdf.watermark-rotated-cover"},
                )
            matrix = image_matrix(drawing, rotation)
            operator_parts = ["\nq", "/DSWMGS gs"]
            if image["fit"] == "cover":
                box = placement["box"]
                operator_parts.append(
                    f"{pdf_number(box[0])} {pdf_number(box[1])} "
                    f"{pdf_number(box[2])} {pdf_number(box[3])} re W n"
                )
            operator_parts.extend(
                [
                    " ".join(pdf_number(component) for component in matrix)
                    + " cm /DSWMImage Do",
                    "Q\n",
                ]
            )
            operators = "\n".join(operator_parts)
            bbox = (
                placement["visible_bbox"]
                if rotation == 0.0
                else transformed_unit_bbox(matrix)
            )
            image_evidence.append(
                {"page": page.page_number, "bbox": bbox}
            )
        additions[page.contents[0].obj_num] = operators.encode("latin-1", errors="strict")
    return additions, image_evidence


def _watermark_font_resource(page: Any, font: str) -> str:
    resource_name = "F1" if font == "Helvetica" else ""
    fonts = page.resources.get("/Font") if page.resources is not None else None
    if not resource_name or not hasattr(fonts, "get") or fonts.get(f"/{resource_name}") is None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Page does not expose the requested watermark font resource.",
            status="enhancement_required",
            details={"page": page.page_number, "font": font},
        )
    return resource_name


def _watermark_image_objects(
    model: PdfObjectModel,
    asset: ImageAsset,
    alt: str | None,
) -> tuple[int, dict[int, bytes]]:
    next_object = max(model.objects) + 1
    objects: dict[int, bytes] = {}
    soft_mask_object = None
    if asset.alpha_data is not None:
        soft_mask_object = next_object
        objects[soft_mask_object] = _stream_object_payload(
            soft_mask_object,
            soft_mask_dictionary(asset),
            asset.alpha_data,
        )
        next_object += 1
    image_object = next_object
    objects[image_object] = _stream_object_payload(
        image_object,
        image_xobject_dictionary(
            asset,
            stream_length=len(asset.image_data),
            soft_mask_object=soft_mask_object,
            alt=alt,
        ),
        asset.image_data,
    )
    return image_object, objects


def _stream_object_payload(
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


def _copy_with_watermark(
    model: PdfObjectModel,
    content_additions: dict[int, bytes],
    page_objects: set[int],
    opacity: float,
    image_object: int | None,
    added_objects: dict[int, bytes],
    changed: set[int],
) -> bytes:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    resource_rewriter = WatermarkResourceRewriter(
        model,
        opacity,
        image_object,
        added_objects,
    )
    for obj_num in sorted(model.objects):
        obj = model.objects[obj_num]
        payload = obj.payload_bytes
        if obj_num in page_objects:
            payload = resource_rewriter.rewrite_page(obj_num, payload)
            changed.add(obj_num)
        if obj_num in content_additions:
            payload = _append_stream_bytes(payload, content_additions[obj_num])
            changed.add(obj_num)
        offsets[obj_num] = len(header) + len(body)
        body.extend(payload + b"\n")

    for obj_num in sorted(added_objects):
        offsets[obj_num] = len(header) + len(body)
        body.extend(added_objects[obj_num] + b"\n")

    return _finish_pdf(header, body, offsets, model)


def _append_stream_bytes(payload: bytes, addition: bytes) -> bytes:
    insert_pos = payload.rfind(b"endstream")
    if insert_pos < 0:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Watermark target is not a valid content stream.",
        )
    result = payload[:insert_pos] + addition + payload[insert_pos:]
    return re.sub(
        rb"/Length\s+(\d+)",
        lambda match: f"/Length {int(match.group(1)) + len(addition)}".encode("ascii"),
        result,
        count=1,
    )


def _finish_pdf(
    header: bytes,
    body: bytearray,
    offsets: dict[int, int],
    model: PdfObjectModel,
) -> bytes:
    xref_offset = len(header) + len(body)
    max_object = max(offsets) if offsets else 0
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {max_object + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for obj_num in range(1, max_object + 1):
        xref.extend(f"{offsets.get(obj_num, 0):010d} 00000 n\r\n".encode("ascii"))
    xref.extend(trailer_bytes(model, size=max_object + 1))
    xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return header + bytes(body) + bytes(xref)


def _escape_pdf_string(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
