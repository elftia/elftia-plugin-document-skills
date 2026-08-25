"""Image embedding and placement helpers for PDF creation."""

from typing import Any, Protocol

from .image_assets import (
    ImageAsset,
    image_xobject_dictionary,
    load_image_asset,
    soft_mask_dictionary,
)


class ImageObjectWriter(Protocol):
    def add_stream_object(self, dictionary: bytes, stream_data: bytes) -> int: ...


def embed_image(
    writer: ImageObjectWriter,
    asset: ImageAsset,
    alt: str | None,
) -> int:
    soft_mask_object = None
    if asset.alpha_data is not None:
        soft_mask_object = writer.add_stream_object(
            soft_mask_dictionary(asset),
            asset.alpha_data,
        )
    dictionary = image_xobject_dictionary(
        asset,
        stream_length=len(asset.image_data),
        soft_mask_object=soft_mask_object,
        alt=alt,
    )
    return writer.add_stream_object(dictionary, asset.image_data)


def image_placement(
    image: dict[str, Any],
    asset: ImageAsset,
    *,
    left: float,
    top: float,
) -> dict[str, list[float]]:
    box_width = image["width"]
    box_height = image["height"]
    box_bottom = top - box_height
    if image["fit"] == "stretch":
        draw_width = box_width
        draw_height = box_height
    else:
        scale_x = box_width / asset.width
        scale_y = box_height / asset.height
        scale = min(scale_x, scale_y) if image["fit"] == "contain" else max(scale_x, scale_y)
        draw_width = asset.width * scale
        draw_height = asset.height * scale
    draw_left = left + (box_width - draw_width) / 2.0
    draw_bottom = box_bottom + (box_height - draw_height) / 2.0
    box = [left, box_bottom, box_width, box_height]
    draw = [draw_left, draw_bottom, draw_width, draw_height]
    if image["fit"] == "contain":
        visible_bbox = [
            draw_left,
            draw_bottom,
            draw_left + draw_width,
            draw_bottom + draw_height,
        ]
    else:
        visible_bbox = [left, box_bottom, left + box_width, top]
    return {
        "box": _round_values(box),
        "draw": _round_values(draw),
        "visible_bbox": _round_values(visible_bbox),
    }


def build_created_image(
    writer: ImageObjectWriter,
    image: dict[str, Any],
    *,
    page_number: int,
    block_index: int,
    resource_name: str,
    left: float,
    top: float,
    mcid: int | None,
    struct_parent: int | None,
) -> tuple[list[str], int, dict[str, Any]]:
    """Embed and draw one image while retaining exact create evidence."""
    asset = load_image_asset(image)
    image_object = embed_image(writer, asset, image.get("alt"))
    placement = image_placement(image, asset, left=left, top=top)
    operators = ["%DS-BLOCK:image"]
    if mcid is not None:
        if struct_parent is None:
            raise ValueError("Tagged image page is missing StructParents")
        operators.append(f"/Figure << /MCID {mcid} >> BDC")
    operators.append("q")
    if image["fit"] == "cover":
        box = placement["box"]
        operators.append(f"{box[0]} {box[1]} {box[2]} {box[3]} re W n")
    draw = placement["draw"]
    operators.extend([
        f"{draw[2]} 0 0 {draw[3]} {draw[0]} {draw[1]} cm /{resource_name} Do",
        "Q",
    ])
    if mcid is not None:
        operators.append("EMC")
    return operators, image_object, {
        "page": page_number,
        "block_index": block_index,
        "resolved_path": str(asset.path),
        "asset_sha256": asset.sha256,
        "asset_bytes": asset.byte_count,
        "content_type": asset.content_type,
        "source_width": asset.width,
        "source_height": asset.height,
        "image_object": image_object,
        "bbox": placement["visible_bbox"],
        "transcoded": asset.transcoded,
        "alt": image.get("alt"),
        "mcid": mcid,
        "struct_parent": struct_parent if mcid is not None else None,
        "structure_object": None,
    }


def _round_values(values: list[float]) -> list[float]:
    return [round(value, 4) for value in values]
