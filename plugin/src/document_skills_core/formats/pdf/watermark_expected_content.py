"""Request-derived canonical content for PDF watermark promotion."""

import hashlib
import math
from typing import Any

from .create_images import image_placement
from .create_layout import pdf_number
from .image_assets import ImageAsset
from .watermark_layout import (
    image_box_origin,
    image_matrix,
    rgb_operator,
    watermark_origin,
    watermark_rotation,
)


def expected_content_evidence(
    page: Any,
    primitive: dict[str, Any],
    *,
    asset: ImageAsset | None,
    graphics_state: str,
    font_resource: str | None,
    image_resource: str | None,
) -> tuple[str, int]:
    """Hash and size independently reconstructed dedicated stream bytes."""
    content = expected_content_bytes(
        page,
        primitive,
        asset=asset,
        graphics_state=graphics_state,
        font_resource=font_resource,
        image_resource=image_resource,
    )
    return hashlib.sha256(content).hexdigest(), len(content)


def expected_content_bytes(
    page: Any,
    primitive: dict[str, Any],
    *,
    asset: ImageAsset | None,
    graphics_state: str,
    font_resource: str | None,
    image_resource: str | None,
) -> bytes:
    """Reconstruct the exact dedicated stream bytes from the request."""
    return (
        _image_content(page, primitive, asset, graphics_state, image_resource)
        if asset is not None
        else _text_content(page, primitive, graphics_state, font_resource)
    )


def _text_content(
    page: Any,
    primitive: dict[str, Any],
    graphics_state: str,
    font_resource: str | None,
) -> bytes:
    if font_resource is None:
        raise ValueError("Text watermark expectation has no font resource.")
    text = primitive["text"]
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    size = primitive.get("size", 48.0)
    x, y = watermark_origin(
        page,
        primitive.get("position", "center"),
        text=text,
        size=size,
    )
    radians = math.radians(watermark_rotation(primitive, False))
    cosine = pdf_number(math.cos(radians))
    sine = pdf_number(math.sin(radians))
    negative_sine = pdf_number(-math.sin(radians))
    content = (
        f"\nq\n{graphics_state} gs\n"
        f"{rgb_operator(primitive.get('color', [0.7, 0.7, 0.7]))}\nBT\n"
        f"{font_resource} {pdf_number(size)} Tf\n"
        f"{cosine} {sine} {negative_sine} {cosine} "
        f"{pdf_number(x)} {pdf_number(y)} Tm\n"
        f"({escaped}) Tj\nET\nQ\n"
    )
    return content.encode("latin-1", errors="strict")


def _image_content(
    page: Any,
    primitive: dict[str, Any],
    asset: ImageAsset,
    graphics_state: str,
    image_resource: str | None,
) -> bytes:
    if image_resource is None:
        raise ValueError("Image watermark expectation has no image resource.")
    image = primitive["image"]
    left, bottom = image_box_origin(
        page,
        primitive.get("position", "center"),
        width=image["width"],
        height=image["height"],
    )
    placement = image_placement(
        image,
        asset,
        left=left,
        top=bottom + image["height"],
    )
    matrix = image_matrix(
        placement["draw"],
        watermark_rotation(primitive, True),
    )
    parts = ["\nq", f"{graphics_state} gs"]
    if image["fit"] == "cover":
        box = placement["box"]
        parts.append(
            f"{pdf_number(box[0])} {pdf_number(box[1])} "
            f"{pdf_number(box[2])} {pdf_number(box[3])} re W n"
        )
    parts.extend([
        " ".join(pdf_number(component) for component in matrix)
        + f" cm {image_resource} Do",
        "Q\n",
    ])
    return "\n".join(parts).encode("latin-1", errors="strict")
