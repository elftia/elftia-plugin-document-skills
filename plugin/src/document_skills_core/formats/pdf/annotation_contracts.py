"""Closed request contract for safe PDF text-annotation edits.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_PAGES
from .create_contracts import parse_rgb


def parse_annotation_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    allowed = {
        "type", "action", "subtype", "page", "index", "expected_contents",
        "rectangle", "contents", "title", "color",
    }
    unknown = sorted(set(primitive) - allowed)
    field = f"primitives.{index}"
    if unknown:
        _invalid("Unknown PDF annotation argument.", field=field, unknown=unknown)
    action = primitive.get("action")
    if action not in {"add", "update", "delete"}:
        _invalid("annotation.action must be add, update, or delete.", field=f"{field}.action")
    page = _integer(primitive.get("page"), 1, MAX_PAGES, f"{field}.page")
    annotation_index = primitive.get("index")
    if annotation_index is not None:
        annotation_index = _integer(annotation_index, 1, 10_000, f"{field}.index")
    subtype = primitive.get("subtype")
    rectangle = _rectangle(primitive.get("rectangle"), f"{field}.rectangle")
    contents = _optional_text(primitive.get("contents"), f"{field}.contents")
    title = _optional_text(primitive.get("title"), f"{field}.title", allow_empty=False)
    expected = _optional_text(
        primitive.get("expected_contents"),
        f"{field}.expected_contents",
    )
    color = parse_rgb(primitive.get("color"), f"{field}.color")
    for value, value_field in (
        (contents, f"{field}.contents"),
        (title, f"{field}.title"),
        (expected, f"{field}.expected_contents"),
    ):
        if value is not None:
            _require_latin1(value, value_field)
    if action == "add":
        if subtype != "text" or annotation_index is not None or expected is not None:
            _invalid(
                "annotation add requires subtype=text and does not accept index fields.",
                field=field,
            )
        if rectangle is None or contents is None:
            _invalid("annotation add requires rectangle and contents.", field=field)
        color = color or [1.0, 1.0, 0.0]
    elif action == "update":
        if subtype is not None or annotation_index is None:
            _invalid("annotation update requires index and no subtype.", field=field)
        if all(value is None for value in (rectangle, contents, title, color)):
            _invalid(
                "annotation update requires a rectangle, contents, title, or color change.",
                field=field,
            )
    else:
        if annotation_index is None or any(
            value is not None for value in (subtype, rectangle, contents, title, color)
        ):
            _invalid(
                "annotation delete requires index and does not accept mutation fields.",
                field=field,
            )
    return {
        "type": "annotation",
        "action": action,
        "subtype": subtype,
        "page": page,
        "index": annotation_index,
        "expected_contents": expected,
        "rectangle": rectangle,
        "contents": contents,
        "title": title,
        "color": color,
    }


def _rectangle(value: Any, field: str) -> list[float] | None:
    if value is None:
        return None
    if type(value) is not list or len(value) != 4:
        _invalid("Annotation rectangle must be [x0, y0, x1, y1].", field=field)
    rectangle = [_number(item, field) for item in value]
    if rectangle[2] <= rectangle[0] or rectangle[3] <= rectangle[1]:
        _invalid("Annotation rectangle must have positive width and height.", field=field)
    return rectangle


def _optional_text(value: Any, field: str, *, allow_empty: bool = True) -> str | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > MAX_ARGUMENT_TEXT or (not allow_empty and not value):
        _invalid("Annotation text value is invalid or exceeds the bound.", field=field)
    return value


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or type(value) is bool or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _number(value: Any, field: str) -> float:
    if (type(value) is not int and type(value) is not float) or type(value) is bool:
        _invalid("Annotation coordinate must be numeric.", field=field)
    number = float(value)
    if not -10_000.0 <= number <= 10_000.0:
        _invalid("Annotation coordinate is outside the bound.", field=field)
    return number


def _require_latin1(value: str, field: str) -> None:
    try:
        value.encode("latin-1", errors="strict")
    except UnicodeEncodeError as error:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Core text annotations currently require Latin-1 text.",
            status="enhancement_required",
            details={"field": field, "capability": "pdf.annotation-unicode"},
        ) from error


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
