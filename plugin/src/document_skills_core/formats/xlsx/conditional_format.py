"""Native SpreadsheetML conditional-format construction and mutation."""

from __future__ import annotations

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


def append_conditional_format(
    worksheet: Element,
    rule: dict[str, Any],
    style_registry: Any,
) -> Element:
    """Append one typed rule and return its cfRule element."""

    container = Element(
        f"{{{_MAIN_NS}}}conditionalFormatting",
        {"sqref": rule["ref"]},
    )
    _insert_ordered(worksheet, container)
    return _append_rule(container, rule, style_registry)


def apply_conditional_format_edit(
    worksheet: Element,
    edit: dict[str, Any],
    style_registry: Any,
) -> None:
    """Apply add/update/delete and keep priorities unique and deterministic."""

    edit_type = edit["type"]
    _assert_valid_priorities(worksheet)
    if edit_type == "conditional_format_add":
        rule = dict(edit["rule"])
        rule["priority"] = _next_priority(worksheet)
        append_conditional_format(worksheet, rule, style_registry)
        return
    container, existing = _find_rule(
        worksheet,
        edit["ref"],
        edit["priority"],
    )
    if edit_type == "conditional_format_delete":
        container.remove(existing)
        if not len(container):
            worksheet.remove(container)
        return
    if edit_type != "conditional_format_update":
        _invalid("Conditional-format edit type is not implemented.", edit_type=edit_type)
    replacement = dict(edit["rule"])
    replacement["priority"] = edit["priority"]
    container.remove(existing)
    if not len(container):
        worksheet.remove(container)
    append_conditional_format(worksheet, replacement, style_registry)


def _append_rule(
    container: Element,
    rule: dict[str, Any],
    style_registry: Any,
) -> Element:
    attributes = {
        "type": rule["type"],
        "priority": str(rule["priority"]),
    }
    if rule.get("stop_if_true"):
        attributes["stopIfTrue"] = "1"
    if rule.get("operator") is not None:
        attributes["operator"] = rule["operator"]
    if rule.get("style"):
        attributes["dxfId"] = str(style_registry.register_dxf(rule["style"]))
    element = SubElement(container, f"{{{_MAIN_NS}}}cfRule", attributes)
    rule_type = rule["type"]
    if rule_type in {"cellIs", "expression"}:
        for formula in rule["formulas"]:
            SubElement(element, f"{{{_MAIN_NS}}}formula").text = formula
    elif rule_type == "colorScale":
        color_scale = SubElement(element, f"{{{_MAIN_NS}}}colorScale")
        for threshold in rule["thresholds"]:
            _append_threshold(color_scale, threshold)
        for color in rule["colors"]:
            SubElement(color_scale, f"{{{_MAIN_NS}}}color", {"rgb": color})
    elif rule_type == "dataBar":
        data_bar = SubElement(
            element,
            f"{{{_MAIN_NS}}}dataBar",
            {"showValue": "1" if rule["show_value"] else "0"},
        )
        for threshold in rule["thresholds"]:
            _append_threshold(data_bar, threshold)
        SubElement(data_bar, f"{{{_MAIN_NS}}}color", {"rgb": rule["color"]})
    elif rule_type == "iconSet":
        icon_set = SubElement(
            element,
            f"{{{_MAIN_NS}}}iconSet",
            {
                "iconSet": rule["icon_set"],
                "showValue": "1" if rule["show_value"] else "0",
                "reverse": "1" if rule["reverse"] else "0",
            },
        )
        for threshold in rule["thresholds"]:
            _append_threshold(icon_set, threshold)
    return element


def _append_threshold(parent: Element, threshold: dict[str, Any]) -> None:
    attributes = {
        "type": threshold["type"],
        "gte": "1" if threshold["gte"] else "0",
    }
    if threshold.get("value") is not None:
        attributes["val"] = threshold["value"]
    SubElement(parent, f"{{{_MAIN_NS}}}cfvo", attributes)


def _find_rule(
    worksheet: Element,
    ref: str,
    priority: int,
) -> tuple[Element, Element]:
    matches: list[tuple[Element, Element]] = []
    for container in worksheet.findall(f"{{{_MAIN_NS}}}conditionalFormatting"):
        if _normalize_range(container.attrib.get("sqref", "")) != _normalize_range(ref):
            continue
        for rule in container.findall(f"{{{_MAIN_NS}}}cfRule"):
            if int(rule.attrib.get("priority", "0")) == priority:
                matches.append((container, rule))
    if len(matches) != 1:
        _invalid(
            "Conditional-format selector must match exactly one existing rule.",
            ref=ref,
            priority=priority,
            matches=len(matches),
        )
    return matches[0]


def _next_priority(worksheet: Element) -> int:
    priorities = [
        int(rule.attrib.get("priority", "0"))
        for rule in worksheet.findall(
            f".//{{{_MAIN_NS}}}conditionalFormatting/{{{_MAIN_NS}}}cfRule"
        )
        if rule.attrib.get("priority", "0").isdigit()
    ]
    return max(priorities, default=0) + 1


def _assert_valid_priorities(worksheet: Element) -> None:
    rules = list(
        worksheet.findall(
            f".//{{{_MAIN_NS}}}conditionalFormatting/{{{_MAIN_NS}}}cfRule"
        )
    )
    priorities = [rule.attrib.get("priority", "") for rule in rules]
    if any(not value.isdigit() or int(value) < 1 for value in priorities):
        _invalid("Existing conditional-format priorities are invalid.")
    if len(set(priorities)) != len(priorities):
        _invalid("Existing conditional-format priorities are ambiguous.")


def _insert_ordered(root: Element, element: Element) -> None:
    target_order = _WORKSHEET_ORDER[_local_name(element.tag)]
    insertion_index = len(root)
    for index, child in enumerate(root):
        child_order = _WORKSHEET_ORDER.get(_local_name(child.tag), 30)
        if child_order > target_order:
            insertion_index = index
            break
        if child_order == target_order:
            insertion_index = index + 1
    root.insert(insertion_index, element)


def _normalize_range(ref: str) -> str:
    return ":".join(item.replace("$", "").upper() for item in ref.split(":"))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
