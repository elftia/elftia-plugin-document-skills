"""Placement and transformation helpers for PDF watermarks.

Module provenance: original Elftia-authored clean-room implementation.
"""

import math
from typing import Any

from .create_layout import pdf_number


def watermark_origin(
    page: Any,
    position: str | dict[str, float],
    *,
    text: str,
    size: float,
) -> tuple[float, float]:
    if isinstance(position, dict):
        return position["x"], position["y"]
    x0, y0, x1, y1 = page.media_box
    width = max(size, len(text) * size * 0.5)
    margin = 36.0
    positions = {
        "center": (x0 + ((x1 - x0) - width) / 2.0, y0 + (y1 - y0) / 2.0),
        "top-left": (x0 + margin, y1 - margin - size),
        "top-right": (x1 - margin - width, y1 - margin - size),
        "bottom-left": (x0 + margin, y0 + margin),
        "bottom-right": (x1 - margin - width, y0 + margin),
    }
    return positions[position]


def image_box_origin(
    page: Any,
    position: str | dict[str, float],
    *,
    width: float,
    height: float,
) -> tuple[float, float]:
    if isinstance(position, dict):
        return position["x"], position["y"]
    x0, y0, x1, y1 = page.media_box
    margin = 36.0
    positions = {
        "center": (x0 + ((x1 - x0) - width) / 2.0, y0 + ((y1 - y0) - height) / 2.0),
        "top-left": (x0 + margin, y1 - margin - height),
        "top-right": (x1 - margin - width, y1 - margin - height),
        "bottom-left": (x0 + margin, y0 + margin),
        "bottom-right": (x1 - margin - width, y0 + margin),
    }
    return positions[position]


def image_matrix(drawing: list[float], rotation: float) -> list[float]:
    radians = math.radians(rotation)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    draw_left, draw_bottom, draw_width, draw_height = drawing
    return [
        draw_width * cosine,
        draw_width * sine,
        -draw_height * sine,
        draw_height * cosine,
        draw_left,
        draw_bottom,
    ]


def transformed_unit_bbox(matrix: list[float]) -> list[float]:
    a, b, c, d, e, f = matrix
    corners = [
        (e, f),
        (a + e, b + f),
        (c + e, d + f),
        (a + c + e, b + d + f),
    ]
    return [
        round(min(x for x, _ in corners), 4),
        round(min(y for _, y in corners), 4),
        round(max(x for x, _ in corners), 4),
        round(max(y for _, y in corners), 4),
    ]


def rgb_operator(color: list[float]) -> str:
    return " ".join(pdf_number(component) for component in color) + " rg"


def watermark_rotation(primitive: dict[str, Any], is_image: bool) -> float:
    return primitive.get("rotation", 0.0 if is_image else 45.0)
