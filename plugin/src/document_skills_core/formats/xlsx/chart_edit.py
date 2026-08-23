"""Transactional native chart add/update/delete for existing XLSX packages."""

from __future__ import annotations

import posixpath
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart import CHART_NS, DRAWING_NS, append_chart_anchor, build_chart_root
from .constants import CONTENT_TYPES, CONTENT_TYPES_NS, NS, REL_CHART, REL_DRAWING

_MAIN_NS = NS["main"]
_REL_NS = NS["rels"]
_CHART_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
_DRAWING_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawing+xml"


def apply_chart_edit(context: Any, edit: dict[str, Any]) -> None:
    edit_type = edit["type"]
    if edit_type == "chart_add":
        _add_chart(context, edit["chart"])
    elif edit_type == "chart_update":
        _update_chart(context, edit["sheet"], edit["name"], edit["chart"])
    elif edit_type == "chart_delete":
        _delete_chart(context, edit["sheet"], edit["name"])
    else:
        _invalid("Chart edit type is not implemented.", edit_type=edit_type)


def _add_chart(context: Any, chart: dict[str, Any]) -> None:
    _assert_chart_references(context, chart)
    _assert_unique_name(context, chart["name"])
    sheet_part = context.sheet_parts.get(chart["sheet"])
    if sheet_part is None:
        _invalid("Chart placement sheet was not found.", sheet=chart["sheet"])
    drawing_part, drawing_root, drawing_rels_part, drawing_rels = _ensure_sheet_drawing(
        context,
        sheet_part,
    )
    chart_part = _next_part(context, "xl/charts/chart", ".xml")
    chart_id = _part_number(chart_part, "chart")
    context.add_root(chart_part, build_chart_root(chart, chart_id))
    relationship_id = _next_relationship_id(drawing_rels)
    SubElement(
        drawing_rels,
        f"{{{_REL_NS}}}Relationship",
        {
            "Id": relationship_id,
            "Type": REL_CHART,
            "Target": posixpath.relpath(chart_part, posixpath.dirname(drawing_part)),
        },
    )
    if drawing_rels_part not in context.added:
        context.mark_dirty(drawing_rels_part)
    append_chart_anchor(
        drawing_root,
        chart,
        relationship_id=relationship_id,
        object_id=_next_object_id(drawing_root),
    )
    context.mark_dirty(drawing_part)
    _add_content_type(context, chart_part, _CHART_CONTENT_TYPE)


def _update_chart(
    context: Any,
    sheet_name: str,
    name: str,
    chart: dict[str, Any],
) -> None:
    _assert_chart_references(context, chart)
    record = _find_chart(context, sheet_name, name)
    _assert_unique_name(context, chart["name"], excluding=record["anchor"])
    chart_id = _part_number(record["chart_part"], "chart")
    context.roots[record["chart_part"]] = build_chart_root(chart, chart_id)
    context.mark_dirty(record["chart_part"])
    non_visual = record["anchor"].find(f".//{{{DRAWING_NS}}}cNvPr")
    if non_visual is None:
        _invalid("Chart drawing is missing its non-visual properties.", chart=name)
    non_visual.attrib["name"] = chart["name"]
    for marker_name in ("from", "to"):
        marker = record["anchor"].find(f"{{{DRAWING_NS}}}{marker_name}")
        if marker is not None:
            record["anchor"].remove(marker)
    temporary = Element(f"{{{DRAWING_NS}}}wsDr")
    replacement = append_chart_anchor(
        temporary,
        chart,
        relationship_id="unused",
        object_id=0,
    )
    markers = [
        replacement.find(f"{{{DRAWING_NS}}}{marker_name}")
        for marker_name in ("from", "to")
    ]
    for index, marker in enumerate(markers):
        assert marker is not None
        record["anchor"].insert(index, marker)
    context.mark_dirty(record["drawing_part"])


def _delete_chart(context: Any, sheet_name: str, name: str) -> None:
    record = _find_chart(context, sheet_name, name)
    drawing_root = record["drawing_root"]
    drawing_root.remove(record["anchor"])
    drawing_rels = record["drawing_rels"]
    drawing_rels.remove(record["chart_relationship"])
    context.remove_part(record["chart_part"])
    _remove_content_type(context, record["chart_part"])
    remaining_anchors = [
        child
        for child in drawing_root
        if child.tag.rsplit("}", 1)[-1] in {"twoCellAnchor", "oneCellAnchor", "absoluteAnchor"}
    ]
    if remaining_anchors:
        context.mark_dirty(record["drawing_part"])
        context.mark_dirty(record["drawing_rels_part"])
        return
    if len(drawing_root):
        _invalid(
            "Chart delete cannot remove a drawing that retains unsupported metadata.",
            drawing=record["drawing_part"],
        )
    worksheet = context.worksheet(record["sheet_part"])
    drawing_element = record["worksheet_drawing"]
    worksheet.remove(drawing_element)
    context.mark_dirty(record["sheet_part"])
    worksheet_rels = record["worksheet_rels"]
    worksheet_rels.remove(record["drawing_relationship"])
    if len(worksheet_rels):
        context.mark_dirty(record["worksheet_rels_part"])
    else:
        context.remove_part(record["worksheet_rels_part"])
    context.remove_part(record["drawing_rels_part"])
    context.remove_part(record["drawing_part"])
    _remove_content_type(context, record["drawing_part"])


def _find_chart(context: Any, sheet_name: str, name: str) -> dict[str, Any]:
    sheet_part = context.sheet_parts.get(sheet_name)
    if sheet_part is None:
        _invalid("Chart placement sheet was not found.", sheet=sheet_name)
    worksheet = context.worksheet(sheet_part)
    worksheet_rels_part = _rels_part(sheet_part)
    if worksheet_rels_part not in context.package.parts and worksheet_rels_part not in context.added:
        _invalid("Worksheet does not contain native charts.", sheet=sheet_name)
    worksheet_rels = context.root(worksheet_rels_part)
    matches = []
    for worksheet_drawing in worksheet.findall(f"{{{_MAIN_NS}}}drawing"):
        relationship_id = worksheet_drawing.attrib.get(f"{{{NS['r']}}}id", "")
        drawing_relationship = _relationship_by_id(worksheet_rels, relationship_id)
        if drawing_relationship is None or drawing_relationship.attrib.get("Type") != REL_DRAWING:
            continue
        drawing_part = _resolve_target(sheet_part, drawing_relationship.attrib.get("Target", ""))
        drawing_rels_part = _rels_part(drawing_part)
        drawing_root = context.root(drawing_part)
        drawing_rels = context.root(drawing_rels_part)
        for anchor in drawing_root:
            chart_reference = anchor.find(f".//{{{CHART_NS}}}chart")
            non_visual = anchor.find(f".//{{{DRAWING_NS}}}cNvPr")
            if chart_reference is None or non_visual is None:
                continue
            if non_visual.attrib.get("name", "").casefold() != name.casefold():
                continue
            chart_relationship = _relationship_by_id(
                drawing_rels,
                chart_reference.attrib.get(f"{{{NS['r']}}}id", ""),
            )
            if chart_relationship is None or chart_relationship.attrib.get("Type") != REL_CHART:
                _invalid("Chart drawing relationship is invalid.", chart=name)
            chart_part = _resolve_target(
                drawing_part,
                chart_relationship.attrib.get("Target", ""),
            )
            matches.append(
                {
                    "sheet_part": sheet_part,
                    "worksheet_drawing": worksheet_drawing,
                    "worksheet_rels_part": worksheet_rels_part,
                    "worksheet_rels": worksheet_rels,
                    "drawing_relationship": drawing_relationship,
                    "drawing_part": drawing_part,
                    "drawing_root": drawing_root,
                    "drawing_rels_part": drawing_rels_part,
                    "drawing_rels": drawing_rels,
                    "anchor": anchor,
                    "chart_relationship": chart_relationship,
                    "chart_part": chart_part,
                }
            )
    if len(matches) != 1:
        _invalid(
            "Chart selector must match exactly one named chart on the sheet.",
            sheet=sheet_name,
            chart=name,
            matches=len(matches),
        )
    return matches[0]


def _ensure_sheet_drawing(
    context: Any,
    sheet_part: str,
) -> tuple[str, Element, str, Element]:
    worksheet = context.worksheet(sheet_part)
    worksheet_rels_part = _rels_part(sheet_part)
    if worksheet_rels_part in context.package.parts or worksheet_rels_part in context.added:
        worksheet_rels = context.root(worksheet_rels_part)
    else:
        worksheet_rels = Element(f"{{{_REL_NS}}}Relationships")
        context.add_root(worksheet_rels_part, worksheet_rels)
    drawing_elements = worksheet.findall(f"{{{_MAIN_NS}}}drawing")
    if len(drawing_elements) > 1:
        _invalid("Worksheet contains ambiguous drawing references.", sheet_part=sheet_part)
    if drawing_elements:
        relationship = _relationship_by_id(
            worksheet_rels,
            drawing_elements[0].attrib.get(f"{{{NS['r']}}}id", ""),
        )
        if relationship is None or relationship.attrib.get("Type") != REL_DRAWING:
            _invalid("Worksheet drawing relationship is invalid.", sheet_part=sheet_part)
        drawing_part = _resolve_target(sheet_part, relationship.attrib.get("Target", ""))
        drawing_rels_part = _rels_part(drawing_part)
        if drawing_rels_part in context.package.parts or drawing_rels_part in context.added:
            drawing_rels = context.root(drawing_rels_part)
        else:
            drawing_rels = Element(f"{{{_REL_NS}}}Relationships")
            context.add_root(drawing_rels_part, drawing_rels)
        return drawing_part, context.root(drawing_part), drawing_rels_part, drawing_rels
    drawing_part = _next_part(context, "xl/drawings/drawing", ".xml")
    drawing_root = Element(f"{{{DRAWING_NS}}}wsDr")
    context.add_root(drawing_part, drawing_root)
    drawing_rels_part = _rels_part(drawing_part)
    drawing_rels = Element(f"{{{_REL_NS}}}Relationships")
    context.add_root(drawing_rels_part, drawing_rels)
    relationship_id = _next_relationship_id(worksheet_rels)
    SubElement(
        worksheet_rels,
        f"{{{_REL_NS}}}Relationship",
        {
            "Id": relationship_id,
            "Type": REL_DRAWING,
            "Target": posixpath.relpath(drawing_part, posixpath.dirname(sheet_part)),
        },
    )
    if worksheet_rels_part not in context.added:
        context.mark_dirty(worksheet_rels_part)
    drawing_element = Element(
        f"{{{_MAIN_NS}}}drawing",
        {f"{{{NS['r']}}}id": relationship_id},
    )
    _insert_drawing(worksheet, drawing_element)
    context.mark_dirty(sheet_part)
    _add_content_type(context, drawing_part, _DRAWING_CONTENT_TYPE)
    return drawing_part, drawing_root, drawing_rels_part, drawing_rels


def _assert_chart_references(context: Any, chart: dict[str, Any]) -> None:
    if chart["sheet"] not in context.sheet_parts:
        _invalid("Chart placement sheet was not found.", sheet=chart["sheet"])
    for series in chart["series"]:
        for key in ("categories", "values", "x_values", "y_values"):
            formula = series.get(key)
            if formula is None:
                continue
            sheet = formula.rsplit("!", 1)[0]
            if sheet.startswith("'") and sheet.endswith("'"):
                sheet = sheet[1:-1].replace("''", "'")
            if sheet not in context.sheet_parts:
                _invalid("Chart data sheet was not found.", chart=chart["name"], sheet=sheet)


def _assert_unique_name(
    context: Any,
    name: str,
    *,
    excluding: Element | None = None,
) -> None:
    for drawing_part in sorted(
        part
        for part in {*context.package.parts, *context.added}
        if part.startswith("xl/drawings/")
        and "/_rels/" not in part
        and part.endswith(".xml")
        and part not in context.removed
    ):
        root = context.root(drawing_part)
        for anchor in root:
            if anchor is excluding or anchor.find(f".//{{{CHART_NS}}}chart") is None:
                continue
            non_visual = anchor.find(f".//{{{DRAWING_NS}}}cNvPr")
            if non_visual is not None and non_visual.attrib.get("name", "").casefold() == name.casefold():
                _invalid("Chart names must be unique.", chart=name)


def _add_content_type(context: Any, part: str, content_type: str) -> None:
    root = context.root(CONTENT_TYPES)
    if any(
        item.attrib.get("PartName", "").lstrip("/") == part
        for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
    ):
        _invalid("Chart content-type override already exists.", part=part)
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": f"/{part}", "ContentType": content_type},
    )
    context.mark_dirty(CONTENT_TYPES)


def _remove_content_type(context: Any, part: str) -> None:
    root = context.root(CONTENT_TYPES)
    match = next(
        (
            item
            for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
            if item.attrib.get("PartName", "").lstrip("/") == part
        ),
        None,
    )
    if match is None:
        _invalid("Chart content-type override is missing.", part=part)
    root.remove(match)
    context.mark_dirty(CONTENT_TYPES)


def _next_part(context: Any, prefix: str, suffix: str) -> str:
    used = {*context.package.parts, *context.added}
    index = 1
    while f"{prefix}{index}{suffix}" in used:
        index += 1
    return f"{prefix}{index}{suffix}"


def _part_number(part: str, stem: str) -> int:
    filename = part.rsplit("/", 1)[-1]
    number = filename.removeprefix(stem).removesuffix(".xml")
    return int(number) if number.isdigit() else 1


def _next_relationship_id(root: Element) -> str:
    used = {
        item.attrib.get("Id", "")
        for item in root.findall(f"{{{_REL_NS}}}Relationship")
    }
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def _next_object_id(root: Element) -> int:
    ids = [
        int(item.attrib.get("id", "0"))
        for item in root.findall(f".//{{{DRAWING_NS}}}cNvPr")
        if item.attrib.get("id", "0").isdigit()
    ]
    return max(ids, default=0) + 1


def _relationship_by_id(root: Element, relationship_id: str) -> Element | None:
    return next(
        (
            item
            for item in root.findall(f"{{{_REL_NS}}}Relationship")
            if item.attrib.get("Id") == relationship_id
        ),
        None,
    )


def _rels_part(part: str) -> str:
    directory, filename = part.rsplit("/", 1)
    return f"{directory}/_rels/{filename}.rels"


def _resolve_target(source_part: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target)).lstrip("/")


def _insert_drawing(worksheet: Element, drawing: Element) -> None:
    table_parts = worksheet.find(f"{{{_MAIN_NS}}}tableParts")
    ext_list = worksheet.find(f"{{{_MAIN_NS}}}extLst")
    following = table_parts if table_parts is not None else ext_list
    if following is None:
        worksheet.append(drawing)
    else:
        worksheet.insert(list(worksheet).index(following), drawing)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
