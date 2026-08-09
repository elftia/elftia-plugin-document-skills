"""Styles cross-reference reader for SpreadsheetML."""

from typing import Any

from .constants import STYLES_PART, qn


def read_styles(parts: dict[str, bytes]) -> dict[str, Any]:
    """Read the styles part and return resolved style records.

    Returns a dict with:
    - ``cell_xfs``: list of style index -> {font_id, fill_id, border_id, num_fmt_id, apply_*}
    - ``fonts``: list of font records
    - ``fills``: list of fill records
    - ``borders``: list of border records
    - ``num_fmts``: dict of id -> format code
    """
    payload = parts.get(STYLES_PART)
    if payload is None:
        return {"cell_xfs": [], "fonts": [], "fills": [], "borders": [], "num_fmts": {}}
    from defusedxml.ElementTree import fromstring
    root = fromstring(payload)
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    num_fmts: dict[int, str] = {}
    num_fmts_elem = root.find(f"{{{main_ns}}}numFmts")
    if num_fmts_elem is not None:
        for nf in num_fmts_elem.findall(f"{{{main_ns}}}numFmt"):
            nf_id = int(nf.attrib.get("numFmtId", "0"))
            num_fmts[nf_id] = nf.attrib.get("formatCode", "")

    fonts: list[dict[str, Any]] = []
    fonts_elem = root.find(f"{{{main_ns}}}fonts")
    if fonts_elem is not None:
        for font in fonts_elem.findall(f"{{{main_ns}}}font"):
            fonts.append(_parse_font(font, main_ns))

    fills: list[dict[str, Any]] = []
    fills_elem = root.find(f"{{{main_ns}}}fills")
    if fills_elem is not None:
        for fill in fills_elem.findall(f"{{{main_ns}}}fill"):
            fills.append(_parse_fill(fill, main_ns))

    borders: list[dict[str, Any]] = []
    borders_elem = root.find(f"{{{main_ns}}}borders")
    if borders_elem is not None:
        for border in borders_elem.findall(f"{{{main_ns}}}border"):
            borders.append({"diagonal": bool(border.attrib.get("diagonalUp") or border.attrib.get("diagonalDown"))})

    cell_xfs: list[dict[str, Any]] = []
    xfs_elem = root.find(f"{{{main_ns}}}cellXfs")
    if xfs_elem is not None:
        for xf in xfs_elem.findall(f"{{{main_ns}}}xf"):
            cell_xfs.append({
                "num_fmt_id": int(xf.attrib.get("numFmtId", "0")),
                "font_id": int(xf.attrib.get("fontId", "0")),
                "fill_id": int(xf.attrib.get("fillId", "0")),
                "border_id": int(xf.attrib.get("borderId", "0")),
                "apply_number_format": xf.attrib.get("applyNumberFormat") == "1",
                "apply_font": xf.attrib.get("applyFont") == "1",
                "apply_fill": xf.attrib.get("applyFill") == "1",
                "apply_border": xf.attrib.get("applyBorder") == "1",
            })

    return {
        "cell_xfs": cell_xfs,
        "fonts": fonts,
        "fills": fills,
        "borders": borders,
        "num_fmts": num_fmts,
    }


def resolve_style_index(styles: dict[str, Any], style_index: int) -> dict[str, Any]:
    """Resolve a cell's style index to a concrete style record."""
    cell_xfs = styles.get("cell_xfs", [])
    if style_index < 0 or style_index >= len(cell_xfs):
        return {"num_fmt_id": 0, "font": {}, "fill": {}, "border": {}}
    xf = cell_xfs[style_index]
    fonts = styles.get("fonts", [])
    fills = styles.get("fills", [])
    borders = styles.get("borders", [])
    return {
        "num_fmt_id": xf.get("num_fmt_id", 0),
        "num_fmt_code": styles.get("num_fmts", {}).get(xf.get("num_fmt_id", 0), ""),
        "font": fonts[xf["font_id"]] if xf.get("font_id", 0) < len(fonts) else {},
        "fill": fills[xf["fill_id"]] if xf.get("fill_id", 0) < len(fills) else {},
        "border": borders[xf["border_id"]] if xf.get("border_id", 0) < len(borders) else {},
    }


def _parse_font(font_elem: Any, main_ns: str) -> dict[str, Any]:
    return {
        "bold": font_elem.find(f"{{{main_ns}}}b") is not None,
        "italic": font_elem.find(f"{{{main_ns}}}i") is not None,
        "underline": font_elem.find(f"{{{main_ns}}}u") is not None,
        "size": _attr_text(font_elem.find(f"{{{main_ns}}}sz"), "val"),
        "color": _attr_text(font_elem.find(f"{{{main_ns}}}color"), "rgb"),
        "name": _attr_text(font_elem.find(f"{{{main_ns}}}name"), "val"),
    }


def _parse_fill(fill_elem: Any, main_ns: str) -> dict[str, Any]:
    pattern = fill_elem.find(f"{{{main_ns}}}patternFill")
    if pattern is None:
        return {}
    return {
        "pattern_type": pattern.attrib.get("patternType", ""),
        "fg_color": _attr_text(pattern.find(f"{{{main_ns}}}fgColor"), "rgb"),
        "bg_color": _attr_text(pattern.find(f"{{{main_ns}}}bgColor"), "rgb"),
    }


def _attr_text(elem: Any, attr: str) -> str:
    if elem is None:
        return ""
    return elem.attrib.get(attr, "")
