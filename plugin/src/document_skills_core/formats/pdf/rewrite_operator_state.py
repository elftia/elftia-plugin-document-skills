"""Graphics and text state for exact PDF operator rewrites."""

from dataclasses import dataclass, field
import math
from typing import Any

from .object_model import PdfObjectModel
from .page_tree import PageInfo
from .rewrite_layout import text_advance_for_font

AffineMatrix = tuple[float, float, float, float, float, float]
IDENTITY_MATRIX: AffineMatrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class OperatorGraphicsState:
    ctm: AffineMatrix = IDENTITY_MATRIX
    font_name: str = ""
    font_size: float = 0.0
    leading: float = 0.0
    character_spacing: float | None = 0.0
    word_spacing: float | None = 0.0
    horizontal_scaling: float | None = 100.0
    text_rise: float | None = 0.0
    rendering_mode: float | None = 0.0
    external_graphics_state: bool = False


@dataclass
class OperatorTraversalState:
    graphics: OperatorGraphicsState = field(default_factory=OperatorGraphicsState)
    graphics_stack: list[OperatorGraphicsState] = field(default_factory=list)
    text_matrix: AffineMatrix = IDENTITY_MATRIX
    text_line_matrix: AffineMatrix = IDENTITY_MATRIX
    text_position_supported: bool = True
    marked_stack: list[tuple[int | None, str | None]] = field(default_factory=list)
    next_marked_content: int = 0


def text_show_advance(
    model: PdfObjectModel,
    page: PageInfo,
    operator: str,
    operands: list[Any],
    graphics: OperatorGraphicsState,
) -> float | None:
    if operator == "Tj" and operands:
        items: list[Any] = [operands[-1]]
    elif operator == "TJ" and operands and isinstance(operands[-1], list):
        items = operands[-1]
    else:
        return None
    if (
        graphics.character_spacing is None
        or graphics.word_spacing is None
        or graphics.horizontal_scaling is None
    ):
        return None
    total = 0.0
    for item in items:
        encoded = _encoded_item(item)
        if encoded is not None:
            advance = text_advance_for_font(
                model,
                page,
                graphics.font_name,
                encoded,
                graphics.font_size,
                character_spacing=graphics.character_spacing,
                word_spacing=graphics.word_spacing,
                horizontal_scaling=graphics.horizontal_scaling,
            )
            if advance is None:
                return None
            total += advance
            continue
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            return None
        adjustment = float(item)
        if not math.isfinite(adjustment):
            return None
        total -= (
            adjustment
            * graphics.font_size
            / 1000.0
            * graphics.horizontal_scaling
            / 100.0
        )
    return total


def numeric_operands(
    operands: list[Any],
    count: int,
) -> tuple[float, ...] | None:
    if len(operands) < count:
        return None
    values = operands[-count:]
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in values
    ):
        return None
    return tuple(float(value) for value in values)


def concatenate_matrix(
    matrix: tuple[float, ...],
    current: AffineMatrix,
) -> AffineMatrix:
    """Return ``matrix x current`` using the PDF affine convention."""
    a, b, c, d, e, f = matrix
    ca, cb, cc, cd, ce, cf = current
    return (
        ca * a + cc * b,
        cb * a + cd * b,
        ca * c + cc * d,
        cb * c + cd * d,
        ca * e + cc * f + ce,
        cb * e + cd * f + cf,
    )


def unsupported_text_state(
    graphics: OperatorGraphicsState,
) -> tuple[str, ...]:
    defaults = {
        "Tc": (graphics.character_spacing, 0.0),
        "Tw": (graphics.word_spacing, 0.0),
        "Tz": (graphics.horizontal_scaling, 100.0),
        "Tr": (graphics.rendering_mode, 0.0),
        "Ts": (graphics.text_rise, 0.0),
    }
    unsupported = tuple(
        operator
        for operator, (value, default) in defaults.items()
        if value is None or abs(value - default) > 1e-9
    )
    if graphics.external_graphics_state:
        unsupported += ("gs",)
    return unsupported


def translate_matrix(matrix: AffineMatrix, tx: float, ty: float) -> AffineMatrix:
    a, b, c, d, e, f = matrix
    return (
        a,
        b,
        c,
        d,
        e + tx * a + ty * c,
        f + tx * b + ty * d,
    )


def _encoded_item(item: Any) -> bytes | None:
    if isinstance(item, bytes):
        return item
    if not isinstance(item, str):
        return None
    try:
        return item.encode("latin-1", errors="strict")
    except UnicodeEncodeError:
        return None
