"""Native table add/resize/rename/style/delete for XLSX mutations."""

from __future__ import annotations

import posixpath
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import CONTENT_TYPES, CONTENT_TYPES_NS, NS, REL_TABLE

_MAIN_NS = NS["main"]
_REL_NS = NS["rels"]
_TABLE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
_FORMULA_TAGS = {
    "f",
    "formula",
    "formula1",
    "formula2",
    "calculatedColumnFormula",
    "totalsRowFormula",
    "definedName",
}


def apply_table_edit(
    context: Any,
    edit: dict[str, Any],
    shared_strings: list[str],
) -> None:
    edit_type = edit["type"]
    if edit_type == "table_add":
        _add_table(context, edit, shared_strings)
    elif edit_type == "table_resize":
        _resize_table(context, edit, shared_strings)
    elif edit_type == "table_rename":
        _rename_table(context, edit)
    elif edit_type == "table_style":
        _style_table(context, edit)
    elif edit_type == "table_delete":
        _delete_table(context, edit)
    else:
        _invalid("Table edit type is not implemented.", edit_type=edit_type)


def _add_table(context: Any, edit: dict[str, Any], shared_strings: list[str]) -> None:
    _assert_unique_name(context, edit["name"])
    sheet_part = context.sheet_parts.get(edit["sheet"])
    if sheet_part is None:
        _invalid("Table sheet was not found.", sheet=edit["sheet"])
    ref = _normalize_range(edit["ref"])
    _assert_nonoverlapping(context, sheet_part, ref)
    headers = _extract_headers(context.worksheet(sheet_part), ref, shared_strings)
    table_id = _next_table_id(context)
    table_part = _next_table_part(context)
    root = _build_table_root(
        table_id=table_id,
        name=edit["name"],
        ref=ref,
        style=edit["table_style"],
        headers=headers,
    )
    context.add_root(table_part, root)
    relationship_id = _add_table_relationship(context, sheet_part, table_part)
    _add_table_part_reference(context.worksheet(sheet_part), relationship_id)
    _add_content_type(context, table_part)
    context.mark_dirty(sheet_part)


def _resize_table(context: Any, edit: dict[str, Any], shared_strings: list[str]) -> None:
    sheet_part, _rels_part, _relationship, table_part, root = _find_table(
        context,
        edit["sheet"],
        edit["name"],
    )
    old_ref = root.attrib.get("ref", "")
    new_ref = _normalize_range(edit["ref"])
    old_bounds = _range_bounds(old_ref)
    new_bounds = _range_bounds(new_ref)
    if old_bounds[:2] != new_bounds[:2]:
        _invalid("Table resize must preserve the top-left header cell.", table=edit["name"])
    _assert_nonoverlapping(context, sheet_part, new_ref, exclude_part=table_part)
    old_headers = _table_columns(root)
    new_headers = _extract_headers(context.worksheet(sheet_part), new_ref, shared_strings)
    shared_width = min(len(old_headers), len(new_headers))
    if old_headers[:shared_width] != new_headers[:shared_width]:
        _invalid("Table resize cannot rename existing header columns.", table=edit["name"])
    removed_headers = old_headers[len(new_headers):]
    if removed_headers:
        _assert_no_removed_column_references(context, edit["name"], removed_headers)
    root.attrib["ref"] = new_ref
    auto_filter = root.find(f"{{{_MAIN_NS}}}autoFilter")
    if auto_filter is None:
        auto_filter = Element(f"{{{_MAIN_NS}}}autoFilter")
        root.insert(0, auto_filter)
    auto_filter.attrib["ref"] = new_ref
    _replace_table_columns(root, new_headers)
    context.mark_dirty(table_part)


def _rename_table(context: Any, edit: dict[str, Any]) -> None:
    _assert_unique_name(context, edit["value"], excluding=edit["name"])
    _sheet_part, _rels_part, _relationship, table_part, root = _find_table(
        context,
        edit["sheet"],
        edit["name"],
    )
    old_name = root.attrib.get("name", edit["name"])
    new_name = edit["value"]
    for part in _reference_parts(context):
        part_root = context.root(part)
        changed = False
        for element in part_root.iter():
            if _local_name(element.tag) not in _FORMULA_TAGS or not element.text:
                continue
            rewritten = _rename_table_token(element.text, old_name, new_name)
            if rewritten != element.text:
                element.text = rewritten
                changed = True
        if changed:
            context.mark_dirty(part)
    root.attrib["name"] = new_name
    root.attrib["displayName"] = new_name
    context.mark_dirty(table_part)


def _style_table(context: Any, edit: dict[str, Any]) -> None:
    _sheet_part, _rels_part, _relationship, table_part, root = _find_table(
        context,
        edit["sheet"],
        edit["name"],
    )
    style = root.find(f"{{{_MAIN_NS}}}tableStyleInfo")
    if style is None:
        style = SubElement(root, f"{{{_MAIN_NS}}}tableStyleInfo")
    style.attrib.update(
        {
            "name": edit["table_style"],
            "showFirstColumn": style.attrib.get("showFirstColumn", "0"),
            "showLastColumn": style.attrib.get("showLastColumn", "0"),
            "showRowStripes": style.attrib.get("showRowStripes", "1"),
            "showColumnStripes": style.attrib.get("showColumnStripes", "0"),
        }
    )
    context.mark_dirty(table_part)


def _delete_table(context: Any, edit: dict[str, Any]) -> None:
    sheet_part, rels_part, relationship, table_part, root = _find_table(
        context,
        edit["sheet"],
        edit["name"],
    )
    _assert_no_table_references(context, root.attrib.get("name", edit["name"]), table_part)
    rels_root = context.root(rels_part)
    rels_root.remove(relationship)
    if len(rels_root):
        context.mark_dirty(rels_part)
    else:
        context.remove_part(rels_part)
    worksheet = context.worksheet(sheet_part)
    table_parts = worksheet.find(f"{{{_MAIN_NS}}}tableParts")
    if table_parts is None:
        _invalid("Worksheet tableParts collection is missing.", table=edit["name"])
    table_part_ref = next(
        (
            item
            for item in table_parts.findall(f"{{{_MAIN_NS}}}tablePart")
            if item.attrib.get(f"{{{NS['r']}}}id") == relationship.attrib.get("Id")
        ),
        None,
    )
    if table_part_ref is None:
        _invalid("Worksheet table reference is missing.", table=edit["name"])
    table_parts.remove(table_part_ref)
    if len(table_parts):
        table_parts.attrib["count"] = str(len(table_parts))
    else:
        worksheet.remove(table_parts)
    context.mark_dirty(sheet_part)
    _remove_content_type(context, table_part)
    context.remove_part(table_part)


def _find_table(
    context: Any,
    sheet_name: str,
    table_name: str,
) -> tuple[str, str, Element, str, Element]:
    sheet_part = context.sheet_parts.get(sheet_name)
    if sheet_part is None:
        _invalid("Table sheet was not found.", sheet=sheet_name)
    rels_part = _worksheet_rels_part(sheet_part)
    if rels_part not in context.package.parts and rels_part not in context.added:
        _invalid("Worksheet does not contain native tables.", sheet=sheet_name)
    rels_root = context.root(rels_part)
    for relationship in rels_root.findall(f"{{{_REL_NS}}}Relationship"):
        if relationship.attrib.get("Type", "").rsplit("/", 1)[-1] != "table":
            continue
        table_part = _resolve_target(sheet_part, relationship.attrib.get("Target", ""))
        if table_part in context.removed:
            continue
        root = context.root(table_part)
        if root.attrib.get("name", "").casefold() == table_name.casefold():
            return sheet_part, rels_part, relationship, table_part, root
    _invalid("Native table was not found on the requested sheet.", sheet=sheet_name, table=table_name)


def _table_entries(context: Any, sheet_part: str) -> list[tuple[str, Element]]:
    rels_part = _worksheet_rels_part(sheet_part)
    if rels_part not in context.package.parts and rels_part not in context.added:
        return []
    result: list[tuple[str, Element]] = []
    for relationship in context.root(rels_part).findall(f"{{{_REL_NS}}}Relationship"):
        if relationship.attrib.get("Type", "").rsplit("/", 1)[-1] != "table":
            continue
        table_part = _resolve_target(sheet_part, relationship.attrib.get("Target", ""))
        if table_part not in context.removed:
            result.append((table_part, context.root(table_part)))
    return result


def _assert_unique_name(
    context: Any,
    name: str,
    *,
    excluding: str | None = None,
) -> None:
    for sheet_part in context.sheet_parts.values():
        for _part, root in _table_entries(context, sheet_part):
            existing = root.attrib.get("name", "")
            if excluding and existing.casefold() == excluding.casefold():
                continue
            if existing.casefold() == name.casefold():
                _invalid("Native table display names must be unique.", table=name)


def _assert_nonoverlapping(
    context: Any,
    sheet_part: str,
    ref: str,
    *,
    exclude_part: str | None = None,
) -> None:
    bounds = _range_bounds(ref)
    for part, root in _table_entries(context, sheet_part):
        if part == exclude_part:
            continue
        if _ranges_overlap(bounds, _range_bounds(root.attrib.get("ref", ""))):
            _invalid(
                "Native table ranges cannot overlap.",
                ref=ref,
                existing_table=root.attrib.get("name", ""),
            )


def _extract_headers(root: Element, ref: str, shared_strings: list[str]) -> list[str]:
    first_column, first_row, last_column, _last_row = _range_bounds(ref)
    cells = {
        cell.attrib.get("r", "").replace("$", "").upper(): cell
        for cell in root.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row/{{{_MAIN_NS}}}c")
    }
    headers: list[str] = []
    for column in range(first_column, last_column + 1):
        cell_ref = f"{_column_name(column)}{first_row}"
        cell = cells.get(cell_ref)
        value = _cell_text(cell, shared_strings) if cell is not None else None
        if not value:
            _invalid("Every table column requires a non-empty text header cell.", cell=cell_ref)
        if value.casefold() in {header.casefold() for header in headers}:
            _invalid("Table column headers must be unique.", cell=cell_ref)
        headers.append(value)
    return headers


def _cell_text(cell: Element, shared_strings: list[str]) -> str | None:
    if cell.find(f"{{{_MAIN_NS}}}f") is not None:
        return None
    cell_type = cell.attrib.get("t", "n")
    value = cell.find(f"{{{_MAIN_NS}}}v")
    if cell_type == "s" and value is not None:
        index = int(value.text or "-1")
        return shared_strings[index] if 0 <= index < len(shared_strings) else None
    if cell_type == "inlineStr":
        text = cell.find(f".//{{{_MAIN_NS}}}t")
        return text.text if text is not None else None
    return value.text if cell_type in {"str"} and value is not None else None


def _build_table_root(
    *,
    table_id: int,
    name: str,
    ref: str,
    style: str,
    headers: list[str],
) -> Element:
    root = Element(
        f"{{{_MAIN_NS}}}table",
        {"id": str(table_id), "name": name, "displayName": name, "ref": ref},
    )
    SubElement(root, f"{{{_MAIN_NS}}}autoFilter", {"ref": ref})
    _replace_table_columns(root, headers)
    SubElement(
        root,
        f"{{{_MAIN_NS}}}tableStyleInfo",
        {
            "name": style,
            "showFirstColumn": "0",
            "showLastColumn": "0",
            "showRowStripes": "1",
            "showColumnStripes": "0",
        },
    )
    return root


def _replace_table_columns(root: Element, headers: list[str]) -> None:
    existing = root.find(f"{{{_MAIN_NS}}}tableColumns")
    new = Element(f"{{{_MAIN_NS}}}tableColumns", {"count": str(len(headers))})
    for index, name in enumerate(headers, start=1):
        SubElement(new, f"{{{_MAIN_NS}}}tableColumn", {"id": str(index), "name": name})
    if existing is None:
        style = root.find(f"{{{_MAIN_NS}}}tableStyleInfo")
        root.insert(list(root).index(style) if style is not None else len(root), new)
    else:
        index = list(root).index(existing)
        root.remove(existing)
        root.insert(index, new)


def _table_columns(root: Element) -> list[str]:
    return [
        item.attrib.get("name", "")
        for item in root.findall(f".//{{{_MAIN_NS}}}tableColumn")
    ]


def _add_table_relationship(context: Any, sheet_part: str, table_part: str) -> str:
    rels_part = _worksheet_rels_part(sheet_part)
    if rels_part in context.package.parts or rels_part in context.added:
        root = context.root(rels_part)
    else:
        root = Element(f"{{{_REL_NS}}}Relationships")
        context.add_root(rels_part, root)
    used = {item.attrib.get("Id", "") for item in root.findall(f"{{{_REL_NS}}}Relationship")}
    index = 1
    while f"rId{index}" in used:
        index += 1
    relationship_id = f"rId{index}"
    relative = posixpath.relpath(table_part, posixpath.dirname(sheet_part))
    SubElement(
        root,
        f"{{{_REL_NS}}}Relationship",
        {"Id": relationship_id, "Type": REL_TABLE, "Target": relative},
    )
    if rels_part not in context.added:
        context.mark_dirty(rels_part)
    return relationship_id


def _add_table_part_reference(worksheet: Element, relationship_id: str) -> None:
    container = worksheet.find(f"{{{_MAIN_NS}}}tableParts")
    if container is None:
        container = Element(f"{{{_MAIN_NS}}}tableParts")
        ext = worksheet.find(f"{{{_MAIN_NS}}}extLst")
        if ext is None:
            worksheet.append(container)
        else:
            worksheet.insert(list(worksheet).index(ext), container)
    SubElement(
        container,
        f"{{{_MAIN_NS}}}tablePart",
        {f"{{{NS['r']}}}id": relationship_id},
    )
    container.attrib["count"] = str(len(container))


def _add_content_type(context: Any, table_part: str) -> None:
    root = context.root(CONTENT_TYPES)
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": f"/{table_part}", "ContentType": _TABLE_CONTENT_TYPE},
    )
    context.mark_dirty(CONTENT_TYPES)


def _remove_content_type(context: Any, table_part: str) -> None:
    root = context.root(CONTENT_TYPES)
    match = next(
        (
            item
            for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
            if item.attrib.get("PartName", "").lstrip("/") == table_part
        ),
        None,
    )
    if match is None:
        _invalid("Native table content type is missing.", part=table_part)
    root.remove(match)
    context.mark_dirty(CONTENT_TYPES)


def _next_table_part(context: Any) -> str:
    used = {*context.package.parts, *context.added}
    index = 1
    while f"xl/tables/table{index}.xml" in used:
        index += 1
    return f"xl/tables/table{index}.xml"


def _next_table_id(context: Any) -> int:
    ids = [
        int(root.attrib.get("id", "0"))
        for sheet_part in context.sheet_parts.values()
        for _part, root in _table_entries(context, sheet_part)
    ]
    return max(ids, default=0) + 1


def _assert_no_table_references(context: Any, name: str, table_part: str) -> None:
    for part in _reference_parts(context):
        if part == table_part:
            continue
        root = context.root(part)
        for element in root.iter():
            if (
                _local_name(element.tag) in _FORMULA_TAGS
                and _contains_table_token(element.text or "", name)
            ):
                _enhancement(
                    "Table delete would invalidate a structured reference.",
                    capability="xlsx.table-delete-reference-migration",
                    table=name,
                    part=part,
                )


def _assert_no_removed_column_references(
    context: Any,
    name: str,
    removed_headers: list[str],
) -> None:
    for part in _reference_parts(context):
        root = context.root(part)
        for element in root.iter():
            text = element.text or ""
            if _local_name(element.tag) not in _FORMULA_TAGS or not _contains_table_token(text, name):
                continue
            if any(f"[{header}]".casefold() in text.casefold() for header in removed_headers):
                _enhancement(
                    "Table resize would remove a referenced structured column.",
                    capability="xlsx.table-resize-reference-migration",
                    table=name,
                    columns=removed_headers,
                )


def _reference_parts(context: Any) -> list[str]:
    prefixes = ("xl/worksheets/", "xl/charts/", "xl/tables/")
    parts = {
        part
        for part in {*context.package.parts, *context.added}
        if part.endswith(".xml") and part.startswith(prefixes) and part not in context.removed
    }
    parts.add("xl/workbook.xml")
    return sorted(parts)


def _rename_table_token(value: str, old_name: str, new_name: str) -> str:
    pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(old_name)}(?=\[)", re.IGNORECASE)
    fragments = value.split('"')
    for index in range(0, len(fragments), 2):
        fragments[index] = pattern.sub(new_name, fragments[index])
    return '"'.join(fragments)


def _contains_table_token(value: str, name: str) -> bool:
    return re.search(
        rf"(?<![A-Za-z0-9_.]){re.escape(name)}(?=\[)",
        value,
        re.IGNORECASE,
    ) is not None


def _worksheet_rels_part(sheet_part: str) -> str:
    directory, filename = sheet_part.rsplit("/", 1)
    return f"{directory}/_rels/{filename}.rels"


def _resolve_target(source_part: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target)).lstrip("/")


def _range_bounds(ref: str) -> tuple[int, int, int, int]:
    first, separator, last = ref.partition(":")
    first_col, first_row = _cell_ref(first)
    last_col, last_row = _cell_ref(last if separator else first)
    return first_col, first_row, last_col, last_row


def _cell_ref(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    if match is None:
        _invalid("Table cell reference is invalid.", ref=ref)
    return _column_number(match.group(1)), int(match.group(2))


def _ranges_overlap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _normalize_range(ref: str) -> str:
    return ":".join(item.replace("$", "").upper() for item in ref.split(":"))


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


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
