"""Explicitly low-confidence geometric stream heuristic for PDF tables."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
from .byte_preflight import PdfByteLimits, preflight_pdf
from .content_streams import extract_content_stream, TextBlock
from .mapping import map_text_blocks
from .object_model import parse_pdf
from .page_tree import PageInfo, walk_pages
from .table_lattice import extract_lattice_tables

_CONFIDENCE = 0.35
_CONFIDENCE_CEILING = 0.4


def extract_pdf_tables(source: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limits = PdfByteLimits()
    preflight = preflight_pdf(source, limits)
    if preflight.encrypted:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Explicit decryption is required before table extraction.",
        )
    model = parse_pdf(source, limits)
    actions = classify_actions(model)
    if has_dangerous_actions(actions) or has_executable_embedded_files(model):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF contains active or executable content and is rejected in normal mode.",
        )
    pages = _select_pages(walk_pages(model), arguments["pages"])
    blocks = map_text_blocks(model, pages, max_blocks_per_page=5_000)
    tables: list[dict[str, Any]] = []
    for page in pages:
        page_blocks = [block for block in blocks if block.page == page.page_number and block.text]
        content = extract_content_stream(model, page.contents, page.page_number)
        lattice_tables, ruled_blocks = extract_lattice_tables(
            content,
            page.page_number,
            page_blocks,
            min_rows=arguments["min_rows"],
            min_columns=arguments["min_columns"],
        )
        page_tables = lattice_tables
        heuristic_blocks = [
            block for block in page_blocks if id(block) not in ruled_blocks
        ]
        rows = _geometric_rows(heuristic_blocks, arguments["min_columns"])
        for group in _row_groups(rows):
            if len(group) < arguments["min_rows"]:
                continue
            page_tables.append(_project_table(0, page.page_number, group))
        page_tables.sort(key=lambda table: (-float(table["bbox"][3]), float(table["bbox"][0])))
        for table in page_tables:
            table["index"] = len(tables) + 1
            tables.append(table)
            if len(tables) == arguments["max_tables"]:
                break
        if len(tables) >= arguments["max_tables"]:
            break
    tables = _merge_repeated_header_tables(tables)
    sources = {table["source"] for table in tables}
    result_source = (
        "core-mixed-table-extraction"
        if len(sources) > 1
        else next(iter(sources), "core-stream-heuristic")
    )
    return {
        "source": result_source,
        "confidence_ceiling": 0.95 if "core-lattice" in sources else _CONFIDENCE_CEILING,
        "selected_pages": [page.page_number for page in pages],
        "table_count": len(tables),
        "tables": tables,
        "limitations": [
            "Text bboxes are approximate and derived from content-stream operators.",
            "Lattice inference is limited to axis-aligned stroked m/l/h ruling paths; re rectangles, curves, filled-only rules, and rotated or skewed paths use the low-confidence text heuristic.",
            "Merged cells are inferred only when missing internal rulings form a rectangular row/column span.",
            "Cross-page continuity is inferred only for adjacent tables with matching repeated headers and column anchors.",
            "Text-only stream heuristic results are deliberately capped at low confidence.",
        ],
    }


def _select_pages(
    pages: list[PageInfo],
    requested: list[int] | None,
) -> list[PageInfo]:
    if requested is None:
        return pages
    by_number = {page.page_number: page for page in pages}
    missing = [page for page in requested if page not in by_number]
    if missing:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Requested table extraction page is outside the document.",
            status="invalid_request",
            details={"pages": missing, "page_count": len(pages)},
        )
    return [by_number[page] for page in requested]


def _geometric_rows(
    blocks: list[TextBlock],
    min_columns: int,
) -> list[list[TextBlock]]:
    ordered = sorted(blocks, key=lambda block: (-_center_y(block), block.bbox[0]))
    grouped: list[list[TextBlock]] = []
    centers: list[float] = []
    for block in ordered:
        center = _center_y(block)
        if grouped and abs(center - centers[-1]) <= max(2.0, block.font_size * 0.25):
            grouped[-1].append(block)
            centers[-1] = sum(_center_y(item) for item in grouped[-1]) / len(grouped[-1])
        else:
            grouped.append([block])
            centers.append(center)
    return [
        sorted(row, key=lambda block: block.bbox[0])
        for row in grouped
        if len(row) >= min_columns
    ]


def _row_groups(rows: list[list[TextBlock]]) -> list[list[list[TextBlock]]]:
    groups: list[list[list[TextBlock]]] = []
    for row in rows:
        if not groups:
            groups.append([row])
            continue
        previous = groups[-1][-1]
        same_columns = len(previous) == len(row)
        vertical_gap = abs(_row_center(previous) - _row_center(row))
        max_height = max(_row_height(previous), _row_height(row), 1.0)
        if same_columns and vertical_gap <= max(60.0, max_height * 4.0):
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def _project_table(
    index: int,
    page: int,
    rows: list[list[TextBlock]],
) -> dict[str, Any]:
    all_blocks = [block for row in rows for block in row]
    return {
        "index": index,
        "page": page,
        "pages": [page],
        "bbox": _bbox(all_blocks),
        "source": "core-stream-heuristic",
        "confidence": _CONFIDENCE,
        "cross_page": False,
        "rows": [
            {
                "bbox": _bbox(row),
                "cells": [
                    {
                        "text": block.text,
                        "bbox": list(block.bbox),
                        "confidence": _CONFIDENCE,
                    }
                    for block in row
                ],
            }
            for row in rows
        ],
    }


def _merge_repeated_header_tables(
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for table in tables:
        if merged and _is_repeated_header_continuation(merged[-1], table):
            previous = merged[-1]
            previous["pages"].append(table["page"])
            previous["cross_page"] = True
            previous.setdefault("continuations", []).append({
                "page": table["page"],
                "bbox": table["bbox"],
                "repeated_header": True,
            })
            previous["rows"].extend(table["rows"][1:])
            continue
        merged.append({
            **table,
            "continuations": [],
        })
    for index, table in enumerate(merged, start=1):
        table["index"] = index
    return merged


def _is_repeated_header_continuation(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    if current["source"] != previous["source"]:
        return False
    if current["page"] != previous["pages"][-1] + 1:
        return False
    previous_rows = previous["rows"]
    current_rows = current["rows"]
    if not previous_rows or not current_rows:
        return False
    previous_header = previous_rows[0]["cells"]
    current_header = current_rows[0]["cells"]
    if len(previous_header) != len(current_header):
        return False
    for old, new in zip(previous_header, current_header, strict=True):
        if old["text"] != new["text"]:
            return False
        if abs(float(old["bbox"][0]) - float(new["bbox"][0])) > 3.0:
            return False
    return True


def _bbox(blocks: list[TextBlock]) -> list[float]:
    return [
        min(block.bbox[0] for block in blocks),
        min(block.bbox[1] for block in blocks),
        max(block.bbox[2] for block in blocks),
        max(block.bbox[3] for block in blocks),
    ]


def _center_y(block: TextBlock) -> float:
    return (block.bbox[1] + block.bbox[3]) / 2.0


def _row_center(row: list[TextBlock]) -> float:
    return sum(_center_y(block) for block in row) / len(row)


def _row_height(row: list[TextBlock]) -> float:
    box = _bbox(row)
    return box[3] - box[1]
