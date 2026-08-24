"""Bounded contracts for PPTX outline planning and Markdown reconstruction."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_SLIDES
from .design_contracts import LAYOUT_RECIPES, parse_layout_tokens, parse_theme

_MAX_BULLETS = 64
_MAX_TAGS = 16


def parse_outline_arguments(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {"audience", "objective", "slides", "subtitle", "title"},
    )
    title = _text(value.get("title"), "title", allow_empty=False)
    slides = value.get("slides")
    if type(slides) is not list or not slides or len(slides) > MAX_SLIDES:
        _invalid("Outline slides must be a non-empty bounded array.", field="slides")
    parsed_slides = [
        _parse_outline_slide(item, index)
        for index, item in enumerate(slides)
    ]
    return {
        "audience": _optional_text(value.get("audience"), "audience"),
        "objective": _optional_text(value.get("objective"), "objective"),
        "slides": parsed_slides,
        "subtitle": _optional_text(value.get("subtitle"), "subtitle"),
        "title": title,
    }


def parse_markdown_arguments(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"layout_tokens", "metadata", "template", "theme"})
    metadata = value.get("metadata", {})
    if type(metadata) is not dict:
        _invalid("Markdown metadata must be an object.", field="metadata")
    _exact_keys(metadata, {"creator", "subject", "title"})
    template = _optional_path(value.get("template"), "template")
    if template is not None and template.suffix.casefold() not in {".potx", ".pptx"}:
        _invalid(
            "Markdown template must use the .pptx or .potx extension.",
            field="template",
        )
    if template is not None and "theme" in value:
        _invalid(
            "Markdown template reuse cannot be combined with theme tokens.",
            field="theme",
        )
    return {
        "layout_tokens": parse_layout_tokens(
            value.get("layout_tokens"),
            "layout_tokens",
        ),
        "metadata": {
            "creator": _text(
                metadata.get("creator", "Elftia Document Skills"),
                "metadata.creator",
            ),
            "subject": _text(metadata.get("subject", ""), "metadata.subject"),
            "title": _text(metadata.get("title", ""), "metadata.title"),
        },
        "template": template,
        "theme": None if template is not None else parse_theme(value.get("theme"), "theme"),
    }


def parse_slide_metadata(value: Any, line: int) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Markdown slide metadata must be an object.", line=line)
    _exact_keys(value, {"notes", "recipe", "tags"})
    recipe = value.get("recipe")
    if recipe is not None:
        recipe = _text(recipe, "recipe", allow_empty=False)
        if recipe not in LAYOUT_RECIPES:
            _invalid("Markdown slide recipe is unsupported.", line=line)
    tags = value.get("tags", [])
    if type(tags) is not list or len(tags) > _MAX_TAGS:
        _invalid("Markdown slide tags must be a bounded array.", line=line)
    return {
        "notes": _optional_text(value.get("notes"), "notes"),
        "recipe": recipe,
        "tags": [
            _text(item, f"tags.{index}", allow_empty=False)
            for index, item in enumerate(tags)
        ],
    }


def _parse_outline_slide(value: Any, index: int) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Each outline slide must be an object.", field=f"slides.{index}")
    _exact_keys(value, {"bullets", "metadata", "notes", "purpose", "title"})
    bullets = value.get("bullets", [])
    if type(bullets) is not list or len(bullets) > _MAX_BULLETS:
        _invalid("Outline bullets must be a bounded array.", field=f"slides.{index}.bullets")
    metadata = value.get("metadata", {})
    if type(metadata) is not dict:
        _invalid("Outline slide metadata must be an object.", field=f"slides.{index}.metadata")
    parsed_metadata = parse_slide_metadata(metadata, index + 1)
    return {
        "bullets": [
            _text(item, f"slides.{index}.bullets.{bullet}", allow_empty=False)
            for bullet, item in enumerate(bullets)
        ],
        "metadata": {
            "recipe": parsed_metadata["recipe"],
            "tags": parsed_metadata["tags"],
        },
        "notes": _optional_text(
            value.get("notes", parsed_metadata["notes"]),
            f"slides.{index}.notes",
        ),
        "purpose": _optional_text(value.get("purpose"), f"slides.{index}.purpose"),
        "title": _text(value.get("title"), f"slides.{index}.title", allow_empty=False),
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PPTX content-entry argument.", unknown=unknown)


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _text(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
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
