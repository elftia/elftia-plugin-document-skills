"""Styled XLSX workbook construction from bounded typed data."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .annotations import append_hyperlinks, build_comments_root, build_comments_vml
from .chart import DRAWING_NS, append_chart_anchor, build_chart_root
from .constants import (
    NS,
    REL_CHART,
    REL_COMMENTS,
    REL_DRAWING,
    REL_TABLE,
    REL_VML_DRAWING,
)
from .conditional_format import append_conditional_format
from .data_validation import append_data_validation
from .formula_state import derive_create_state, build_formula_cell_state
from .package import write_deterministic_zip
from .sparkline import append_sparklines
from .styles import StyleRegistry, merge_styles
from .workbook_properties import build_app_properties, build_core_properties
from .worksheet_metadata import append_worksheet_metadata

_MAIN_NS = NS["main"]
_R_NS = NS["r"]
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def create_xlsx(destination: Path, workbook: dict[str, Any]) -> dict[str, Any]:
    """Create a styled XLSX workbook from the parsed workbook model.

    Returns a creation record with sheet names, formula cells, and metadata.
    """
    metadata = workbook.get("metadata", {})
    sheets_data = workbook.get("sheets", [])
    defined_names = workbook.get("defined_names", [])
    tables = workbook.get("tables", [])
    charts = workbook.get("charts", [])
    page_setup = workbook.get("page_setup")

    # Build shared strings table
    shared_strings: list[str] = []
    string_index: dict[str, int] = {}

    format_definitions = [
        definition
        for sheet in sheets_data
        for definition in sheet.get("number_formats", [])
    ]
    style_registry = StyleRegistry(format_definitions)
    style_assignments: dict[str, dict[str, int]] = {
        "cells": {},
        "rows": {},
        "columns": {},
    }

    # Build parts
    parts: dict[str, bytes] = {}

    indexed_charts = [dict(chart, chart_id=index + 1) for index, chart in enumerate(charts)]
    drawing_groups: list[dict[str, Any]] = []
    for sheet in sheets_data:
        sheet_charts = [chart for chart in indexed_charts if chart["sheet"] == sheet["name"]]
        if sheet_charts:
            drawing_groups.append(
                {
                    "drawing_id": len(drawing_groups) + 1,
                    "sheet": sheet["name"],
                    "charts": sheet_charts,
                }
            )
    drawings_by_sheet = {item["sheet"]: item for item in drawing_groups}
    comment_groups = [
        {
            "comment_id": index + 1,
            "sheet": sheet["name"],
            "comments": sheet.get("comments", []),
        }
        for index, sheet in enumerate(
            sheet for sheet in sheets_data if sheet.get("comments")
        )
    ]
    comments_by_sheet = {item["sheet"]: item for item in comment_groups}

    # Content types
    parts["[Content_Types].xml"] = _build_content_types(
        sheets_data,
        tables=tables,
        chart_count=len(indexed_charts),
        drawing_count=len(drawing_groups),
        comment_count=len(comment_groups),
    )

    # Root rels
    parts["_rels/.rels"] = _build_root_rels()

    # Workbook rels
    workbook_rels: dict[str, str] = {}
    for idx in range(len(sheets_data)):
        workbook_rels[f"sht{idx}"] = f"worksheets/sheet{idx + 1}.xml"
    parts["xl/_rels/workbook.xml.rels"] = _build_workbook_rels(sheets_data)

    # Workbook
    parts["xl/workbook.xml"] = _build_workbook(sheets_data, defined_names, page_setup)

    # Worksheets
    formula_cells: dict[str, dict[str, Any]] = {}
    indexed_tables = [dict(table, table_id=index + 1) for index, table in enumerate(tables)]
    for idx, sheet in enumerate(sheets_data):
        sheet_part = f"xl/worksheets/sheet{idx + 1}.xml"
        sheet_tables = [table for table in indexed_tables if table["sheet"] == sheet["name"]]
        drawing = drawings_by_sheet.get(sheet["name"])
        comments = comments_by_sheet.get(sheet["name"])
        drawing_relationship_id = (
            f"rId{len(sheet_tables) + 1}" if drawing is not None else None
        )
        relationship_offset = len(sheet_tables) + (1 if drawing is not None else 0)
        legacy_drawing_relationship_id = (
            f"rId{relationship_offset + 2}" if comments is not None else None
        )
        parts[sheet_part] = _build_worksheet(
            sheet, idx, shared_strings, string_index, formula_cells,
            style_registry,
            style_assignments,
            sheet_tables,
            drawing_relationship_id,
            legacy_drawing_relationship_id,
        )
        if sheet_tables or drawing is not None or comments is not None:
            parts[f"xl/worksheets/_rels/sheet{idx + 1}.xml.rels"] = (
                _build_worksheet_rels(
                    sheet_tables,
                    drawing_id=None if drawing is None else drawing["drawing_id"],
                    comments=comments,
                )
            )

    # Shared strings
    parts["xl/sharedStrings.xml"] = _build_shared_strings(shared_strings)

    # Styles
    parts["xl/styles.xml"] = style_registry.build_xml()

    # Tables
    for table in indexed_tables:
        tbl_part = f"xl/tables/table{table['table_id']}.xml"
        parts[tbl_part] = _build_table(table)

    # Cell notes/comments and their legacy VML drawings
    for group in comment_groups:
        comment_id = group["comment_id"]
        parts[f"xl/comments{comment_id}.xml"] = _to_xml_bytes(
            build_comments_root(group["comments"])
        )
        parts[f"xl/drawings/commentsDrawing{comment_id}.vml"] = _to_xml_bytes(
            build_comments_vml(group["comments"])
        )

    # Native charts and their sheet drawings
    for chart in indexed_charts:
        parts[f"xl/charts/chart{chart['chart_id']}.xml"] = _to_xml_bytes(
            build_chart_root(chart, chart["chart_id"])
        )
    for drawing in drawing_groups:
        drawing_id = drawing["drawing_id"]
        drawing_root = Element(f"{{{DRAWING_NS}}}wsDr")
        for index, chart in enumerate(drawing["charts"], start=1):
            append_chart_anchor(
                drawing_root,
                chart,
                relationship_id=f"rId{index}",
                object_id=index,
            )
        parts[f"xl/drawings/drawing{drawing_id}.xml"] = _to_xml_bytes(drawing_root)
        parts[f"xl/drawings/_rels/drawing{drawing_id}.xml.rels"] = (
            _build_drawing_rels(drawing["charts"])
        )

    # DocProps
    parts["docProps/core.xml"] = build_core_properties(metadata)
    parts["docProps/app.xml"] = build_app_properties(sheets_data, metadata)

    write_deterministic_zip(destination, parts)

    # Apply formula state for created formulas
    for ref_key, info in formula_cells.items():
        has_cached = info.get("cached_value") is not None
        state = derive_create_state(has_cached_value=has_cached)
        info["formula_state"] = build_formula_cell_state(
            state=state,
            formula=info["formula"],
            cached_value=info.get("cached_value"),
            precedents_count=info.get("precedents_count", 0),
            dependents_count=0,
        )
        # Replace the placeholder dict with the formula-state record
        formula_cells[ref_key] = info["formula_state"]

    return {
        "sheets": [s["name"] for s in sheets_data],
        "formula_cells": formula_cells,
        "shared_strings_count": len(shared_strings),
        "metadata": metadata,
        "styles": {
            **style_registry.manifest(),
            "assignments": style_assignments,
        },
        "tables": [
            {
                "name": table["name"],
                "sheet": table["sheet"],
                "ref": table["ref"],
                "part": f"xl/tables/table{table['table_id']}.xml",
            }
            for table in indexed_tables
        ],
        "data_validations": [
            {"sheet": sheet["name"], **validation}
            for sheet in sheets_data
            for validation in sheet.get("data_validations", [])
        ],
        "conditional_formats": [
            {"sheet": sheet["name"], **rule}
            for sheet in sheets_data
            for rule in sheet.get("conditional_formats", [])
        ],
        "sparklines": [
            {"sheet": sheet["name"], **sparkline}
            for sheet in sheets_data
            for sparkline in sheet.get("sparklines", [])
        ],
        "charts": [
            {
                "name": chart["name"],
                "sheet": chart["sheet"],
                "type": chart["type"],
                "part": f"xl/charts/chart{chart['chart_id']}.xml",
                "drawing_part": (
                    f"xl/drawings/drawing{drawings_by_sheet[chart['sheet']]['drawing_id']}.xml"
                ),
            }
            for chart in indexed_charts
        ],
        "worksheet_metadata": [
            {
                "sheet": sheet["name"],
                "view": sheet.get("view"),
                "page_setup": sheet.get("page_setup"),
                "header_footer": sheet.get("header_footer"),
                "print_area": sheet.get("print_area"),
                "print_titles": sheet.get("print_titles"),
            }
            for sheet in sheets_data
        ],
        "hyperlinks": [
            {"sheet": sheet["name"], **hyperlink}
            for sheet in sheets_data
            for hyperlink in sheet.get("hyperlinks", [])
        ],
        "comments": [
            {"sheet": sheet["name"], **comment}
            for sheet in sheets_data
            for comment in sheet.get("comments", [])
        ],
    }


# --- Part builders ---

def _build_content_types(
    sheets: list[dict[str, Any]],
    *,
    tables: list[dict[str, Any]],
    chart_count: int,
    drawing_count: int,
    comment_count: int,
) -> bytes:
    root = Element(f"{{{_CONTENT_TYPES_NS}}}Types")
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
        "Extension": "rels",
        "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
        "Extension": "xml",
        "ContentType": "application/xml",
    })
    if comment_count:
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
            "Extension": "vml",
            "ContentType": "application/vnd.openxmlformats-officedocument.vmlDrawing",
        })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/xl/workbook.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    })
    for idx in range(len(sheets)):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/xl/worksheets/sheet{idx + 1}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/xl/styles.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/xl/sharedStrings.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/docProps/core.xml",
        "ContentType": "application/vnd.openxmlformats-package.core-properties+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/docProps/app.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    })
    for index in range(len(tables)):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/xl/tables/table{index + 1}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml",
        })
    for index in range(chart_count):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/xl/charts/chart{index + 1}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        })
    for index in range(drawing_count):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/xl/drawings/drawing{index + 1}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.drawing+xml",
        })
    for index in range(comment_count):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/xl/comments{index + 1}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml",
        })
    return _to_xml_bytes(root)


def _build_root_rels() -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "Target": "xl/workbook.xml",
    })
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rId2",
        "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
        "Target": "docProps/core.xml",
    })
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rId3",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
        "Target": "docProps/app.xml",
    })
    return _to_xml_bytes(root)


def _build_workbook_rels(sheets: list[dict[str, Any]]) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
        "Target": "styles.xml",
    })
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rId2",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings",
        "Target": "sharedStrings.xml",
    })
    for idx in range(len(sheets)):
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": f"sht{idx}",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            "Target": f"worksheets/sheet{idx + 1}.xml",
        })
    return _to_xml_bytes(root)


def _build_workbook(sheets: list[dict[str, Any]], defined_names: list[dict[str, Any]], page_setup: dict[str, Any] | None) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}workbook")
    sheets_elem = SubElement(root, f"{{{_MAIN_NS}}}sheets")
    for idx, sheet in enumerate(sheets):
        SubElement(sheets_elem, f"{{{_MAIN_NS}}}sheet", attrib={
            "name": sheet["name"],
            "sheetId": str(idx + 1),
            f"{{{_R_NS}}}id": f"sht{idx}",
        })
    print_names = []
    for sheet_index, sheet in enumerate(sheets):
        if sheet.get("print_area"):
            print_names.append(
                {
                    "name": "_xlnm.Print_Area",
                    "ref": f"{_quote_sheet(sheet['name'])}!{_absolute_cell_range(sheet['print_area'])}",
                    "local_sheet_id": sheet_index,
                }
            )
        if sheet.get("print_titles"):
            titles = sheet["print_titles"]
            fragments = []
            if titles.get("columns"):
                first, separator, last = titles["columns"].partition(":")
                fragments.append(
                    f"{_quote_sheet(sheet['name'])}!${first}:${last if separator else first}"
                )
            if titles.get("rows"):
                first, separator, last = titles["rows"].partition(":")
                fragments.append(
                    f"{_quote_sheet(sheet['name'])}!${first}:${last if separator else first}"
                )
            print_names.append(
                {
                    "name": "_xlnm.Print_Titles",
                    "ref": ",".join(fragments),
                    "local_sheet_id": sheet_index,
                }
            )
    if defined_names or print_names:
        dn_elem = SubElement(root, f"{{{_MAIN_NS}}}definedNames")
        for dn in defined_names:
            SubElement(dn_elem, f"{{{_MAIN_NS}}}definedName", attrib={
                "name": dn["name"],
            }).text = dn["ref"]
        for dn in print_names:
            SubElement(
                dn_elem,
                f"{{{_MAIN_NS}}}definedName",
                attrib={"name": dn["name"], "localSheetId": str(dn["local_sheet_id"])},
            ).text = dn["ref"]
    calc_pr = SubElement(root, f"{{{_MAIN_NS}}}calcPr", attrib={
        "calcId": "0",
        "fullCalcOnLoad": "1",
    })
    return _to_xml_bytes(root)


def _quote_sheet(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


def _absolute_cell_range(value: str) -> str:
    result = []
    for cell in value.split(":"):
        letters = cell.rstrip("0123456789")
        digits = cell[len(letters):]
        result.append(f"${letters.upper()}${digits}")
    return ":".join(result)


def _build_worksheet(
    sheet: dict[str, Any],
    sheet_idx: int,
    shared_strings: list[str],
    string_index: dict[str, int],
    formula_cells: dict[str, dict[str, Any]],
    style_registry: StyleRegistry,
    style_assignments: dict[str, dict[str, int]],
    tables: list[dict[str, Any]],
    drawing_relationship_id: str | None,
    legacy_drawing_relationship_id: str | None,
) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}worksheet")
    columns = sheet.get("columns", [])
    if columns:
        columns_element = SubElement(root, f"{{{_MAIN_NS}}}cols")
        for column in columns:
            attributes = {
                "min": str(column["min"]),
                "max": str(column["max"]),
            }
            if column.get("width") is not None:
                attributes["width"] = str(column["width"])
                attributes["customWidth"] = "1"
            if column.get("hidden"):
                attributes["hidden"] = "1"
            style_id = style_registry.register(column.get("style"))
            if style_id:
                attributes["style"] = str(style_id)
            SubElement(columns_element, f"{{{_MAIN_NS}}}col", attrib=attributes)
            style_assignments["columns"][f"{sheet['name']}!{column['ref']}"] = style_id
    sheet_data = SubElement(root, f"{{{_MAIN_NS}}}sheetData")
    rows = sheet.get("rows", [])
    row_buckets: dict[int, list[tuple[dict[str, Any], dict[str, Any] | None]]] = {}
    row_properties: dict[int, dict[str, Any]] = {}
    for row_idx, row in enumerate(rows):
        first_ref = next(
            (c.get("ref", "") for c in row.get("cells", []) if c.get("ref")),
            "",
        )
        ref_row = _a1_row(first_ref)
        row_number = ref_row if ref_row > 0 else row_idx + 1
        row_properties.setdefault(row_number, row)
        row_buckets.setdefault(row_number, [])
        for cell in row.get("cells", []):
            cell_row = _a1_row(cell["ref"])
            row_buckets.setdefault(cell_row, []).append((cell, row.get("style")))
    for row_number in sorted(row_buckets):
        row = row_properties.get(row_number, {})
        row_attributes = {"r": str(row_number)}
        row_style_id = style_registry.register(row.get("style"))
        if row_style_id:
            row_attributes["s"] = str(row_style_id)
            row_attributes["customFormat"] = "1"
        if row.get("height") is not None:
            row_attributes["ht"] = str(row["height"])
            row_attributes["customHeight"] = "1"
        if row.get("hidden"):
            row_attributes["hidden"] = "1"
        style_assignments["rows"][f"{sheet['name']}!{row_number}"] = row_style_id
        row_elem = SubElement(sheet_data, f"{{{_MAIN_NS}}}row", attrib=row_attributes)
        for cell, requested_row_style in sorted(
            row_buckets[row_number],
            key=lambda item: _a1_col(item[0]["ref"]),
        ):
            ref = cell["ref"]
            cell_type = cell.get("type", "n")
            formula = cell.get("formula")
            value = cell.get("value")
            cached = cell.get("cached_value")
            cell_attribs: dict[str, str] = {"r": ref}
            column_style = _column_style(columns, _a1_col(ref))
            resolved_style = merge_styles(
                column_style,
                requested_row_style,
                cell.get("style"),
            )
            style_id = style_registry.register(resolved_style)
            if style_id:
                cell_attribs["s"] = str(style_id)
            style_assignments["cells"][f"{sheet['name']}!{ref}"] = style_id
            if cell_type != "n":
                cell_attribs["t"] = cell_type

            cell_elem = SubElement(row_elem, f"{{{_MAIN_NS}}}c", attrib=cell_attribs)
            if formula:
                f_elem = SubElement(cell_elem, f"{{{_MAIN_NS}}}f")
                f_elem.text = formula
                ref_key = f"{sheet['name']}!{ref}"
                formula_cells[ref_key] = {
                    "formula": formula,
                    "cached_value": cached,
                }
                if cached is not None:
                    v_elem = SubElement(cell_elem, f"{{{_MAIN_NS}}}v")
                    v_elem.text = cached
            elif value is not None:
                if cell_type == "s":
                    if value not in string_index:
                        string_index[value] = len(shared_strings)
                        shared_strings.append(value)
                    cell_attribs["t"] = "s"
                    v_elem = SubElement(cell_elem, f"{{{_MAIN_NS}}}v")
                    v_elem.text = str(string_index[value])
                    # Re-set the cell type attribute
                    cell_elem.attrib["t"] = "s"
                else:
                    v_elem = SubElement(cell_elem, f"{{{_MAIN_NS}}}v")
                    v_elem.text = value
    for rule in sheet.get("conditional_formats", []):
        append_conditional_format(root, rule, style_registry)
    data_validations = sheet.get("data_validations", [])
    if data_validations:
        validations_element = SubElement(
            root,
            f"{{{_MAIN_NS}}}dataValidations",
            attrib={"count": str(len(data_validations))},
        )
        for validation in data_validations:
            append_data_validation(validations_element, validation)
    append_hyperlinks(root, sheet.get("hyperlinks", []))
    append_worksheet_metadata(root, sheet)
    if drawing_relationship_id is not None:
        SubElement(
            root,
            f"{{{_MAIN_NS}}}drawing",
            {f"{{{_R_NS}}}id": drawing_relationship_id},
        )
    if legacy_drawing_relationship_id is not None:
        SubElement(
            root,
            f"{{{_MAIN_NS}}}legacyDrawing",
            {f"{{{_R_NS}}}id": legacy_drawing_relationship_id},
        )
    if tables:
        table_parts = SubElement(
            root,
            f"{{{_MAIN_NS}}}tableParts",
            attrib={"count": str(len(tables))},
        )
        for index, _table in enumerate(tables, start=1):
            SubElement(
                table_parts,
                f"{{{_MAIN_NS}}}tablePart",
                attrib={f"{{{_R_NS}}}id": f"rId{index}"},
            )
    append_sparklines(root, sheet.get("sparklines", []))
    return _to_xml_bytes(root)


def _build_shared_strings(strings: list[str]) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}sst", attrib={
        "count": str(len(strings)),
        "uniqueCount": str(len(strings)),
    })
    for text in strings:
        si = SubElement(root, f"{{{_MAIN_NS}}}si")
        t = SubElement(si, f"{{{_MAIN_NS}}}t")
        t.text = text
    return _to_xml_bytes(root)


def _build_table(tbl: dict[str, Any]) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}table", attrib={
        "id": str(tbl["table_id"]),
        "name": tbl["name"],
        "ref": tbl["ref"],
        "displayName": tbl["name"],
    })
    SubElement(root, f"{{{_MAIN_NS}}}autoFilter", attrib={"ref": tbl["ref"]})
    columns = SubElement(
        root,
        f"{{{_MAIN_NS}}}tableColumns",
        attrib={"count": str(len(tbl["columns"]))},
    )
    for index, name in enumerate(tbl["columns"], start=1):
        SubElement(
            columns,
            f"{{{_MAIN_NS}}}tableColumn",
            attrib={"id": str(index), "name": name},
        )
    SubElement(root, f"{{{_MAIN_NS}}}tableStyleInfo", attrib={
        "name": tbl.get("style", "TableStyleMedium2"),
        "showFirstColumn": "0",
        "showLastColumn": "0",
        "showRowStripes": "1",
        "showColumnStripes": "0",
    })
    return _to_xml_bytes(root)


def _build_worksheet_rels(
    tables: list[dict[str, Any]],
    *,
    drawing_id: int | None,
    comments: dict[str, Any] | None,
) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    for index, table in enumerate(tables, start=1):
        SubElement(
            root,
            f"{{{_RELS_NS}}}Relationship",
            attrib={
                "Id": f"rId{index}",
                "Type": REL_TABLE,
                "Target": f"../tables/table{table['table_id']}.xml",
            },
        )
    if drawing_id is not None:
        SubElement(
            root,
            f"{{{_RELS_NS}}}Relationship",
            attrib={
                "Id": f"rId{len(tables) + 1}",
                "Type": REL_DRAWING,
                "Target": f"../drawings/drawing{drawing_id}.xml",
            },
        )
    if comments is not None:
        relationship_offset = len(tables) + (1 if drawing_id is not None else 0)
        comment_id = comments["comment_id"]
        SubElement(
            root,
            f"{{{_RELS_NS}}}Relationship",
            attrib={
                "Id": f"rId{relationship_offset + 1}",
                "Type": REL_COMMENTS,
                "Target": f"../comments{comment_id}.xml",
            },
        )
        SubElement(
            root,
            f"{{{_RELS_NS}}}Relationship",
            attrib={
                "Id": f"rId{relationship_offset + 2}",
                "Type": REL_VML_DRAWING,
                "Target": f"../drawings/commentsDrawing{comment_id}.vml",
            },
        )
    return _to_xml_bytes(root)


def _build_drawing_rels(charts: list[dict[str, Any]]) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    for index, chart in enumerate(charts, start=1):
        SubElement(
            root,
            f"{{{_RELS_NS}}}Relationship",
            {
                "Id": f"rId{index}",
                "Type": REL_CHART,
                "Target": f"../charts/chart{chart['chart_id']}.xml",
            },
        )
    return _to_xml_bytes(root)


def _build_calc_chain(formula_cells: dict[str, dict[str, Any]], sheets: list[dict[str, Any]]) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}calcChain")
    sheet_names = [s["name"] for s in sheets]
    for ref_key in sorted(formula_cells.keys()):
        parts = ref_key.rsplit("!", 1)
        sheet_name = parts[0] if len(parts) > 1 else ""
        cell_ref = parts[-1]
        sheet_idx = sheet_names.index(sheet_name) if sheet_name in sheet_names else 0
        SubElement(root, f"{{{_MAIN_NS}}}c", attrib={
            "r": cell_ref,
            "s": str(sheet_idx),
        })
    return _to_xml_bytes(root)


def _to_xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _a1_row(ref: str) -> int:
    """Extract the numeric row from an A1 reference like 'B5' -> 5."""

    digits = ""
    for char in reversed(ref):
        if char.isdigit():
            digits = char + digits
        else:
            break
    return int(digits) if digits else 0


def _a1_col(ref: str) -> int:
    result = 0
    for char in ref.upper().replace("$", ""):
        if not char.isalpha():
            break
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_style(
    columns: list[dict[str, Any]],
    column_number: int,
) -> dict[str, Any] | None:
    for column in columns:
        if column["min"] <= column_number <= column["max"]:
            return column.get("style")
    return None
