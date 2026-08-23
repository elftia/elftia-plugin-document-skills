"""Graphics-state tracking for page-content XObject invocations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_streams import tokenize_content_stream


@dataclass(frozen=True)
class XObjectDraw:
    """One page-content ``Do`` invocation and its unit-square user-space bbox."""

    page: int
    resource_name: str
    bbox: tuple[float, float, float, float]


def walk_xobject_draws(
    content: bytes,
    page_number: int,
    *,
    max_operators: int = 500_000,
) -> tuple[list[XObjectDraw], bool]:
    """Capture bounded XObject invocations and detect unsupported inline images."""
    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    current = identity
    stack: list[tuple[float, float, float, float, float, float]] = []
    draws: list[XObjectDraw] = []
    inline_image = False
    for index, (operator, operands) in enumerate(tokenize_content_stream(content)):
        if index >= max_operators:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF content stream exceeds the image-operator budget.",
                details={"page": page_number, "limit": max_operators},
            )
        if operator == "q":
            stack.append(current)
        elif operator == "Q":
            current = stack.pop() if stack else identity
        elif operator == "cm" and len(operands) >= 6:
            try:
                matrix = tuple(float(value) for value in operands[-6:])
            except (TypeError, ValueError):
                continue
            current = _concatenate_matrix(matrix, current)
        elif operator == "BI":
            inline_image = True
        elif operator == "Do" and operands and isinstance(operands[-1], str):
            resource_name = operands[-1]
            if resource_name.startswith("/"):
                draws.append(
                    XObjectDraw(
                        page=page_number,
                        resource_name=resource_name,
                        bbox=_unit_square_bbox(current),
                    )
                )
    return draws, inline_image


def _concatenate_matrix(
    matrix: tuple[float, float, float, float, float, float],
    current: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    """Return ``matrix × current`` using the PDF affine-matrix convention."""
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


def _unit_square_bbox(
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float]:
    a, b, c, d, e, f = matrix
    points = (
        (e, f),
        (a + e, b + f),
        (c + e, d + f),
        (a + c + e, b + d + f),
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return tuple(round(value, 6) for value in (min(xs), min(ys), max(xs), max(ys)))
