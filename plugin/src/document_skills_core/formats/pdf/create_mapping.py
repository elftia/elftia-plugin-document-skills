"""Stable page/block-to-object geometry mapping for PDF create results."""

from typing import Any

from .page_tree import PageInfo

_TOLERANCE = 0.02


def build_creation_mapping(
    pages_data: list[dict[str, Any]],
    page_objects: list[int],
    content_objects: list[int],
    page_sizes: list[list[float]],
    *,
    text_blocks: list[dict[str, Any]],
    images: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    shapes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the versioned public mapping in emitted page/block order."""
    pages: list[dict[str, Any]] = []
    evidence = {
        "image": images,
        "table": tables,
        "vector_shape": shapes,
    }
    for page_index, page_data in enumerate(pages_data):
        page_number = page_index + 1
        content_object = content_objects[page_index]
        blocks: list[dict[str, Any]] = []
        for block_index, block in enumerate(page_data.get("blocks", [])):
            block_type = str(block["type"])
            records = (
                _records_for(text_blocks, page_number, block_index)
                if block_type in {"heading", "paragraph"}
                else _records_for(evidence[block_type], page_number, block_index)
            )
            if not records:
                raise ValueError(
                    f"Missing PDF create evidence for page {page_number} block {block_index}"
                )
            blocks.append({
                "block_index": block_index,
                "type": block_type,
                "object": (
                    int(records[0]["image_object"])
                    if block_type == "image"
                    else content_object
                ),
                "bbox": _bbox_union(records),
            })
        width, height = page_sizes[page_index]
        pages.append({
            "page": page_number,
            "page_object": page_objects[page_index],
            "content_stream_object": content_object,
            "bbox": [0.0, 0.0, width, height],
            "blocks": blocks,
        })
    return {"schema_version": "1.0", "pages": pages}


def creation_mapping_mismatches(
    creation: dict[str, Any] | None,
    pages: list[PageInfo],
) -> list[dict[str, Any]]:
    """Check mapping object identities and geometry against reopened pages/evidence."""
    if creation is None:
        return []
    mapping = creation.get("mapping")
    if not isinstance(mapping, dict) or mapping.get("schema_version") != "1.0":
        return [{"reason": "missing-or-invalid-mapping"}]
    mapped_pages = mapping.get("pages")
    if not isinstance(mapped_pages, list) or len(mapped_pages) != len(pages):
        return [{"reason": "page-mapping-count"}]
    mismatches: list[dict[str, Any]] = []
    evidence = {
        "heading": creation.get("text_blocks", []),
        "paragraph": creation.get("text_blocks", []),
        "image": creation.get("images", []),
        "table": creation.get("tables", []),
        "vector_shape": creation.get("shapes", []),
    }
    for page, record in zip(pages, mapped_pages):
        if not isinstance(record, dict):
            mismatches.append({"reason": "invalid-page-mapping", "page": page.page_number})
            continue
        content_objects = [reference.obj_num for reference in page.contents]
        if (
            record.get("page") != page.page_number
            or record.get("page_object") != page.obj_num
            or record.get("content_stream_object") not in content_objects
            or not _bbox_close(record.get("bbox"), list(page.media_box))
        ):
            mismatches.append({"reason": "page-mapping-mismatch", "page": page.page_number})
        blocks = record.get("blocks")
        if not isinstance(blocks, list):
            mismatches.append({"reason": "invalid-block-mapping", "page": page.page_number})
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") not in evidence:
                mismatches.append({"reason": "invalid-block-mapping", "page": page.page_number})
                continue
            block_type = block["type"]
            records = _records_for(
                evidence[block_type],
                page.page_number,
                block.get("block_index"),
            )
            expected_object = (
                records[0].get("image_object")
                if records and block_type == "image"
                else record.get("content_stream_object")
            )
            if (
                not records
                or block.get("object") != expected_object
                or not _bbox_close(block.get("bbox"), _bbox_union(records))
            ):
                mismatches.append({
                    "reason": "block-mapping-mismatch",
                    "page": page.page_number,
                    "block_index": block.get("block_index"),
                })
    return mismatches


def _records_for(
    records: Any,
    page: int,
    block_index: Any,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("page") == page
        and record.get("block_index") == block_index
    ]


def _bbox_union(records: list[dict[str, Any]]) -> list[float]:
    boxes = [record["bbox"] for record in records]
    return [
        min(float(box[0]) for box in boxes),
        min(float(box[1]) for box in boxes),
        max(float(box[2]) for box in boxes),
        max(float(box[3]) for box in boxes),
    ]


def _bbox_close(actual: Any, expected: list[float]) -> bool:
    return (
        isinstance(actual, list)
        and len(actual) == len(expected) == 4
        and all(
            abs(float(left) - float(right)) <= _TOLERANCE
            for left, right in zip(actual, expected)
        )
    )
