"""Bounded typed report contract used by DOCX creation.

Only ``blocks`` is required. Tables, images, a running head, a running foot,
extra sections, and metadata are all opt-in: the contract never conjures
content the caller did not ask for, so a plain heading-and-paragraph document
is a first-class request rather than something to be padded out.
"""

from pathlib import Path
from typing import Any

from .constants import MAX_HEADING_LEVEL
from .contracts import (
    _exact_keys,
    _integer,
    _invalid,
    _optional_text,
    _text,
)

MAX_CREATE_CELLS = 8_192
MAX_CREATE_IMAGES = 32
MAX_CREATE_NODES = 10_000
MAX_CREATE_TEXT_BYTES = 524_288


def parse_create(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"report"})
    report = value.get("report")
    if type(report) is not dict:
        _invalid("report must be an object.", field="report")
    _exact_keys(
        report,
        {"blocks", "footer", "header", "image", "metadata", "sections"},
    )
    _enforce_aggregate_budgets(report)
    blocks = _parse_blocks(report.get("blocks"))
    trailing_image = _parse_image(report.get("image"), "report.image")
    inline_images = sum(1 for block in blocks if block["type"] == "image")
    if inline_images + (0 if trailing_image is None else 1) > MAX_CREATE_IMAGES:
        _invalid(
            "Report exceeds the image count limit.",
            budget="report.total_images",
            ceiling=MAX_CREATE_IMAGES,
        )
    return {
        "report": {
            "blocks": blocks,
            "image": trailing_image,
            "header": _story_text(report.get("header"), "report.header"),
            "footer": _story_text(report.get("footer"), "report.footer"),
            "sections": _parse_sections(report.get("sections")),
            "metadata": _parse_metadata(report.get("metadata", {})),
        }
    }


def _enforce_aggregate_budgets(report: dict[str, Any]) -> None:
    """Bound the fully materialized report below the 2 MiB worker envelope."""
    total_nodes = 0
    total_text_bytes = 0
    pending: list[Any] = [report]
    while pending:
        item = pending.pop()
        total_nodes += 1
        if total_nodes > MAX_CREATE_NODES:
            _invalid(
                "Report exceeds the aggregate structured-node limit.",
                budget="report.total_nodes",
                actual=total_nodes,
                ceiling=MAX_CREATE_NODES,
            )
        if type(item) is str:
            total_text_bytes += len(item.encode("utf-8", errors="strict"))
            if total_text_bytes > MAX_CREATE_TEXT_BYTES:
                _invalid(
                    "Report exceeds the aggregate text byte limit.",
                    budget="report.total_text_bytes",
                    actual=total_text_bytes,
                    ceiling=MAX_CREATE_TEXT_BYTES,
                )
        elif type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)

    total_cells = 0
    blocks = report.get("blocks")
    if type(blocks) is list:
        for block in blocks:
            if type(block) is not dict or block.get("type") != "table":
                continue
            rows = block.get("rows")
            if type(rows) is not list:
                continue
            for row in rows:
                if type(row) is list:
                    total_cells += len(row)
                    if total_cells > MAX_CREATE_CELLS:
                        _invalid(
                            "Report exceeds the aggregate table-cell limit.",
                            budget="report.total_cells",
                            actual=total_cells,
                            ceiling=MAX_CREATE_CELLS,
                        )


def _parse_blocks(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or not value or len(value) > 512:
        _invalid("report.blocks must be a non-empty bounded array.")
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(value):
        if type(block) is not dict:
            _invalid("Each block must be an object.", field=f"blocks.{index}")
        kind = block.get("type")
        if kind == "heading":
            _exact_keys(block, {"level", "text", "type"})
            blocks.append(
                {
                    "type": kind,
                    "text": _text(block.get("text"), f"blocks.{index}.text", False),
                    "level": _integer(block.get("level", 1), 1, MAX_HEADING_LEVEL),
                }
            )
        elif kind == "paragraph":
            _exact_keys(block, {"style", "text", "type"})
            style = _optional_text(block.get("style"), f"blocks.{index}.style")
            if style not in {None, "Normal"}:
                _invalid(
                    "Core DOCX supports only the Normal paragraph style.",
                    field=f"blocks.{index}.style",
                )
            blocks.append(
                {
                    "type": kind,
                    "text": _text(block.get("text"), f"blocks.{index}.text"),
                    "style": style,
                }
            )
        elif kind == "table":
            blocks.append(_parse_table(block))
        elif kind == "image":
            _exact_keys(block, {"alt_text", "path", "type", "width_inches"})
            blocks.append(
                {"type": kind, **_image_payload(block, f"blocks.{index}")}
            )
        else:
            _invalid("Unsupported report block type.", field=f"blocks.{index}.type")
    return blocks


def _parse_table(block: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(block, {"rows", "style", "type"})
    style = _optional_text(block.get("style"), "table.style") or "TableGrid"
    if style != "TableGrid":
        _invalid("Core DOCX supports only the TableGrid table style.")
    rows = block.get("rows")
    if type(rows) is not list or not rows or len(rows) > 1_000:
        _invalid("Table rows must be a non-empty bounded array.")
    normalized_rows = []
    width = None
    for row in rows:
        if type(row) is not list or not row or len(row) > 64:
            _invalid("Each table row must be a non-empty bounded array.")
        cells = [_text(cell, "table.cell") for cell in row]
        width = width or len(cells)
        if len(cells) != width:
            _invalid("All table rows must have the same cell count.")
        normalized_rows.append(cells)
    return {
        "type": "table",
        "rows": normalized_rows,
        "style": style,
    }


def _parse_image(value: Any, field: str) -> dict[str, Any] | None:
    """Parse the optional trailing report image; ``None`` means no image."""
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("report.image must be an object when it is provided.", field=field)
    _exact_keys(value, {"alt_text", "path", "width_inches"})
    return _image_payload(value, field)


def _image_payload(value: dict[str, Any], field: str) -> dict[str, Any]:
    raw_path = _text(value.get("path"), f"{field}.path", False)
    if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
        _invalid("Image path must reference a local file.", field=f"{field}.path")
    width = value.get("width_inches", 4)
    if (
        type(width) not in {int, float}
        or isinstance(width, bool)
        or not 0.25 <= width <= 10
    ):
        _invalid(
            "Image width must be between 0.25 and 10 inches.",
            field=f"{field}.width_inches",
        )
    return {
        "path": Path(raw_path).expanduser().resolve(strict=False),
        "alt_text": _text(value.get("alt_text", "Report image"), f"{field}.alt_text"),
        "width_inches": float(width),
    }


def _story_text(value: Any, field: str) -> str | None:
    """Parse an optional header/footer story; ``None`` means no such part."""
    if value is None:
        return None
    return _text(value, field) or None


def _parse_sections(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return [{"orientation": "portrait", "title": None}]
    if type(value) is not list or not 1 <= len(value) <= 32:
        _invalid("report.sections must contain between 1 and 32 sections.")
    sections = []
    for index, section in enumerate(value):
        if type(section) is not dict:
            _invalid("Each section must be an object.")
        _exact_keys(section, {"orientation", "title"})
        orientation = section.get("orientation", "portrait")
        if orientation not in {"portrait", "landscape"}:
            _invalid("Section orientation must be portrait or landscape.")
        sections.append(
            {
                "orientation": orientation,
                "title": _optional_text(section.get("title"), f"sections.{index}.title"),
            }
        )
    return sections


def _parse_metadata(value: Any) -> dict[str, str]:
    if type(value) is not dict:
        _invalid("report.metadata must be an object.")
    _exact_keys(value, {"creator", "keywords", "subject", "title"})
    return {
        field: _text(value.get(field, ""), f"metadata.{field}")
        for field in ("title", "subject", "creator", "keywords")
    }
