"""Deterministic native-object frames for typed PPTX layout recipes."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .design_contracts import LAYOUT_RECIPES

EMU_PER_POINT = 12_700


def layout_recipe(
    name: str,
    slide_size: dict[str, Any],
    tokens: dict[str, Any],
    shape_count: int,
) -> dict[str, Any]:
    if name not in LAYOUT_RECIPES:
        _invalid("Unsupported PPTX layout recipe.", recipe=name)
    cx = int(slide_size.get("cx", 9_144_000))
    cy = int(slide_size.get("cy", 6_858_000))
    margins = tokens["safe_margins"]
    x = margins["left"]
    y = margins["top"]
    width = cx - margins["left"] - margins["right"]
    height = cy - margins["top"] - margins["bottom"]
    gutter = tokens["grid"]["gutter"]
    spacing = tokens["spacing"]
    if width <= gutter or height <= spacing["lg"]:
        _invalid("Layout tokens leave no usable slide area.")

    title_height = max(
        2 * round(tokens["typography_scale"]["title"] * EMU_PER_POINT),
        685_800,
    )
    title_height = min(title_height, max(1, height // 3))
    title = _frame(x, y, width, title_height)
    content_y = y + title_height + spacing["md"]
    content_height = max(1, y + height - content_y)
    full = _frame(x, content_y, width, content_height)
    left, right = _columns(x, content_y, width, content_height, gutter)

    if name == "cover":
        cover_title_height = min(max(title_height * 2, 1), height // 2)
        title = _frame(x, y + height // 5, width, cover_title_height)
        subtitle_y = title["y"] + title["cy"] + spacing["lg"]
        body = [_frame(x + width // 8, subtitle_y, width * 3 // 4, max(1, height // 5))]
        media = _frame(x, y, width, height)
        data = full
    elif name == "section":
        title = _frame(x, y + height // 4, width * 3 // 4, title_height * 2)
        body = [_frame(x, title["y"] + title["cy"] + spacing["md"], width // 2, height // 5)]
        media = right
        data = right
    elif name == "two-column":
        body = _alternating_frames(left, right, shape_count)
        media = right
        data = right
    elif name == "image-focus":
        media_width = max(1, round(width * 0.68))
        media = _frame(x, content_y, media_width, content_height)
        side_x = x + media_width + gutter
        side_width = max(1, width - media_width - gutter)
        body = [_frame(side_x, content_y, side_width, content_height)]
        data = body[0]
    elif name == "comparison":
        body = _alternating_frames(left, right, shape_count)
        media = right
        data = _frame(x, content_y + content_height * 2 // 3, width, max(1, content_height // 3))
    elif name == "summary":
        body = _summary_frames(x, content_y, width, content_height, gutter, shape_count)
        media = right
        data = full
    else:
        body = _stacked_frames(full, shape_count, spacing["sm"])
        media = _frame(x + width // 2, content_y, width // 2, content_height)
        data = full

    if not body:
        body = [full]
    return {
        "name": name,
        "title": title,
        "body": body,
        "media": media,
        "data": data,
        "placeholder_mapping": {
            "title": "title",
            "body": [f"body-{index + 1}" for index in range(shape_count)],
            "media": "media",
            "data": "data",
        },
    }


def layout_index(recipe: str) -> int:
    return LAYOUT_RECIPES.index(recipe) + 1


def _columns(
    x: int,
    y: int,
    width: int,
    height: int,
    gutter: int,
) -> tuple[dict[str, int], dict[str, int]]:
    column_width = max(1, (width - gutter) // 2)
    return (
        _frame(x, y, column_width, height),
        _frame(x + column_width + gutter, y, column_width, height),
    )


def _alternating_frames(
    left: dict[str, int],
    right: dict[str, int],
    count: int,
) -> list[dict[str, int]]:
    return [dict(left if index % 2 == 0 else right) for index in range(count)]


def _stacked_frames(
    frame: dict[str, int],
    count: int,
    gap: int,
) -> list[dict[str, int]]:
    if count <= 0:
        return []
    item_height = max(1, (frame["cy"] - gap * (count - 1)) // count)
    return [
        _frame(
            frame["x"],
            frame["y"] + index * (item_height + gap),
            frame["cx"],
            item_height,
        )
        for index in range(count)
    ]


def _summary_frames(
    x: int,
    y: int,
    width: int,
    height: int,
    gap: int,
    count: int,
) -> list[dict[str, int]]:
    if count <= 0:
        return []
    columns = 2
    rows = (count + columns - 1) // columns
    cell_width = max(1, (width - gap) // columns)
    cell_height = max(1, (height - gap * (rows - 1)) // rows)
    return [
        _frame(
            x + (index % columns) * (cell_width + gap),
            y + (index // columns) * (cell_height + gap),
            cell_width,
            cell_height,
        )
        for index in range(count)
    ]


def _frame(x: int, y: int, cx: int, cy: int) -> dict[str, int]:
    return {"x": int(x), "y": int(y), "cx": max(1, int(cx)), "cy": max(1, int(cy))}


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
