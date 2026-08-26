"""Text watermark emission with an effective ExtGState opacity resource.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
import math
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .create_images import image_placement
from .image_assets import (
    ImageAsset,
    load_image_asset,
)
from .mutation_writer import write_pdf_mutation
from .object_model import PdfObjectModel, parse_pdf
from .page_tree import walk_pages
from .watermark_layout import (
    image_box_origin,
    image_matrix,
    rgb_operator,
    transformed_unit_bbox,
    watermark_origin,
    watermark_rotation,
)
from .watermark_fonts import plan_watermark_font
from .watermark_objects import (
    allocate_watermark_content_objects,
    reopened_image_evidence,
    reopened_use_evidence,
    watermark_image_objects,
)
from .watermark_resources import (
    WatermarkResourceRewriter,
    plan_watermark_graphics_state,
    plan_watermark_image_resource,
)


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
    graphics_state_resource = plan_watermark_graphics_state(
        model,
        selected_pages,
    )
    changed: set[int] = set()
    added_objects: dict[int, bytes] = {}
    image_asset = None
    image_object = None
    image_resource = None
    font_resource = None
    font_object = None
    image_request = primitive.get("image")
    if image_request is not None:
        image_asset = load_image_asset(image_request)
        image_resource = plan_watermark_image_resource(model, selected_pages)
        image_object, added_objects = watermark_image_objects(
            model,
            image_asset,
            image_request.get("alt"),
        )
    else:
        font_plan = plan_watermark_font(
            model,
            selected_pages,
            primitive.get("font", "Helvetica"),
            added_objects,
        )
        font_resource = font_plan.resource_name
        font_object = font_plan.object_number
    content_additions, use_evidence = _content_additions(
        selected_pages,
        primitive,
        image_asset=image_asset,
        image_resource=image_resource,
        font_resource=font_resource,
        graphics_state_resource=graphics_state_resource,
    )
    content_objects = allocate_watermark_content_objects(
        model,
        content_additions,
        added_objects,
    )
    output_bytes = _copy_with_watermark(
        model,
        content_objects,
        page_objects,
        primitive["opacity"],
        image_object,
        added_objects,
        changed,
        graphics_state_resource,
        image_resource,
        font_resource,
        font_object,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)

    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    use_evidence = reopened_use_evidence(
        output_model,
        use_evidence,
        content_objects,
        graphics_state_resource=graphics_state_resource,
        image_resource=image_resource,
        image_object=image_object,
        font_resource=font_resource,
    )
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
        "graphics_state": f"/{graphics_state_resource}",
        "watermark_uses": use_evidence,
        "rotation": watermark_rotation(primitive, image_asset is not None),
        "font": primitive.get("font", "Helvetica") if image_asset is None else None,
        "size": primitive.get("size", 48.0) if image_asset is None else None,
        "color": primitive.get("color", [0.7, 0.7, 0.7]) if image_asset is None else None,
        "position": primitive.get("position", "center"),
        "preservation": manifest,
    }
    if image_asset is not None:
        image_semantics = reopened_image_evidence(output_model, image_object)
        result["image"] = {
            "resolved_path": str(image_asset.path),
            "asset_sha256": image_asset.sha256,
            "asset_bytes": image_asset.byte_count,
            "content_type": image_asset.content_type,
            "source_width": image_asset.width,
            "source_height": image_asset.height,
            "resource": f"/{image_resource}",
            **image_semantics,
            "bbox": use_evidence[0]["bbox"],
            "page_bboxes": use_evidence,
            "transcoded": image_asset.transcoded,
        }
    return result, manifest


def _content_additions(
    pages: list[Any],
    primitive: dict[str, Any],
    *,
    image_asset: ImageAsset | None,
    image_resource: str | None,
    font_resource: str | None,
    graphics_state_resource: str,
) -> tuple[dict[int, bytes], list[dict[str, Any]]]:
    additions: dict[int, bytes] = {}
    image_evidence: list[dict[str, Any]] = []
    for page in pages:
        if image_asset is None:
            escaped_text = _escape_pdf_string(primitive["text"])
            if font_resource is None:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Text watermark font planning did not produce a resource.",
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
                f"\nq\n/{graphics_state_resource} gs\n{rgb_operator(color)}\nBT\n"
                f"/{font_resource} {pdf_number(size)} Tf\n"
                f"{cosine} {sine} {negative_sine} {cosine} "
                f"{pdf_number(x)} {pdf_number(y)} Tm\n"
                f"({escaped_text}) Tj\nET\nQ\n"
            )
        else:
            if image_resource is None:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Image watermark resource planning did not produce a resource.",
                )
            image = primitive["image"]
            box_left, box_bottom = image_box_origin(
                page,
                primitive.get("position", "center"),
                width=image["width"],
                height=image["height"],
            )
            placement = image_placement(
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
            operator_parts = ["\nq", f"/{graphics_state_resource} gs"]
            if image["fit"] == "cover":
                box = placement["box"]
                operator_parts.append(
                    f"{pdf_number(box[0])} {pdf_number(box[1])} "
                    f"{pdf_number(box[2])} {pdf_number(box[3])} re W n"
                )
            operator_parts.extend(
                [
                    " ".join(pdf_number(component) for component in matrix)
                    + f" cm /{image_resource} Do",
                    "Q\n",
                ]
            )
            operators = "\n".join(operator_parts)
            bbox = (
                placement["visible_bbox"]
                if rotation == 0.0
                else transformed_unit_bbox(matrix)
            )
        image_evidence.append({
            "page": page.page_number,
            "page_object": page.obj_num,
            "bbox": bbox if image_asset is not None else None,
        })
        additions[page.obj_num] = operators.encode("latin-1", errors="strict")
    return additions, image_evidence


def _copy_with_watermark(
    model: PdfObjectModel,
    content_objects: dict[int, int],
    page_objects: set[int],
    opacity: float,
    image_object: int | None,
    added_objects: dict[int, bytes],
    changed: set[int],
    graphics_state_resource: str,
    image_resource: str | None,
    font_resource: str | None,
    font_object: int | None,
) -> bytes:
    resource_rewriter = WatermarkResourceRewriter(
        model,
        opacity,
        image_object,
        added_objects,
        graphics_state_resource,
        image_resource,
        font_resource,
        font_object,
    )
    mutations = {
        obj_num: resource_rewriter.rewrite_page(
            obj_num,
            content_objects[obj_num],
        )
        for obj_num in sorted(page_objects)
    }
    changed.update(mutations)
    return write_pdf_mutation(model, mutations, added_objects, set())


def _escape_pdf_string(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
