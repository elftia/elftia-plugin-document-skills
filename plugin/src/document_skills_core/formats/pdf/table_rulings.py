"""Bounded extraction of axis-aligned stroked PDF path segments."""

from dataclasses import dataclass
from typing import Any

from .content_streams import tokenize_content_stream

COORDINATE_TOLERANCE = 0.5
_MATRIX_TOLERANCE = 1e-6
_MIN_SEGMENT_LENGTH = 2.0
_MAX_RULING_SEGMENTS = 4_096


@dataclass(frozen=True)
class RulingLine:
    orientation: str
    position: float
    start: float
    end: float


def extract_stroked_rulings(content: bytes) -> list[RulingLine]:
    """Extract the safe m/l/h subset; discard paths containing unsupported geometry."""
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    matrices: list[tuple[float, float, float, float, float, float]] = []
    current: tuple[float, float] | None = None
    start: tuple[float, float] | None = None
    path: list[RulingLine] = []
    path_supported = True
    ruled: list[RulingLine] = []
    for operator, operands in tokenize_content_stream(content):
        if operator == "q":
            matrices.append(matrix)
        elif operator == "Q":
            if matrices:
                matrix = matrices.pop()
        elif operator == "cm":
            if _has_numbers(operands, 6):
                matrix = _concatenate(
                    matrix, tuple(float(value) for value in operands[-6:])
                )
            else:
                path_supported = False
        elif operator == "m":
            if _has_numbers(operands, 2):
                current = _transform(matrix, float(operands[-2]), float(operands[-1]))
                start = current
                path_supported = _is_axis_scale_translate(matrix) and path_supported
            else:
                path_supported = False
        elif operator == "l":
            if _has_numbers(operands, 2):
                point = _transform(matrix, float(operands[-2]), float(operands[-1]))
                path_supported = _append_line(path, current, point) and path_supported
                current = point
            else:
                path_supported = False
        elif operator == "h":
            path_supported = _append_line(path, current, start) and path_supported
            current = start
        elif operator in {"re", "c", "v", "y"}:
            path_supported = False
        elif operator in {"s", "b", "b*"}:
            path_supported = _append_line(path, current, start) and path_supported
            ruled = _commit_path(ruled, path, path_supported)
            current, start, path, path_supported = None, None, [], True
        elif operator in {"S", "B", "B*"}:
            ruled = _commit_path(ruled, path, path_supported)
            current, start, path, path_supported = None, None, [], True
        elif operator in {"f", "F", "f*", "n"}:
            current, start, path, path_supported = None, None, [], True
        if len(ruled) > _MAX_RULING_SEGMENTS:
            return []
    return list(dict.fromkeys(ruled))


def _has_numbers(operands: list[Any], count: int) -> bool:
    return len(operands) >= count and all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in operands[-count:]
    )


def _concatenate(
    current: tuple[float, float, float, float, float, float],
    new: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = current
    na, nb, nc, nd, ne, nf = new
    return (
        a * na + c * nb,
        b * na + d * nb,
        a * nc + c * nd,
        b * nc + d * nd,
        a * ne + c * nf + e,
        b * ne + d * nf + f,
    )


def _transform(
    matrix: tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _is_axis_scale_translate(
    matrix: tuple[float, float, float, float, float, float],
) -> bool:
    return abs(matrix[1]) <= _MATRIX_TOLERANCE and abs(matrix[2]) <= _MATRIX_TOLERANCE


def _append_line(
    path: list[RulingLine],
    first: tuple[float, float] | None,
    second: tuple[float, float] | None,
) -> bool:
    if first is None or second is None:
        return False
    if (
        abs(first[0] - second[0]) <= COORDINATE_TOLERANCE
        and abs(first[1] - second[1]) <= COORDINATE_TOLERANCE
    ):
        return True
    line = _axis_line(first, second)
    if line is None:
        return False
    path.append(line)
    return True


def _axis_line(
    first: tuple[float, float],
    second: tuple[float, float],
) -> RulingLine | None:
    x0, y0 = first
    x1, y1 = second
    if abs(y0 - y1) <= COORDINATE_TOLERANCE:
        start, end = sorted((x0, x1))
        if end - start >= _MIN_SEGMENT_LENGTH:
            return RulingLine(
                "horizontal", round((y0 + y1) / 2.0, 4), round(start, 4), round(end, 4)
            )
    elif abs(x0 - x1) <= COORDINATE_TOLERANCE:
        start, end = sorted((y0, y1))
        if end - start >= _MIN_SEGMENT_LENGTH:
            return RulingLine(
                "vertical", round((x0 + x1) / 2.0, 4), round(start, 4), round(end, 4)
            )
    return None


def _commit_path(
    lines: list[RulingLine],
    path: list[RulingLine],
    supported: bool,
) -> list[RulingLine]:
    if not supported:
        return lines
    return [*lines, *path]
