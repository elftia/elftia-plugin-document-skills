"""Bounded worksheet metadata, range, dimension, and defined-name edits."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .structural_refs import has_external_workbook_reference

_MAIN_NS = NS["main"]
_WORKSHEET_ORDER = {
    "sheetPr": 0,
    "dimension": 1,
    "sheetViews": 2,
    "sheetFormatPr": 3,
    "cols": 4,
    "sheetData": 5,
    "sheetCalcPr": 6,
    "sheetProtection": 7,
    "protectedRanges": 8,
    "scenarios": 9,
    "autoFilter": 10,
    "sortState": 11,
    "dataConsolidate": 12,
    "customSheetViews": 13,
    "mergeCells": 14,
    "phoneticPr": 15,
    "conditionalFormatting": 16,
    "dataValidations": 17,
    "hyperlinks": 18,
    "printOptions": 19,
    "pageMargins": 20,
    "pageSetup": 21,
    "headerFooter": 22,
    "rowBreaks": 28,
    "colBreaks": 29,
    "extLst": 31,
}


def apply_worksheet_edit(root: Element, edit: dict[str, Any]) -> None:
    edit_type = edit["type"]
    if edit_type == "row_height":
        _edit_rows(root, edit["ref"], {"ht": _number_text(edit["height"]), "customHeight": "1"})
    elif edit_type == "row_hidden":
        _edit_rows(root, edit["ref"], {"hidden": "1" if edit["hidden"] else None})
    elif edit_type == "column_width":
        _edit_columns(
            root,
            edit["ref"],
            {"width": _number_text(edit["width"]), "customWidth": "1"},
        )
    elif edit_type == "column_hidden":
        _edit_columns(root, edit["ref"], {"hidden": "1" if edit["hidden"] else None})
    elif edit_type == "cells_merge":
        _merge_cells(root, edit["ref"])
    elif edit_type == "cells_unmerge":
        _unmerge_cells(root, edit["ref"])
    elif edit_type == "range_clear":
        _clear_range(root, edit["ref"], edit["clear"])
    elif edit_type == "freeze_panes":
        _set_freeze_panes(root, edit["ref"])
    elif edit_type == "auto_filter":
        _set_auto_filter(root, edit["ref"])
    elif edit_type == "auto_filter_clear":
        _remove_required(root, "autoFilter", edit_type)
    elif edit_type in {"row_page_break", "column_page_break"}:
        _set_page_break(root, edit)
    else:
        _invalid("Worksheet edit type is not implemented.", edit_type=edit_type)


def apply_defined_name_edit(
    workbook_root: Element,
    sheets: list[dict[str, Any]],
    edit: dict[str, Any],
) -> None:
    edit_type = edit["type"]
    if edit_type in {"print_area", "print_area_clear"}:
        normalized = _absolute_range(edit["ref"]) if edit_type == "print_area" else None
        reference = (
            f"{_quote_sheet(edit['sheet'])}!{normalized}"
            if normalized is not None
            else None
        )
        _mutate_defined_name(
            workbook_root,
            sheets,
            action="upsert" if reference is not None else "delete",
            name="_xlnm.Print_Area",
            reference=reference,
            scope="sheet",
            sheet_name=edit["sheet"],
        )
        return
    if edit_type in {"print_titles", "print_titles_clear"}:
        reference = None
        if edit_type == "print_titles":
            fragments = []
            titles = edit["print_titles"]
            if titles.get("columns"):
                fragments.append(
                    f"{_quote_sheet(edit['sheet'])}!{_absolute_index_range(titles['columns'])}"
                )
            if titles.get("rows"):
                fragments.append(
                    f"{_quote_sheet(edit['sheet'])}!{_absolute_index_range(titles['rows'])}"
                )
            reference = ",".join(fragments)
        _mutate_defined_name(
            workbook_root,
            sheets,
            action="upsert" if reference is not None else "delete",
            name="_xlnm.Print_Titles",
            reference=reference,
            scope="sheet",
            sheet_name=edit["sheet"],
        )
        return
    action = edit_type.rsplit("_", 1)[-1]
    reference = edit["ref"] if action != "delete" else None
    if reference and has_external_workbook_reference(reference):
        _enhancement(
            "Defined-name edits do not accept external workbook references.",
            capability="xlsx.external-defined-name-edit",
        )
    _mutate_defined_name(
        workbook_root,
        sheets,
        action=action,
        name=edit["name"],
        reference=reference,
        scope=edit["scope"],
        sheet_name=edit["sheet"],
    )


def _edit_rows(root: Element, ref: str, changes: dict[str, str | None]) -> None:
    first, last = _row_range(ref)
    sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        _invalid("Worksheet is missing sheetData.")
    rows = {
        int(row.attrib["r"]): row
        for row in sheet_data.findall(f"{{{_MAIN_NS}}}row")
        if row.attrib.get("r", "").isdigit()
    }
    for row_number in range(first, last + 1):
        row = rows.get(row_number)
        if row is None:
            row = Element(f"{{{_MAIN_NS}}}row", {"r": str(row_number)})
            _insert_row(sheet_data, row, row_number)
        _apply_attributes(row, changes)


def _edit_columns(root: Element, ref: str, changes: dict[str, str | None]) -> None:
    first, last = _column_range(ref)
    container = root.find(f"{{{_MAIN_NS}}}cols")
    if container is None:
        container = Element(f"{{{_MAIN_NS}}}cols")
        _insert_ordered(root, container)
    definitions = list(container.findall(f"{{{_MAIN_NS}}}col"))
    _assert_nonoverlapping_columns(definitions)
    boundaries = {first, last + 1}
    for column in definitions:
        boundaries.update(
            {
                int(column.attrib.get("min", "1")),
                int(column.attrib.get("max", column.attrib.get("min", "1"))) + 1,
            }
        )
    ordered = sorted(boundaries)
    rebuilt: list[Element] = []
    for start, stop in zip(ordered, ordered[1:]):
        end = stop - 1
        source = next(
            (
                column
                for column in definitions
                if int(column.attrib.get("min", "1")) <= start
                and end <= int(column.attrib.get("max", column.attrib.get("min", "1")))
            ),
            None,
        )
        targeted = first <= start and end <= last
        if source is None and not targeted:
            continue
        column = deepcopy(source) if source is not None else Element(f"{{{_MAIN_NS}}}col")
        column.attrib["min"] = str(start)
        column.attrib["max"] = str(end)
        if targeted:
            _apply_attributes(column, changes)
        rebuilt.append(column)
    for column in definitions:
        container.remove(column)
    container.extend(rebuilt)


def _merge_cells(root: Element, ref: str) -> None:
    first_col, first_row, last_col, last_row = _cell_range(ref)
    if first_col == last_col and first_row == last_row:
        _invalid("cells_merge requires a range containing at least two cells.", ref=ref)
    container = root.find(f"{{{_MAIN_NS}}}mergeCells")
    existing = [] if container is None else list(container.findall(f"{{{_MAIN_NS}}}mergeCell"))
    for merged in existing:
        existing_ref = merged.attrib.get("ref", "")
        if existing_ref.casefold() == ref.casefold():
            _invalid("Requested cells are already merged.", ref=ref)
        if _ranges_overlap(_cell_range(existing_ref), (first_col, first_row, last_col, last_row)):
            _invalid("Requested merge overlaps an existing merged range.", ref=ref, existing=existing_ref)
    _assert_merge_payload_safe(root, first_col, first_row, last_col, last_row)
    if container is None:
        container = Element(f"{{{_MAIN_NS}}}mergeCells")
        _insert_ordered(root, container)
    SubElement(container, f"{{{_MAIN_NS}}}mergeCell", {"ref": _normalize_range(ref)})
    container.attrib["count"] = str(len(container))


def _unmerge_cells(root: Element, ref: str) -> None:
    container = root.find(f"{{{_MAIN_NS}}}mergeCells")
    if container is None:
        _invalid("Requested merged range does not exist.", ref=ref)
    match = next(
        (
            item
            for item in container.findall(f"{{{_MAIN_NS}}}mergeCell")
            if item.attrib.get("ref", "").casefold() == ref.casefold()
        ),
        None,
    )
    if match is None:
        _invalid("Requested merged range does not exist.", ref=ref)
    container.remove(match)
    if len(container):
        container.attrib["count"] = str(len(container))
    else:
        root.remove(container)


def _clear_range(root: Element, ref: str, clear: str) -> None:
    first_col, first_row, last_col, last_row = _cell_range(ref)
    sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        _invalid("Worksheet is missing sheetData.")
    matched = 0
    for row in sheet_data.findall(f"{{{_MAIN_NS}}}row"):
        row_number = int(row.attrib.get("r", "0"))
        if not first_row <= row_number <= last_row:
            continue
        for cell in list(row.findall(f"{{{_MAIN_NS}}}c")):
            column, _ = _cell_ref(cell.attrib.get("r", ""))
            if not first_col <= column <= last_col:
                continue
            matched += 1
            if clear == "all":
                row.remove(cell)
                continue
            if clear == "styles":
                cell.attrib.pop("s", None)
                continue
            cell.attrib.pop("t", None)
            for child in list(cell):
                if _local_name(child.tag) in {"f", "v", "is"}:
                    cell.remove(child)
    if matched == 0:
        _invalid("range_clear did not match any stored cells.", ref=ref)


def _set_freeze_panes(root: Element, ref: str) -> None:
    column, row = _cell_ref(ref)
    sheet_views = root.find(f"{{{_MAIN_NS}}}sheetViews")
    if sheet_views is None:
        sheet_views = Element(f"{{{_MAIN_NS}}}sheetViews")
        _insert_ordered(root, sheet_views)
    sheet_view = sheet_views.find(f"{{{_MAIN_NS}}}sheetView")
    if sheet_view is None:
        sheet_view = SubElement(sheet_views, f"{{{_MAIN_NS}}}sheetView", {"workbookViewId": "0"})
    for pane in list(sheet_view.findall(f"{{{_MAIN_NS}}}pane")):
        sheet_view.remove(pane)
    if column == 1 and row == 1:
        return
    attributes = {"state": "frozen", "topLeftCell": _normalize_cell(ref)}
    if column > 1:
        attributes["xSplit"] = str(column - 1)
    if row > 1:
        attributes["ySplit"] = str(row - 1)
    attributes["activePane"] = (
        "bottomRight" if column > 1 and row > 1 else "topRight" if column > 1 else "bottomLeft"
    )
    sheet_view.insert(0, Element(f"{{{_MAIN_NS}}}pane", attributes))


def _set_auto_filter(root: Element, ref: str) -> None:
    auto_filter = root.find(f"{{{_MAIN_NS}}}autoFilter")
    if auto_filter is None:
        auto_filter = Element(f"{{{_MAIN_NS}}}autoFilter")
        _insert_ordered(root, auto_filter)
    auto_filter.attrib["ref"] = _normalize_range(ref)


def _set_page_break(root: Element, edit: dict[str, Any]) -> None:
    is_row = edit["type"] == "row_page_break"
    tag = "rowBreaks" if is_row else "colBreaks"
    break_id = int(edit["ref"]) if is_row else _column_number(edit["ref"])
    container = root.find(f"{{{_MAIN_NS}}}{tag}")
    existing = None if container is None else next(
        (
            item
            for item in container.findall(f"{{{_MAIN_NS}}}brk")
            if int(item.attrib.get("id", "0")) == break_id
        ),
        None,
    )
    if edit["enabled"]:
        if existing is not None:
            _invalid("Requested manual page break already exists.", ref=edit["ref"])
        if container is None:
            container = Element(f"{{{_MAIN_NS}}}{tag}")
            _insert_ordered(root, container)
        SubElement(
            container,
            f"{{{_MAIN_NS}}}brk",
            {"id": str(break_id), "max": "16383" if is_row else "1048575", "man": "1"},
        )
    else:
        if container is None or existing is None:
            _invalid("Requested manual page break does not exist.", ref=edit["ref"])
        container.remove(existing)
        if not len(container):
            root.remove(container)
            return
    container.attrib["count"] = str(len(container))
    container.attrib["manualBreakCount"] = str(len(container))


def _mutate_defined_name(
    workbook_root: Element,
    sheets: list[dict[str, Any]],
    *,
    action: str,
    name: str,
    reference: str | None,
    scope: str,
    sheet_name: str,
) -> None:
    local_id = None
    if scope == "sheet":
        local_id = next(
            (index for index, sheet in enumerate(sheets) if sheet["name"] == sheet_name),
            None,
        )
        if local_id is None:
            _invalid("Defined-name sheet scope was not found.", sheet=sheet_name)
    container = workbook_root.find(f"{{{_MAIN_NS}}}definedNames")
    candidates = [] if container is None else list(container.findall(f"{{{_MAIN_NS}}}definedName"))
    match = next(
        (
            item
            for item in candidates
            if item.attrib.get("name", "").casefold() == name.casefold()
            and item.attrib.get("localSheetId") == (str(local_id) if local_id is not None else None)
        ),
        None,
    )
    if action == "add" and match is not None:
        _invalid("Defined name already exists in the requested scope.", name=name)
    if action in {"update", "delete"} and match is None:
        _invalid("Defined name does not exist in the requested scope.", name=name)
    if action == "delete":
        assert container is not None and match is not None
        container.remove(match)
        if not len(container):
            workbook_root.remove(container)
        return
    if match is None:
        if container is None:
            container = Element(f"{{{_MAIN_NS}}}definedNames")
            calc_pr = workbook_root.find(f"{{{_MAIN_NS}}}calcPr")
            if calc_pr is None:
                workbook_root.append(container)
            else:
                workbook_root.insert(list(workbook_root).index(calc_pr), container)
        attributes = {"name": name}
        if local_id is not None:
            attributes["localSheetId"] = str(local_id)
        match = SubElement(container, f"{{{_MAIN_NS}}}definedName", attributes)
    match.text = reference


def _assert_merge_payload_safe(
    root: Element,
    first_col: int,
    first_row: int,
    last_col: int,
    last_row: int,
) -> None:
    sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        return
    for cell in sheet_data.findall(f".//{{{_MAIN_NS}}}c"):
        column, row = _cell_ref(cell.attrib.get("r", ""))
        if (column, row) == (first_col, first_row):
            continue
        if first_col <= column <= last_col and first_row <= row <= last_row:
            if any(_local_name(child.tag) in {"f", "v", "is"} for child in cell):
                _enhancement(
                    "Merging cells would discard a non-anchor cell value.",
                    capability="xlsx.lossless-cell-merge",
                    cell=cell.attrib.get("r", ""),
                )


def _remove_required(root: Element, local_name: str, edit_type: str) -> None:
    element = root.find(f"{{{_MAIN_NS}}}{local_name}")
    if element is None:
        _invalid("Clear edit did not match existing worksheet metadata.", edit_type=edit_type)
    root.remove(element)


def _insert_ordered(root: Element, element: Element) -> None:
    target_order = _WORKSHEET_ORDER[_local_name(element.tag)]
    for index, child in enumerate(root):
        if _WORKSHEET_ORDER.get(_local_name(child.tag), 30) > target_order:
            root.insert(index, element)
            return
    root.append(element)


def _insert_row(sheet_data: Element, row: Element, row_number: int) -> None:
    for index, existing in enumerate(sheet_data.findall(f"{{{_MAIN_NS}}}row")):
        if int(existing.attrib.get("r", "0")) > row_number:
            sheet_data.insert(index, row)
            return
    sheet_data.append(row)


def _apply_attributes(element: Element, changes: dict[str, str | None]) -> None:
    for name, value in changes.items():
        if value is None:
            element.attrib.pop(name, None)
        else:
            element.attrib[name] = value


def _assert_nonoverlapping_columns(columns: list[Element]) -> None:
    intervals = sorted(
        (
            int(column.attrib.get("min", "1")),
            int(column.attrib.get("max", column.attrib.get("min", "1"))),
        )
        for column in columns
    )
    if any(current[0] <= previous[1] for previous, current in zip(intervals, intervals[1:])):
        _enhancement(
            "Column dimension edit encountered overlapping existing definitions.",
            capability="xlsx.overlapping-column-dimensions",
        )


def _row_range(ref: str) -> tuple[int, int]:
    first, separator, last = ref.partition(":")
    return int(first), int(last) if separator else int(first)


def _column_range(ref: str) -> tuple[int, int]:
    first, separator, last = ref.partition(":")
    return _column_number(first), _column_number(last) if separator else _column_number(first)


def _cell_range(ref: str) -> tuple[int, int, int, int]:
    first, separator, last = ref.partition(":")
    first_col, first_row = _cell_ref(first)
    last_col, last_row = _cell_ref(last if separator else first)
    return first_col, first_row, last_col, last_row


def _cell_ref(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    if match is None:
        _invalid("Cell reference is invalid.", ref=ref)
    return _column_number(match.group(1)), int(match.group(2))


def _ranges_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _absolute_range(ref: str) -> str:
    return ":".join(_absolute_cell(item) for item in ref.split(":"))


def _absolute_cell(ref: str) -> str:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    assert match is not None
    return f"${match.group(1).upper()}${match.group(2)}"


def _absolute_index_range(ref: str) -> str:
    first, separator, last = ref.partition(":")
    return f"${first.upper()}:${(last if separator else first).upper()}"


def _normalize_cell(ref: str) -> str:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    assert match is not None
    return f"{match.group(1).upper()}{match.group(2)}"


def _normalize_range(ref: str) -> str:
    return ":".join(_normalize_cell(item) for item in ref.split(":"))


def _quote_sheet(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
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
