"""Request-derived content and table-cell bounds validation."""

from typing import Any

from .create_layout import bbox_within
from .page_tree import PageInfo


def content_box_mismatches(
    creation: dict[str, Any] | None,
    pages: list[PageInfo],
) -> list[dict[str, Any]]:
    if creation is None:
        return []
    boxes = creation.get("content_boxes")
    if not isinstance(boxes, list) or len(boxes) != len(pages):
        return [{"reason": "content-box-count"}]
    mismatches: list[dict[str, Any]] = []
    for page, box in zip(pages, boxes):
        if not _valid_bbox(box) or not bbox_within(box, list(page.media_box)):
            mismatches.append({"reason": "invalid-content-box", "page": page.page_number})
    if mismatches:
        return mismatches
    for kind in ("text_blocks", "images", "tables"):
        records = creation.get(kind, [])
        if not isinstance(records, list):
            mismatches.append({"reason": "invalid-evidence", "kind": kind})
            continue
        for record in records:
            page_number = record.get("page") if isinstance(record, dict) else None
            bbox = record.get("bbox") if isinstance(record, dict) else None
            if (
                type(page_number) is not int
                or page_number < 1
                or page_number > len(boxes)
                or not _valid_bbox(bbox)
                or not bbox_within(bbox, boxes[page_number - 1])
            ):
                mismatches.append({
                    "reason": "evidence-outside-content-box",
                    "kind": kind,
                    "page": page_number,
                    "bbox": bbox,
                })
                continue
            if kind == "tables":
                mismatches.extend(_table_cell_box_mismatches(record))
    return mismatches


def _table_cell_box_mismatches(table: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    table_bbox = table["bbox"]
    cells = table.get("cells")
    if not isinstance(cells, list):
        return [{"reason": "missing-table-cell-evidence", "page": table.get("page")}]
    for cell in cells:
        bbox = cell.get("bbox") if isinstance(cell, dict) else None
        content = cell.get("content_bbox") if isinstance(cell, dict) else None
        lines = cell.get("line_bboxes") if isinstance(cell, dict) else None
        valid = (
            _valid_bbox(bbox)
            and _valid_bbox(content)
            and bbox_within(bbox, table_bbox)
            and bbox_within(content, bbox)
            and isinstance(lines, list)
            and all(_valid_bbox(line) and bbox_within(line, content) for line in lines)
        )
        if not valid:
            mismatches.append({
                "reason": "table-cell-content-overflow",
                "page": table.get("page"),
                "row": cell.get("row") if isinstance(cell, dict) else None,
                "column": cell.get("column") if isinstance(cell, dict) else None,
            })
    return mismatches


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        coordinates = [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    return coordinates[0] <= coordinates[2] and coordinates[1] <= coordinates[3]
