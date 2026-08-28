"""Geometry and operator emission for shaped PDF rewrite overlays."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .font_embedding import EmbeddedFontSet
from .font_shaping import ShapedLine
from .rewrite_layout import bbox_within
from .unicode_text import emit_shaped_line


def emit_rewrite_lines(
    lines: list[ShapedLine],
    bbox: list[float],
    style: dict[str, Any],
    fonts: EmbeddedFontSet,
) -> tuple[list[str], list[str], list[list[float]]]:
    """Emit shaped lines while binding glyph offsets to visible line boxes."""
    x0, y0, x1, y1 = (float(value) for value in bbox)
    font_size = float(style["font_size"])
    y_offsets = [
        (
            min((glyph.y_offset for glyph in line.glyphs), default=0.0),
            max((glyph.y_offset for glyph in line.glyphs), default=0.0),
        )
        for line in lines
    ]
    if len(lines) == 1:
        baselines = [y0 + font_size * 0.2 - y_offsets[0][0]]
    else:
        baselines = [
            y1
            - font_size * 0.8
            - maximum_offset
            - index * float(style["line_height"])
            for index, (_minimum_offset, maximum_offset) in enumerate(y_offsets)
        ]
    operators: list[str] = []
    resources: list[str] = []
    line_boxes: list[list[float]] = []
    for line, baseline, (minimum_offset, maximum_offset) in zip(
        lines,
        baselines,
        y_offsets,
        strict=True,
    ):
        x, _unused_baseline = _rewrite_position(bbox, line.width, style)
        line_operators, line_resources = emit_shaped_line(
            line,
            style,
            x=x,
            baseline=baseline,
            fonts=fonts,
        )
        operators.extend(line_operators)
        for resource in line_resources:
            if resource not in resources:
                resources.append(resource)
        line_boxes.append([
            round(x, 4),
            round(baseline + minimum_offset - font_size * 0.2, 4),
            round(x + line.width, 4),
            round(baseline + maximum_offset + font_size * 0.8, 4),
        ])
        if not bbox_within(tuple(line_boxes[-1]), (x0, y0, x1, y1)):
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Rewritten text exceeds the selected block bounds.",
                status="invalid_request",
                details={"bbox": bbox},
            )
    return operators, resources, line_boxes


def bbox_intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] < second[0]
        or first[0] > second[2]
        or first[3] < second[1]
        or first[1] > second[3]
    )


def _rewrite_position(
    bbox: list[float],
    width: float,
    style: dict[str, Any],
) -> tuple[float, float]:
    x0, y0, x1, y1 = (float(value) for value in bbox)
    available_width = x1 - x0
    if width > available_width + 0.01:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Rewritten text exceeds the selected block width.",
            status="invalid_request",
            details={"bbox": bbox, "text_width": round(width, 4)},
        )
    if style["alignment"] == "right":
        x = x1 - width
    elif style["alignment"] == "center":
        x = x0 + (available_width - width) / 2.0
    else:
        x = x0
    baseline = y0 + style["font_size"] * 0.2
    if baseline + style["font_size"] * 0.8 > y1 + style["line_height"]:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Rewritten text exceeds the selected block height.",
            status="invalid_request",
            details={"bbox": bbox},
        )
    return x, baseline
