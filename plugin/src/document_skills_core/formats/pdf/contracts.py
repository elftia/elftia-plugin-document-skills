"""Strict bounded argument contracts for accepted PDF operations.

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
from .create_contracts import (
    parse_block_style,
    parse_dash,
    parse_page_margin,
    parse_page_size,
    parse_rgb,
)
from .annotation_contracts import parse_annotation_primitive
from .extract_contracts import parse_images_extract_arguments
from .page_contracts import parse_page_labels_primitive, parse_page_sequence_primitive
from .optional_provider_contracts import parse_optional_provider_arguments
from .provider_contracts import parse_provider_arguments
from .redaction_contracts import parse_redact_text_primitive
from .table_contracts import parse_table_extract_arguments

PDF_OPERATIONS = frozenset(
    {
        "pdf.read",
        "pdf.inspect.structure",
        "pdf.create",
        "pdf.edit",
        "pdf.rewrite.apply",
        "pdf.images.extract",
        "pdf.encrypt",
        "pdf.decrypt",
        "pdf.compress",
        "pdf.render",
        "pdf.ocr",
        "pdf.table.extract",
    }
)

EDIT_PRIMITIVES = frozenset({
    "merge",
    "split",
    "rotate",
    "watermark",
    "form_fill",
    "metadata_update",
    "outline",
    "annotation",
    "page_sequence",
    "page_labels",
    "redact_text",
})


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
    if operation in {"pdf.read", "pdf.inspect.structure", "pdf.table.extract"}:
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
    expected_output_suffix = (
        ".zip"
        if operation in {"pdf.images.extract", "pdf.render", "pdf.ocr"}
        else ".pdf"
    )
    if output_path is not None and output_path.suffix.casefold() != expected_output_suffix:
        _invalid(
            f"PDF operation output path must use the {expected_output_suffix} extension.",
            field="output",
        )
    if operation in PDF_OPERATIONS - {"pdf.read", "pdf.inspect.structure"}:
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
        "pdf.images.extract": parse_images_extract_arguments,
        "pdf.encrypt": lambda value: parse_provider_arguments("pdf.encrypt", value),
        "pdf.decrypt": lambda value: parse_provider_arguments("pdf.decrypt", value),
        "pdf.compress": lambda value: parse_provider_arguments("pdf.compress", value),
        "pdf.render": lambda value: parse_optional_provider_arguments("pdf.render", value),
        "pdf.ocr": lambda value: parse_optional_provider_arguments("pdf.ocr", value),
        "pdf.table.extract": parse_table_extract_arguments,
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
        _require_lossless_text(
            rewrite_text,
            f"rewrites.{index}.text",
            encoding="latin-1",
        )
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
    for field, text in parsed_meta.items():
        _require_lossless_text(text, f"metadata.{field}", encoding="ascii")
    page_size = parse_page_size(document.get("page_size", "A4"), "page_size")
    assert page_size is not None
    pages = document.get("pages")
    if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
        _invalid("document.pages must contain 1 to the bounded maximum pages.", field="pages")
    parsed_pages = []
    for idx, page in enumerate(pages):
        if type(page) is not dict:
            _invalid(f"Page {idx} must be an object.", field=f"pages.{idx}")
        _exact_keys(page, {"blocks", "metadata", "allow_blank", "size", "margin"})
        page_specific_size = parse_page_size(
            page.get("size"),
            f"pages.{idx}.size",
            optional=True,
        )
        page_margin = parse_page_margin(
            page.get("margin"),
            f"pages.{idx}.margin",
            page_specific_size or page_size,
        )
        page_blocks = page.get("blocks", [])
        if type(page_blocks) is not list:
            _invalid(f"Page {idx} blocks must be an array.", field=f"pages.{idx}.blocks")
        allow_blank = _boolean(
            page.get("allow_blank", False),
            f"pages.{idx}.allow_blank",
        )
        if not page_blocks and not allow_blank:
            _invalid(
                "A page without blocks requires allow_blank: true.",
                field=f"pages.{idx}.allow_blank",
            )
        parsed_page_blocks = []
        for b_idx, block in enumerate(page_blocks):
            if type(block) is not dict:
                _invalid(f"Block must be an object.", field=f"pages.{idx}.blocks.{b_idx}")
            _exact_keys(block, {"type", "text", "style", "table", "image", "shape"})
            block_type = block.get("type")
            if block_type not in {"heading", "paragraph", "table", "image", "vector_shape"}:
                _invalid("Unknown block type.", field=f"pages.{idx}.blocks.{b_idx}.type")
            block_text = _optional_text(block.get("text"), f"pages.{idx}.blocks.{b_idx}.text")
            if block_text is not None:
                _require_lossless_text(
                    block_text,
                    f"pages.{idx}.blocks.{b_idx}.text",
                    encoding="latin-1",
                )
            style = parse_block_style(
                block.get("style"),
                f"pages.{idx}.blocks.{b_idx}.style",
            )
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
        parsed_pages.append({
            "blocks": parsed_page_blocks,
            "metadata": page_metadata,
            "allow_blank": allow_blank,
            "size": page_specific_size,
            "margin": page_margin,
        })
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
        for c_idx, cell in enumerate(parsed_cells):
            if cell is not None:
                _require_lossless_text(
                    cell,
                    f"{field_prefix}.table.rows.{r_idx}.cells.{c_idx}",
                    encoding="latin-1",
                )
        parsed_rows.append({"cells": parsed_cells})
    return {"rows": parsed_rows}


def _parse_block_image(image: Any, field_prefix: str) -> dict[str, Any] | None:
    if image is None:
        _invalid("image must be an object.", field=f"{field_prefix}.image")
    if type(image) is not dict:
        _invalid("image must be an object.", field=f"{field_prefix}.image")
    if not image:
        _invalid(
            "image must be a non-empty bounded request.",
            field=f"{field_prefix}.image",
        )
    _exact_keys(
        image,
        {"filename", "content_type", "fit", "width", "height", "alt"},
    )
    if not {"filename", "content_type"}.issubset(image):
        _invalid(
            "image must include filename and content_type.",
            field=f"{field_prefix}.image",
        )
    filename = _text(
        image.get("filename"),
        f"{field_prefix}.image.filename",
        allow_empty=False,
    )
    if "://" in filename or filename.casefold().startswith(("data:", "file:")):
        _invalid(
            "image.filename must be a local filesystem path, not a URL.",
            field=f"{field_prefix}.image.filename",
        )
    content_type = _text(
        image.get("content_type"),
        f"{field_prefix}.image.content_type",
        allow_empty=False,
    )
    if content_type not in {"image/png", "image/jpeg"}:
        _invalid(
            "image.content_type must be image/png or image/jpeg.",
            field=f"{field_prefix}.image.content_type",
        )
    fit = image.get("fit", "contain")
    if fit not in {"contain", "cover", "stretch"}:
        _invalid(
            "image.fit must be contain, cover, or stretch.",
            field=f"{field_prefix}.image.fit",
        )
    return {
        "filename": str(Path(filename).expanduser().resolve(strict=False)),
        "content_type": content_type,
        "fit": fit,
        "width": _bounded_number(
            image.get("width", 200.0),
            f"{field_prefix}.image.width",
            1.0,
            2_000.0,
        ),
        "height": _bounded_number(
            image.get("height", 100.0),
            f"{field_prefix}.image.height",
            1.0,
            2_000.0,
        ),
        "alt": _optional_text(
            image.get("alt"),
            f"{field_prefix}.image.alt",
        ),
    }


def _parse_block_shape(shape: Any, field_prefix: str) -> dict[str, Any] | None:
    if shape is None:
        return None
    if type(shape) is not dict:
        _invalid("shape must be an object.", field=f"{field_prefix}.shape")
    _exact_keys(
        shape,
        {
            "kind", "x", "y", "width", "height", "stroke", "fill",
            "opacity", "dash",
        },
    )
    kind = shape.get("kind")
    if kind not in {"line", "rectangle", "ellipse"}:
        _invalid("shape.kind must be line, rectangle, or ellipse.", field=f"{field_prefix}.shape.kind")
    return {
        "kind": kind,
        "x": _number(shape.get("x", 0.0), f"{field_prefix}.shape.x"),
        "y": _number(shape.get("y", 0.0), f"{field_prefix}.shape.y"),
        "width": _bounded_number(shape.get("width", 100.0), f"{field_prefix}.shape.width", 0.01, 2_000.0),
        "height": _bounded_number(shape.get("height", 100.0), f"{field_prefix}.shape.height", 0.01, 2_000.0),
        "stroke": parse_rgb(shape.get("stroke"), f"{field_prefix}.shape.stroke"),
        "fill": parse_rgb(shape.get("fill"), f"{field_prefix}.shape.fill"),
        "opacity": _bounded_number(shape.get("opacity", 1.0), f"{field_prefix}.shape.opacity", 0.0, 1.0),
        "dash": parse_dash(shape.get("dash"), f"{field_prefix}.shape.dash"),
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
        _exact_keys(
            primitive,
            {
                "type", "text", "image", "pages", "opacity", "rotation",
                "font", "size", "color", "position",
            },
        )
        has_text = primitive.get("text") is not None
        has_image = primitive.get("image") is not None
        if has_text == has_image:
            _invalid(
                "watermark requires exactly one of text or image.",
                field=f"primitives.{index}",
            )
        text = None
        image = None
        if has_text:
            text = _text(
                primitive.get("text"),
                f"primitives.{index}.text",
                allow_empty=False,
            )
            _require_lossless_text(
                text,
                f"primitives.{index}.text",
                encoding="latin-1",
            )
        else:
            image = _parse_block_image(
                primitive.get("image"),
                f"primitives.{index}",
            )
        pages = primitive.get("pages")
        if type(pages) is not list or not pages:
            _invalid("watermark.pages must be a non-empty array.", field=f"primitives.{index}.pages")
        opacity = _bounded_number(
            primitive.get("opacity", 0.3),
            f"primitives.{index}.opacity",
            0.0,
            1.0,
        )
        rotation = _bounded_number(
            primitive.get("rotation", 45.0 if has_text else 0.0),
            f"primitives.{index}.rotation",
            -360.0,
            360.0,
        )
        position = _parse_watermark_position(
            primitive.get("position", "center"),
            f"primitives.{index}.position",
        )
        font = None
        size = None
        color = None
        if has_text:
            font = _text(
                primitive.get("font", "Helvetica"),
                f"primitives.{index}.font",
                allow_empty=False,
            )
            if font != "Helvetica":
                _enhancement(
                    "Only Helvetica is available for Core text watermarks.",
                    field=f"primitives.{index}.font",
                    capability="pdf.watermark-font",
                )
            size = _bounded_number(
                primitive.get("size", 48.0),
                f"primitives.{index}.size",
                1.0,
                512.0,
            )
            color = parse_rgb(
                primitive.get("color", [0.7, 0.7, 0.7]),
                f"primitives.{index}.color",
            )
        elif any(key in primitive for key in ("font", "size", "color")):
            _invalid(
                "font, size, and color apply only to text watermarks.",
                field=f"primitives.{index}",
            )
        return {
            "type": "watermark",
            "text": text,
            "image": image,
            "pages": [_integer(p, 1, MAX_PAGES) for p in pages],
            "opacity": opacity,
            "rotation": rotation,
            "font": font,
            "size": size,
            "color": color,
            "position": position,
        }
    if prim_type == "metadata_update":
        _exact_keys(primitive, {"type", "metadata"})
        metadata = primitive.get("metadata")
        if type(metadata) is not dict or not metadata:
            _invalid(
                "metadata_update.metadata must be a non-empty object.",
                field=f"primitives.{index}.metadata",
            )
        _exact_keys(metadata, {"title", "author", "subject", "keywords"})
        parsed_metadata = {
            key: _text(value, f"primitives.{index}.metadata.{key}")
            for key, value in metadata.items()
        }
        for key, value in parsed_metadata.items():
            _require_lossless_text(
                value,
                f"primitives.{index}.metadata.{key}",
                encoding="latin-1",
            )
        return {"type": "metadata_update", "metadata": parsed_metadata}
    if prim_type == "outline":
        return _parse_outline_primitive(primitive, index)
    if prim_type == "annotation":
        return parse_annotation_primitive(primitive, index)
    if prim_type == "page_sequence":
        return parse_page_sequence_primitive(primitive, index)
    if prim_type == "page_labels":
        return parse_page_labels_primitive(primitive, index)
    if prim_type == "redact_text":
        return parse_redact_text_primitive(primitive, index)
    # form_fill
    _exact_keys(primitive, {"type", "fields", "flatten"})
    fields = primitive.get("fields")
    if type(fields) is not dict or not fields:
        _invalid("form_fill.fields must be a non-empty object.", field=f"primitives.{index}.fields")
    parsed_fields: dict[str, str | bool] = {}
    for key, value in fields.items():
        field_name = _text(key, f"primitives.{index}.fields", allow_empty=False)
        if type(value) is bool:
            parsed_fields[field_name] = value
        else:
            parsed_fields[field_name] = _text(
                value,
                f"primitives.{index}.fields.{field_name}",
            )
    return {
        "type": "form_fill",
        "fields": parsed_fields,
        "flatten": _boolean(
            primitive.get("flatten", False),
            f"primitives.{index}.flatten",
        ),
    }


def _parse_outline_primitive(
    primitive: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    _exact_keys(
        primitive,
        {"type", "action", "index", "expected_title", "title", "page"},
    )
    field = f"primitives.{index}"
    action = primitive.get("action")
    if action not in {"add", "update", "delete"}:
        _invalid("outline.action must be add, update, or delete.", field=f"{field}.action")
    title = primitive.get("title")
    if title is not None:
        title = _text(title, f"{field}.title", allow_empty=False)
        _require_lossless_text(title, f"{field}.title", encoding="latin-1")
    expected_title = primitive.get("expected_title")
    if expected_title is not None:
        expected_title = _text(
            expected_title,
            f"{field}.expected_title",
            allow_empty=False,
        )
        _require_lossless_text(
            expected_title,
            f"{field}.expected_title",
            encoding="latin-1",
        )
    page = primitive.get("page")
    if page is not None:
        page = _integer(page, 1, MAX_PAGES)
    outline_index = primitive.get("index")
    if outline_index is not None:
        outline_index = _integer(outline_index, 1, 10_000)
    if action == "add":
        if title is None or page is None or outline_index is not None or expected_title is not None:
            _invalid("outline add requires title/page and does not accept index fields.", field=field)
    elif action == "update":
        if outline_index is None or (title is None and page is None):
            _invalid("outline update requires index and at least one of title/page.", field=field)
    elif outline_index is None or title is not None or page is not None:
        _invalid("outline delete requires index and does not accept title/page.", field=field)
    return {
        "type": "outline",
        "action": action,
        "index": outline_index,
        "expected_title": expected_title,
        "title": title,
        "page": page,
    }


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PDF operation argument.", unknown=unknown)


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _parse_watermark_position(value: Any, field: str) -> str | dict[str, float]:
    if type(value) is str:
        if value not in {
            "center", "top-left", "top-right", "bottom-left", "bottom-right",
        }:
            _invalid("Unknown watermark position.", field=field)
        return value
    if type(value) is not dict:
        _invalid("Watermark position must be a named position or x/y object.", field=field)
    _exact_keys(value, {"x", "y"})
    if set(value) != {"x", "y"}:
        _invalid("Watermark x/y position requires both coordinates.", field=field)
    return {
        "x": _bounded_number(value["x"], f"{field}.x", -10_000.0, 10_000.0),
        "y": _bounded_number(value["y"], f"{field}.y", -10_000.0, 10_000.0),
    }


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


def _bounded_number(value: Any, field: str, minimum: float, maximum: float) -> float:
    number = _number(value, field)
    if not minimum <= number <= maximum:
        _invalid(
            f"Value must be between {minimum} and {maximum}.",
            field=field,
        )
    return number


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


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )


def _require_lossless_text(text: str, field: str, *, encoding: str) -> None:
    try:
        text.encode(encoding, errors="strict")
    except UnicodeEncodeError as error:
        _enhancement(
            "Requested PDF text is not representable by the active Core font path.",
            field=field,
            capability="pdf.lossless-text",
            encoding=encoding,
            codepoint=f"U+{ord(text[error.start]):04X}",
        )
