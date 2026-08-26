"""Closed bounded contract for declarative DOCX paragraph template regions."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_MAX_REGIONS = 64
_MAX_ITEMS_PER_REGION = 256
_MAX_EMITTED_PARAGRAPHS = 1_000
_MAX_ITEM_FIELDS = 64
_MAX_REGION_VALUE_BYTES = 512 * 1_024


def parse_template_regions(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= _MAX_REGIONS:
        _invalid("Template regions must be a non-empty bounded array.", field="regions")
    parsed: list[dict[str, Any]] = []
    target_indices: set[int] = set()
    emitted = 0
    value_bytes = 0
    for index, region in enumerate(value):
        field = f"regions.{index}"
        if type(region) is not dict:
            _invalid("Each template region must be an object.", field=field)
        region_type = region.get("type")
        if region_type == "paragraph_repeat":
            _exact_keys(region, {"items", "target", "type"}, field)
            items = _items(region.get("items"), f"{field}.items")
            emitted += len(items)
            value_bytes += sum(
                len(item_value.encode("utf-8", errors="strict"))
                for item in items
                for item_value in item.values()
            )
            parsed_region = {
                "type": "paragraph_repeat",
                "target": _target(region.get("target"), f"{field}.target"),
                "items": items,
            }
        elif region_type == "paragraph_condition":
            _exact_keys(region, {"include", "target", "type"}, field)
            include = region.get("include")
            if type(include) is not bool:
                _invalid(
                    "Template paragraph conditions require a literal boolean include value.",
                    field=f"{field}.include",
                )
            emitted += 1 if include else 0
            parsed_region = {
                "type": "paragraph_condition",
                "target": _target(region.get("target"), f"{field}.target"),
                "include": include,
            }
        else:
            _invalid(
                "Template region type must be paragraph_repeat or paragraph_condition.",
                field=f"{field}.type",
            )
        paragraph_index = parsed_region["target"]["paragraph_index"]
        if paragraph_index in target_indices:
            _invalid(
                "Template regions must target distinct immutable paragraphs.",
                field=f"{field}.target.paragraph_index",
            )
        target_indices.add(paragraph_index)
        parsed.append(parsed_region)
    if emitted > _MAX_EMITTED_PARAGRAPHS:
        _invalid("Template regions exceed the emitted paragraph limit.", field="regions")
    if value_bytes > _MAX_REGION_VALUE_BYTES:
        _invalid("Template region values exceed the aggregate byte limit.", field="regions")
    return parsed


def _target(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Template region target must be an object.", field=field)
    _exact_keys(
        value,
        {"expected_text", "paragraph_index", "range", "story"},
        field,
    )
    if value.get("story") != "body" or value.get("range") != "paragraph":
        _invalid(
            "Template regions target only body paragraphs.",
            field=field,
        )
    return {
        "story": "body",
        "range": "paragraph",
        "paragraph_index": _integer(
            value.get("paragraph_index"),
            0,
            10_000,
            f"{field}.paragraph_index",
        ),
        "expected_text": _text(value.get("expected_text"), f"{field}.expected_text"),
    }


def _items(value: Any, field: str) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > _MAX_ITEMS_PER_REGION:
        _invalid("Template repeat items must be a bounded array.", field=field)
    parsed: list[dict[str, str]] = []
    for item_index, item in enumerate(value):
        item_field = f"{field}.{item_index}"
        if type(item) is not dict or len(item) > _MAX_ITEM_FIELDS:
            _invalid("Template repeat item must be a bounded object.", field=item_field)
        values: dict[str, str] = {}
        for name, raw_value in item.items():
            if type(name) is not str or _IDENTIFIER.fullmatch(name) is None:
                _invalid(
                    "Template repeat item keys must be bounded identifiers.",
                    field=item_field,
                )
            if raw_value is None:
                rendered = ""
            elif type(raw_value) is bool:
                rendered = str(raw_value).lower()
            elif type(raw_value) in {str, int, float}:
                rendered = str(raw_value)
            else:
                _invalid(
                    "Template repeat item values must be scalar.",
                    field=f"{item_field}.{name}",
                )
            values[name] = _text(rendered, f"{item_field}.{name}")
        parsed.append(values)
    return parsed


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(
            f"Integer must be between {minimum} and {maximum}.",
            field=field,
        )
    return value


def _text(value: Any, field: str) -> str:
    if type(value) is not str:
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the operation byte limit.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown template region argument.", field=field, unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
