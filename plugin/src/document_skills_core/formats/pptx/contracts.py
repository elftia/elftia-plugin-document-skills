"""Strict bounded argument contracts for Core PPTX operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import MAX_ARGUMENT_TEXT, MAX_EDIT_OPS, MAX_SHAPES_PER_SLIDE, MAX_SLIDES
from .content_contracts import parse_markdown_arguments, parse_outline_arguments
from .design_contracts import parse_layout_tokens, parse_recipe, parse_theme
from .edit_contracts import parse_edit
from .html_contracts import parse_html_create_arguments
from .typed_object_contracts import parse_chart_reference, parse_image_reference

PPTX_OPERATIONS = frozenset(
    {
        "pptx.read",
        "pptx.inspect.structure",
        "pptx.render",
        "pptx.convert.pdf",
        "pptx.convert.legacy",
        "pptx.validate.schema",
        "pptx.outline.create",
        "pptx.create",
        "pptx.create.from-markdown",
        "pptx.create.from-html",
        "pptx.edit",
    }
)


@dataclass(frozen=True)
class ParsedPptxRequest:
    operation: str
    input_path: Path | None
    output_path: Path | None
    arguments: dict[str, Any]
    requested_fidelity: str


def parse_pptx_request(request: dict[str, Any]) -> ParsedPptxRequest:
    operation = request.get("operation")
    if operation not in PPTX_OPERATIONS:
        _invalid("The operation is not a Core PPTX operation.", field="operation")
    arguments = request.get("arguments", {})
    if type(arguments) is not dict:
        _invalid("PPTX arguments must be an object.", field="arguments")
    input_path = _optional_path(request.get("input"), "input")
    output_path = _optional_path(request.get("output"), "output")
    options = request.get("options", {})
    fidelity = options.get("fidelity", "core") if type(options) is dict else "core"
    in_place = options.get("in_place", False) if type(options) is dict else False
    if operation in {"pptx.read", "pptx.inspect.structure", "pptx.validate.schema"}:
        if input_path is None:
            _invalid("This PPTX operation requires an input path.", field="input")
        if output_path is not None:
            _invalid("Read-only PPTX operations do not accept output.", field="output")
    elif operation == "pptx.create":
        if output_path is None:
            _invalid("PPTX creation requires an explicit output path.", field="output")
        if input_path is not None:
            _invalid("PPTX creation does not accept input.", field="input")
    elif operation == "pptx.outline.create":
        if output_path is None:
            _invalid("PPTX outline planning requires an explicit output path.", field="output")
        if input_path is not None:
            _invalid("PPTX outline planning does not accept input.", field="input")
    elif operation in {"pptx.create.from-html", "pptx.create.from-markdown"}:
        if input_path is None or output_path is None:
            _invalid("PPTX content reconstruction requires input and output paths.")
    elif operation in {"pptx.convert.legacy", "pptx.convert.pdf", "pptx.render"}:
        if input_path is None or output_path is None:
            _invalid("LibreOffice PPTX output requires input and output paths.")
    elif input_path is None or output_path is None:
        _invalid("PPTX mutation requires distinct input and output paths.")
    expected_input_suffixes = {
        "pptx.create.from-html": {".htm", ".html"},
        "pptx.create.from-markdown": {".markdown", ".md"},
        "pptx.edit": {".pptm", ".pptx"},
        "pptx.inspect.structure": {".pptm", ".pptx"},
        "pptx.convert.legacy": {".ppt"},
    }.get(operation, {".pptx"})
    if input_path is not None and input_path.suffix.casefold() not in expected_input_suffixes:
        expected = ", ".join(sorted(expected_input_suffixes))
        _invalid(f"{operation} input must use one of: {expected}.", field="input")
    expected_output_suffix = {
        "pptx.convert.pdf": ".pdf",
        "pptx.outline.create": ".json",
        "pptx.render": ".zip",
    }.get(
        operation,
        ".pptm" if operation == "pptx.edit" and input_path is not None
        and input_path.suffix.casefold() == ".pptm" else ".pptx",
    )
    if (
        output_path is not None
        and output_path.suffix.casefold() != expected_output_suffix
    ):
        _invalid(
            f"{operation} output must use the {expected_output_suffix} extension.",
            field="output",
        )
    if operation in {"pptx.convert.legacy", "pptx.convert.pdf", "pptx.edit", "pptx.render"}:
        assert input_path is not None and output_path is not None
        if in_place or same_path(input_path, output_path):
            raise DocumentSkillsError(
                ErrorCode.OUTPUT_EQUALS_INPUT,
                "PPTX output operations require a distinct output and do not "
                "support in-place mode.",
                status="invalid_request",
            )
    elif in_place:
        _invalid("in_place is not meaningful for this PPTX operation.", field="options.in_place")
    parsed = {
        "pptx.read": _parse_read,
        "pptx.inspect.structure": _parse_inspect,
        "pptx.render": _parse_provider_output,
        "pptx.convert.pdf": _parse_provider_output,
        "pptx.convert.legacy": _parse_provider_output,
        "pptx.outline.create": parse_outline_arguments,
        "pptx.validate.schema": _parse_schema_validation,
        "pptx.create": _parse_create,
        "pptx.create.from-html": parse_html_create_arguments,
        "pptx.create.from-markdown": parse_markdown_arguments,
        "pptx.edit": _parse_edit,
    }[operation](arguments)
    if operation == "pptx.edit":
        assert input_path is not None
        macro_enabled = input_path.suffix.casefold() == ".pptm"
        if macro_enabled and parsed["keep_vba"] is not True:
            _invalid("PPTM editing requires explicit arguments.keep_vba: true.", field="keep_vba")
        if not macro_enabled and parsed["keep_vba"] is True:
            _invalid("keep_vba is accepted only for .pptm input and output.", field="keep_vba")
    if (
        operation in {"pptx.create", "pptx.create.from-markdown"}
        and parsed.get("template") is not None
        and output_path is not None
        and same_path(parsed["template"], output_path)
    ):
        raise DocumentSkillsError(
            ErrorCode.OUTPUT_EQUALS_INPUT,
            "PPTX template-as-base requires a distinct output path.",
            status="invalid_request",
        )
    return ParsedPptxRequest(operation, input_path, output_path, parsed, fidelity)


def _parse_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_notes", "include_connectors", "max_slides", "max_shapes_per_slide"})
    return {
        "include_notes": _boolean(value.get("include_notes", True), "include_notes"),
        "include_connectors": _boolean(value.get("include_connectors", True), "include_connectors"),
        "max_slides": _integer(value.get("max_slides", MAX_SLIDES), 1, MAX_SLIDES),
        "max_shapes_per_slide": _integer(
            value.get("max_shapes_per_slide", MAX_SHAPES_PER_SLIDE), 1, MAX_SHAPES_PER_SLIDE
        ),
    }


def _parse_inspect(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_hashes", "max_parts", "max_relationships"})
    return {
        "include_hashes": _boolean(value.get("include_hashes", True), "include_hashes"),
        "max_parts": _integer(value.get("max_parts", 2_000), 1, 5_000),
        "max_relationships": _integer(
            value.get("max_relationships", 5_000), 1, 10_000
        ),
    }


def _parse_schema_validation(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, set())
    return {}


def _parse_provider_output(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, set())
    return {}


def _parse_create(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"deck", "template"})
    deck = value.get("deck")
    if type(deck) is not dict:
        _invalid("create requires a deck object.", field="deck")
    template = _optional_path(value.get("template"), "template")
    if template is not None:
        if template.suffix.casefold() not in {".potx", ".pptx"}:
            _invalid("PPTX template-as-base requires a .pptx or .potx file.", field="template")
        if "theme" in deck:
            _invalid(
                "Template-as-base reuses the template theme and does not accept deck.theme.",
                field="deck.theme",
            )
    return {"deck": parse_deck(deck), "template": template}


def _parse_edit(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"edits", "expected_edits", "keep_vba"})
    edits = value.get("edits")
    if type(edits) is not list or not edits or len(edits) > MAX_EDIT_OPS:
        _invalid("edits must be a non-empty bounded array.", field="edits")
    parsed_edits = []
    for index, edit in enumerate(edits):
        if type(edit) is not dict:
            _invalid("Each edit must be an object.", field=f"edits.{index}")
        parsed_edits.append(parse_edit(edit, index))
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {
        "edits": parsed_edits,
        "expected_edits": expected,
        "keep_vba": _boolean(value.get("keep_vba", False), "keep_vba"),
    }


def parse_deck(deck: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(deck, {"layout_tokens", "metadata", "slide_size", "slides", "theme"})
    metadata = deck.get("metadata")
    if type(metadata) is not dict:
        _invalid("deck.metadata must be an object.", field="metadata")
    _exact_keys(metadata, {"title", "creator", "subject"})
    parsed_meta = {
        "title": _text(metadata.get("title", "Elftia Presentation"), "metadata.title"),
        "creator": _text(metadata.get("creator", "Elftia Document Skills"), "metadata.creator"),
        "subject": _text(metadata.get("subject", ""), "metadata.subject"),
    }
    slide_size = deck.get("slide_size")
    if slide_size is not None:
        if type(slide_size) is not dict:
            _invalid("slide_size must be an object.", field="slide_size")
        _exact_keys(slide_size, {"cx", "cy", "type"})
        slide_size = {
            "cx": _text(slide_size.get("cx", "9144000"), "slide_size.cx"),
            "cy": _text(slide_size.get("cy", "6858000"), "slide_size.cy"),
            "type": _text(slide_size.get("type", "screen4x3"), "slide_size.type"),
        }
    slides = deck.get("slides")
    if type(slides) is not list or not slides or len(slides) > MAX_SLIDES:
        _invalid("deck.slides must be a non-empty bounded array.", field="slides")
    parsed_slides = []
    for idx, slide in enumerate(slides):
        if type(slide) is not dict:
            _invalid(f"Slide {idx} must be an object.", field=f"slides.{idx}")
        _exact_keys(slide, {"layout", "recipe", "title", "shapes", "table", "chart_reference", "image_reference", "notes"})
        layout = _text(slide.get("layout", "content"), f"slides.{idx}.layout")
        recipe = parse_recipe(slide.get("recipe"), layout, f"slides.{idx}.recipe")
        title = _optional_text(slide.get("title"), f"slides.{idx}.title")
        shapes = slide.get("shapes", [])
        if type(shapes) is not list:
            _invalid(f"Slide {idx} shapes must be an array.", field=f"slides.{idx}.shapes")
        parsed_shapes = []
        for s_idx, shape in enumerate(shapes):
            if type(shape) is not dict:
                _invalid(f"Shape must be an object.", field=f"slides.{idx}.shapes.{s_idx}")
            _exact_keys(shape, {"text", "runs"})
            shape_text = _optional_text(shape.get("text"), f"slides.{idx}.shapes.{s_idx}.text")
            runs = shape.get("runs", [])
            if type(runs) is not list:
                _invalid(f"Shape runs must be an array.", field=f"slides.{idx}.shapes.{s_idx}.runs")
            parsed_runs = []
            for r_idx, run in enumerate(runs):
                if type(run) is not dict:
                    _invalid(f"Run must be an object.", field=f"slides.{idx}.shapes.{s_idx}.runs.{r_idx}")
                _exact_keys(run, {"text", "style"})
                run_text = _optional_text(run.get("text"), f"runs.{r_idx}.text")
                run_style = run.get("style")
                if run_style is not None and type(run_style) is not dict:
                    _invalid("Run style must be an object.", field=f"runs.{r_idx}.style")
                parsed_runs.append({"text": run_text, "style": run_style})
            parsed_shapes.append({"text": shape_text, "runs": parsed_runs})
        table = slide.get("table")
        if table is not None:
            if type(table) is not dict:
                _invalid(f"Slide {idx} table must be an object.", field=f"slides.{idx}.table")
            _exact_keys(table, {"rows"})
            table_rows = table.get("rows", [])
            if type(table_rows) is not list:
                _invalid("table.rows must be an array.", field=f"slides.{idx}.table.rows")
            parsed_table_rows = []
            for tr_idx, tr in enumerate(table_rows):
                if type(tr) is not dict:
                    _invalid("table row must be an object.", field=f"table.rows.{tr_idx}")
                _exact_keys(tr, {"cells"})
                table_cells = tr.get("cells", [])
                if type(table_cells) is not list:
                    _invalid("row.cells must be an array.", field=f"table.rows.{tr_idx}.cells")
                parsed_cells = [_optional_text(c, f"cells.{c_idx}") if c is not None else None for c_idx, c in enumerate(table_cells)]
                parsed_table_rows.append({"cells": parsed_cells})
            table = {"rows": parsed_table_rows}
        chart_ref = parse_chart_reference(
            slide.get("chart_reference"), f"slides.{idx}.chart_reference"
        )
        image_ref = parse_image_reference(
            slide.get("image_reference"), f"slides.{idx}.image_reference"
        )
        notes = slide.get("notes")
        if notes is not None:
            notes = _optional_text(notes, f"slides.{idx}.notes")
        parsed_slides.append({
            "layout": layout,
            "recipe": recipe,
            "title": title,
            "shapes": parsed_shapes,
            "table": table,
            "chart_reference": chart_ref,
            "image_reference": image_ref,
            "notes": notes,
        })
    return {
        "layout_tokens": parse_layout_tokens(deck.get("layout_tokens"), "layout_tokens"),
        "metadata": parsed_meta,
        "slide_size": slide_size,
        "slides": parsed_slides,
        "theme": parse_theme(deck.get("theme"), "theme"),
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PPTX operation argument.", unknown=unknown)


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


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
