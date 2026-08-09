"""Strict bounded argument contracts for the five Core PDF operations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import (
    MAX_ARGUMENT_TEXT,
    MAX_BLOCKS_PER_PAGE,
    MAX_EDIT_PRIMITIVES,
    MAX_PAGES,
    MAX_REWRITE_BLOCKS,
    MAX_TABLE_COLS,
    MAX_TABLE_ROWS,
)

PDF_OPERATIONS = frozenset(
    {
        "pdf.read",
        "pdf.inspect.structure",
        "pdf.create",
        "pdf.edit",
        "pdf.rewrite.apply",
    }
)

EDIT_PRIMITIVES = frozenset({"merge", "split", "rotate", "watermark", "form_fill"})


@dataclass(frozen=True)
class ParsedPdfRequest:
    operation: str
    input_path: Path | None
    output_path: Path | None
    arguments: dict[str, Any]
    requested_fidelity: str


def parse_pdf_request(request: dict[str, Any]) -> ParsedPdfRequest:
    operation = request.get("operation")
    if operation not in PDF_OPERATIONS:
        _invalid("The operation is not a Core PDF operation.", field="operation")
    arguments = request.get("arguments", {})
    if type(arguments) is not dict:
        _invalid("PDF arguments must be an object.", field="arguments")
    input_path = _optional_path(request.get("input"), "input")
    output_path = _optional_path(request.get("output"), "output")
    options = request.get("options", {})
    fidelity = options.get("fidelity", "core") if type(options) is dict else "core"
    in_place = options.get("in_place", False) if type(options) is dict else False
    if operation in {"pdf.read", "pdf.inspect.structure"}:
        if input_path is None:
            _invalid("This PDF operation requires an input path.", field="input")
        if output_path is not None:
            _invalid("Read-only PDF operations do not accept output.", field="output")
    elif operation == "pdf.create":
        if output_path is None:
            _invalid("PDF creation requires an explicit output path.", field="output")
        if input_path is not None:
            _invalid("PDF creation does not accept input.", field="input")
    elif input_path is None or output_path is None:
        _invalid("PDF mutation requires distinct input and output paths.")
    if input_path is not None and input_path.suffix.casefold() != ".pdf":
        _invalid("PDF input path must use the .pdf extension.", field="input")
    if output_path is not None and output_path.suffix.casefold() != ".pdf":
        _invalid("PDF output path must use the .pdf extension.", field="output")
    if operation in {"pdf.edit", "pdf.rewrite.apply", "pdf.create"}:
        if in_place or (input_path is not None and output_path is not None and same_path(input_path, output_path)):
            raise DocumentSkillsError(
                ErrorCode.OUTPUT_EQUALS_INPUT,
                "Core PDF mutations require a distinct output and do not support in-place mode.",
                status="invalid_request",
            )
    elif in_place:
        _invalid("in_place is not meaningful for this PDF operation.", field="options.in_place")
    parsed = {
        "pdf.read": _parse_read,
        "pdf.inspect.structure": _parse_inspect,
        "pdf.create": _parse_create,
        "pdf.edit": _parse_edit,
        "pdf.rewrite.apply": _parse_rewrite,
    }[operation](arguments)
    return ParsedPdfRequest(operation, input_path, output_path, parsed, fidelity)


def _parse_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {
        "include_annotations", "include_forms", "include_embedded_files",
        "max_pages", "max_blocks_per_page",
    })
    return {
        "include_annotations": _boolean(value.get("include_annotations", True), "include_annotations"),
        "include_forms": _boolean(value.get("include_forms", True), "include_forms"),
        "include_embedded_files": _boolean(value.get("include_embedded_files", True), "include_embedded_files"),
        "max_pages": _integer(value.get("max_pages", MAX_PAGES), 1, MAX_PAGES),
        "max_blocks_per_page": _integer(
            value.get("max_blocks_per_page", MAX_BLOCKS_PER_PAGE), 1, MAX_BLOCKS_PER_PAGE
        ),
    }


def _parse_inspect(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_hashes", "max_objects", "max_streams"})
    return {
        "include_hashes": _boolean(value.get("include_hashes", True), "include_hashes"),
        "max_objects": _integer(value.get("max_objects", 50_000), 1, 2_000_000),
        "max_streams": _integer(value.get("max_streams", 10_000), 1, 100_000),
    }


def _parse_create(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"document"})
    document = value.get("document")
    if type(document) is not dict:
        _invalid("create requires a document object.", field="document")
    return {"document": _parse_document(document)}


def _parse_edit(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"primitives", "expected_edits"})
    primitives = value.get("primitives")
    if type(primitives) is not list or not primitives or len(primitives) > MAX_EDIT_PRIMITIVES:
        _invalid("primitives must be a non-empty bounded array.", field="primitives")
    parsed_primitives = []
    for index, primitive in enumerate(primitives):
        if type(primitive) is not dict:
            _invalid("Each primitive must be an object.", field=f"primitives.{index}")
        prim_type = primitive.get("type")
        if prim_type not in EDIT_PRIMITIVES:
            _invalid("Unknown edit primitive type.", field=f"primitives.{index}.type")
        parsed_primitives.append(_parse_primitive(primitive, prim_type, index))
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {"primitives": parsed_primitives, "expected_edits": expected}


def _parse_rewrite(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"blocks", "rewrites", "expected_edits"})
    blocks = value.get("blocks")
    if type(blocks) is not list or not blocks or len(blocks) > MAX_REWRITE_BLOCKS:
        _invalid("blocks must be a non-empty bounded array.", field="blocks")
    parsed_blocks = []
    for index, block in enumerate(blocks):
        if type(block) is not dict:
            _invalid("Each block must be an object.", field=f"blocks.{index}")
        _exact_keys(block, {"page", "bbox", "text", "font", "size", "color"})
        page = _integer(block.get("page", 1), 1, MAX_PAGES)
        bbox = block.get("bbox")
        if type(bbox) is not list or len(bbox) != 4:
            _invalid("block.bbox must be [x0, y0, x1, y1].", field=f"blocks.{index}.bbox")
        text = _text(block.get("text", ""), f"blocks.{index}.text")
        font = _text(block.get("font", "F1"), f"blocks.{index}.font")
        size = _number(block.get("size", 12.0), f"blocks.{index}.size")
        color = block.get("color")
        if color is not None and type(color) is not list:
            _invalid("block.color must be an array.", field=f"blocks.{index}.color")
        parsed_blocks.append({"page": page, "bbox": list(bbox), "text": text, "font": font, "size": size, "color": color})
    rewrites = value.get("rewrites")
    if type(rewrites) is not list or len(rewrites) > len(blocks):
        _invalid("rewrites must be an array not longer than blocks.", field="rewrites")
    parsed_rewrites = []
    for index, rewrite in enumerate(rewrites):
        if type(rewrite) is not dict:
            _invalid("Each rewrite must be an object.", field=f"rewrites.{index}")
        _exact_keys(rewrite, {"block_index", "text"})
        block_index = _integer(rewrite.get("block_index"), 0, len(blocks) - 1)
        rewrite_text = _text(rewrite.get("text", ""), f"rewrites.{index}.text")
        parsed_rewrites.append({"block_index": block_index, "text": rewrite_text})
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {"blocks": parsed_blocks, "rewrites": parsed_rewrites, "expected_edits": expected}


def _parse_document(document: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(document, {"metadata", "page_size", "pages"})
    metadata = document.get("metadata")
    if type(metadata) is not dict:
        _invalid("document.metadata must be an object.", field="metadata")
    _exact_keys(metadata, {"title", "author", "subject"})
    parsed_meta = {
        "title": _text(metadata.get("title", "Elftia PDF"), "metadata.title"),
        "author": _text(metadata.get("author", "Elftia Document Skills"), "metadata.author"),
        "subject": _text(metadata.get("subject", ""), "metadata.subject"),
    }
    page_size = document.get("page_size", "A4")
    if type(page_size) is str:
        if page_size not in {"A4", "Letter", "Legal"}:
            _invalid("page_size must be one of: A4, Letter, Legal.", field="page_size")
    elif type(page_size) is dict:
        _exact_keys(page_size, {"width", "height"})
        page_size = {
            "width": _number(page_size.get("width", 595.276), "page_size.width"),
            "height": _number(page_size.get("height", 841.89), "page_size.height"),
        }
    else:
        _invalid("page_size must be a string or object.", field="page_size")
    pages = document.get("pages")
    if type(pages) is not list or len(pages) < 2 or len(pages) > MAX_PAGES:
        _invalid("document.pages must contain at least 2 pages (bounded).", field="pages")
    parsed_pages = []
    for idx, page in enumerate(pages):
        if type(page) is not dict:
            _invalid(f"Page {idx} must be an object.", field=f"pages.{idx}")
        _exact_keys(page, {"blocks", "metadata"})
        page_blocks = page.get("blocks", [])
        if type(page_blocks) is not list:
            _invalid(f"Page {idx} blocks must be an array.", field=f"pages.{idx}.blocks")
        parsed_page_blocks = []
        for b_idx, block in enumerate(page_blocks):
            if type(block) is not dict:
                _invalid(f"Block must be an object.", field=f"pages.{idx}.blocks.{b_idx}")
            _exact_keys(block, {"type", "text", "style", "table", "image", "shape"})
            block_type = block.get("type")
            if block_type not in {"heading", "paragraph", "table", "image", "vector_shape"}:
                _invalid("Unknown block type.", field=f"pages.{idx}.blocks.{b_idx}.type")
            block_text = _optional_text(block.get("text"), f"pages.{idx}.blocks.{b_idx}.text")
            style = block.get("style")
            if style is not None and type(style) is not dict:
                _invalid("Style must be an object.", field=f"pages.{idx}.blocks.{b_idx}.style")
            table = _parse_block_table(block.get("table"), f"pages.{idx}.blocks.{b_idx}") if block_type == "table" else None
            image = _parse_block_image(block.get("image"), f"pages.{idx}.blocks.{b_idx}") if block_type == "image" else None
            shape = _parse_block_shape(block.get("shape"), f"pages.{idx}.blocks.{b_idx}") if block_type == "vector_shape" else None
            parsed_page_blocks.append({
                "type": block_type, "text": block_text, "style": style,
                "table": table, "image": image, "shape": shape,
            })
        page_metadata = page.get("metadata")
        if page_metadata is not None and type(page_metadata) is not dict:
            _invalid(f"Page {idx} metadata must be an object.", field=f"pages.{idx}.metadata")
        parsed_pages.append({"blocks": parsed_page_blocks, "metadata": page_metadata})
    return {"metadata": parsed_meta, "page_size": page_size, "pages": parsed_pages}


def _parse_block_table(table: Any, field_prefix: str) -> dict[str, Any] | None:
    if table is None:
        return None
    if type(table) is not dict:
        _invalid("table must be an object.", field=f"{field_prefix}.table")
    _exact_keys(table, {"rows"})
    rows = table.get("rows", [])
    if type(rows) is not list or not rows or len(rows) > MAX_TABLE_ROWS:
        _invalid("table.rows must be a non-empty bounded array.", field=f"{field_prefix}.table.rows")
    parsed_rows = []
    for r_idx, row in enumerate(rows):
        if type(row) is not dict:
            _invalid("table row must be an object.", field=f"{field_prefix}.table.rows.{r_idx}")
        _exact_keys(row, {"cells"})
        cells = row.get("cells", [])
        if type(cells) is not list or len(cells) > MAX_TABLE_COLS:
            _invalid("row.cells must be a bounded array.", field=f"{field_prefix}.table.rows.{r_idx}.cells")
        parsed_cells = [_optional_text(c, f"cells.{c_idx}") if c is not None else None for c_idx, c in enumerate(cells)]
        parsed_rows.append({"cells": parsed_cells})
    return {"rows": parsed_rows}


def _parse_block_image(image: Any, field_prefix: str) -> dict[str, Any] | None:
    if image is None:
        return None
    if type(image) is not dict:
        _invalid("image must be an object.", field=f"{field_prefix}.image")
    _exact_keys(image, {"filename", "content_type"})
    return {
        "filename": _text(image.get("filename", "image.png"), f"{field_prefix}.image.filename"),
        "content_type": _text(image.get("content_type", "image/png"), f"{field_prefix}.image.content_type"),
    }


def _parse_block_shape(shape: Any, field_prefix: str) -> dict[str, Any] | None:
    if shape is None:
        return None
    if type(shape) is not dict:
        _invalid("shape must be an object.", field=f"{field_prefix}.shape")
    _exact_keys(shape, {"kind", "x", "y", "width", "height", "stroke", "fill"})
    kind = shape.get("kind")
    if kind not in {"line", "rectangle", "ellipse"}:
        _invalid("shape.kind must be line, rectangle, or ellipse.", field=f"{field_prefix}.shape.kind")
    return {
        "kind": kind,
        "x": _number(shape.get("x", 0.0), f"{field_prefix}.shape.x"),
        "y": _number(shape.get("y", 0.0), f"{field_prefix}.shape.y"),
        "width": _number(shape.get("width", 100.0), f"{field_prefix}.shape.width"),
        "height": _number(shape.get("height", 100.0), f"{field_prefix}.shape.height"),
        "stroke": shape.get("stroke"),
        "fill": shape.get("fill"),
    }


def _parse_primitive(primitive: dict[str, Any], prim_type: str, index: int) -> dict[str, Any]:
    if prim_type == "merge":
        _exact_keys(primitive, {"type", "inputs"})
        inputs = primitive.get("inputs")
        if type(inputs) is not list or len(inputs) < 2 or len(inputs) > 10:
            _invalid("merge.inputs must be 2-10 paths.", field=f"primitives.{index}.inputs")
        return {"type": "merge", "inputs": [_text(p, f"primitives.{index}.inputs") for p in inputs]}
    if prim_type == "split":
        _exact_keys(primitive, {"type", "page_ranges"})
        ranges = primitive.get("page_ranges")
        if type(ranges) is not list or not ranges:
            _invalid("split.page_ranges must be a non-empty array.", field=f"primitives.{index}.page_ranges")
        parsed_ranges = []
        for r_idx, rng in enumerate(ranges):
            if type(rng) is not list or len(rng) != 2:
                _invalid("Each range must be [start, end].", field=f"primitives.{index}.page_ranges.{r_idx}")
            parsed_ranges.append([_integer(rng[0], 1, MAX_PAGES), _integer(rng[1], 1, MAX_PAGES)])
        return {"type": "split", "page_ranges": parsed_ranges}
    if prim_type == "rotate":
        _exact_keys(primitive, {"type", "pages", "degrees"})
        pages = primitive.get("pages")
        if type(pages) is not list or not pages:
            _invalid("rotate.pages must be a non-empty array.", field=f"primitives.{index}.pages")
        degrees = primitive.get("degrees")
        if degrees not in {0, 90, 180, 270, 360}:
            _invalid("rotate.degrees must be 0/90/180/270/360.", field=f"primitives.{index}.degrees")
        return {"type": "rotate", "pages": [_integer(p, 1, MAX_PAGES) for p in pages], "degrees": degrees}
    if prim_type == "watermark":
        _exact_keys(primitive, {"type", "text", "pages", "opacity"})
        text = _text(primitive.get("text", ""), f"primitives.{index}.text")
        pages = primitive.get("pages")
        if type(pages) is not list or not pages:
            _invalid("watermark.pages must be a non-empty array.", field=f"primitives.{index}.pages")
        opacity = primitive.get("opacity", 0.3)
        opacity = _number(opacity, f"primitives.{index}.opacity")
        return {"type": "watermark", "text": text, "pages": [_integer(p, 1, MAX_PAGES) for p in pages], "opacity": opacity}
    # form_fill
    _exact_keys(primitive, {"type", "fields"})
    fields = primitive.get("fields")
    if type(fields) is not dict or not fields:
        _invalid("form_fill.fields must be a non-empty object.", field=f"primitives.{index}.fields")
    parsed_fields = {k: _text(v, f"primitives.{index}.fields.{k}") for k, v in fields.items()}
    return {"type": "form_fill", "fields": parsed_fields}


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PDF operation argument.", unknown=unknown)


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or type(value) is bool or not minimum <= value <= maximum:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            f"Integer must be between {minimum} and {maximum}.",
            status="invalid_request",
        )
    return value


def _number(value: Any, field: str) -> float:
    if (type(value) is not int and type(value) is not float) or type(value) is bool:
        _invalid("Value must be a number.", field=field)
    return float(value)


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
