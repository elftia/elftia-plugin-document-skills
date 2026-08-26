"""Bounded affine transforms and path geometry for the SVG closed profile."""

import math
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MAX_PATH_COMMANDS = 2_048
MAX_PATH_BYTES = 128 * 1024
MAX_TRANSFORM_COMPONENT = 100_000.0

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(rf"[MmLlHhVvCcQqZz]|{_NUMBER}")
_TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")


def multiply(left: Matrix, right: Matrix) -> Matrix:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re_, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re_ + lc * rf + le,
        lb * re_ + ld * rf + lf,
    )


def apply(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    transformed = (a * x + c * y + e, b * x + d * y + f)
    if not all(math.isfinite(value) for value in transformed):
        _invalid("SVG transform produced non-finite geometry.")
    return transformed


def parse_transform(value: str | None) -> Matrix:
    if value is None or not value.strip():
        return IDENTITY
    result = IDENTITY
    cursor = 0
    for match in _TRANSFORM.finditer(value):
        if value[cursor:match.start()].strip(" ,\t\r\n"):
            _invalid("SVG transform syntax is unsupported.")
        cursor = match.end()
        name = match.group(1)
        numbers = _numbers(match.group(2))
        if name == "translate" and len(numbers) in {1, 2}:
            operation = (1.0, 0.0, 0.0, 1.0, numbers[0], numbers[1] if len(numbers) == 2 else 0.0)
        elif name == "scale" and len(numbers) in {1, 2}:
            operation = (numbers[0], 0.0, 0.0, numbers[-1], 0.0, 0.0)
        elif name == "rotate" and len(numbers) in {1, 3}:
            radians = math.radians(numbers[0])
            rotation = (
                math.cos(radians), math.sin(radians),
                -math.sin(radians), math.cos(radians), 0.0, 0.0,
            )
            if len(numbers) == 3:
                before = (1.0, 0.0, 0.0, 1.0, numbers[1], numbers[2])
                after = (1.0, 0.0, 0.0, 1.0, -numbers[1], -numbers[2])
                operation = multiply(multiply(before, rotation), after)
            else:
                operation = rotation
        else:
            _invalid("SVG transform function is outside the closed profile.", transform=name)
        result = multiply(result, operation)
    if value[cursor:].strip(" ,\t\r\n"):
        _invalid("SVG transform syntax is unsupported.")
    if any(abs(component) > MAX_TRANSFORM_COMPONENT for component in result):
        _invalid("SVG transform exceeds the bounded component policy.")
    determinant = result[0] * result[3] - result[1] * result[2]
    if abs(determinant) < 1e-9:
        _invalid("SVG transform is singular.")
    return result


def transform_frame(
    x: float,
    y: float,
    width: float,
    height: float,
    matrix: Matrix,
) -> dict[str, float]:
    center = apply(matrix, (x + width / 2, y + height / 2))
    scale_x = math.hypot(matrix[0], matrix[1])
    scale_y = math.hypot(matrix[2], matrix[3])
    dot = matrix[0] * matrix[2] + matrix[1] * matrix[3]
    if abs(dot) > 1e-6 * max(1.0, scale_x * scale_y):
        _invalid("SVG skew transforms are outside the closed profile.")
    transformed_width = width * scale_x
    transformed_height = height * scale_y
    if transformed_width <= 0 or transformed_height <= 0:
        _invalid("SVG transform collapsed an object.")
    return {
        "x": center[0] - transformed_width / 2,
        "y": center[1] - transformed_height / 2,
        "width": transformed_width,
        "height": transformed_height,
        "rotation": math.degrees(math.atan2(matrix[1], matrix[0])),
    }


def parse_polygon(value: str, matrix: Matrix) -> tuple[list[Point], dict[str, float]]:
    numbers = _numbers(value)
    if len(numbers) < 6 or len(numbers) % 2 or len(numbers) > MAX_PATH_COMMANDS * 2:
        _invalid("SVG polygon points are invalid or exceed policy.")
    points = [apply(matrix, (numbers[index], numbers[index + 1])) for index in range(0, len(numbers), 2)]
    return points, bounds(points)


def parse_path(value: str, matrix: Matrix) -> tuple[list[dict[str, Any]], dict[str, float]]:
    if not value or len(value.encode("utf-8")) > MAX_PATH_BYTES:
        _invalid("SVG path data is empty or exceeds the byte ceiling.")
    tokens = _tokens(value)
    commands: list[dict[str, Any]] = []
    points: list[Point] = []
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    while index < len(tokens):
        token = tokens[index]
        if isinstance(token, str):
            command = token
            index += 1
            if command in "Zz":
                commands.append({"op": "close", "points": []})
                current = start
                continue
        if command in "MmLl":
            required = 2
        elif command in "HhVv":
            required = 1
        elif command in "Qq":
            required = 4
        elif command in "Cc":
            required = 6
        else:
            _invalid("SVG path command is unsupported or missing.")
        if index + required > len(tokens) or any(isinstance(item, str) for item in tokens[index:index + required]):
            _invalid("SVG path command arguments are incomplete.")
        values = [float(item) for item in tokens[index:index + required]]
        index += required
        relative = command.islower()
        op = command.upper()
        raw_points: list[Point]
        if op == "H":
            raw_points = [((current[0] + values[0]) if relative else values[0], current[1])]
            op = "L"
        elif op == "V":
            raw_points = [(current[0], (current[1] + values[0]) if relative else values[0])]
            op = "L"
        else:
            raw_points = []
            for offset in range(0, required, 2):
                point = (values[offset], values[offset + 1])
                if relative:
                    point = (point[0] + current[0], point[1] + current[1])
                raw_points.append(point)
        if op == "M":
            start = raw_points[-1]
            emitted_op = "move" if not commands or commands[-1]["op"] == "close" else "line"
            command = "l" if relative else "L"
        else:
            emitted_op = {"L": "line", "Q": "quad", "C": "cubic"}[op]
        current = raw_points[-1]
        transformed = [apply(matrix, point) for point in raw_points]
        commands.append({"op": emitted_op, "points": transformed})
        points.extend(transformed)
        if len(commands) > MAX_PATH_COMMANDS:
            _invalid("SVG path command count exceeds policy.")
    if not commands or commands[0]["op"] != "move":
        _invalid("SVG path must begin with a move command.")
    return commands, bounds(points)


def bounds(points: list[Point]) -> dict[str, float]:
    if not points:
        _invalid("SVG geometry has no points.")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    width = right - left
    height = bottom - top
    if width <= 0:
        width = 0.01
    if height <= 0:
        height = 0.01
    return {"x": left, "y": top, "width": width, "height": height, "rotation": 0.0}


def _numbers(value: str) -> list[float]:
    result: list[float] = []
    cursor = 0
    for match in re.finditer(_NUMBER, value):
        if value[cursor:match.start()].strip(" ,\t\r\n"):
            _invalid("SVG numeric list contains unsupported syntax.")
        cursor = match.end()
        number = float(match.group(0))
        if not math.isfinite(number) or abs(number) > MAX_TRANSFORM_COMPONENT:
            _invalid("SVG numeric value exceeds policy.")
        result.append(number)
    if value[cursor:].strip(" ,\t\r\n"):
        _invalid("SVG numeric list contains unsupported syntax.")
    return result


def _tokens(value: str) -> list[str | float]:
    result: list[str | float] = []
    cursor = 0
    for match in _TOKEN.finditer(value):
        if value[cursor:match.start()].strip(" ,\t\r\n"):
            _invalid("SVG path contains unsupported syntax.")
        cursor = match.end()
        token = match.group(0)
        result.append(token if token.isalpha() else float(token))
    if value[cursor:].strip(" ,\t\r\n"):
        _invalid("SVG path contains unsupported syntax.")
    return result


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


__all__ = [
    "IDENTITY",
    "Matrix",
    "apply",
    "bounds",
    "multiply",
    "parse_path",
    "parse_polygon",
    "parse_transform",
    "transform_frame",
]
