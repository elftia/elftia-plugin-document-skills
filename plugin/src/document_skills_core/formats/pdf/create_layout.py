"""Deterministic Core text layout for direct PDF creation.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_contracts import DEFAULT_MARGIN, resolved_page_size


@dataclass(frozen=True)
class PageLayout:
    width: float
    height: float
    top: float
    right: float
    bottom: float
    left: float

    @property
    def content_width(self) -> float:
        return self.width - self.left - self.right


def resolve_page_layout(
    default_size: str | dict[str, float],
    page: dict[str, Any],
) -> PageLayout:
    width, height = resolved_page_size(page.get("size") or default_size)
    margin = page.get("margin") or DEFAULT_MARGIN
    return PageLayout(
        width=width,
        height=height,
        top=margin["top"],
        right=margin["right"],
        bottom=margin["bottom"],
        left=margin["left"],
    )


def build_text_block(
    block: dict[str, Any],
    layout: PageLayout,
    baseline: float,
    *,
    page_number: int,
    block_index: int,
    escape_text: Callable[[str], str],
) -> tuple[list[str], float, list[dict[str, Any]]]:
    """Lay out a heading or paragraph and return operators plus evidence."""
    block_type = block["type"]
    style = _resolved_style(block_type, block.get("style"))
    text = block.get("text") or ""
    lines = _wrap_text(text, style["font_size"], layout.content_width)
    operators: list[str] = []
    evidence: list[dict[str, Any]] = []
    current_baseline = baseline
    for line in lines:
        bbox = _line_bbox(line, style, layout, current_baseline)
        if bbox[1] < layout.bottom:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Text content exceeds the page content box.",
                status="invalid_request",
                details={
                    "field": f"pages.{page_number - 1}.blocks.{block_index}",
                    "page": page_number,
                    "bbox": bbox,
                    "content_bottom": layout.bottom,
                },
            )
        operators.extend(
            [
                "BT",
                f"/{style['font_resource']} {pdf_number(style['font_size'])} Tf",
                f"{_rgb_operator(style['color'], 'rg')}",
                f"1 0 0 1 {pdf_number(bbox[0])} {pdf_number(current_baseline)} Tm",
                f"({escape_text(line)}) Tj",
                "ET",
            ]
        )
        evidence.append(
            {
                "page": page_number,
                "block_index": block_index,
                "text": line,
                "bbox": bbox,
                "font": f"/{style['font_resource']}",
                "size": style["font_size"],
                "color": style["color"],
                "line_height": style["line_height"],
                "alignment": style["alignment"],
            }
        )
        current_baseline -= style["line_height"]
    return operators, current_baseline - 8.0, evidence


def shape_path(shape: dict[str, Any]) -> list[str]:
    """Return path construction operators without painting the path."""
    x = shape["x"]
    y = shape["y"]
    width = shape["width"]
    height = shape["height"]
    if shape["kind"] == "rectangle":
        return [f"{pdf_number(x)} {pdf_number(y)} {pdf_number(width)} {pdf_number(height)} re"]
    if shape["kind"] == "line":
        return [
            f"{pdf_number(x)} {pdf_number(y)} m",
            f"{pdf_number(x + width)} {pdf_number(y + height)} l",
        ]
    center_x = x + width / 2.0
    center_y = y + height / 2.0
    radius_x = width / 2.0
    radius_y = height / 2.0
    kappa = 0.5522847498307793
    return [
        f"{pdf_number(center_x - radius_x)} {pdf_number(center_y)} m",
        _curve(center_x - radius_x, center_y + radius_y * kappa, center_x - radius_x * kappa, center_y + radius_y, center_x, center_y + radius_y),
        _curve(center_x + radius_x * kappa, center_y + radius_y, center_x + radius_x, center_y + radius_y * kappa, center_x + radius_x, center_y),
        _curve(center_x + radius_x, center_y - radius_y * kappa, center_x + radius_x * kappa, center_y - radius_y, center_x, center_y - radius_y),
        _curve(center_x - radius_x * kappa, center_y - radius_y, center_x - radius_x, center_y - radius_y * kappa, center_x - radius_x, center_y),
        "h",
    ]


def shape_style_operators(shape: dict[str, Any], graphics_state: str) -> list[str]:
    operators = ["q", f"/{graphics_state} gs"]
    if shape["stroke"] is not None:
        operators.append(_rgb_operator(shape["stroke"], "RG"))
    if shape["fill"] is not None:
        operators.append(_rgb_operator(shape["fill"], "rg"))
    dash = " ".join(pdf_number(value) for value in shape["dash"])
    operators.append(f"[{dash}] 0 d")
    return operators


def shape_paint_operator(shape: dict[str, Any]) -> str:
    if shape["stroke"] is not None and shape["fill"] is not None:
        return "B"
    if shape["fill"] is not None:
        return "f"
    return "S"


def shape_evidence(
    shape: dict[str, Any],
    *,
    page_number: int,
    block_index: int,
) -> dict[str, Any]:
    return {
        "page": page_number,
        "block_index": block_index,
        "kind": shape["kind"],
        "bbox": [
            shape["x"],
            shape["y"],
            shape["x"] + shape["width"],
            shape["y"] + shape["height"],
        ],
        "stroke": shape["stroke"],
        "fill": shape["fill"],
        "opacity": shape["opacity"],
        "dash": shape["dash"],
    }


def pdf_number(value: float) -> str:
    rendered = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return rendered if rendered not in {"", "-0"} else "0"


def _resolved_style(block_type: str, style: dict[str, Any] | None) -> dict[str, Any]:
    if style is None:
        size = 16.0 if block_type == "heading" else 12.0
        style = {
            "font_size": size,
            "font_weight": "bold" if block_type == "heading" else "normal",
            "font_style": "normal",
            "color": [0.0, 0.0, 0.0],
            "line_height": 28.0 if block_type == "heading" else 14.0,
            "alignment": "left",
        }
    font_resource = {
        ("normal", "normal"): "F1",
        ("bold", "normal"): "F2",
        ("normal", "italic"): "F3",
        ("bold", "italic"): "F4",
    }[(style["font_weight"], style["font_style"])]
    return {**style, "font_resource": font_resource}


def _wrap_text(text: str, font_size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for source_line in text.split("\n"):
        words = source_line.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if not current or _text_width(candidate, font_size) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
            while _text_width(current, font_size) > max_width and len(current) > 1:
                split_at = max(1, int(max_width / (font_size * 0.5)))
                lines.append(current[:split_at])
                current = current[split_at:]
        lines.append(current)
    return lines or [""]


def _line_bbox(
    text: str,
    style: dict[str, Any],
    layout: PageLayout,
    baseline: float,
) -> list[float]:
    text_width = _text_width(text, style["font_size"])
    if style["alignment"] == "center":
        x = layout.left + (layout.content_width - text_width) / 2.0
    elif style["alignment"] == "right":
        x = layout.width - layout.right - text_width
    else:
        x = layout.left
    return [
        round(x, 4),
        round(baseline - style["font_size"] * 0.2, 4),
        round(x + text_width, 4),
        round(baseline + style["font_size"] * 0.8, 4),
    ]


def _text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * 0.5


def _rgb_operator(color: list[float], operator: str) -> str:
    return " ".join(pdf_number(value) for value in color) + f" {operator}"


def _curve(*values: float) -> str:
    return " ".join(pdf_number(value) for value in values) + " c"
