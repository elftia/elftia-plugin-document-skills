"""Candidate-derived layout bounds for exact PDF text rewrites."""

from __future__ import annotations

import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError

from .base14_metrics import base14_text_width
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .rewrite_font_encoding import decode_text_for_font, resolve_font_dictionary

TextMatrix = tuple[float, float, float, float, float, float]
Rectangle = tuple[float, float, float, float]


def text_bbox_for_font(
    model: PdfObjectModel,
    page: PageInfo,
    font_name: str,
    encoded: bytes,
    font_size: float,
    text_matrix: TextMatrix,
) -> Rectangle | None:
    """Compute a conservative visible bbox from actual font bytes and metrics."""
    advance = text_advance_for_font(
        model,
        page,
        font_name,
        encoded,
        font_size,
    )
    if advance is None or font_size <= 0:
        return None
    return _transformed_bbox(
        (0.0, -font_size * 0.2, advance, font_size * 0.8),
        text_matrix,
    )


def bbox_within(
    inner: Rectangle,
    outer: Rectangle,
    *,
    tolerance: float = 0.01,
) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def page_bounds(page: PageInfo) -> Rectangle:
    return page.crop_box or page.media_box


def text_advance_for_font(
    model: PdfObjectModel,
    page: PageInfo,
    font_name: str,
    encoded: bytes,
    font_size: float,
    *,
    character_spacing: float = 0.0,
    word_spacing: float = 0.0,
    horizontal_scaling: float = 100.0,
) -> float | None:
    """Return the text-space advance from exact font widths and text state."""
    if any(
        not math.isfinite(value)
        for value in (
            font_size,
            character_spacing,
            word_spacing,
            horizontal_scaling,
        )
    ) or font_size <= 0:
        return None
    font = resolve_font_dictionary(model, page, font_name)
    if font is None:
        return None
    codes = _encoded_codes(font, encoded)
    if codes is None:
        return None
    glyph_advance = _glyph_advance(
        model,
        page,
        font_name,
        font,
        encoded,
        font_size,
    )
    if glyph_advance is None:
        return None
    if font.get("/Subtype") == "/Type0" and word_spacing != 0.0:
        return None
    spacing = character_spacing * len(codes)
    if font.get("/Subtype") != "/Type0":
        spacing += word_spacing * codes.count(0x20)
    return (glyph_advance + spacing) * horizontal_scaling / 100.0


def _glyph_advance(
    model: PdfObjectModel,
    page: PageInfo,
    font_name: str,
    font: PdfDict,
    encoded: bytes,
    font_size: float,
) -> float | None:
    explicit_widths = (
        font.get("/FirstChar") is not None
        or font.get("/Widths") is not None
    )
    if explicit_widths:
        width = _simple_width(model, font, encoded)
        return None if width is None else width * font_size / 1000.0
    base_font = font.get("/BaseFont")
    decoded = decode_text_for_font(model, page, font_name, encoded)
    if isinstance(base_font, str) and decoded is not None:
        if base_font in {"/Helvetica", "/Helvetica-Oblique"}:
            return base14_text_width(decoded, font_size, "/F1")
        if base_font in {"/Helvetica-Bold", "/Helvetica-BoldOblique"}:
            return base14_text_width(decoded, font_size, "/F2")
    if font.get("/Subtype") == "/Type0":
        width = _type0_width(model, font, encoded)
    else:
        width = _simple_width(model, font, encoded)
    return None if width is None else width * font_size / 1000.0


def _encoded_codes(font: PdfDict, encoded: bytes) -> list[int] | None:
    if font.get("/Subtype") != "/Type0":
        return list(encoded)
    if font.get("/Encoding") != "/Identity-H" or len(encoded) % 2:
        return None
    return [
        int.from_bytes(encoded[offset:offset + 2], "big")
        for offset in range(0, len(encoded), 2)
    ]


def _simple_width(
    model: PdfObjectModel,
    font: PdfDict,
    encoded: bytes,
) -> float | None:
    first = font.get("/FirstChar")
    widths = _resolve_value(model, font.get("/Widths"))
    if (
        not isinstance(first, int)
        or isinstance(first, bool)
        or not 0 <= first <= 255
        or not isinstance(widths, list)
        or not widths
        or len(widths) > 256 - first
        or any(
            not isinstance(width, (int, float))
            or isinstance(width, bool)
            or not math.isfinite(float(width))
            or float(width) < 0.0
            for width in widths
        )
    ):
        return None
    total = 0.0
    for value in encoded:
        index = value - first
        if not 0 <= index < len(widths):
            return None
        total += float(widths[index])
    return total


def _type0_width(
    model: PdfObjectModel,
    font: PdfDict,
    encoded: bytes,
) -> float | None:
    if font.get("/Encoding") != "/Identity-H" or len(encoded) % 2:
        return None
    descendants = font.get("/DescendantFonts")
    if not isinstance(descendants, list) or not descendants:
        return None
    descendant = _resolve_value(model, descendants[0])
    if not isinstance(descendant, PdfDict):
        return None
    default = descendant.get("/DW", 1000)
    if not isinstance(default, (int, float)):
        return None
    widths = _cid_widths(descendant.get("/W"))
    if widths is None:
        return None
    return sum(
        widths.get(int.from_bytes(encoded[offset:offset + 2], "big"), float(default))
        for offset in range(0, len(encoded), 2)
    )


def _cid_widths(value: Any) -> dict[int, float] | None:
    if value is None:
        return {}
    if not isinstance(value, list):
        return None
    result: dict[int, float] = {}
    index = 0
    while index < len(value):
        start = value[index]
        index += 1
        if not isinstance(start, int) or index >= len(value):
            return None
        specification = value[index]
        index += 1
        if isinstance(specification, list):
            for offset, width in enumerate(specification):
                if not isinstance(width, (int, float)):
                    return None
                result[start + offset] = float(width)
            continue
        if not isinstance(specification, int) or index >= len(value):
            return None
        width = value[index]
        index += 1
        if specification < start or not isinstance(width, (int, float)):
            return None
        for cid in range(start, specification + 1):
            result[cid] = float(width)
    return result


def _transformed_bbox(
    bbox: Rectangle,
    matrix: TextMatrix,
) -> Rectangle:
    x0, y0, x1, y1 = bbox
    a, b, c, d, e, f = matrix
    points = tuple(
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _resolve_value(model: PdfObjectModel, value: Any) -> Any:
    visited: set[int] = set()
    while isinstance(value, IndirectReference):
        if value.obj_num in visited:
            return None
        visited.add(value.obj_num)
        try:
            value = model.get_object(value).value
        except DocumentSkillsError:
            return None
    return value
