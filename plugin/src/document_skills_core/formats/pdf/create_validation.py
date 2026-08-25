"""Request-bound semantic validation for newly created PDFs."""

from collections import Counter
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_bounds_validation import content_box_mismatches as find_content_box_mismatches
from .content_streams import extract_content_stream
from .create_image_validation import actual_image_draws, image_evidence_mismatches
from .create_layout import resolve_page_layout
from .create_mapping import creation_mapping_mismatches
from .create_shape_validation import actual_shape_draws, shape_evidence_mismatches
from .mapping import map_text_blocks
from .object_model import parse_pdf
from .page_tree import PageInfo, walk_pages

_TOLERANCE = 0.02
_TEXT_TOLERANCE = 0.06


def assert_created(
    path: Path,
    document: dict[str, Any],
    creation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require page, text, structure, and image evidence from reopened bytes."""
    model = parse_pdf(path)
    pages = walk_pages(model)
    failures: list[str] = []
    expected_count = len(document.get("pages", []))
    allows_pagination = _allows_pagination(document)
    if len(pages) < expected_count or (
        not allows_pagination and len(pages) != expected_count
    ):
        failures.append("page-count")

    page_box_mismatches = _page_box_mismatches(
        document,
        pages,
        creation,
        allows_pagination=allows_pagination,
    )
    if page_box_mismatches:
        failures.append("page-boxes")

    content_box_mismatches = find_content_box_mismatches(creation, pages)
    if content_box_mismatches:
        failures.append("content-boxes")

    expected_text = _requested_text_counts(document)
    mapped_text = map_text_blocks(model, pages)
    missing_text = _missing_requested_text(document, mapped_text, creation)
    text_evidence_mismatches = _text_evidence_mismatches(mapped_text, creation)
    if missing_text or text_evidence_mismatches:
        failures.append("requested-text")

    image_draws = actual_image_draws(model, pages)
    shape_draws = actual_shape_draws(model, pages)
    expected_structures = _requested_structure_counts(document)
    content = b"\n".join(
        extract_content_stream(model, page.contents, page.page_number)
        for page in pages
    )
    actual_structures = Counter({
        block_type: content.count(f"%DS-BLOCK:{block_type}".encode("ascii"))
        for block_type in expected_structures
    })
    actual_structures["image"] = len(image_draws)
    actual_structures["vector_shape"] = len(shape_draws)
    missing_structures = sorted(
        block_type
        for block_type, count in expected_structures.items()
        if actual_structures[block_type] < count
    )
    mapping_mismatches = creation_mapping_mismatches(creation, pages)
    image_mismatches, image_evidence = image_evidence_mismatches(
        document,
        creation,
        image_draws,
        model,
        pages,
    )
    shape_mismatches, shape_evidence = shape_evidence_mismatches(
        document,
        creation,
        shape_draws,
        candidate_page_count=len(pages),
        dynamic_source_pages=_dynamic_source_pages(document),
        mapped_shape_positions=(
            _mapped_shape_positions(creation)
            if not mapping_mismatches
            else None
        ),
    )
    if missing_structures or image_mismatches or shape_mismatches:
        failures.append("requested-structure")

    if mapping_mismatches:
        failures.append("creation-mapping")

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Created PDF does not satisfy the document contract.",
            details={
                "missing_or_mismatched": failures,
                "page_box_mismatches": page_box_mismatches,
                "content_box_mismatches": content_box_mismatches,
                "missing_text": missing_text,
                "text_evidence_mismatches": text_evidence_mismatches,
                "missing_structures": missing_structures,
                "image_mismatches": image_mismatches,
                "shape_mismatches": shape_mismatches,
                "mapping_mismatches": mapping_mismatches,
            },
        )
    return {
        "pages": len(pages),
        "page_boxes": [list(page.media_box) for page in pages],
        "requested_structure": True,
        "requested_text_blocks": sum(expected_text.values()),
        "verified_text_lines": len(_created_text_evidence(creation)),
        "requested_structure_counts": dict(expected_structures),
        "images": image_evidence,
        "shapes": shape_evidence,
        "mapping": (creation or {}).get("mapping"),
    }


def _allows_pagination(document: dict[str, Any]) -> bool:
    return any(_page_can_expand(page) for page in document.get("pages", []))


def _dynamic_source_pages(document: dict[str, Any]) -> set[int]:
    dynamic: set[int] = set()
    prior_page_can_expand = False
    for page_number, page in enumerate(document.get("pages", []), start=1):
        page_can_expand = _page_can_expand(page)
        if prior_page_can_expand or page_can_expand:
            dynamic.add(page_number)
        prior_page_can_expand = prior_page_can_expand or page_can_expand
    return dynamic


def _page_can_expand(page: dict[str, Any]) -> bool:
    return page.get("overflow_policy") == "paginate" or any(
        block.get("type") == "table"
        and (block.get("table") or {}).get("repeat_header", False)
        for block in page.get("blocks", [])
    )


def _mapped_shape_positions(
    creation: dict[str, Any] | None,
) -> list[tuple[int, int]] | None:
    mapping = (creation or {}).get("mapping")
    pages = mapping.get("pages") if isinstance(mapping, dict) else None
    if not isinstance(pages, list):
        return None
    positions: list[tuple[int, int]] = []
    for page in pages:
        if not isinstance(page, dict) or type(page.get("page")) is not int:
            return None
        blocks = page.get("blocks")
        if not isinstance(blocks, list):
            return None
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "vector_shape":
                block_index = block.get("block_index")
                if type(block_index) is not int or block_index < 0:
                    return None
                positions.append((page["page"], block_index))
    return positions


def _page_box_mismatches(
    document: dict[str, Any],
    pages: list[PageInfo],
    creation: dict[str, Any] | None,
    *,
    allows_pagination: bool,
) -> list[dict[str, Any]]:
    actual = [[page.media_box[2] - page.media_box[0], page.media_box[3] - page.media_box[1]] for page in pages]
    requested = [
        [layout.width, layout.height]
        for page in document.get("pages", [])
        for layout in [resolve_page_layout(document["page_size"], page)]
    ]
    expected = (creation or {}).get("page_sizes")
    if not isinstance(expected, list):
        expected = requested if not allows_pagination else None
    mismatches: list[dict[str, Any]] = []
    if expected is not None and (
        len(expected) != len(actual)
        or any(not _numbers_close(left, right) for left, right in zip(expected, actual))
    ):
        mismatches.append({"expected": expected, "actual": actual})
    if not allows_pagination and (
        len(requested) != len(actual)
        or any(not _numbers_close(left, right) for left, right in zip(requested, actual))
    ):
        mismatches.append({"requested": requested, "actual": actual})
    unexpected_crop = [page.page_number for page in pages if page.crop_box is not None]
    if unexpected_crop:
        mismatches.append({"unexpected_crop_box_pages": unexpected_crop})
    return mismatches


def _text_evidence_mismatches(
    mapped_text: list[Any],
    creation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    expected = _created_text_evidence(creation)
    if not expected:
        return []
    remaining = list(mapped_text)
    mismatches: list[dict[str, Any]] = []
    for record in expected:
        match_index = next(
            (
                index
                for index, block in enumerate(remaining)
                if _text_record_matches(record, block)
            ),
            None,
        )
        if match_index is None:
            mismatches.append({
                "expected": {
                    key: record.get(key)
                    for key in ("page", "block_index", "text", "bbox", "font", "size", "color")
                },
                "candidate": [
                    {
                        "page": block.page,
                        "text": block.text,
                        "bbox": list(block.bbox),
                        "font": block.font_name,
                        "size": block.font_size,
                        "color": list(block.color),
                    }
                    for block in remaining
                    if block.page == record.get("page")
                    and block.text == record.get("text")
                ],
            })
        else:
            remaining.pop(match_index)
    return mismatches


def _text_record_matches(record: dict[str, Any], block: Any) -> bool:
    return (
        block.page == record.get("page")
        and block.text == record.get("text")
        and block.font_name == record.get("font")
        and _numbers_close([block.font_size], [record.get("size")])
        and _numbers_close(list(block.color), record.get("color"))
        and _text_bbox_matches(
            list(block.bbox),
            record.get("bbox"),
            embedded=block.font_name not in {"/F1", "/F2", "/F3", "/F4"},
        )
    )


def _text_bbox_matches(actual: list[float], expected: Any, *, embedded: bool) -> bool:
    if not isinstance(expected, (list, tuple)) or len(expected) != 4:
        return False
    indexes = (0, 1, 3) if embedded else (0, 1, 2, 3)
    try:
        return all(
            abs(float(actual[index]) - float(expected[index])) <= _TEXT_TOLERANCE
            for index in indexes
        )
    except (TypeError, ValueError):
        return False


def _numbers_close(left: Any, right: Any) -> bool:
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        return False
    if len(left) != len(right):
        return False
    try:
        return all(abs(float(a) - float(b)) <= _TOLERANCE for a, b in zip(left, right))
    except (TypeError, ValueError):
        return False


def _requested_text_counts(document: dict[str, Any]) -> Counter[str]:
    requested: Counter[str] = Counter()
    for page in document.get("pages", []):
        for block in page.get("blocks", []):
            block_type = block.get("type")
            text = block.get("text")
            if block_type in {"heading", "paragraph"} and text:
                requested[text] += 1
            if block_type == "table":
                for row in (block.get("table") or {}).get("rows", []):
                    for cell in row.get("cells", []):
                        if text := _table_cell_text(cell):
                            requested[text] += 1
    return requested


def _missing_requested_text(
    document: dict[str, Any],
    mapped_text: list[Any],
    creation: dict[str, Any] | None,
) -> list[str]:
    page_text = {
        page_number: _normalized_text(" ".join(
            block.text for block in mapped_text if block.page == page_number
        ))
        for page_number in range(1, len(document.get("pages", [])) + 1)
    }
    document_text = _normalized_text(" ".join(block.text for block in mapped_text))
    created_logical = _created_logical_text_counts(creation)
    missing: list[str] = []
    for page_number, page in enumerate(document.get("pages", []), start=1):
        requested_items = _page_requested_text(page)
        for text in requested_items:
            normalized = _normalized_text(text)
            paginated = page.get("overflow_policy") == "paginate" or _is_repeated_header(page, normalized)
            available = document_text if paginated else page_text[page_number]
            if normalized and normalized in available:
                if paginated:
                    document_text = document_text.replace(normalized, "", 1)
                else:
                    page_text[page_number] = available.replace(normalized, "", 1)
            else:
                if created_logical[text] > 0:
                    created_logical[text] -= 1
                else:
                    missing.append(text)
    return sorted(missing)


def _created_text_evidence(
    creation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(creation, dict):
        return []
    records = creation.get("text_blocks")
    combined = list(records) if isinstance(records, list) else []
    tables = creation.get("tables")
    if isinstance(tables, list):
        for table in tables:
            lines = table.get("text_lines") if isinstance(table, dict) else None
            if isinstance(lines, list):
                combined.extend(lines)
    return [record for record in combined if isinstance(record, dict)]


def _created_logical_text_counts(
    creation: dict[str, Any] | None,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    seen_blocks: set[tuple[Any, Any, Any]] = set()
    for record in (creation or {}).get("text_blocks", []):
        if not isinstance(record, dict) or not isinstance(record.get("source_text"), str):
            continue
        identity = (record.get("page"), record.get("block_index"), record["source_text"])
        if identity not in seen_blocks:
            seen_blocks.add(identity)
            counts[record["source_text"]] += 1
    for table in (creation or {}).get("tables", []):
        if not isinstance(table, dict):
            continue
        for cell in table.get("cells", []):
            if isinstance(cell, dict) and isinstance(cell.get("text"), str):
                counts[cell["text"]] += 1
    return counts


def _page_requested_text(page: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for block in page.get("blocks", []):
        if block.get("type") in {"heading", "paragraph"} and block.get("text"):
            items.append(str(block["text"]))
        elif block.get("type") == "table":
            for row in (block.get("table") or {}).get("rows", []):
                items.extend(
                    text
                    for cell in row.get("cells", [])
                    if (text := _table_cell_text(cell))
                )
    return items


def _is_repeated_header(page: dict[str, Any], text: str) -> bool:
    return any(
        block.get("type") == "table"
        and (block.get("table") or {}).get("repeat_header", False)
        and text in {
            _normalized_text(_table_cell_text(cell))
            for row in (block.get("table") or {}).get("rows", [])
            for cell in row.get("cells", [])
        }
        for block in page.get("blocks", [])
    )


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _table_cell_text(cell: Any) -> str:
    if isinstance(cell, dict):
        return str(cell.get("text") or "")
    return "" if cell is None else str(cell)


def _requested_structure_counts(document: dict[str, Any]) -> Counter[str]:
    requested: Counter[str] = Counter()
    for page in document.get("pages", []):
        for block in page.get("blocks", []):
            if block.get("type") in {"table", "image", "vector_shape"}:
                requested[block["type"]] += 1
    return requested
