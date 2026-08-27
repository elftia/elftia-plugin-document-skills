"""Safe worksheet add/delete/copy/reorder and reference-aware rename."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import CONTENT_TYPES, CONTENT_TYPES_NS, NS, REL_WORKSHEET, WORKBOOK_RELS
from .structural_refs import (
    has_external_workbook_reference,
    references_sheet,
    rename_sheet_references,
)

_MAIN_NS = NS["main"]
_REL_NS = NS["rels"]
_SHEET_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
_FORMULA_TAGS = {
    "f",
    "formula",
    "formula1",
    "formula2",
    "calculatedColumnFormula",
    "totalsRowFormula",
    "definedName",
}


def apply_sheet_edit(context: Any, edit: dict[str, Any]) -> None:
    edit_type = edit["type"]
    if edit_type == "sheet_add":
        _add_sheet(context, edit["sheet"], edit["position"])
    elif edit_type == "sheet_copy":
        _copy_sheet(context, edit["sheet"], edit["name"], edit["position"])
    elif edit_type == "sheet_delete":
        _delete_sheet(context, edit["sheet"])
    elif edit_type == "sheet_reorder":
        _reorder_sheet(context, edit["sheet"], edit["position"])
    elif edit_type == "sheet_rename":
        _rename_sheet(context, edit["sheet"], edit["value"])
    else:
        _invalid("Sheet edit type is not implemented.", edit_type=edit_type)
    context._invalidate_calc_chain()
    context._force_full_calculation()


def _add_sheet(context: Any, name: str, position: int) -> None:
    _assert_unique_name(context, name)
    root = Element(f"{{{_MAIN_NS}}}worksheet")
    SubElement(root, f"{{{_MAIN_NS}}}dimension", {"ref": "A1"})
    SubElement(root, f"{{{_MAIN_NS}}}sheetData")
    _register_sheet(context, name, root, position)


def _copy_sheet(context: Any, source_name: str, new_name: str, position: int) -> None:
    _assert_unique_name(context, new_name)
    source_part = context.sheet_parts.get(source_name)
    if source_part is None:
        _invalid("Sheet copy source was not found.", sheet=source_name)
    relationships = context.package.sheet_rels(source_part)
    if relationships:
        _enhancement(
            "Sheet copy is limited to worksheets without related objects.",
            capability="xlsx.related-object-sheet-copy",
            sheet=source_name,
            relationship_types=sorted(
                {item.relationship_type.rsplit("/", 1)[-1] for item in relationships}
            ),
        )
    new_index = _register_sheet(
        context,
        new_name,
        deepcopy(context.worksheet(source_part)),
        position,
    )
    _copy_local_defined_names(context, source_name, new_name, new_index)


def _delete_sheet(context: Any, name: str) -> None:
    sheets = context.workbook["sheets"]
    if len(sheets) <= 1:
        _invalid("A workbook must retain at least one worksheet.", sheet=name)
    index = _sheet_index(sheets, name)
    target_part = context.sheet_parts[name]
    relationships = context.package.sheet_rels(target_part)
    if relationships:
        _enhancement(
            "Sheet delete is blocked when the worksheet owns related objects.",
            capability="xlsx.related-object-sheet-delete",
            sheet=name,
            relationship_types=sorted(
                {item.relationship_type.rsplit("/", 1)[-1] for item in relationships}
            ),
        )
    _assert_no_inbound_sheet_references(context, name, target_part, index)
    old_order = [sheet["name"] for sheet in sheets]
    sheet_element = _sheet_element(context, name)
    relationship_id = sheet_element.attrib[f"{{{NS['r']}}}id"]
    _sheets_element(context).remove(sheet_element)
    _remove_relationship(context, relationship_id)
    _remove_content_type(context, target_part)
    context.remove_part(target_part)
    rels_part = _worksheet_relationship_part(target_part)
    if rels_part in context.package.parts:
        context.remove_part(rels_part)
    del sheets[index]
    context.sheet_parts.pop(name)
    context.sheet_names_by_part.pop(target_part, None)
    _remove_local_defined_names(context.workbook_root, index)
    _remap_local_sheet_ids(
        context.workbook_root,
        old_order,
        [sheet["name"] for sheet in sheets],
    )
    context.mark_dirty("xl/workbook.xml")


def _reorder_sheet(context: Any, name: str, position: int) -> None:
    sheets = context.workbook["sheets"]
    old_order = [sheet["name"] for sheet in sheets]
    current_index = _sheet_index(sheets, name)
    target_index = min(position, len(sheets) - 1)
    if current_index == target_index:
        _invalid("Sheet is already at the requested position.", sheet=name, position=position)
    sheet = sheets.pop(current_index)
    sheets.insert(target_index, sheet)
    container = _sheets_element(context)
    elements = list(container.findall(f"{{{_MAIN_NS}}}sheet"))
    moved = elements.pop(current_index)
    elements.insert(target_index, moved)
    for element in list(container):
        if element.tag == f"{{{_MAIN_NS}}}sheet":
            container.remove(element)
    container.extend(elements)
    _remap_local_sheet_ids(
        context.workbook_root,
        old_order,
        [item["name"] for item in sheets],
    )
    context.mark_dirty("xl/workbook.xml")


def _rename_sheet(context: Any, old_name: str, new_name: str) -> None:
    if old_name.casefold() == new_name.casefold():
        _invalid("Sheet rename must change the sheet name.", sheet=old_name)
    _assert_unique_name(context, new_name)
    sheet_element = _sheet_element(context, old_name)
    target_part = context.sheet_parts[old_name]
    for part in _reference_xml_parts(context):
        root = context.root(part)
        for element in root.iter():
            if (
                _local_name(element.tag) in _FORMULA_TAGS
                and has_external_workbook_reference(element.text or "")
            ):
                _enhancement(
                    "Sheet rename does not rewrite external-workbook references.",
                    capability="xlsx.external-reference-sheet-rename",
                    part=part,
                )
        changed = _rename_references_in_root(root, old_name, new_name)
        if changed:
            context.mark_dirty(part)
    for defined_name in context.workbook_root.findall(
        f".//{{{_MAIN_NS}}}definedName"
    ):
        if has_external_workbook_reference(defined_name.text or ""):
            _enhancement(
                "Sheet rename does not rewrite external-workbook defined names.",
                capability="xlsx.external-reference-sheet-rename",
                name=defined_name.attrib.get("name", ""),
            )
    _rename_references_in_root(context.workbook_root, old_name, new_name)
    sheet_element.attrib["name"] = new_name
    for sheet in context.workbook["sheets"]:
        if sheet["name"] == old_name:
            sheet["name"] = new_name
            break
    context.sheet_parts.pop(old_name)
    context.sheet_parts[new_name] = target_part
    context.sheet_names_by_part[target_part] = new_name
    context.mark_dirty("xl/workbook.xml")


def _register_sheet(context: Any, name: str, root: Element, position: int) -> int:
    part = _next_sheet_part(context)
    relationship_id = _add_relationship(context, part)
    _add_content_type(context, part)
    sheets = context.workbook["sheets"]
    old_order = [sheet["name"] for sheet in sheets]
    target_index = min(position, len(sheets))
    sheet_ids = [
        int(item.attrib.get("sheetId", "0"))
        for item in _sheets_element(context).findall(f"{{{_MAIN_NS}}}sheet")
    ]
    element = Element(
        f"{{{_MAIN_NS}}}sheet",
        {
            "name": name,
            "sheetId": str(max(sheet_ids, default=0) + 1),
            f"{{{NS['r']}}}id": relationship_id,
        },
    )
    _sheets_element(context).insert(target_index, element)
    sheets.insert(
        target_index,
        {
            "name": name,
            "part": part,
            "order": target_index,
            "state": "visible",
            "rows": [],
            "columns": [],
        },
    )
    context.sheet_parts[name] = part
    context.sheet_names_by_part[part] = name
    context.add_root(part, root)
    _remap_local_sheet_ids(
        context.workbook_root,
        old_order,
        [sheet["name"] for sheet in sheets],
    )
    context.mark_dirty("xl/workbook.xml")
    return target_index


def _assert_no_inbound_sheet_references(
    context: Any,
    sheet_name: str,
    target_part: str,
    target_index: int,
) -> None:
    for part in _reference_xml_parts(context):
        if part == target_part:
            continue
        root = context.root(part)
        for element in root.iter():
            if _local_name(element.tag) in _FORMULA_TAGS and references_sheet(
                element.text or "",
                sheet_name,
            ):
                _enhancement(
                    "Sheet delete would invalidate a formula or object reference.",
                    capability="xlsx.sheet-delete-reference-migration",
                    sheet=sheet_name,
                    part=part,
                )
            location = element.attrib.get("location")
            if location and references_sheet(location, sheet_name):
                _enhancement(
                    "Sheet delete would invalidate an internal hyperlink.",
                    capability="xlsx.sheet-delete-reference-migration",
                    sheet=sheet_name,
                    part=part,
                )
    for defined_name in context.workbook_root.findall(f".//{{{_MAIN_NS}}}definedName"):
        if defined_name.attrib.get("localSheetId") == str(target_index):
            continue
        if references_sheet(defined_name.text or "", sheet_name):
            _enhancement(
                "Sheet delete would invalidate a defined name.",
                capability="xlsx.sheet-delete-reference-migration",
                sheet=sheet_name,
                name=defined_name.attrib.get("name", ""),
            )


def _rename_references_in_root(root: Element, old_name: str, new_name: str) -> bool:
    changed = False
    for element in root.iter():
        if _local_name(element.tag) in _FORMULA_TAGS and element.text:
            rewritten = rename_sheet_references(element.text, old_name, new_name)
            if rewritten != element.text:
                element.text = rewritten
                changed = True
        location = element.attrib.get("location")
        if location:
            rewritten = rename_sheet_references(location, old_name, new_name)
            if rewritten != location:
                element.attrib["location"] = rewritten
                changed = True
    return changed


def _copy_local_defined_names(
    context: Any,
    source_name: str,
    new_name: str,
    new_index: int,
) -> None:
    sheets = context.workbook["sheets"]
    source_index = next(
        index for index, sheet in enumerate(sheets) if sheet["name"] == source_name
    )
    container = context.workbook_root.find(f"{{{_MAIN_NS}}}definedNames")
    if container is None:
        return
    copies = []
    for item in container.findall(f"{{{_MAIN_NS}}}definedName"):
        if item.attrib.get("localSheetId") != str(source_index):
            continue
        clone = deepcopy(item)
        clone.attrib["localSheetId"] = str(new_index)
        clone.text = rename_sheet_references(clone.text or "", source_name, new_name)
        copies.append(clone)
    container.extend(copies)
    if copies:
        context.mark_dirty("xl/workbook.xml")


def _remap_local_sheet_ids(root: Element, old_order: list[str], new_order: list[str]) -> None:
    new_indexes = {name: index for index, name in enumerate(new_order)}
    for item in root.findall(f".//{{{_MAIN_NS}}}definedName"):
        raw = item.attrib.get("localSheetId")
        if raw is None:
            continue
        old_index = int(raw)
        if 0 <= old_index < len(old_order) and old_order[old_index] in new_indexes:
            item.attrib["localSheetId"] = str(new_indexes[old_order[old_index]])


def _remove_local_defined_names(root: Element, deleted_index: int) -> None:
    container = root.find(f"{{{_MAIN_NS}}}definedNames")
    if container is None:
        return
    for item in list(container.findall(f"{{{_MAIN_NS}}}definedName")):
        if item.attrib.get("localSheetId") == str(deleted_index):
            container.remove(item)
    if not len(container):
        root.remove(container)


def _reference_xml_parts(context: Any) -> list[str]:
    prefixes = ("xl/worksheets/", "xl/charts/", "xl/tables/")
    return sorted(
        part
        for part in {*context.package.parts, *context.added}
        if part.endswith(".xml") and part.startswith(prefixes)
    )


def _add_relationship(context: Any, part: str) -> str:
    root = context.root(WORKBOOK_RELS)
    used = {item.attrib.get("Id", "") for item in root.findall(f"{{{_REL_NS}}}Relationship")}
    index = 1
    while f"rId{index}" in used:
        index += 1
    relationship_id = f"rId{index}"
    SubElement(
        root,
        f"{{{_REL_NS}}}Relationship",
        {
            "Id": relationship_id,
            "Type": REL_WORKSHEET,
            "Target": f"worksheets/{part.rsplit('/', 1)[-1]}",
        },
    )
    context.mark_dirty(WORKBOOK_RELS)
    return relationship_id


def _remove_relationship(context: Any, relationship_id: str) -> None:
    root = context.root(WORKBOOK_RELS)
    match = next(
        (
            item
            for item in root.findall(f"{{{_REL_NS}}}Relationship")
            if item.attrib.get("Id") == relationship_id
        ),
        None,
    )
    if match is None:
        _invalid("Worksheet relationship was not found.", relationship_id=relationship_id)
    root.remove(match)
    context.mark_dirty(WORKBOOK_RELS)


def _add_content_type(context: Any, part: str) -> None:
    root = context.root(CONTENT_TYPES)
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": f"/{part}", "ContentType": _SHEET_CONTENT_TYPE},
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
        _invalid("Worksheet content type was not found.", part=part)
    root.remove(match)
    context.mark_dirty(CONTENT_TYPES)


def _next_sheet_part(context: Any) -> str:
    used = {*context.package.parts, *context.added}
    index = 1
    while f"xl/worksheets/sheet{index}.xml" in used:
        index += 1
    return f"xl/worksheets/sheet{index}.xml"


def _assert_unique_name(context: Any, name: str) -> None:
    if any(sheet["name"].casefold() == name.casefold() for sheet in context.workbook["sheets"]):
        _invalid("Worksheet name must be unique.", sheet=name)


def _sheet_index(sheets: list[dict[str, Any]], name: str) -> int:
    match = next(
        (index for index, sheet in enumerate(sheets) if sheet["name"] == name),
        None,
    )
    if match is None:
        _invalid("Worksheet was not found.", sheet=name)
    return match


def _sheets_element(context: Any) -> Element:
    result = context.workbook_root.find(f"{{{_MAIN_NS}}}sheets")
    if result is None:
        _invalid("Workbook is missing its sheets collection.")
    return result


def _sheet_element(context: Any, name: str) -> Element:
    result = next(
        (
            item
            for item in _sheets_element(context).findall(f"{{{_MAIN_NS}}}sheet")
            if item.attrib.get("name") == name
        ),
        None,
    )
    if result is None:
        _invalid("Worksheet was not found.", sheet=name)
    return result


def _worksheet_relationship_part(part: str) -> str:
    directory, filename = part.rsplit("/", 1)
    return f"{directory}/_rels/{filename}.rels"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
