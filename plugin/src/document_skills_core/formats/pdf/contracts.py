"""Strict bounded argument contracts for accepted PDF operations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import (
    MAX_BLOCKS_PER_PAGE,
    MAX_EDIT_PRIMITIVES,
    MAX_PAGES,
    MAX_REWRITE_BLOCKS,
)
from .contract_utils import (
    boolean as _boolean,
    bounded_number as _bounded_number,
    exact_keys as _exact_keys,
    integer as _integer,
    invalid as _invalid,
    number as _number,
    optional_path as _optional_path,
    text as _text,
)
from .create_contracts import parse_block_style
from .document_contracts import parse_document
from .edit_contracts import parse_edit_primitive
from .extract_contracts import parse_images_extract_arguments
from .font_contracts import parse_font_assets, parse_sha256, require_unicode_font
from .optional_provider_contracts import parse_optional_provider_arguments
from .provider_contracts import parse_provider_arguments
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
    "page_insert",
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
    secrets = request.get("secrets", {})
    if type(secrets) is not dict:
        _invalid("PDF secrets must be an object.", field="secrets")
    arguments = _bind_provider_secrets(operation, arguments, secrets)
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
        if in_place or (
            input_path is not None
            and output_path is not None
            and same_path(input_path, output_path)
        ):
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
    if operation == "pdf.edit" and input_path is not None:
        for index, primitive in enumerate(parsed["primitives"]):
            if primitive["type"] != "merge":
                continue
            primary = Path(primitive["inputs"][0]["input"])
            if not same_path(input_path, primary):
                _invalid(
                    "The first merge input must match the top-level input path.",
                    field=f"primitives.{index}.inputs.0.input",
                )
    return ParsedPdfRequest(operation, input_path, output_path, parsed, fidelity)


def _bind_provider_secrets(
    operation: str,
    arguments: dict[str, Any],
    secrets: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        "pdf.encrypt": {"user_password", "owner_password"},
        "pdf.decrypt": {"password"},
    }.get(operation, set())
    leaked = sorted(set(arguments) & {"user_password", "owner_password", "password"})
    if leaked:
        _invalid(
            "PDF passwords must be supplied through the top-level secrets field.",
            field="arguments",
            unknown=leaked,
        )
    unknown = sorted(set(secrets) - expected)
    if unknown:
        _invalid("Unknown PDF secret field.", field="secrets", unknown=unknown)
    if secrets and not expected:
        _invalid("This PDF operation does not accept secrets.", field="secrets")
    return {**arguments, **secrets}


def _parse_read(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {
        "include_annotations", "include_forms", "include_embedded_files",
        "max_pages", "max_blocks_per_page", "pages", "bbox",
        "reading_order", "column_count",
    })
    pages = value.get("pages")
    if pages is not None:
        if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
            _invalid("pages must be a non-empty bounded array.", field="pages")
        pages = [_integer(page, 1, MAX_PAGES) for page in pages]
        if len(set(pages)) != len(pages):
            _invalid("pages must not contain duplicates.", field="pages")
    bbox = value.get("bbox")
    if bbox is not None:
        if type(bbox) is not list or len(bbox) != 4:
            _invalid("bbox must be [x0, y0, x1, y1].", field="bbox")
        bbox = [
            _bounded_number(item, f"bbox.{index}", -100_000.0, 100_000.0)
            for index, item in enumerate(bbox)
        ]
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            _invalid("bbox must have positive width and height.", field="bbox")
    reading_order = value.get("reading_order", "content_stream")
    if reading_order not in {"content_stream", "geometric", "columns"}:
        _invalid(
            "reading_order must be content_stream, geometric, or columns.",
            field="reading_order",
        )
    column_count = value.get("column_count")
    if column_count is not None:
        column_count = _integer(column_count, 1, 8)
    if reading_order == "columns" and column_count is None:
        column_count = 2
    if reading_order != "columns" and column_count is not None:
        _invalid(
            "column_count is only valid with columns reading order.",
            field="column_count",
        )
    return {
        "include_annotations": _boolean(value.get("include_annotations", True), "include_annotations"),
        "include_forms": _boolean(value.get("include_forms", True), "include_forms"),
        "include_embedded_files": _boolean(value.get("include_embedded_files", True), "include_embedded_files"),
        "max_pages": _integer(value.get("max_pages", MAX_PAGES), 1, MAX_PAGES),
        "max_blocks_per_page": _integer(
            value.get("max_blocks_per_page", MAX_BLOCKS_PER_PAGE),
            1,
            MAX_BLOCKS_PER_PAGE,
        ),
        "pages": pages,
        "bbox": bbox,
        "reading_order": reading_order,
        "column_count": column_count,
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
    return {"document": parse_document(document)}


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
        parsed_primitives.append(parse_edit_primitive(primitive, prim_type, index))
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {"primitives": parsed_primitives, "expected_edits": expected}


def _parse_rewrite(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {"blocks", "rewrites", "expected_edits", "fonts", "source_sha256"},
    )
    fonts = parse_font_assets(value.get("fonts"), "fonts")
    font_ids = {font["id"] for font in fonts}
    source_sha256 = parse_sha256(value.get("source_sha256"), "source_sha256")
    if source_sha256 is None:
        _invalid("source_sha256 is required for PDF rewrite.", field="source_sha256")
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
        parsed_blocks.append({
            "page": page,
            "bbox": list(bbox),
            "text": text,
            "font": font,
            "size": size,
            "color": color,
        })
    rewrites = value.get("rewrites")
    if type(rewrites) is not list or len(rewrites) > len(blocks):
        _invalid("rewrites must be an array not longer than blocks.", field="rewrites")
    parsed_rewrites = []
    for index, rewrite in enumerate(rewrites):
        if type(rewrite) is not dict:
            _invalid("Each rewrite must be an object.", field=f"rewrites.{index}")
        _exact_keys(rewrite, {"block_index", "text", "style"})
        block_index = _integer(rewrite.get("block_index"), 0, len(blocks) - 1)
        rewrite_text = _text(rewrite.get("text", ""), f"rewrites.{index}.text")
        source_block = parsed_blocks[block_index]
        requested_style = rewrite.get("style")
        if requested_style is None:
            style = None
        else:
            if type(requested_style) is not dict:
                _invalid("rewrite.style must be an object.", field=f"rewrites.{index}.style")
            inherited = {
                "font_size": source_block["size"],
                "color": source_block["color"] or [0.0, 0.0, 0.0],
                **requested_style,
            }
            style = parse_block_style(
                inherited,
                f"rewrites.{index}.style",
                font_ids=font_ids,
            )
        require_unicode_font(
            rewrite_text,
            style,
            f"rewrites.{index}.text",
        )
        parsed_rewrites.append({
            "block_index": block_index,
            "text": rewrite_text,
            "style": style,
        })
    expected = value.get("expected_edits")
    if expected is not None:
        expected = _integer(expected, 0, 1_000_000)
    return {
        "blocks": parsed_blocks,
        "rewrites": parsed_rewrites,
        "expected_edits": expected,
        "fonts": fonts,
        "source_sha256": source_sha256,
    }
