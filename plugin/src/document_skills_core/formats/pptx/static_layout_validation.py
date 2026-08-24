"""Bounded heuristic content and static-layout audit for PresentationML slides."""

from collections import Counter
import math
import re
from typing import Any

from .constants import NS, PRESENTATION_MAIN, local_name

_A = f"{{{NS['a']}}}"
_TOKEN_PATTERNS = (
    ("debug-text", re.compile(r"\bdebug\b", re.IGNORECASE)),
    ("placeholder-token", re.compile(r"\{\{[^{}]+\}\}|<<[^<>]+>>|\$\{[^{}]+\}")),
    ("todo-text", re.compile(r"\b(?:TODO|TBD)\b", re.IGNORECASE)),
)
_MAX_FINDINGS = 128
_MAX_OVERLAP_OBJECTS = 200
_MIN_FONT_POINTS = 10.0
_MIN_CONTRAST = 4.5


def audit_static_layout(package: Any) -> dict[str, Any]:
    width, height = _slide_size(package)
    findings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    objects_checked = 0
    for slide_number, part in enumerate(_ordered_slides(package), 1):
        shapes = _slide_shapes(package, part)
        objects_checked += len(shapes)
        records: list[dict[str, Any]] = []
        for ordinal, element in enumerate(shapes, 1):
            record = _shape_record(element, ordinal)
            records.append(record)
            _audit_shape(
                slide_number,
                record,
                width,
                height,
                findings,
                counts,
            )
        _audit_overlaps(slide_number, records, findings, counts)
    return {
        "by_code": dict(sorted(counts.items())),
        "findings": findings,
        "findings_truncated": max(0, sum(counts.values()) - len(findings)),
        "objects_checked": objects_checked,
        "slides_checked": len(_ordered_slides(package)),
        "thresholds": {
            "maximum_overlap_objects_per_slide": _MAX_OVERLAP_OBJECTS,
            "minimum_contrast_ratio": _MIN_CONTRAST,
            "minimum_font_points": _MIN_FONT_POINTS,
        },
    }


def _audit_shape(
    slide: int,
    record: dict[str, Any],
    slide_width: int,
    slide_height: int,
    findings: list[dict[str, Any]],
    counts: Counter[str],
) -> None:
    box = record["bbox"]
    if box is not None:
        x, y, width, height = box
        if width <= 0 or height <= 0:
            _record("invalid-bbox", slide, record, findings, counts)
        elif x < 0 or y < 0 or x + width > slide_width or y + height > slide_height:
            _record("out-of-bounds", slide, record, findings, counts)
    text = record["text"]
    placeholder = record["placeholder"]
    if placeholder in {"body", "ctrTitle", "subTitle", "title"} and not text.strip():
        _record(f"empty-{_placeholder_category(placeholder)}", slide, record, findings, counts)
    for code, pattern in _TOKEN_PATTERNS:
        if pattern.search(text):
            _record(code, slide, record, findings, counts)
    font_sizes = record["font_sizes"]
    if font_sizes and min(font_sizes) < _MIN_FONT_POINTS:
        _record("minimum-font-size", slide, record, findings, counts)
    if text and box is not None and _text_overflow_risk(text, box, font_sizes):
        _record("text-overflow-risk", slide, record, findings, counts)
    contrast = _contrast_ratio(record["text_color"], record["fill_color"])
    if contrast is not None and contrast < _MIN_CONTRAST:
        _record(
            "low-contrast",
            slide,
            record,
            findings,
            counts,
            evidence={"ratio": round(contrast, 3)},
        )


def _audit_overlaps(
    slide: int,
    records: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    counts: Counter[str],
) -> None:
    candidates = [
        record
        for record in records[:_MAX_OVERLAP_OBJECTS]
        if record["bbox"] is not None
        and record["kind"] not in {"cxnSp", "grpSp"}
    ]
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            ratio = _overlap_ratio(left["bbox"], right["bbox"])
            if ratio < 0.5:
                continue
            _record(
                "overlap-risk",
                slide,
                left,
                findings,
                counts,
                evidence={
                    "overlap_of_smaller": round(ratio, 3),
                    "with_shape_id": right["shape_id"],
                },
            )


def _shape_record(element: Any, ordinal: int) -> dict[str, Any]:
    non_visual = next(
        (node for node in element.iter() if local_name(node.tag) == "cNvPr"),
        None,
    )
    placeholder = next(
        (node for node in element.iter() if local_name(node.tag) == "ph"),
        None,
    )
    font_sizes = [
        int(node.attrib["sz"]) / 100
        for node in element.iter()
        if local_name(node.tag) in {"defRPr", "endParaRPr", "rPr"}
        and node.attrib.get("sz", "").isdigit()
    ]
    return {
        "bbox": _bbox(element),
        "fill_color": _shape_fill(element),
        "font_sizes": font_sizes,
        "kind": local_name(element.tag),
        "name": "" if non_visual is None else non_visual.attrib.get("name", ""),
        "placeholder": None if placeholder is None else placeholder.attrib.get("type", "body"),
        "shape_id": str(ordinal) if non_visual is None else non_visual.attrib.get("id", str(ordinal)),
        "text": "".join(node.text or "" for node in element.iter(f"{_A}t")),
        "text_color": _text_fill(element),
    }


def _bbox(element: Any) -> tuple[int, int, int, int] | None:
    for transform in element.iter():
        if local_name(transform.tag) != "xfrm":
            continue
        offset = next((node for node in list(transform) if local_name(node.tag) == "off"), None)
        extent = next((node for node in list(transform) if local_name(node.tag) == "ext"), None)
        if offset is None or extent is None:
            continue
        try:
            return (
                int(offset.attrib["x"]),
                int(offset.attrib["y"]),
                int(extent.attrib["cx"]),
                int(extent.attrib["cy"]),
            )
        except (KeyError, ValueError):
            return None
    return None


def _slide_shapes(package: Any, part: str) -> list[Any]:
    root = package.xml(part)
    tree = next((node for node in root.iter() if local_name(node.tag) == "spTree"), None)
    if tree is None:
        return []
    return [
        node
        for node in list(tree)
        if local_name(node.tag) in {"cxnSp", "graphicFrame", "grpSp", "pic", "sp"}
    ]


def _ordered_slides(package: Any) -> list[str]:
    presentation = package.xml(PRESENTATION_MAIN)
    relationships = {
        relationship.relationship_id: relationship.resolved_target
        for relationship in package.part_rels(PRESENTATION_MAIN)
        if relationship.relationship_type.rsplit("/", 1)[-1] == "slide"
    }
    return [
        relationships.get(node.attrib.get(f"{{{NS['r']}}}id", ""), "")
        for node in presentation.iter()
        if local_name(node.tag) == "sldId"
        and relationships.get(node.attrib.get(f"{{{NS['r']}}}id", ""), "")
    ]


def _slide_size(package: Any) -> tuple[int, int]:
    root = package.xml(PRESENTATION_MAIN)
    node = next((item for item in root if local_name(item.tag) == "sldSz"), None)
    if node is None:
        return 0, 0
    try:
        return int(node.attrib["cx"]), int(node.attrib["cy"])
    except (KeyError, ValueError):
        return 0, 0


def _shape_fill(element: Any) -> str | None:
    properties = next((node for node in list(element) if local_name(node.tag) == "spPr"), None)
    return _solid_rgb(properties)


def _text_fill(element: Any) -> str | None:
    for node in element.iter():
        if local_name(node.tag) in {"defRPr", "endParaRPr", "rPr"}:
            color = _solid_rgb(node)
            if color is not None:
                return color
    return None


def _solid_rgb(parent: Any) -> str | None:
    if parent is None:
        return None
    solid = next((node for node in list(parent) if local_name(node.tag) == "solidFill"), None)
    if solid is None:
        return None
    color = next((node for node in list(solid) if local_name(node.tag) == "srgbClr"), None)
    value = "" if color is None else color.attrib.get("val", "")
    return value.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", value) else None


def _text_overflow_risk(
    text: str,
    box: tuple[int, int, int, int],
    font_sizes: list[float],
) -> bool:
    _x, _y, width, height = box
    font = max(font_sizes or [18.0])
    character_width = max(1.0, font * 0.55 * 12_700)
    line_height = max(1.0, font * 1.2 * 12_700)
    capacity = max(1, int(width / character_width)) * max(1, int(height / line_height))
    return len(text) > math.ceil(capacity * 1.15)


def _overlap_ratio(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    intersection_width = max(0, min(left_x + left_width, right_x + right_width) - max(left_x, right_x))
    intersection_height = max(0, min(left_y + left_height, right_y + right_height) - max(left_y, right_y))
    smaller = min(left_width * left_height, right_width * right_height)
    return 0.0 if smaller <= 0 else intersection_width * intersection_height / smaller


def _contrast_ratio(foreground: str | None, background: str | None) -> float | None:
    if foreground is None or background is None:
        return None
    values = sorted((_luminance(foreground), _luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def _luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _placeholder_category(value: str) -> str:
    return "title" if value in {"ctrTitle", "title"} else "body"


def _record(
    code: str,
    slide: int,
    shape: dict[str, Any],
    findings: list[dict[str, Any]],
    counts: Counter[str],
    *,
    evidence: dict[str, Any] | None = None,
) -> None:
    counts[code] += 1
    if len(findings) >= _MAX_FINDINGS:
        return
    findings.append({
        "code": code,
        "evidence": evidence or {},
        "severity": "warning",
        "shape_id": shape["shape_id"],
        "shape_name": shape["name"],
        "slide": slide,
    })
