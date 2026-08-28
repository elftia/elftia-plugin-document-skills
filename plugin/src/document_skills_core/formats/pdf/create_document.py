"""Document-wide text collection and bounded table page expansion."""

import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_PAGES
from .create_layout import PageLayout, resolve_page_layout
from .font_shaping import resolved_style, ShapedLine, TextShaper
from .table_layout import paginate_table_block, table_block_height


def document_text(document: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for page in document["pages"]:
        for block in page.get("blocks", []):
            if block.get("text") is not None:
                texts.append(block["text"])
            table = block.get("table")
            if table is not None:
                for row in table.get("rows", []):
                    texts.extend(
                        _cell_text(cell)
                        for cell in row.get("cells", [])
                        if _cell_text(cell)
                    )
    return texts


def paginate_document_pages(
    pages: list[dict[str, Any]],
    default_page_size: str | dict[str, float],
    shaper: TextShaper,
    spacing: dict[str, float],
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for page in pages:
        blocks = page.get("blocks", [])
        if page.get("overflow_policy") == "paginate":
            expanded.extend(
                _paginate_flow_page(page, default_page_size, shaper, spacing)
            )
        elif (
            len(blocks) == 1
            and blocks[0].get("type") == "table"
            and (blocks[0].get("table") or {}).get("repeat_header")
        ):
            layout = resolve_page_layout(default_page_size, page)
            paginated = paginate_table_block(blocks[0], layout, shaper)
            expanded.extend({**page, "blocks": [block]} for block in paginated)
        else:
            expanded.append(page)
    if len(expanded) > MAX_PAGES:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Paginated PDF exceeds the page limit.",
            status="invalid_request",
            details={"max_pages": MAX_PAGES},
        )
    return expanded


def _paginate_flow_page(
    page: dict[str, Any],
    default_page_size: str | dict[str, float],
    shaper: TextShaper,
    spacing: dict[str, float],
) -> list[dict[str, Any]]:
    blocks = page.get("blocks", [])
    layout = resolve_page_layout(default_page_size, page)
    widow_lines = int(page["widow_lines"])
    orphan_lines = int(page["orphan_lines"])
    pages: list[dict[str, Any]] = []
    current_blocks: list[dict[str, Any]] = []
    baseline = layout.height - layout.top

    def finish_page() -> None:
        nonlocal current_blocks, baseline
        pages.append({**page, "blocks": current_blocks})
        current_blocks = []
        baseline = layout.height - layout.top

    for block_index, block in enumerate(blocks):
        block_type = block["type"]
        if block_type == "vector_shape":
            current_blocks.append(block)
            continue
        if block_type == "image":
            required_height = float(block["image"]["height"])
            _ensure_fixed_block_fits_page(
                required_height,
                layout,
                block_type="image",
                block_index=block_index,
            )
            if baseline - required_height < layout.bottom:
                finish_page()
            current_blocks.append(block)
            baseline -= required_height + spacing["image_gap"]
            continue
        if block_type == "table":
            height = table_block_height(block, layout, shaper)
            if height <= baseline - layout.bottom:
                current_blocks.append(block)
                baseline -= height + spacing["table_gap"]
                continue
            full_height = layout.height - layout.top - layout.bottom
            if height <= full_height:
                finish_page()
                current_blocks.append(block)
                baseline -= height + spacing["table_gap"]
                continue
            if not (block.get("table") or {}).get("repeat_header"):
                _raise_fixed_block_overflow(
                    height,
                    full_height,
                    block_type="table",
                    block_index=block_index,
                )
            if current_blocks:
                finish_page()
            table_pages = paginate_table_block(block, layout, shaper)
            for table_page_index, table_block in enumerate(table_pages):
                current_blocks.append(table_block)
                baseline -= (
                    table_block_height(table_block, layout, shaper)
                    + spacing["table_gap"]
                )
                if table_page_index < len(table_pages) - 1:
                    finish_page()
            continue

        style = resolved_style(block["type"], block.get("style"))
        lines = shaper.wrap_and_shape(
            block.get("text") or "",
            style,
            layout.content_width,
        )
        remaining = list(lines)
        while remaining:
            baseline = min(
                baseline,
                layout.height - layout.top - style["font_size"] * 0.8,
            )
            capacity = _line_capacity(
                baseline,
                layout.bottom,
                style["font_size"],
                style["line_height"],
            )
            if capacity <= 0:
                if current_blocks:
                    finish_page()
                    continue
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "Text cannot fit inside the page content box.",
                    status="invalid_request",
                    details={
                        "block_index": block_index,
                        "font_size": style["font_size"],
                        "line_height": style["line_height"],
                    },
                )
            if (
                len(remaining) > capacity
                and capacity < orphan_lines
                and current_blocks
            ):
                finish_page()
                continue
            if len(remaining) <= capacity:
                current_blocks.append(_text_chunk(block, remaining))
                baseline -= (
                    len(remaining) * style["line_height"]
                    + spacing[f"{block['type']}_gap"]
                )
                remaining = []
                continue

            take = capacity
            if len(remaining) - take < widow_lines:
                take = len(remaining) - widow_lines
            if take < orphan_lines:
                if current_blocks:
                    finish_page()
                    continue
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "Text cannot satisfy the requested widow/orphan policy on this page.",
                    status="invalid_request",
                    details={
                        "widow_lines": widow_lines,
                        "orphan_lines": orphan_lines,
                        "available_lines": capacity,
                        "remaining_lines": len(remaining),
                    },
                )
            current_blocks.append(_text_chunk(block, remaining[:take]))
            remaining = remaining[take:]
            finish_page()
    if current_blocks or not pages:
        finish_page()
    return pages


def _ensure_fixed_block_fits_page(
    required_height: float,
    layout: PageLayout,
    *,
    block_type: str,
    block_index: int,
) -> None:
    available_height = layout.height - layout.top - layout.bottom
    if required_height > available_height:
        _raise_fixed_block_overflow(
            required_height,
            available_height,
            block_type=block_type,
            block_index=block_index,
        )


def _raise_fixed_block_overflow(
    required_height: float,
    available_height: float,
    *,
    block_type: str,
    block_index: int,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        f"{block_type.capitalize()} content exceeds the page content box.",
        status="invalid_request",
        details={
            "capability": f"pdf.{block_type}-overflow",
            "block_index": block_index,
            "required_height": round(required_height, 4),
            "available_height": round(available_height, 4),
        },
    )


def _line_capacity(
    baseline: float,
    bottom: float,
    font_size: float,
    line_height: float,
) -> int:
    usable = baseline - font_size * 0.2 - bottom
    if usable < 0:
        return 0
    return math.floor(usable / line_height) + 1


def _text_chunk(
    block: dict[str, Any],
    lines: list[ShapedLine],
) -> dict[str, Any]:
    return {
        **block,
        "text": "\n".join(line.text for line in lines),
    }


def _cell_text(cell: Any) -> str:
    if isinstance(cell, dict):
        return str(cell.get("text") or "")
    return "" if cell is None else str(cell)
