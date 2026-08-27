"""Native SpreadsheetML data-validation construction and mutation."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS

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


def append_data_validation(parent: Element, validation: dict[str, Any]) -> Element:
    """Append one normalized typed data validation to its collection."""

    attributes = {
        "sqref": validation["ref"],
        "type": validation["type"],
        "allowBlank": "1" if validation["allow_blank"] else "0",
        "showInputMessage": "1" if validation["show_input_message"] else "0",
        "showErrorMessage": "1" if validation["show_error_message"] else "0",
        "errorStyle": validation["error_style"],
    }
    for source, target in (
        ("operator", "operator"),
        ("prompt_title", "promptTitle"),
        ("prompt", "prompt"),
        ("error_title", "errorTitle"),
        ("error", "error"),
    ):
        if validation.get(source) is not None:
            attributes[target] = validation[source]
    element = SubElement(
        parent,
        f"{{{_MAIN_NS}}}dataValidation",
        attributes,
    )
    SubElement(element, f"{{{_MAIN_NS}}}formula1").text = validation["formula1"]
    if validation.get("formula2") is not None:
        SubElement(element, f"{{{_MAIN_NS}}}formula2").text = validation["formula2"]
    return element


def apply_data_validation_edit(root: Element, edit: dict[str, Any]) -> None:
    """Apply add/update/delete using an exact selector and overlap guard."""

    edit_type = edit["type"]
    container = root.find(f"{{{_MAIN_NS}}}dataValidations")
    entries = (
        []
        if container is None
        else list(container.findall(f"{{{_MAIN_NS}}}dataValidation"))
    )
    if edit_type == "data_validation_add":
        validation = edit["validation"]
        _assert_nonoverlapping(entries, validation["ref"])
        if container is None:
            container = Element(f"{{{_MAIN_NS}}}dataValidations")
            _insert_ordered(root, container)
        append_data_validation(container, validation)
        container.attrib["count"] = str(len(container))
        return

    selector = _normalize_range(edit["ref"])
    matches = [entry for entry in entries if _normalize_sqref(entry) == selector]
    if len(matches) != 1:
        _invalid(
            "Data-validation selector must match exactly one existing rule.",
            ref=selector,
            matches=len(matches),
        )
    assert container is not None
    match = matches[0]
    if edit_type == "data_validation_delete":
        container.remove(match)
        if len(container):
            container.attrib["count"] = str(len(container))
        else:
            root.remove(container)
        return
    if edit_type != "data_validation_update":
        _invalid("Data-validation edit type is not implemented.", edit_type=edit_type)
    validation = edit["validation"]
    _assert_nonoverlapping(entries, validation["ref"], excluding=match)
    index = list(container).index(match)
    container.remove(match)
    replacement_parent = Element("replacement")
    replacement = append_data_validation(replacement_parent, validation)
    container.insert(index, replacement)
    container.attrib["count"] = str(len(container))


def _assert_nonoverlapping(
    entries: list[Element],
    ref: str,
    *,
    excluding: Element | None = None,
) -> None:
    requested = _range_bounds(ref)
    for entry in entries:
        if entry is excluding:
            continue
        sqref = entry.attrib.get("sqref", "")
        for existing_ref in sqref.split():
            if _ranges_overlap(requested, _range_bounds(existing_ref)):
                _invalid(
                    "Data-validation range overlaps an existing rule.",
                    ref=ref,
                    existing=existing_ref,
                )


def _normalize_sqref(entry: Element) -> str:
    tokens = entry.attrib.get("sqref", "").split()
    return _normalize_range(tokens[0]) if len(tokens) == 1 else ""


def _range_bounds(ref: str) -> tuple[int, int, int, int]:
    first, separator, last = ref.partition(":")
    first_column, first_row = _cell_ref(first)
    last_column, last_row = _cell_ref(last if separator else first)
    if first_column > last_column or first_row > last_row:
        _invalid("Data-validation range must be ascending.", ref=ref)
    return first_column, first_row, last_column, last_row


def _cell_ref(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    if match is None:
        _invalid("Existing data-validation range is not a supported A1 range.", ref=ref)
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


def _insert_ordered(root: Element, element: Element) -> None:
    target_order = _WORKSHEET_ORDER[_local_name(element.tag)]
    for index, child in enumerate(root):
        if _WORKSHEET_ORDER.get(_local_name(child.tag), 30) > target_order:
            root.insert(index, element)
            return
    root.append(element)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
