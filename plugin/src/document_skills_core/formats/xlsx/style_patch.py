"""Append-only style patching for existing XLSX workbooks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .styles import builtin_number_format_id

_MAIN_NS = NS["main"]


class ExistingStyleRegistry:
    """Patch styles by appending deduplicated records and retaining existing XML."""

    def __init__(self, root: Element) -> None:
        self.root = root
        self.fonts = _required_container(root, "fonts")
        self.fills = _required_container(root, "fills")
        self.borders = _required_container(root, "borders")
        self.cell_xfs = _required_container(root, "cellXfs")
        self.num_fmts = root.find(f"{{{_MAIN_NS}}}numFmts")
        self.changed = False

    def apply(self, base_style_id: int, style: dict[str, Any]) -> int:
        existing_xfs = list(self.cell_xfs)
        if not 0 <= base_style_id < len(existing_xfs):
            _invalid_style("Base style id is outside cellXfs.", style_id=base_style_id)
        patched = deepcopy(existing_xfs[base_style_id])
        if style.get("font"):
            font_id = self._patch_record(
                self.fonts,
                int(patched.attrib.get("fontId", "0")),
                _patch_font,
                style["font"],
            )
            patched.attrib["fontId"] = str(font_id)
            patched.attrib["applyFont"] = "1"
        if style.get("fill"):
            fill_id = self._patch_record(
                self.fills,
                int(patched.attrib.get("fillId", "0")),
                _patch_fill,
                style["fill"],
            )
            patched.attrib["fillId"] = str(fill_id)
            patched.attrib["applyFill"] = "1"
        if style.get("border"):
            border_id = self._patch_record(
                self.borders,
                int(patched.attrib.get("borderId", "0")),
                _patch_border,
                style["border"],
            )
            patched.attrib["borderId"] = str(border_id)
            patched.attrib["applyBorder"] = "1"
        if style.get("number_format"):
            patched.attrib["numFmtId"] = str(
                self._number_format_id(style["number_format"])
            )
            patched.attrib["applyNumberFormat"] = "1"
        if style.get("alignment"):
            _patch_alignment(patched, style["alignment"])
            patched.attrib["applyAlignment"] = "1"
        if style.get("protection"):
            _patch_protection(patched, style["protection"])
            patched.attrib["applyProtection"] = "1"
        return self._append_or_find(self.cell_xfs, patched)

    def to_bytes(self) -> bytes:
        return tostring(self.root, encoding="UTF-8", xml_declaration=True)

    def _patch_record(
        self,
        container: Element,
        base_id: int,
        patcher: Any,
        changes: dict[str, Any],
    ) -> int:
        records = list(container)
        if not 0 <= base_id < len(records):
            _invalid_style("Style component id is outside its table.", component_id=base_id)
        patched = deepcopy(records[base_id])
        patcher(patched, changes)
        return self._append_or_find(container, patched)

    def _append_or_find(self, container: Element, candidate: Element) -> int:
        signature = _signature(candidate)
        for index, existing in enumerate(container):
            if _signature(existing) == signature:
                return index
        container.append(candidate)
        container.attrib["count"] = str(len(container))
        self.changed = True
        return len(container) - 1

    def _number_format_id(self, number_format: dict[str, Any]) -> int:
        if "id" in number_format:
            format_id = number_format["id"]
            if format_id < 164:
                return format_id
            if self.num_fmts is not None and any(
                int(item.attrib.get("numFmtId", "0")) == format_id
                for item in self.num_fmts
            ):
                return format_id
            _invalid_style(
                "Custom number format id does not exist in the source workbook.",
                number_format_id=format_id,
            )
        code = number_format["code"]
        builtin_id = builtin_number_format_id(code)
        if builtin_id is not None:
            return builtin_id
        if self.num_fmts is not None:
            for item in self.num_fmts:
                if item.attrib.get("formatCode") == code:
                    return int(item.attrib["numFmtId"])
        container = self._ensure_number_formats()
        used = {
            int(item.attrib.get("numFmtId", "0"))
            for item in container
        }
        format_id = max([163, *used]) + 1
        while format_id in used:
            format_id += 1
        SubElement(
            container,
            f"{{{_MAIN_NS}}}numFmt",
            attrib={"numFmtId": str(format_id), "formatCode": code},
        )
        container.attrib["count"] = str(len(container))
        self.changed = True
        return format_id

    def _ensure_number_formats(self) -> Element:
        if self.num_fmts is not None:
            return self.num_fmts
        self.num_fmts = Element(f"{{{_MAIN_NS}}}numFmts", attrib={"count": "0"})
        fonts_index = list(self.root).index(self.fonts)
        self.root.insert(fonts_index, self.num_fmts)
        self.changed = True
        return self.num_fmts


def _patch_font(font: Element, changes: dict[str, Any]) -> None:
    for key, tag in (("bold", "b"), ("italic", "i")):
        if key in changes:
            _set_flag_child(font, tag, changes[key])
    if "name" in changes:
        _set_value_child(font, "name", "val", str(changes["name"]))
    if "size" in changes:
        _set_value_child(font, "sz", "val", str(changes["size"]))
    if "underline" in changes:
        underline = _replace_child(font, "u")
        if changes["underline"] != "single":
            underline.attrib["val"] = changes["underline"]
    if "color" in changes:
        color = _replace_child(font, "color")
        color.attrib["rgb"] = changes["color"]


def _patch_fill(fill: Element, changes: dict[str, Any]) -> None:
    pattern = fill.find(f"{{{_MAIN_NS}}}patternFill")
    if pattern is None:
        pattern = SubElement(fill, f"{{{_MAIN_NS}}}patternFill")
    if "pattern" in changes:
        pattern.attrib["patternType"] = changes["pattern"]
    if "color" in changes:
        color = _replace_child(pattern, "fgColor")
        color.attrib["rgb"] = changes["color"]
        if "pattern" not in changes:
            pattern.attrib["patternType"] = "solid"
    if "background_color" in changes:
        color = _replace_child(pattern, "bgColor")
        color.attrib["rgb"] = changes["background_color"]


def _patch_border(border: Element, changes: dict[str, Any]) -> None:
    for side_name in ("left", "right", "top", "bottom", "diagonal"):
        if side_name not in changes:
            continue
        side = border.find(f"{{{_MAIN_NS}}}{side_name}")
        if side is None:
            side = SubElement(border, f"{{{_MAIN_NS}}}{side_name}")
        side_changes = changes[side_name]
        if "style" in side_changes:
            side.attrib["style"] = side_changes["style"]
        if "color" in side_changes:
            color = _replace_child(side, "color")
            color.attrib["rgb"] = side_changes["color"]
    for key, attribute in (
        ("diagonal_up", "diagonalUp"),
        ("diagonal_down", "diagonalDown"),
        ("outline", "outline"),
    ):
        if key in changes:
            border.attrib[attribute] = _xml_bool(changes[key])


def _patch_alignment(xf: Element, changes: dict[str, Any]) -> None:
    alignment = xf.find(f"{{{_MAIN_NS}}}alignment")
    if alignment is None:
        alignment = SubElement(xf, f"{{{_MAIN_NS}}}alignment")
    aliases = {
        "wrap": "wrapText",
        "rotation": "textRotation",
        "shrink_to_fit": "shrinkToFit",
    }
    for key, value in changes.items():
        if type(value) is bool:
            rendered = _xml_bool(value)
        elif key == "rotation" and value < 0:
            rendered = str(90 - value)
        else:
            rendered = str(value)
        alignment.attrib[aliases.get(key, key)] = rendered


def _patch_protection(xf: Element, changes: dict[str, Any]) -> None:
    protection = xf.find(f"{{{_MAIN_NS}}}protection")
    if protection is None:
        protection = SubElement(xf, f"{{{_MAIN_NS}}}protection")
    for key, value in changes.items():
        protection.attrib[key] = _xml_bool(value)


def _set_flag_child(parent: Element, name: str, enabled: bool) -> None:
    existing = parent.findall(f"{{{_MAIN_NS}}}{name}")
    for child in existing:
        parent.remove(child)
    if enabled:
        SubElement(parent, f"{{{_MAIN_NS}}}{name}")


def _set_value_child(parent: Element, name: str, attribute: str, value: str) -> None:
    child = _replace_child(parent, name)
    child.attrib[attribute] = value


def _replace_child(parent: Element, name: str) -> Element:
    for child in parent.findall(f"{{{_MAIN_NS}}}{name}"):
        parent.remove(child)
    return SubElement(parent, f"{{{_MAIN_NS}}}{name}")


def _required_container(root: Element, name: str) -> Element:
    container = root.find(f"{{{_MAIN_NS}}}{name}")
    if container is None:
        _invalid_style("Required style container is missing.", container=name)
    return container


def _signature(element: Element) -> bytes:
    return tostring(element, encoding="UTF-8")


def _xml_bool(value: Any) -> str:
    return "1" if value else "0"


def _invalid_style(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
