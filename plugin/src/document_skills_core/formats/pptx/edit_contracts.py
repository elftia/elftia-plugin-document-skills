"""Strict per-primitive contracts for transactional PPTX edits."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_SLIDES
from .object_contracts import OBJECT_EDIT_TYPES, parse_object_edit
from .typed_object_contracts import parse_chart_reference, parse_image_reference

EDIT_TYPES = frozenset({
    "notes_text",
    "slide_add",
    "slide_copy",
    "slide_delete",
    "slide_duplicate",
    "slide_move",
    "slide_reorder",
    "slide_text",
}).union(OBJECT_EDIT_TYPES)


def parse_edit(edit: dict[str, Any], index: int) -> dict[str, Any]:
    edit_type = edit.get("type")
    if edit_type not in EDIT_TYPES:
        _invalid("Unknown edit type.", field=f"edits.{index}.type")
    if edit_type in OBJECT_EDIT_TYPES:
        return parse_object_edit(edit, index)
    field = f"edits.{index}"
    if edit_type == "slide_add":
        _exact_keys(edit, {"position", "slide", "type"}, field)
        slide = edit.get("slide")
        if type(slide) is not dict:
            _invalid("slide_add requires a typed slide object.", field=f"{field}.slide")
        return {
            "position": _optional_integer(edit.get("position"), 1, MAX_SLIDES, f"{field}.position"),
            "slide": _parse_added_slide(slide, f"{field}.slide"),
            "type": edit_type,
        }
    if edit_type in {"slide_text", "notes_text"}:
        _exact_keys(edit, {"precondition_sha256", "ref", "slide", "style", "type", "value"}, field)
        style = edit.get("style")
        if style is not None and type(style) is not dict:
            _invalid("Style must be an object.", field=f"{field}.style")
        return {
            "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
            "ref": _text(edit.get("ref", ""), f"{field}.ref"),
            "slide": _integer(edit.get("slide", 1), 1, MAX_SLIDES, f"{field}.slide"),
            "style": style,
            "type": edit_type,
            "value": _optional_text(edit.get("value"), f"{field}.value"),
        }
    if edit_type in {"slide_reorder", "slide_move"}:
        _exact_keys(edit, {"position", "precondition_sha256", "ref", "slide", "type", "value"}, field)
        raw_position = edit.get("position", edit.get("value"))
        if type(raw_position) is str and raw_position.isdigit():
            raw_position = int(raw_position)
        position = _integer(raw_position, 1, MAX_SLIDES, f"{field}.position")
        return {
            "position": position,
            "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
            "ref": _text(edit.get("ref", ""), f"{field}.ref"),
            "slide": _integer(edit.get("slide", 1), 1, MAX_SLIDES, f"{field}.slide"),
            "type": "slide_reorder",
            "value": str(position),
        }
    if edit_type == "slide_delete":
        _exact_keys(edit, {"precondition_sha256", "slide", "type"}, field)
        return {
            "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
            "slide": _integer(edit.get("slide"), 1, MAX_SLIDES, f"{field}.slide"),
            "type": edit_type,
        }
    if edit_type == "slide_duplicate":
        _exact_keys(edit, {"position", "precondition_sha256", "slide", "type"}, field)
        return {
            "position": _optional_integer(edit.get("position"), 1, MAX_SLIDES, f"{field}.position"),
            "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
            "slide": _integer(edit.get("slide"), 1, MAX_SLIDES, f"{field}.slide"),
            "type": edit_type,
        }
    _exact_keys(
        edit,
        {"position", "precondition_sha256", "source", "source_slide", "type"},
        field,
    )
    source = edit.get("source")
    source_path = None
    if source is not None:
        raw_path = _text(source, f"{field}.source", allow_empty=False)
        if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
            _invalid("Slide copy source must be a local PPTX.", field=f"{field}.source")
        source_path = Path(raw_path).expanduser().resolve(strict=False)
        if source_path.suffix.casefold() != ".pptx":
            _invalid("Slide copy source must use the .pptx extension.", field=f"{field}.source")
    return {
        "position": _optional_integer(edit.get("position"), 1, MAX_SLIDES, f"{field}.position"),
        "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
        "source": source_path,
        "source_slide": _integer(edit.get("source_slide", 1), 1, MAX_SLIDES, f"{field}.source_slide"),
        "type": edit_type,
    }


def _parse_added_slide(value: dict[str, Any], field: str) -> dict[str, Any]:
    _exact_keys(
        value,
        {"chart_reference", "image_reference", "layout", "notes", "shapes", "table", "title"},
        field,
    )
    shapes = value.get("shapes", [])
    if type(shapes) is not list or len(shapes) > 500:
        _invalid("Added slide shapes must be a bounded array.", field=f"{field}.shapes")
    parsed_shapes = []
    for index, shape in enumerate(shapes):
        if type(shape) is not dict:
            _invalid("Added slide shape must be an object.", field=f"{field}.shapes.{index}")
        _exact_keys(shape, {"runs", "text"}, f"{field}.shapes.{index}")
        runs = shape.get("runs", [])
        if type(runs) is not list or len(runs) > 1_000:
            _invalid("Added slide runs must be a bounded array.", field=f"{field}.shapes.{index}.runs")
        parsed_runs = []
        for run_index, run in enumerate(runs):
            if type(run) is not dict:
                _invalid("Added slide run must be an object.", field=f"{field}.shapes.{index}.runs.{run_index}")
            _exact_keys(run, {"style", "text"}, f"{field}.shapes.{index}.runs.{run_index}")
            style = run.get("style")
            if style is not None and type(style) is not dict:
                _invalid("Added slide run style must be an object.", field=f"{field}.shapes.{index}.runs.{run_index}.style")
            parsed_runs.append({
                "style": style,
                "text": _optional_text(run.get("text"), f"{field}.shapes.{index}.runs.{run_index}.text"),
            })
        parsed_shapes.append({
            "runs": parsed_runs,
            "text": _optional_text(shape.get("text"), f"{field}.shapes.{index}.text"),
        })
    return {
        "chart_reference": parse_chart_reference(value.get("chart_reference"), f"{field}.chart_reference"),
        "image_reference": parse_image_reference(value.get("image_reference"), f"{field}.image_reference"),
        "layout": _text(value.get("layout", "content"), f"{field}.layout", False),
        "notes": _optional_text(value.get("notes"), f"{field}.notes"),
        "shapes": parsed_shapes,
        "table": _parse_table(value.get("table"), f"{field}.table"),
        "title": _optional_text(value.get("title"), f"{field}.title"),
    }


def _parse_table(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("Added slide table must be an object.", field=field)
    _exact_keys(value, {"rows"}, field)
    rows = value.get("rows", [])
    if type(rows) is not list or len(rows) > 1_000:
        _invalid("Added slide table rows must be a bounded array.", field=f"{field}.rows")
    parsed_rows = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            _invalid("Added slide table row must be an object.", field=f"{field}.rows.{index}")
        _exact_keys(row, {"cells"}, f"{field}.rows.{index}")
        cells = row.get("cells", [])
        if type(cells) is not list or len(cells) > 1_000:
            _invalid("Added slide table cells must be a bounded array.", field=f"{field}.rows.{index}.cells")
        parsed_rows.append({
            "cells": [
                _optional_text(cell, f"{field}.rows.{index}.cells.{cell_index}")
                for cell_index, cell in enumerate(cells)
            ]
        })
    return {"rows": parsed_rows}


def _precondition(value: Any, field: str) -> str | None:
    if value is None:
        return None
    digest = _text(value, f"{field}.precondition_sha256", False).casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        _invalid("precondition_sha256 must be a SHA-256 hex digest.", field=field)
    return digest


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown fields for PPTX edit primitive.", field=field, unknown=unknown)


def _optional_integer(
    value: Any, minimum: int, maximum: int, field: str
) -> int | None:
    return None if value is None else _integer(value, minimum, maximum, field)


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _optional_text(value: Any, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
