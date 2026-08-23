"""Worksheet view, print, page-setup, and header/footer OOXML helpers."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import NS
from .relationships import relationship_map

_MAIN_NS = NS["main"]
_PAPER_SIZE_TO_ID = {
    "letter": "1",
    "legal": "5",
    "tabloid": "3",
    "a3": "8",
    "a4": "9",
    "a5": "11",
    "b4": "12",
    "b5": "13",
}
_PAPER_ID_TO_SIZE = {value: key for key, value in _PAPER_SIZE_TO_ID.items()}
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
    "drawing": 30,
    "legacyDrawing": 31,
    "tableParts": 40,
    "extLst": 41,
}


def append_worksheet_metadata(root: Element, sheet: dict[str, Any]) -> None:
    if sheet.get("view") is not None:
        _replace_view(root, sheet["view"])
    if sheet.get("page_setup") is not None:
        _replace_page_setup(root, sheet["page_setup"])
    if sheet.get("header_footer") is not None:
        _replace_header_footer(root, sheet["header_footer"])


def apply_worksheet_metadata_edit(root: Element, edit: dict[str, Any]) -> None:
    if edit["type"] == "sheet_view":
        _replace_view(root, edit["view"])
    elif edit["type"] == "page_setup":
        _replace_page_setup(root, edit["page_setup"])
    elif edit["type"] == "header_footer":
        _replace_header_footer(root, edit["header_footer"])
    else:
        raise ValueError(f"Unsupported worksheet metadata edit: {edit['type']}")


def project_worksheet_metadata(package: Any) -> list[dict[str, Any]]:
    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    sheets = workbook.findall(f".//{{{_MAIN_NS}}}sheet")
    names = [sheet.attrib.get("name", "") for sheet in sheets]
    defined_names = workbook.find(f"{{{_MAIN_NS}}}definedNames")
    result: list[dict[str, Any]] = []
    for sheet_index, sheet in enumerate(sheets):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is None or not relationship.resolved_target:
            continue
        root = package.xml(relationship.resolved_target)
        page_setup = root.find(f"{{{_MAIN_NS}}}pageSetup")
        page_margins = root.find(f"{{{_MAIN_NS}}}pageMargins")
        print_options = root.find(f"{{{_MAIN_NS}}}printOptions")
        sheet_properties = root.find(f"{{{_MAIN_NS}}}sheetPr")
        page_setup_properties = (
            None
            if sheet_properties is None
            else sheet_properties.find(f"{{{_MAIN_NS}}}pageSetUpPr")
        )
        view = root.find(f"{{{_MAIN_NS}}}sheetViews/{{{_MAIN_NS}}}sheetView")
        selection = None if view is None else view.find(f"{{{_MAIN_NS}}}selection")
        header_footer = root.find(f"{{{_MAIN_NS}}}headerFooter")
        print_area, print_titles = _project_print_names(
            defined_names,
            sheet_index,
            names[sheet_index],
        )
        result.append(
            {
                "sheet": names[sheet_index],
                "view": None
                if view is None
                else {
                    "show_grid_lines": _bool_attr(view, "showGridLines", True),
                    "zoom_scale": int(view.attrib.get("zoomScale", "100")),
                    "selected_cell": "A1"
                    if selection is None
                    else selection.attrib.get("activeCell", "A1"),
                },
                "page_setup": None
                if page_setup is None
                else {
                    "orientation": page_setup.attrib.get("orientation", "portrait"),
                    "paper_size": _PAPER_ID_TO_SIZE.get(
                        page_setup.attrib.get("paperSize", "1"),
                        page_setup.attrib.get("paperSize", "1"),
                    ),
                    "margins": _project_margins(page_margins),
                    "fit_to_width": _optional_int(page_setup.attrib.get("fitToWidth")),
                    "fit_to_height": _optional_int(page_setup.attrib.get("fitToHeight")),
                    "scale": _optional_int(page_setup.attrib.get("scale")),
                    "horizontal_centered": _bool_attr(
                        print_options,
                        "horizontalCentered",
                        False,
                    ),
                    "vertical_centered": _bool_attr(
                        print_options,
                        "verticalCentered",
                        False,
                    ),
                    "fit_to_page": _bool_attr(page_setup_properties, "fitToPage", False),
                },
                "header_footer": _project_header_footer(header_footer),
                "print_area": print_area,
                "print_titles": print_titles,
            }
        )
    return result


def _replace_view(root: Element, view: dict[str, Any]) -> None:
    existing = root.find(f"{{{_MAIN_NS}}}sheetViews")
    if existing is not None:
        root.remove(existing)
    container = Element(f"{{{_MAIN_NS}}}sheetViews")
    sheet_view = SubElement(
        container,
        f"{{{_MAIN_NS}}}sheetView",
        {
            "workbookViewId": "0",
            "showGridLines": "1" if view["show_grid_lines"] else "0",
            "zoomScale": str(view["zoom_scale"]),
            "zoomScaleNormal": "100",
        },
    )
    SubElement(
        sheet_view,
        f"{{{_MAIN_NS}}}selection",
        {"activeCell": view["selected_cell"], "sqref": view["selected_cell"]},
    )
    _insert_ordered(root, container)


def _replace_page_setup(root: Element, page_setup: dict[str, Any]) -> None:
    for name in ("printOptions", "pageMargins", "pageSetup"):
        existing = root.find(f"{{{_MAIN_NS}}}{name}")
        if existing is not None:
            root.remove(existing)
    sheet_properties = root.find(f"{{{_MAIN_NS}}}sheetPr")
    fit_to_page = page_setup["fit_to_width"] is not None
    if fit_to_page:
        if sheet_properties is None:
            sheet_properties = Element(f"{{{_MAIN_NS}}}sheetPr")
            _insert_ordered(root, sheet_properties)
        existing_properties = sheet_properties.find(f"{{{_MAIN_NS}}}pageSetUpPr")
        if existing_properties is not None:
            sheet_properties.remove(existing_properties)
        SubElement(
            sheet_properties,
            f"{{{_MAIN_NS}}}pageSetUpPr",
            {"fitToPage": "1", "autoPageBreaks": "0"},
        )
    elif sheet_properties is not None:
        existing_properties = sheet_properties.find(f"{{{_MAIN_NS}}}pageSetUpPr")
        if existing_properties is not None:
            sheet_properties.remove(existing_properties)
        if not len(sheet_properties) and not sheet_properties.attrib:
            root.remove(sheet_properties)
    print_options = Element(
        f"{{{_MAIN_NS}}}printOptions",
        {
            "horizontalCentered": "1" if page_setup["horizontal_centered"] else "0",
            "verticalCentered": "1" if page_setup["vertical_centered"] else "0",
        },
    )
    _insert_ordered(root, print_options)
    margins = Element(
        f"{{{_MAIN_NS}}}pageMargins",
        {key: _number_text(value) for key, value in page_setup["margins"].items()},
    )
    _insert_ordered(root, margins)
    attributes = {
        "orientation": page_setup["orientation"],
        "paperSize": _PAPER_SIZE_TO_ID[page_setup["paper_size"]],
    }
    if fit_to_page:
        attributes["fitToWidth"] = str(page_setup["fit_to_width"])
        attributes["fitToHeight"] = str(page_setup["fit_to_height"])
    else:
        attributes["scale"] = str(page_setup["scale"])
    _insert_ordered(root, Element(f"{{{_MAIN_NS}}}pageSetup", attributes))


def _replace_header_footer(root: Element, header_footer: dict[str, Any]) -> None:
    existing = root.find(f"{{{_MAIN_NS}}}headerFooter")
    if existing is not None:
        root.remove(existing)
    container = Element(
        f"{{{_MAIN_NS}}}headerFooter",
        {
            "differentFirst": "1" if header_footer["different_first"] else "0",
            "differentOddEven": "1" if header_footer["different_odd_even"] else "0",
            "scaleWithDoc": "1" if header_footer["scale_with_doc"] else "0",
            "alignWithMargins": "1" if header_footer["align_with_margins"] else "0",
        },
    )
    for key, tag in (
        ("odd_header", "oddHeader"),
        ("odd_footer", "oddFooter"),
        ("even_header", "evenHeader"),
        ("even_footer", "evenFooter"),
        ("first_header", "firstHeader"),
        ("first_footer", "firstFooter"),
    ):
        SubElement(container, f"{{{_MAIN_NS}}}{tag}").text = header_footer[key]
    _insert_ordered(root, container)


def _project_margins(element: Element | None) -> dict[str, float]:
    defaults = {
        "left": 0.7,
        "right": 0.7,
        "top": 0.75,
        "bottom": 0.75,
        "header": 0.3,
        "footer": 0.3,
    }
    return {
        key: float(default if element is None else element.attrib.get(key, str(default)))
        for key, default in defaults.items()
    }


def _project_header_footer(element: Element | None) -> dict[str, Any] | None:
    if element is None:
        return None
    return {
        key: _child_text(element, tag)
        for key, tag in (
            ("odd_header", "oddHeader"),
            ("odd_footer", "oddFooter"),
            ("even_header", "evenHeader"),
            ("even_footer", "evenFooter"),
            ("first_header", "firstHeader"),
            ("first_footer", "firstFooter"),
        )
    } | {
        key: _bool_attr(element, attribute, default)
        for key, attribute, default in (
            ("different_first", "differentFirst", False),
            ("different_odd_even", "differentOddEven", False),
            ("scale_with_doc", "scaleWithDoc", True),
            ("align_with_margins", "alignWithMargins", True),
        )
    }


def _project_print_names(
    container: Element | None,
    sheet_index: int,
    sheet_name: str,
) -> tuple[str | None, dict[str, str | None] | None]:
    if container is None:
        return None, None
    print_area = None
    print_titles = None
    for item in container.findall(f"{{{_MAIN_NS}}}definedName"):
        if item.attrib.get("localSheetId") != str(sheet_index):
            continue
        text = item.text or ""
        if item.attrib.get("name") == "_xlnm.Print_Area":
            print_area = _local_reference(text, sheet_name)
        elif item.attrib.get("name") == "_xlnm.Print_Titles":
            rows = None
            columns = None
            for fragment in text.split(","):
                local = _local_reference(fragment, sheet_name)
                if local is None:
                    continue
                if any(char.isdigit() for char in local):
                    rows = local.replace("$", "")
                else:
                    columns = local.replace("$", "")
            print_titles = {"rows": rows, "columns": columns}
    return print_area, print_titles


def _local_reference(value: str, sheet_name: str) -> str | None:
    prefix, separator, reference = value.rpartition("!")
    if not separator:
        return None
    normalized_sheet = prefix.strip("'").replace("''", "'")
    return reference.replace("$", "") if normalized_sheet == sheet_name else None


def _bool_attr(element: Element | None, name: str, default: bool) -> bool:
    if element is None or name not in element.attrib:
        return default
    return element.attrib[name] in {"1", "true", "on"}


def _optional_int(value: str | None) -> int | None:
    return None if value is None else int(value)


def _child_text(parent: Element, name: str) -> str:
    child = parent.find(f"{{{_MAIN_NS}}}{name}")
    return "" if child is None else child.text or ""


def _number_text(value: int | float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _insert_ordered(root: Element, element: Element) -> None:
    target_order = _WORKSHEET_ORDER[_local_name(element.tag)]
    insertion_index = len(root)
    for index, child in enumerate(root):
        if _WORKSHEET_ORDER.get(_local_name(child.tag), 39) > target_order:
            insertion_index = index
            break
    root.insert(insertion_index, element)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
