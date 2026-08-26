"""Geometry and type-scale metrics for template content lint."""

from __future__ import annotations

import re
from typing import Any

from .constants import local_name

_CJK = re.compile(
    r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff"
    r"\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)
_EMU_PER_POINT = 12_700


def content_capacity_finding(
    record: dict[str, Any],
    part: str,
    slide_number: int,
) -> dict[str, Any] | None:
    text = record["text"].strip()
    if not contains_cjk(text):
        return None
    actual = len(text)
    slot = record["slot"]
    if slot is not None:
        capacity = slot["capacity"]
        recommended = capacity["cjkRecommendedCharacters"]
        policy = "semantic-slot"
        if capacity["overflowPolicy"] != "reject":
            return None
    else:
        recommended = _geometry_capacity(record)
        policy = "geometry-font-heuristic"
    if recommended is None or actual <= recommended:
        return None
    finding = {
        "actual_characters": actual,
        "capacity_policy": policy,
        "code": "cjk-capacity-exceeded",
        "name": record["name"],
        "part": part,
        "recommended_characters": recommended,
        "sample": text[:80],
        "severity": "error",
        "shape_id": record["shape_id"],
        "slide": slide_number,
    }
    if slot is not None:
        finding["slot_id"] = slot["slotId"]
    return finding


def content_hierarchy_finding(
    records: list[dict[str, Any]],
    part: str,
    slide_number: int,
) -> dict[str, Any] | None:
    sized = [item for item in records if item["font_sizes"]]
    if len(sized) < 2:
        return None
    explicit_titles = [item for item in sized if _title_rank(item) is not None]
    positioned = [item for item in sized if item["frame"] is not None]
    title = (
        min(
            explicit_titles,
            key=lambda item: (
                _title_rank(item),
                float("inf") if item["frame"] is None else item["frame"]["y"],
                -max(item["font_sizes"]),
            ),
        )
        if explicit_titles
        else min(
            positioned,
            key=lambda item: (item["frame"]["y"], -max(item["font_sizes"])),
            default=None,
        )
    )
    if title is None:
        return None
    body = [item for item in sized if item is not title]
    body_max = max((max(item["font_sizes"]) for item in body), default=None)
    title_max = max(title["font_sizes"])
    if body_max is None or body_max < title_max:
        return None
    return {
        "basis": "semantic-or-placeholder" if explicit_titles else "topmost-text-heuristic",
        "body_maximum_pt": body_max,
        "code": "type-scale-hierarchy",
        "part": part,
        "severity": "error",
        "slide": slide_number,
        "title_maximum_pt": title_max,
        "title_name": title["name"],
        "title_shape_id": title["shape_id"],
    }


def contains_cjk(text: str) -> bool:
    """Return whether text uses Han, kana, or Hangul script characters."""

    return _CJK.search(text) is not None


def object_frame(
    element: Any,
    transform: tuple[float, float, float, float] | None = None,
) -> dict[str, int] | None:
    for xml_transform in element.iter():
        if local_name(xml_transform.tag) != "xfrm":
            continue
        offset = next(
            (node for node in xml_transform if local_name(node.tag) == "off"),
            None,
        )
        extent = next(
            (node for node in xml_transform if local_name(node.tag) == "ext"),
            None,
        )
        if offset is None or extent is None:
            continue
        values = {
            "x": offset.attrib.get("x", ""),
            "y": offset.attrib.get("y", ""),
            "cx": extent.attrib.get("cx", ""),
            "cy": extent.attrib.get("cy", ""),
        }
        try:
            frame = {key: int(value) for key, value in values.items()}
        except ValueError:
            continue
        else:
            if transform is None:
                return frame
            scale_x, scale_y, translate_x, translate_y = transform
            return {
                "x": round(frame["x"] * scale_x + translate_x),
                "y": round(frame["y"] * scale_y + translate_y),
                "cx": round(frame["cx"] * scale_x),
                "cy": round(frame["cy"] * scale_y),
            }
    return None


def group_child_transform(
    element: Any,
    parent: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Compose a group child coordinate space into slide coordinates."""

    group_properties = next(
        (node for node in element if local_name(node.tag) == "grpSpPr"),
        None,
    )
    transform = None if group_properties is None else next(
        (node for node in group_properties if local_name(node.tag) == "xfrm"),
        None,
    )
    if transform is None:
        return parent
    values: dict[str, dict[str, str]] = {}
    for name in ("chExt", "chOff", "ext", "off"):
        node = next(
            (item for item in transform if local_name(item.tag) == name),
            None,
        )
        if node is not None:
            values[name] = node.attrib
    raw = (
        values.get("off", {}).get("x", ""),
        values.get("off", {}).get("y", ""),
        values.get("ext", {}).get("cx", ""),
        values.get("ext", {}).get("cy", ""),
        values.get("chOff", {}).get("x", ""),
        values.get("chOff", {}).get("y", ""),
        values.get("chExt", {}).get("cx", ""),
        values.get("chExt", {}).get("cy", ""),
    )
    try:
        parsed = tuple(int(item) for item in raw)
    except ValueError:
        return parent
    if parsed[6] == 0 or parsed[7] == 0:
        return parent
    offset_x, offset_y, extent_x, extent_y, child_x, child_y, child_cx, child_cy = (
        parsed
    )
    local_scale_x = extent_x / child_cx
    local_scale_y = extent_y / child_cy
    local_translate_x = offset_x - child_x * local_scale_x
    local_translate_y = offset_y - child_y * local_scale_y
    parent_scale_x, parent_scale_y, parent_translate_x, parent_translate_y = parent
    return (
        parent_scale_x * local_scale_x,
        parent_scale_y * local_scale_y,
        parent_translate_x + parent_scale_x * local_translate_x,
        parent_translate_y + parent_scale_y * local_translate_y,
    )


def _geometry_capacity(record: dict[str, Any]) -> int | None:
    frame = record["frame"]
    sizes = record["font_sizes"]
    if frame is None or not sizes or frame["cx"] <= 0 or frame["cy"] <= 0:
        return None
    font = max(sizes)
    width_points = frame["cx"] / _EMU_PER_POINT
    height_points = frame["cy"] / _EMU_PER_POINT
    per_line = max(1, int(width_points / font))
    lines = max(1, int(height_points / (font * 1.25)))
    return min(4096, per_line * lines)


def _title_rank(record: dict[str, Any]) -> int | None:
    placeholder = record["placeholder_role"]
    slot = record["slot"]
    role = None if slot is None else str(slot.get("role", "")).lower()
    if placeholder in {"ctrTitle", "title"} or role in {"heading", "title"}:
        return 0
    if placeholder == "subTitle" or role == "subtitle":
        return 1
    return None
