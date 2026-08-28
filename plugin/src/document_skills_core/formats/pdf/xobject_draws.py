"""Graphics-state tracking for page-content XObject invocations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_streams import tokenize_content_stream

AffineMatrix = tuple[float, float, float, float, float, float]
IDENTITY_MATRIX: AffineMatrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class XObjectDraw:
    """One page-content ``Do`` invocation and its unit-square user-space bbox."""

    page: int
    resource_name: str
    bbox: tuple[float, float, float, float]
    matrix: AffineMatrix


@dataclass(frozen=True)
class InlineImageDraw:
    """One inline-image invocation and its unit-square user-space bbox."""

    page: int
    bbox: tuple[float, float, float, float]
    matrix: AffineMatrix


def walk_xobject_draws(
    content: bytes,
    page_number: int,
    *,
    max_operators: int = 500_000,
    initial_matrix: AffineMatrix = IDENTITY_MATRIX,
) -> tuple[list[XObjectDraw], list[InlineImageDraw]]:
    """Capture bounded XObject and inline-image invocations."""
    current = initial_matrix
    stack: list[AffineMatrix] = []
    draws: list[XObjectDraw] = []
    inline_images: list[InlineImageDraw] = []
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
            current = stack.pop() if stack else initial_matrix
        elif operator == "cm" and len(operands) >= 6:
            try:
                matrix = tuple(float(value) for value in operands[-6:])
            except (TypeError, ValueError):
                continue
            current = concatenate_matrix(matrix, current)
        elif operator == "BI":
            inline_images.append(InlineImageDraw(
                page=page_number,
                bbox=unit_square_bbox(current),
                matrix=current,
            ))
        elif operator == "Do" and operands and isinstance(operands[-1], str):
            resource_name = operands[-1]
            if resource_name.startswith("/"):
                draws.append(
                    XObjectDraw(
                        page=page_number,
                        resource_name=resource_name,
                        bbox=unit_square_bbox(current),
                        matrix=current,
                    )
                )
    return draws, inline_images


def concatenate_matrix(matrix: AffineMatrix, current: AffineMatrix) -> AffineMatrix:
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


def unit_square_bbox(matrix: AffineMatrix) -> tuple[float, float, float, float]:
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
