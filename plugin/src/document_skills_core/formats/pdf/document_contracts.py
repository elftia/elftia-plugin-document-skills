"""Contracts for declarative PDF documents and their blocks."""

from typing import Any

from .constants import MAX_PAGES
from .contract_utils import (
    boolean as _boolean,
    exact_keys as _exact_keys,
    integer as _integer,
    invalid as _invalid,
    optional_text as _optional_text,
    text as _text,
)
from .create_contracts import parse_page_margin, parse_page_size
from .design_tokens import (
    design_token_page_size,
    merge_block_style,
    parse_design_tokens,
)
from .document_block_contracts import (
    parse_block_image,
    parse_block_shape,
    parse_block_table,
)
from .font_contracts import parse_font_assets, require_unicode_font


def parse_document(document: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        document,
        {"metadata", "page_size", "pages", "fonts", "design_tokens"},
    )
    metadata = document.get("metadata")
    if type(metadata) is not dict:
        _invalid("document.metadata must be an object.", field="metadata")
    _exact_keys(metadata, {"title", "author", "subject"})
    parsed_meta = {
        "title": _text(metadata.get("title", "Elftia PDF"), "metadata.title"),
        "author": _text(metadata.get("author", "Elftia Document Skills"), "metadata.author"),
        "subject": _text(metadata.get("subject", ""), "metadata.subject"),
    }
    fonts = parse_font_assets(document.get("fonts"))
    font_ids = {font["id"] for font in fonts}
    token_page_size = design_token_page_size(document.get("design_tokens"))
    requested_page_size = document.get("page_size")
    page_size = parse_page_size(
        requested_page_size if requested_page_size is not None else token_page_size or "A4",
        "page_size",
    )
    assert page_size is not None
    design_tokens = parse_design_tokens(
        document.get("design_tokens"),
        font_ids=font_ids,
        page_size=page_size,
    )
    pages = document.get("pages")
    if type(pages) is not list or not pages or len(pages) > MAX_PAGES:
        _invalid("document.pages must contain 1 to the bounded maximum pages.", field="pages")
    parsed_pages = []
    for idx, page in enumerate(pages):
        if type(page) is not dict:
            _invalid(f"Page {idx} must be an object.", field=f"pages.{idx}")
        _exact_keys(
            page,
            {
                "blocks",
                "metadata",
                "allow_blank",
                "size",
                "margin",
                "overflow_policy",
                "widow_lines",
                "orphan_lines",
            },
        )
        page_specific_size = parse_page_size(
            page.get("size"),
            f"pages.{idx}.size",
            optional=True,
        )
        page_margin = parse_page_margin(
            page.get("margin"),
            f"pages.{idx}.margin",
            page_specific_size or page_size,
            default_margin=design_tokens["margin"],
        )
        page_blocks = page.get("blocks", [])
        if type(page_blocks) is not list:
            _invalid(f"Page {idx} blocks must be an array.", field=f"pages.{idx}.blocks")
        allow_blank = _boolean(
            page.get("allow_blank", False),
            f"pages.{idx}.allow_blank",
        )
        overflow_policy = page.get("overflow_policy", "error")
        if overflow_policy not in {"error", "paginate"}:
            _invalid(
                "Page overflow_policy must be error or paginate.",
                field=f"pages.{idx}.overflow_policy",
            )
        widow_lines = _integer(page.get("widow_lines", 2), 1, 10)
        orphan_lines = _integer(page.get("orphan_lines", 2), 1, 10)
        if not page_blocks and not allow_blank:
            _invalid(
                "A page without blocks requires allow_blank: true.",
                field=f"pages.{idx}.allow_blank",
            )
        parsed_page_blocks = []
        for b_idx, block in enumerate(page_blocks):
            if type(block) is not dict:
                _invalid("Block must be an object.", field=f"pages.{idx}.blocks.{b_idx}")
            _exact_keys(block, {"type", "text", "style", "table", "image", "shape"})
            block_type = block.get("type")
            if block_type not in {"heading", "paragraph", "table", "image", "vector_shape"}:
                _invalid("Unknown block type.", field=f"pages.{idx}.blocks.{b_idx}.type")
            block_text = _optional_text(block.get("text"), f"pages.{idx}.blocks.{b_idx}.text")
            style = merge_block_style(
                block_type,
                block.get("style"),
                tokens=design_tokens,
                font_ids=font_ids,
                field=f"pages.{idx}.blocks.{b_idx}.style",
            )
            if block_text is not None:
                require_unicode_font(
                    block_text,
                    style,
                    f"pages.{idx}.blocks.{b_idx}.text",
                )
            table = (
                parse_block_table(
                    block.get("table"),
                    f"pages.{idx}.blocks.{b_idx}",
                    style=style,
                    palette=design_tokens["palette"],
                )
                if block_type == "table"
                else None
            )
            image = (
                parse_block_image(block.get("image"), f"pages.{idx}.blocks.{b_idx}")
                if block_type == "image"
                else None
            )
            shape = (
                parse_block_shape(
                    block.get("shape"),
                    f"pages.{idx}.blocks.{b_idx}",
                    palette=design_tokens["palette"],
                )
                if block_type == "vector_shape"
                else None
            )
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
            "overflow_policy": overflow_policy,
            "widow_lines": widow_lines,
            "orphan_lines": orphan_lines,
        })
    return {
        "metadata": parsed_meta,
        "page_size": page_size,
        "fonts": fonts,
        "design_tokens": design_tokens,
        "pages": parsed_pages,
    }
