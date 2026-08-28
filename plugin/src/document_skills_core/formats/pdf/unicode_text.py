"""Emit positioned shaped text with ActualText extraction semantics."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import bbox_within, PageLayout, pdf_number
from .font_embedding import EmbeddedFontSet
from .font_shaping import resolved_style, ShapedLine, TextShaper


def build_shaped_text_block(
    block: dict[str, Any],
    layout: PageLayout,
    baseline: float,
    *,
    page_number: int,
    block_index: int,
    shaper: TextShaper,
    fonts: EmbeddedFontSet,
    spacing_after: float = 8.0,
) -> tuple[list[str], float, list[dict[str, Any]]]:
    """Lay out and emit one Unicode heading or paragraph."""
    style = resolved_style(block["type"], block.get("style"))
    text = block.get("text") or ""
    lines = shaper.wrap_and_shape(text, style, layout.content_width)
    operators: list[str] = []
    evidence: list[dict[str, Any]] = []
    current_baseline = min(
        baseline,
        layout.height - layout.top - style["font_size"] * 0.8,
    )
    for line in lines:
        x = _line_x(line.width, style["alignment"], layout)
        bbox = [
            round(x, 4),
            round(current_baseline - style["font_size"] * 0.2, 4),
            round(x + line.width, 4),
            round(current_baseline + style["font_size"] * 0.8, 4),
        ]
        if not bbox_within(bbox, layout.content_bbox):
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Text content exceeds the page content box.",
                status="invalid_request",
                details={
                    "field": f"pages.{page_number - 1}.blocks.{block_index}",
                    "page": page_number,
                    "bbox": bbox,
                    "content_bbox": layout.content_bbox,
                },
            )
        line_operators, used_resources = emit_shaped_line(
            line,
            style,
            x=x,
            baseline=current_baseline,
            fonts=fonts,
        )
        operators.extend(line_operators)
        evidence.append({
            "page": page_number,
            "block_index": block_index,
            "source_text": text,
            "text": line.text,
            "bbox": bbox,
            "font": f"/{used_resources[0]}" if used_resources else None,
            "fonts": [f"/{resource}" for resource in used_resources],
            "size": style["font_size"],
            "color": style["color"],
            "line_height": style["line_height"],
            "alignment": style["alignment"],
            "direction": line.direction,
            "language": style.get("language"),
        })
        current_baseline -= style["line_height"]
    return operators, current_baseline - spacing_after, evidence


def emit_shaped_line(
    line: ShapedLine,
    style: dict[str, Any],
    *,
    x: float,
    baseline: float,
    fonts: EmbeddedFontSet,
) -> tuple[list[str], list[str]]:
    """Emit one already-shaped line at an absolute baseline."""
    operators = [
        f"/Span << /ActualText <{_utf16_hex(line.text, bom=True)}> >> BDC",
        "BT",
        _rgb_operator(style["color"]),
    ]
    cursor = x
    used_resources: list[str] = []
    for glyph in line.glyphs:
        if glyph.font_id is None:
            assert glyph.builtin_resource is not None
            resource = glyph.builtin_resource
            encoded = f"({_escape_pdf_string(glyph.text)})"
        else:
            embedded = fonts.by_id[glyph.font_id]
            assert glyph.glyph_id is not None
            resource = embedded.resource_name
            cid = embedded.cid_for(glyph.glyph_id, glyph.text)
            encoded = f"<{cid:04X}>"
        if resource not in used_resources:
            used_resources.append(resource)
        operators.append(f"/{resource} {pdf_number(style['font_size'])} Tf")
        glyph_x = cursor + glyph.x_offset
        glyph_y = baseline + glyph.y_offset
        operators.append(
            f"1 0 0 1 {pdf_number(glyph_x)} {pdf_number(glyph_y)} Tm"
        )
        operators.append(f"{encoded} Tj")
        cursor += glyph.advance
    operators.extend(["ET", "EMC"])
    return operators, used_resources


def _line_x(width: float, alignment: str, layout: PageLayout) -> float:
    if alignment == "center":
        return layout.left + (layout.content_width - width) / 2.0
    if alignment == "right":
        return layout.width - layout.right - width
    return layout.left


def _utf16_hex(text: str, *, bom: bool) -> str:
    prefix = b"\xfe\xff" if bom else b""
    return (prefix + text.encode("utf-16-be")).hex().upper()


def _escape_pdf_string(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _rgb_operator(color: list[float]) -> str:
    return " ".join(pdf_number(value) for value in color) + " rg"
