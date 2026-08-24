"""Native x14 worksheet sparkline emission, CRUD, and readback projection."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement, register_namespace

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .relationships import relationship_map
from .xml_numeric import parse_optional_xml_number

X14_NS = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
XM_NS = "http://schemas.microsoft.com/office/excel/2006/main"
SPARKLINE_EXTENSION_URI = "{05C60535-1F16-4fd2-B633-F4F36F0B64E0}"

_MAIN_NS = NS["main"]
_COLOR_TAGS = {
    "color": "colorSeries",
    "negative_color": "colorNegative",
    "axis_color": "colorAxis",
    "marker_color": "colorMarkers",
    "first_color": "colorFirst",
    "last_color": "colorLast",
    "high_color": "colorHigh",
    "low_color": "colorLow",
}

register_namespace("x14", X14_NS)
register_namespace("xm", XM_NS)


def append_sparklines(root: Element, sparklines: list[dict[str, Any]]) -> None:
    if not sparklines:
        return
    groups = _ensure_groups(root)
    for sparkline in sparklines:
        _append_group(groups, sparkline)


def apply_sparkline_edit(context: Any, root: Element, edit: dict[str, Any]) -> None:
    edit_type = edit["type"]
    if edit_type in {"sparkline_add", "sparkline_update"}:
        _assert_data_sheet(context, edit["sparkline"])
    matches = _groups_for_location(root, edit["ref"]) if edit_type != "sparkline_add" else []
    if edit_type == "sparkline_add":
        sparkline = edit["sparkline"]
        if _groups_for_location(root, sparkline["location"]):
            _invalid("Sparkline location already exists.", ref=sparkline["location"])
        _append_group(_ensure_groups(root), sparkline)
        return
    if len(matches) != 1:
        _invalid(
            "Sparkline selector must match exactly one location.",
            ref=edit["ref"],
            matches=len(matches),
        )
    groups, group = matches[0]
    if edit_type == "sparkline_delete":
        groups.remove(group)
        _cleanup_empty_extension(root, groups)
        return
    sparkline = edit["sparkline"]
    conflicts = [
        item
        for item in _groups_for_location(root, sparkline["location"])
        if item[1] is not group
    ]
    if conflicts:
        _invalid("Sparkline update location already exists.", ref=sparkline["location"])
    index = list(groups).index(group)
    groups.remove(group)
    replacement = _group_element(sparkline)
    groups.insert(index, replacement)


def project_sparklines(package: Any) -> list[dict[str, Any]]:
    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    result: list[dict[str, Any]] = []
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is None or not relationship.resolved_target:
            continue
        root = package.xml(relationship.resolved_target)
        result.extend(_project_root(root, sheet.attrib.get("name", "")))
    return result


def _append_group(groups: Element, sparkline: dict[str, Any]) -> None:
    groups.append(_group_element(sparkline))


def _group_element(sparkline: dict[str, Any]) -> Element:
    attributes = {
        "type": {"line": "line", "column": "column", "win_loss": "stacked"}[
            sparkline["type"]
        ],
        "displayEmptyCellsAs": {
            "gap": "gap",
            "zero": "zero",
            "connect": "span",
        }[sparkline["empty_cells"]],
        "markers": _bool_text(sparkline["markers"]),
        "high": _bool_text(sparkline["high_point"]),
        "low": _bool_text(sparkline["low_point"]),
        "first": _bool_text(sparkline["first_point"]),
        "last": _bool_text(sparkline["last_point"]),
        "negative": _bool_text(sparkline["negative_points"]),
        "rightToLeft": _bool_text(sparkline["right_to_left"]),
        "minAxisType": "custom" if sparkline["manual_min"] is not None else "individual",
        "maxAxisType": "custom" if sparkline["manual_max"] is not None else "individual",
    }
    if sparkline["manual_min"] is not None:
        attributes["manualMin"] = str(sparkline["manual_min"])
    if sparkline["manual_max"] is not None:
        attributes["manualMax"] = str(sparkline["manual_max"])
    group = Element(f"{{{X14_NS}}}sparklineGroup", attributes)
    for field, tag in _COLOR_TAGS.items():
        SubElement(group, f"{{{X14_NS}}}{tag}", {"rgb": sparkline[field]})
    container = SubElement(group, f"{{{X14_NS}}}sparklines")
    item = SubElement(container, f"{{{X14_NS}}}sparkline")
    SubElement(item, f"{{{XM_NS}}}f").text = sparkline["data"]
    SubElement(item, f"{{{XM_NS}}}sqref").text = sparkline["location"]
    return group


def _ensure_groups(root: Element) -> Element:
    ext_list = root.find(f"{{{_MAIN_NS}}}extLst")
    if ext_list is None:
        ext_list = SubElement(root, f"{{{_MAIN_NS}}}extLst")
    for extension in ext_list.findall(f"{{{_MAIN_NS}}}ext"):
        groups = extension.find(f"{{{X14_NS}}}sparklineGroups")
        if groups is not None:
            return groups
    extension = SubElement(
        ext_list,
        f"{{{_MAIN_NS}}}ext",
        {"uri": SPARKLINE_EXTENSION_URI},
    )
    return SubElement(extension, f"{{{X14_NS}}}sparklineGroups")


def _groups_for_location(root: Element, location: str) -> list[tuple[Element, Element]]:
    result: list[tuple[Element, Element]] = []
    for groups in root.findall(f".//{{{X14_NS}}}sparklineGroups"):
        for group in groups.findall(f"{{{X14_NS}}}sparklineGroup"):
            locations = [
                item.text or ""
                for item in group.findall(f".//{{{XM_NS}}}sqref")
            ]
            if any(item.casefold() == location.casefold() for item in locations):
                result.append((groups, group))
    return result


def _assert_data_sheet(context: Any, sparkline: dict[str, Any]) -> None:
    sheet = sparkline["data"].rsplit("!", 1)[0]
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    if sheet not in context.sheet_parts:
        _invalid("Sparkline data sheet was not found.", sheet=sheet)


def _cleanup_empty_extension(root: Element, groups: Element) -> None:
    if len(groups):
        return
    ext_list = root.find(f"{{{_MAIN_NS}}}extLst")
    if ext_list is None:
        return
    extension = next((item for item in ext_list if groups in list(item)), None)
    if extension is not None:
        extension.remove(groups)
        if not len(extension):
            ext_list.remove(extension)
    if not len(ext_list):
        root.remove(ext_list)


def _project_root(root: Element, sheet_name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group in root.findall(f".//{{{X14_NS}}}sparklineGroup"):
        shared = _project_group(group)
        for item in group.findall(f".//{{{X14_NS}}}sparkline"):
            formula = item.find(f"{{{XM_NS}}}f")
            location = item.find(f"{{{XM_NS}}}sqref")
            result.append(
                {
                    "sheet": sheet_name,
                    "location": "" if location is None else location.text or "",
                    "data": _normalize_data("" if formula is None else formula.text or ""),
                    **shared,
                }
            )
    return result


def _project_group(group: Element) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": {
            "line": "line",
            "column": "column",
            "stacked": "win_loss",
        }.get(group.attrib.get("type", "line"), "line"),
        "empty_cells": {
            "gap": "gap",
            "zero": "zero",
            "span": "connect",
        }.get(group.attrib.get("displayEmptyCellsAs", "gap"), "gap"),
        "markers": _xml_bool(group.attrib.get("markers")),
        "high_point": _xml_bool(group.attrib.get("high")),
        "low_point": _xml_bool(group.attrib.get("low")),
        "first_point": _xml_bool(group.attrib.get("first")),
        "last_point": _xml_bool(group.attrib.get("last")),
        "negative_points": _xml_bool(group.attrib.get("negative")),
        "right_to_left": _xml_bool(group.attrib.get("rightToLeft")),
        "manual_min": parse_optional_xml_number(
            group.attrib.get("manualMin"),
            attribute="sparklineGroup.manualMin",
            minimum=-1e100,
            maximum=1e100,
        ),
        "manual_max": parse_optional_xml_number(
            group.attrib.get("manualMax"),
            attribute="sparklineGroup.manualMax",
            minimum=-1e100,
            maximum=1e100,
        ),
    }
    for field, tag in _COLOR_TAGS.items():
        color = group.find(f"{{{X14_NS}}}{tag}")
        result[field] = "" if color is None else color.attrib.get("rgb", "")
    return result


def _normalize_data(value: str) -> str:
    if "!" not in value:
        return value
    sheet, cell_range = value.rsplit("!", 1)
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    return f"'{sheet.replace(chr(39), chr(39) * 2)}'!{cell_range}"


def _bool_text(value: bool) -> str:
    return "1" if value else "0"


def _xml_bool(value: str | None) -> bool:
    return value in {"1", "true", "on"}


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
