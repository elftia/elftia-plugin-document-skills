"""SpreadsheetML style registry, emitter, and resolved-style reader."""

from __future__ import annotations

import json
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS, STYLES_PART
from .xml_numeric import MAX_UNSIGNED_INT, parse_xml_int, parse_xml_number

_MAIN_NS = NS["main"]
_DEFAULT_FONT = {
    "name": "Calibri",
    "size": 11,
    "bold": False,
    "italic": False,
}
_DEFAULT_FILL = {"pattern": "none"}
_BUILTIN_NUMBER_FORMATS = {
    0: "General",
    1: "0",
    2: "0.00",
    3: "#,##0",
    4: "#,##0.00",
    9: "0%",
    10: "0.00%",
    11: "0.00E+00",
    12: "# ?/?",
    13: "# ??/??",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    37: "#,##0 ;(#,##0)",
    38: "#,##0 ;[Red](#,##0)",
    39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
    48: "##0.0E+0",
    49: "@",
}
_BUILTIN_FORMAT_IDS = {code: format_id for format_id, code in _BUILTIN_NUMBER_FORMATS.items()}


class StyleRegistry:
    """Assign deterministic deduplicated style and custom-number-format ids."""

    def __init__(self, format_definitions: list[dict[str, Any]]) -> None:
        self.num_formats = {
            definition["id"]: definition["code"]
            for definition in format_definitions
        }
        self._format_ids_by_code = {
            code: format_id for format_id, code in self.num_formats.items()
        }
        self._next_format_id = max([163, *self.num_formats]) + 1
        self.fonts: list[dict[str, Any]] = [dict(_DEFAULT_FONT)]
        self.fills: list[dict[str, Any]] = [dict(_DEFAULT_FILL), {"pattern": "gray125"}]
        self.borders: list[dict[str, Any]] = [{}]
        self.cell_xfs: list[dict[str, Any]] = [
            {
                "num_fmt_id": 0,
                "font_id": 0,
                "fill_id": 0,
                "border_id": 0,
                "alignment": {},
                "protection": {},
            }
        ]
        self._style_ids = {self._signature(self.cell_xfs[0]): 0}
        self.dxfs: list[dict[str, Any]] = []
        self._dxf_ids: dict[str, int] = {}

    def register(self, style: dict[str, Any] | None) -> int:
        if not style:
            return 0
        font_id = 0
        if style.get("font"):
            font = merge_styles({"font": _DEFAULT_FONT}, {"font": style["font"]})["font"]
            font_id = self._record_id(self.fonts, font)
        fill_id = 0
        if style.get("fill"):
            fill = merge_styles({"fill": _DEFAULT_FILL}, {"fill": style["fill"]})["fill"]
            fill_id = self._record_id(self.fills, fill)
        border_id = 0
        if style.get("border"):
            border_id = self._record_id(self.borders, style["border"])
        xf = {
            "num_fmt_id": self._resolve_number_format(style.get("number_format")),
            "font_id": font_id,
            "fill_id": fill_id,
            "border_id": border_id,
            "alignment": dict(style.get("alignment", {})),
            "protection": dict(style.get("protection", {})),
        }
        signature = self._signature(xf)
        if signature not in self._style_ids:
            self._style_ids[signature] = len(self.cell_xfs)
            self.cell_xfs.append(xf)
        return self._style_ids[signature]

    def register_dxf(self, style: dict[str, Any]) -> int:
        signature = self._signature(style)
        if signature not in self._dxf_ids:
            self._dxf_ids[signature] = len(self.dxfs)
            self.dxfs.append(style)
        return self._dxf_ids[signature]

    def build_xml(self) -> bytes:
        root = Element(f"{{{_MAIN_NS}}}styleSheet")
        if self.num_formats:
            formats = SubElement(
                root,
                f"{{{_MAIN_NS}}}numFmts",
                attrib={"count": str(len(self.num_formats))},
            )
            for format_id, code in sorted(self.num_formats.items()):
                SubElement(
                    formats,
                    f"{{{_MAIN_NS}}}numFmt",
                    attrib={"numFmtId": str(format_id), "formatCode": code},
                )
        fonts = SubElement(
            root,
            f"{{{_MAIN_NS}}}fonts",
            attrib={"count": str(len(self.fonts))},
        )
        for record in self.fonts:
            _write_font(fonts, record)
        fills = SubElement(
            root,
            f"{{{_MAIN_NS}}}fills",
            attrib={"count": str(len(self.fills))},
        )
        for record in self.fills:
            _write_fill(fills, record)
        borders = SubElement(
            root,
            f"{{{_MAIN_NS}}}borders",
            attrib={"count": str(len(self.borders))},
        )
        for record in self.borders:
            _write_border(borders, record)
        style_xfs = SubElement(
            root,
            f"{{{_MAIN_NS}}}cellStyleXfs",
            attrib={"count": "1"},
        )
        SubElement(
            style_xfs,
            f"{{{_MAIN_NS}}}xf",
            attrib={"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0"},
        )
        cell_xfs = SubElement(
            root,
            f"{{{_MAIN_NS}}}cellXfs",
            attrib={"count": str(len(self.cell_xfs))},
        )
        for record in self.cell_xfs:
            _write_xf(cell_xfs, record)
        styles = SubElement(
            root,
            f"{{{_MAIN_NS}}}cellStyles",
            attrib={"count": "1"},
        )
        SubElement(
            styles,
            f"{{{_MAIN_NS}}}cellStyle",
            attrib={"name": "Normal", "xfId": "0", "builtinId": "0"},
        )
        dxfs = SubElement(
            root,
            f"{{{_MAIN_NS}}}dxfs",
            attrib={"count": str(len(self.dxfs))},
        )
        for style in self.dxfs:
            dxfs.append(build_dxf_element(style))
        return tostring(root, encoding="UTF-8", xml_declaration=True)

    def manifest(self) -> dict[str, Any]:
        return {
            "number_formats": {
                str(format_id): code
                for format_id, code in sorted(self.num_formats.items())
            },
            "fonts": len(self.fonts),
            "fills": len(self.fills),
            "borders": len(self.borders),
            "cell_xfs": len(self.cell_xfs),
            "dxfs": len(self.dxfs),
        }

    def _resolve_number_format(self, number_format: dict[str, Any] | None) -> int:
        if not number_format:
            return 0
        if "id" in number_format:
            return number_format["id"]
        code = number_format["code"]
        if code in _BUILTIN_FORMAT_IDS:
            return _BUILTIN_FORMAT_IDS[code]
        if code not in self._format_ids_by_code:
            while self._next_format_id in self.num_formats:
                self._next_format_id += 1
            self._format_ids_by_code[code] = self._next_format_id
            self.num_formats[self._next_format_id] = code
            self._next_format_id += 1
        return self._format_ids_by_code[code]

    @staticmethod
    def _record_id(records: list[dict[str, Any]], value: dict[str, Any]) -> int:
        try:
            return records.index(value)
        except ValueError:
            records.append(value)
            return len(records) - 1

    @staticmethod
    def _signature(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def merge_styles(*styles: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge column → row → cell style fragments with nested override semantics."""

    result: dict[str, Any] = {}
    for style in styles:
        if not style:
            continue
        result = _deep_merge(result, style)
    return result or None


def builtin_number_format_id(code: str) -> int | None:
    return _BUILTIN_FORMAT_IDS.get(code)


def read_styles(parts: dict[str, bytes]) -> dict[str, Any]:
    """Read style tables while retaining theme/indexed color references."""

    payload = parts.get(STYLES_PART)
    if payload is None:
        return {
            "cell_xfs": [],
            "fonts": [],
            "fills": [],
            "borders": [],
            "num_fmts": {},
            "dxfs": [],
        }
    from defusedxml.ElementTree import fromstring

    root = fromstring(payload)
    num_fmts = _read_number_formats(root)
    fonts = _read_records(root, "fonts", "font", _parse_font)
    fills = _read_records(root, "fills", "fill", _parse_fill)
    borders = _read_records(root, "borders", "border", _parse_border)
    cell_xfs = _read_cell_xfs(root)
    return {
        "cell_xfs": cell_xfs,
        "fonts": fonts,
        "fills": fills,
        "borders": borders,
        "num_fmts": num_fmts,
        "dxfs": _read_differential_styles(root),
    }


def build_dxf_element(style: dict[str, Any]) -> Element:
    """Build a differential-style record without adding cell-style defaults."""

    dxf = Element(f"{{{_MAIN_NS}}}dxf")
    if style.get("font"):
        _write_dxf_font(dxf, style["font"])
    if style.get("fill"):
        _write_dxf_fill(dxf, style["fill"])
    if style.get("border"):
        _write_dxf_border(dxf, style["border"])
    return dxf


def _write_dxf_font(parent: Element, record: dict[str, Any]) -> None:
    font = SubElement(parent, f"{{{_MAIN_NS}}}font")
    if "size" in record:
        SubElement(font, f"{{{_MAIN_NS}}}sz", {"val": str(record["size"])})
    if "name" in record:
        SubElement(font, f"{{{_MAIN_NS}}}name", {"val": record["name"]})
    if "bold" in record:
        SubElement(font, f"{{{_MAIN_NS}}}b", {"val": _xml_bool(record["bold"])})
    if "italic" in record:
        SubElement(font, f"{{{_MAIN_NS}}}i", {"val": _xml_bool(record["italic"])})
    if record.get("underline"):
        attributes = {} if record["underline"] == "single" else {"val": record["underline"]}
        SubElement(font, f"{{{_MAIN_NS}}}u", attributes)
    if record.get("color"):
        SubElement(font, f"{{{_MAIN_NS}}}color", {"rgb": record["color"]})


def _write_dxf_fill(parent: Element, record: dict[str, Any]) -> None:
    fill = SubElement(parent, f"{{{_MAIN_NS}}}fill")
    pattern = SubElement(
        fill,
        f"{{{_MAIN_NS}}}patternFill",
        {"patternType": record.get("pattern", "none")},
    )
    if record.get("color"):
        SubElement(pattern, f"{{{_MAIN_NS}}}fgColor", {"rgb": record["color"]})
    if record.get("background_color"):
        SubElement(
            pattern,
            f"{{{_MAIN_NS}}}bgColor",
            {"rgb": record["background_color"]},
        )


def _write_dxf_border(parent: Element, record: dict[str, Any]) -> None:
    border = SubElement(
        parent,
        f"{{{_MAIN_NS}}}border",
        {
            xml_key: _xml_bool(record[key])
            for key, xml_key in (
                ("diagonal_up", "diagonalUp"),
                ("diagonal_down", "diagonalDown"),
                ("outline", "outline"),
            )
            if key in record
        },
    )
    for side_name in ("left", "right", "top", "bottom", "diagonal"):
        if side_name not in record:
            continue
        side_record = record[side_name]
        side = SubElement(
            border,
            f"{{{_MAIN_NS}}}{side_name}",
            {"style": side_record["style"]} if side_record.get("style") else {},
        )
        if side_record.get("color"):
            SubElement(side, f"{{{_MAIN_NS}}}color", {"rgb": side_record["color"]})


def _read_differential_styles(root: Element) -> list[dict[str, Any]]:
    container = root.find(f"{{{_MAIN_NS}}}dxfs")
    if container is None:
        return []
    result: list[dict[str, Any]] = []
    for dxf in container.findall(f"{{{_MAIN_NS}}}dxf"):
        style: dict[str, Any] = {}
        font = dxf.find(f"{{{_MAIN_NS}}}font")
        fill = dxf.find(f"{{{_MAIN_NS}}}fill")
        border = dxf.find(f"{{{_MAIN_NS}}}border")
        if font is not None:
            style["font"] = _parse_dxf_font(font)
        if fill is not None:
            style["fill"] = _parse_dxf_fill(fill)
        if border is not None:
            style["border"] = _parse_dxf_border(border)
        result.append(style)
    return result


def _parse_dxf_font(font: Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tag, key in (("b", "bold"), ("i", "italic")):
        element = font.find(f"{{{_MAIN_NS}}}{tag}")
        if element is not None:
            result[key] = element.attrib.get("val", "1") not in {"0", "false", "off"}
    underline = font.find(f"{{{_MAIN_NS}}}u")
    if underline is not None:
        result["underline"] = underline.attrib.get("val", "single")
    for tag, key in (("name", "name"), ("sz", "size")):
        element = font.find(f"{{{_MAIN_NS}}}{tag}")
        if element is not None:
            value: Any = element.attrib.get("val", "")
            if key == "size":
                value = parse_xml_number(
                    value,
                    attribute="dxf.font.sz",
                    minimum=1,
                    maximum=409,
                )
            result[key] = value
    color = font.find(f"{{{_MAIN_NS}}}color")
    if color is not None:
        result["color"] = _parse_color(color)
    return result


def _parse_dxf_fill(fill: Element) -> dict[str, Any]:
    pattern = fill.find(f"{{{_MAIN_NS}}}patternFill")
    if pattern is None:
        return {}
    result: dict[str, Any] = {"pattern": pattern.attrib.get("patternType", "none")}
    foreground = pattern.find(f"{{{_MAIN_NS}}}fgColor")
    background = pattern.find(f"{{{_MAIN_NS}}}bgColor")
    if foreground is not None:
        result["color"] = _parse_color(foreground)
    if background is not None:
        result["background_color"] = _parse_color(background)
    return result


def _parse_dxf_border(border: Element) -> dict[str, Any]:
    return _parse_border(border)


def resolve_style_index(styles: dict[str, Any], style_index: int) -> dict[str, Any]:
    """Resolve a raw cell/row/column style id to its concrete style components."""

    cell_xfs = styles.get("cell_xfs", [])
    if style_index < 0 or style_index >= len(cell_xfs):
        return _empty_resolved_style()
    xf = cell_xfs[style_index]
    format_id = xf.get("num_fmt_id", 0)
    return {
        "num_fmt_id": format_id,
        "num_fmt_code": styles.get("num_fmts", {}).get(
            format_id,
            _BUILTIN_NUMBER_FORMATS.get(format_id, ""),
        ),
        "font": _record(styles.get("fonts", []), xf.get("font_id", 0)),
        "fill": _record(styles.get("fills", []), xf.get("fill_id", 0)),
        "border": _record(styles.get("borders", []), xf.get("border_id", 0)),
        "alignment": dict(xf.get("alignment", {})),
        "protection": dict(xf.get("protection", {})),
    }


def _write_font(parent: Element, record: dict[str, Any]) -> None:
    font = SubElement(parent, f"{{{_MAIN_NS}}}font")
    if record.get("bold"):
        SubElement(font, f"{{{_MAIN_NS}}}b")
    if record.get("italic"):
        SubElement(font, f"{{{_MAIN_NS}}}i")
    underline = record.get("underline")
    if underline:
        attributes = {} if underline == "single" else {"val": underline}
        SubElement(font, f"{{{_MAIN_NS}}}u", attrib=attributes)
    SubElement(font, f"{{{_MAIN_NS}}}sz", attrib={"val": str(record.get("size", 11))})
    if record.get("color"):
        SubElement(font, f"{{{_MAIN_NS}}}color", attrib={"rgb": record["color"]})
    SubElement(font, f"{{{_MAIN_NS}}}name", attrib={"val": record.get("name", "Calibri")})


def _write_fill(parent: Element, record: dict[str, Any]) -> None:
    fill = SubElement(parent, f"{{{_MAIN_NS}}}fill")
    pattern = SubElement(
        fill,
        f"{{{_MAIN_NS}}}patternFill",
        attrib={"patternType": record.get("pattern", "none")},
    )
    if record.get("color"):
        SubElement(pattern, f"{{{_MAIN_NS}}}fgColor", attrib={"rgb": record["color"]})
    if record.get("background_color"):
        SubElement(
            pattern,
            f"{{{_MAIN_NS}}}bgColor",
            attrib={"rgb": record["background_color"]},
        )
    elif record.get("color"):
        SubElement(pattern, f"{{{_MAIN_NS}}}bgColor", attrib={"indexed": "64"})


def _write_border(parent: Element, record: dict[str, Any]) -> None:
    attributes: dict[str, str] = {}
    for key, xml_key in (
        ("diagonal_up", "diagonalUp"),
        ("diagonal_down", "diagonalDown"),
        ("outline", "outline"),
    ):
        if key in record:
            attributes[xml_key] = _xml_bool(record[key])
    border = SubElement(parent, f"{{{_MAIN_NS}}}border", attrib=attributes)
    for side_name in ("left", "right", "top", "bottom", "diagonal"):
        side_record = record.get(side_name, {})
        side_attributes = {}
        if side_record.get("style"):
            side_attributes["style"] = side_record["style"]
        side = SubElement(border, f"{{{_MAIN_NS}}}{side_name}", attrib=side_attributes)
        if side_record.get("color"):
            SubElement(side, f"{{{_MAIN_NS}}}color", attrib={"rgb": side_record["color"]})


def _write_xf(parent: Element, record: dict[str, Any]) -> None:
    attributes = {
        "numFmtId": str(record.get("num_fmt_id", 0)),
        "fontId": str(record.get("font_id", 0)),
        "fillId": str(record.get("fill_id", 0)),
        "borderId": str(record.get("border_id", 0)),
        "xfId": "0",
    }
    for record_key, apply_key in (
        ("num_fmt_id", "applyNumberFormat"),
        ("font_id", "applyFont"),
        ("fill_id", "applyFill"),
        ("border_id", "applyBorder"),
    ):
        if record.get(record_key, 0):
            attributes[apply_key] = "1"
    alignment = record.get("alignment", {})
    protection = record.get("protection", {})
    if alignment:
        attributes["applyAlignment"] = "1"
    if protection:
        attributes["applyProtection"] = "1"
    xf = SubElement(parent, f"{{{_MAIN_NS}}}xf", attrib=attributes)
    if alignment:
        aliases = {
            "wrap": "wrapText",
            "rotation": "textRotation",
            "shrink_to_fit": "shrinkToFit",
        }
        alignment_attributes = {
            aliases.get(key, key): _alignment_value(key, value)
            for key, value in alignment.items()
        }
        SubElement(xf, f"{{{_MAIN_NS}}}alignment", attrib=alignment_attributes)
    if protection:
        SubElement(
            xf,
            f"{{{_MAIN_NS}}}protection",
            attrib={key: _xml_bool(value) for key, value in protection.items()},
        )


def _read_number_formats(root: Element) -> dict[int, str]:
    result: dict[int, str] = {}
    container = root.find(f"{{{_MAIN_NS}}}numFmts")
    if container is not None:
        for item in container.findall(f"{{{_MAIN_NS}}}numFmt"):
            format_id = parse_xml_int(
                item.attrib.get("numFmtId", "0"),
                attribute="numFmt.numFmtId",
                minimum=0,
                maximum=65_535,
            )
            result[format_id] = item.attrib.get(
                "formatCode",
                "",
            )
    return result


def _read_records(
    root: Element,
    container_name: str,
    record_name: str,
    parser: Any,
) -> list[dict[str, Any]]:
    container = root.find(f"{{{_MAIN_NS}}}{container_name}")
    if container is None:
        return []
    return [parser(item) for item in container.findall(f"{{{_MAIN_NS}}}{record_name}")]


def _read_cell_xfs(root: Element) -> list[dict[str, Any]]:
    container = root.find(f"{{{_MAIN_NS}}}cellXfs")
    if container is None:
        return []
    result = []
    for xf in container.findall(f"{{{_MAIN_NS}}}xf"):
        alignment = xf.find(f"{{{_MAIN_NS}}}alignment")
        protection = xf.find(f"{{{_MAIN_NS}}}protection")
        result.append(
            {
                "num_fmt_id": parse_xml_int(
                    xf.attrib.get("numFmtId", "0"),
                    attribute="xf.numFmtId",
                    minimum=0,
                    maximum=65_535,
                ),
                "font_id": parse_xml_int(
                    xf.attrib.get("fontId", "0"),
                    attribute="xf.fontId",
                    minimum=0,
                    maximum=MAX_UNSIGNED_INT,
                ),
                "fill_id": parse_xml_int(
                    xf.attrib.get("fillId", "0"),
                    attribute="xf.fillId",
                    minimum=0,
                    maximum=MAX_UNSIGNED_INT,
                ),
                "border_id": parse_xml_int(
                    xf.attrib.get("borderId", "0"),
                    attribute="xf.borderId",
                    minimum=0,
                    maximum=MAX_UNSIGNED_INT,
                ),
                "alignment": _parse_alignment(alignment),
                "protection": _parse_protection(protection),
            }
        )
    return result


def _parse_font(font: Element) -> dict[str, Any]:
    return {
        "bold": font.find(f"{{{_MAIN_NS}}}b") is not None,
        "italic": font.find(f"{{{_MAIN_NS}}}i") is not None,
        "underline": _underline_value(font.find(f"{{{_MAIN_NS}}}u")),
        "size": _numeric_attr(font.find(f"{{{_MAIN_NS}}}sz"), "val"),
        "color": _parse_color(font.find(f"{{{_MAIN_NS}}}color")),
        "name": _attr_text(font.find(f"{{{_MAIN_NS}}}name"), "val"),
    }


def _parse_fill(fill: Element) -> dict[str, Any]:
    pattern = fill.find(f"{{{_MAIN_NS}}}patternFill")
    if pattern is None:
        return {}
    return {
        "pattern": pattern.attrib.get("patternType", ""),
        "color": _parse_color(pattern.find(f"{{{_MAIN_NS}}}fgColor")),
        "background_color": _parse_color(pattern.find(f"{{{_MAIN_NS}}}bgColor")),
    }


def _parse_border(border: Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for side_name in ("left", "right", "top", "bottom", "diagonal"):
        side = border.find(f"{{{_MAIN_NS}}}{side_name}")
        if side is not None:
            result[side_name] = {
                "style": side.attrib.get("style", ""),
                "color": _parse_color(side.find(f"{{{_MAIN_NS}}}color")),
            }
    for xml_key, result_key in (
        ("diagonalUp", "diagonal_up"),
        ("diagonalDown", "diagonal_down"),
        ("outline", "outline"),
    ):
        if xml_key in border.attrib:
            result[result_key] = border.attrib[xml_key] == "1"
    return result


def _parse_alignment(alignment: Element | None) -> dict[str, Any]:
    if alignment is None:
        return {}
    result: dict[str, Any] = {}
    for xml_key, result_key in (
        ("horizontal", "horizontal"),
        ("vertical", "vertical"),
        ("wrapText", "wrap"),
        ("textRotation", "rotation"),
        ("shrinkToFit", "shrink_to_fit"),
        ("indent", "indent"),
    ):
        if xml_key not in alignment.attrib:
            continue
        raw = alignment.attrib[xml_key]
        if result_key in {"wrap", "shrink_to_fit"}:
            result[result_key] = raw == "1"
        elif result_key in {"rotation", "indent"}:
            numeric = parse_xml_int(
                raw,
                attribute=f"alignment.{xml_key}",
                minimum=0,
                maximum=255 if result_key == "rotation" else 250,
            )
            result[result_key] = 90 - numeric if result_key == "rotation" and numeric > 90 else numeric
        else:
            result[result_key] = raw
    return result


def _parse_protection(protection: Element | None) -> dict[str, Any]:
    if protection is None:
        return {}
    return {
        key: protection.attrib[key] == "1"
        for key in ("locked", "hidden")
        if key in protection.attrib
    }


def _parse_color(color: Element | None) -> str | dict[str, Any]:
    if color is None:
        return ""
    if "rgb" in color.attrib:
        return color.attrib["rgb"]
    if "theme" in color.attrib:
        result: dict[str, Any] = {
            "theme": parse_xml_int(
                color.attrib["theme"],
                attribute="color.theme",
                minimum=0,
                maximum=MAX_UNSIGNED_INT,
            )
        }
        if "tint" in color.attrib:
            result["tint"] = parse_xml_number(
                color.attrib["tint"],
                attribute="color.tint",
                minimum=-1,
                maximum=1,
            )
        return result
    if "indexed" in color.attrib:
        return {
            "indexed": parse_xml_int(
                color.attrib["indexed"],
                attribute="color.indexed",
                minimum=0,
                maximum=MAX_UNSIGNED_INT,
            )
        }
    if color.attrib.get("auto") == "1":
        return {"auto": True}
    return ""


def _empty_resolved_style() -> dict[str, Any]:
    return {
        "num_fmt_id": 0,
        "num_fmt_code": _BUILTIN_NUMBER_FORMATS[0],
        "font": {},
        "fill": {},
        "border": {},
        "alignment": {},
        "protection": {},
    }


def _record(records: list[dict[str, Any]], index: int) -> dict[str, Any]:
    return dict(records[index]) if 0 <= index < len(records) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = {key: dict(value) if type(value) is dict else value for key, value in base.items()}
    for key, value in override.items():
        if type(value) is dict and type(result.get(key)) is dict:
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = dict(value) if type(value) is dict else value
    return result


def _alignment_value(key: str, value: Any) -> str:
    if type(value) is bool:
        return _xml_bool(value)
    if key == "rotation" and value < 0:
        return str(90 - value)
    return str(value)


def _xml_bool(value: Any) -> str:
    return "1" if value else "0"


def _underline_value(element: Element | None) -> str:
    if element is None:
        return ""
    return element.attrib.get("val", "single")


def _numeric_attr(element: Element | None, attr: str) -> int | float | str:
    text = _attr_text(element, attr)
    if not text:
        return ""
    return parse_xml_number(
        text,
        attribute=f"font.{attr}",
        minimum=1,
        maximum=409,
    )


def _attr_text(element: Element | None, attr: str) -> str:
    return "" if element is None else element.attrib.get(attr, "")
