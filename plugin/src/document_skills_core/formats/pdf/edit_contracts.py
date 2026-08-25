"""Contracts for PDF edit primitives."""

from typing import Any

from .annotation_contracts import parse_annotation_primitive
from .constants import MAX_PAGES
from .contract_utils import (
    boolean as _boolean,
    bounded_number as _bounded_number,
    enhancement as _enhancement,
    exact_keys as _exact_keys,
    integer as _integer,
    invalid as _invalid,
    require_lossless_text as _require_lossless_text,
    text as _text,
)
from .create_contracts import parse_rgb
from .document_contracts import parse_block_image
from .page_contracts import (
    parse_merge_primitive,
    parse_page_insert_primitive,
    parse_page_labels_primitive,
    parse_page_sequence_primitive,
)
from .redaction_contracts import parse_redact_text_primitive
from .watermark_fonts import SUPPORTED_BASE14_WATERMARK_FONTS


def parse_edit_primitive(
    primitive: dict[str, Any],
    prim_type: str,
    index: int,
) -> dict[str, Any]:
    if prim_type == "merge":
        return parse_merge_primitive(primitive, index)
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
            image = parse_block_image(
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
            if font not in SUPPORTED_BASE14_WATERMARK_FONTS:
                _enhancement(
                    "The requested Core text watermark font is unsupported.",
                    field=f"primitives.{index}.font",
                    capability="pdf.watermark-font",
                    supported_fonts=list(SUPPORTED_BASE14_WATERMARK_FONTS),
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
        return {"type": "metadata_update", "metadata": parsed_metadata}
    if prim_type == "outline":
        return _parse_outline_primitive(primitive, index)
    if prim_type == "annotation":
        return parse_annotation_primitive(primitive, index)
    if prim_type == "page_insert":
        return parse_page_insert_primitive(primitive, index)
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
