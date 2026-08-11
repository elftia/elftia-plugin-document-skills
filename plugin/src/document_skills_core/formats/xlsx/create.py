"""Styled XLSX workbook construction from bounded typed data."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS
from .formula_state import derive_create_state, build_formula_cell_state
from .package import write_deterministic_zip

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
    chart_ref = workbook.get("chart_reference")
    page_setup = workbook.get("page_setup")

    # Build shared strings table
    shared_strings: list[str] = []
    string_index: dict[str, int] = {}

    # Build styles
    num_fmts: dict[str, int] = {}
    next_num_fmt_id = 164  # Custom formats start at 164
    styles_map: dict[str, int] = {}  # style_signature -> xf index
    fonts_list: list[dict[str, Any]] = [{"bold": False, "italic": False, "size": "11", "name": "Calibri"}]
    fills_list: list[dict[str, Any]] = [{"pattern_type": "none"}, {"pattern_type": "gray125"}]
    borders_list: list[dict[str, Any]] = [{}]
    cell_xfs: list[dict[str, Any]] = [{"num_fmt_id": 0, "font_id": 0, "fill_id": 0, "border_id": 0}]

    # Build parts
    parts: dict[str, bytes] = {}

    # Content types
    parts["[Content_Types].xml"] = _build_content_types(sheets_data, has_chart=bool(chart_ref))

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
    for idx, sheet in enumerate(sheets_data):
        sheet_part = f"xl/worksheets/sheet{idx + 1}.xml"
        parts[sheet_part] = _build_worksheet(
            sheet, idx, shared_strings, string_index, formula_cells,
            num_fmts, styles_map, cell_xfs, fonts_list, fills_list, borders_list,
            lambda: next_num_fmt_id,
        )

    # Shared strings
    parts["xl/sharedStrings.xml"] = _build_shared_strings(shared_strings)

    # Styles
    parts["xl/styles.xml"] = _build_styles(num_fmts, fonts_list, fills_list, borders_list, cell_xfs)

    # Tables
    for tbl_idx, tbl in enumerate(tables):
        tbl_part = f"xl/tables/table{tbl_idx + 1}.xml"
        parts[tbl_part] = _build_table(tbl)

    # Chart reference (placeholder chart part)
    if chart_ref:
        chart_part = "xl/charts/chart1.xml"
        parts[chart_part] = _build_chart_reference(chart_ref)
        drawing_part = "xl/drawings/drawing1.xml"
        parts[drawing_part] = _build_drawing(chart_part)

    # DocProps
    parts["docProps/core.xml"] = _build_core_props(metadata)
    parts["docProps/app.xml"] = _build_app_props(sheets_data)

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
    }


# --- Part builders ---

def _build_content_types(sheets: list[dict[str, Any]], *, has_chart: bool) -> bytes:
    root = Element(f"{{{_CONTENT_TYPES_NS}}}Types")
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
        "Extension": "rels",
        "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
        "Extension": "xml",
        "ContentType": "application/xml",
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
    if defined_names:
        dn_elem = SubElement(root, f"{{{_MAIN_NS}}}definedNames")
        for dn in defined_names:
            SubElement(dn_elem, f"{{{_MAIN_NS}}}definedName", attrib={
                "name": dn["name"],
            }).text = dn["ref"]
    calc_pr = SubElement(root, f"{{{_MAIN_NS}}}calcPr", attrib={
        "calcId": "0",
        "fullCalcOnLoad": "1",
    })
    return _to_xml_bytes(root)


def _build_worksheet(
    sheet: dict[str, Any],
    sheet_idx: int,
    shared_strings: list[str],
    string_index: dict[str, int],
    formula_cells: dict[str, dict[str, Any]],
    num_fmts: dict[str, int],
    styles_map: dict[str, int],
    cell_xfs: list[dict[str, Any]],
    fonts_list: list[dict[str, Any]],
    fills_list: list[dict[str, Any]],
    borders_list: list[dict[str, Any]],
    next_fmt_id: Any,
) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}worksheet")
    sheet_data = SubElement(root, f"{{{_MAIN_NS}}}sheetData")
    rows = sheet.get("rows", [])
    for row_idx, row in enumerate(rows):
        first_ref = next(
            (c.get("ref", "") for c in row.get("cells", []) if c.get("ref")),
            "",
        )
        ref_row = _a1_row(first_ref)
        row_num = str(ref_row if ref_row > 0 else row_idx + 1)
        row_elem = SubElement(sheet_data, f"{{{_MAIN_NS}}}row", attrib={"r": row_num})
        cells = row.get("cells", [])
        for cell in cells:
            ref = cell.get("ref", "")
            if not ref:
                col_letter = _num_to_col(cell.get("_col_offset", row_idx) + 1)
                ref = f"{col_letter}{row_num}"
            cell_type = cell.get("type", "n")
            formula = cell.get("formula")
            value = cell.get("value")
            cached = cell.get("cached_value")
            cell_attribs: dict[str, str] = {"r": ref}
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


def _build_styles(
    num_fmts: dict[str, int],
    fonts: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    borders: list[dict[str, Any]],
    cell_xfs: list[dict[str, Any]],
) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}styleSheet")
    if num_fmts:
        nfs = SubElement(root, f"{{{_MAIN_NS}}}numFmts", attrib={"count": str(len(num_fmts))})
        for code, fmt_id in sorted(num_fmts.items(), key=lambda x: x[1]):
            SubElement(nfs, f"{{{_MAIN_NS}}}numFmt", attrib={
                "numFmtId": str(fmt_id),
                "formatCode": code,
            })
    fonts_elem = SubElement(root, f"{{{_MAIN_NS}}}fonts", attrib={"count": str(len(fonts))})
    for font in fonts:
        font_elem = SubElement(fonts_elem, f"{{{_MAIN_NS}}}font")
        SubElement(font_elem, f"{{{_MAIN_NS}}}sz", attrib={"val": font.get("size", "11")})
        SubElement(font_elem, f"{{{_MAIN_NS}}}name", attrib={"val": font.get("name", "Calibri")})
        if font.get("bold"):
            SubElement(font_elem, f"{{{_MAIN_NS}}}b")
        if font.get("italic"):
            SubElement(font_elem, f"{{{_MAIN_NS}}}i")
    fills_elem = SubElement(root, f"{{{_MAIN_NS}}}fills", attrib={"count": str(len(fills))})
    for fill in fills:
        fill_elem = SubElement(fills_elem, f"{{{_MAIN_NS}}}fill")
        SubElement(fill_elem, f"{{{_MAIN_NS}}}patternFill", attrib={
            "patternType": fill.get("pattern_type", "none"),
        })
    borders_elem = SubElement(root, f"{{{_MAIN_NS}}}borders", attrib={"count": str(len(borders))})
    for _border in borders:
        border_elem = SubElement(borders_elem, f"{{{_MAIN_NS}}}border")
        for side in ("left", "right", "top", "bottom"):
            SubElement(border_elem, f"{{{_MAIN_NS}}}{side}")
    csxfs_elem = SubElement(root, f"{{{_MAIN_NS}}}cellStyleXfs", attrib={"count": "1"})
    SubElement(csxfs_elem, f"{{{_MAIN_NS}}}xf", attrib={
        "numFmtId": "0",
        "fontId": "0",
        "fillId": "0",
        "borderId": "0",
    })
    cxfs_elem = SubElement(root, f"{{{_MAIN_NS}}}cellXfs", attrib={"count": str(len(cell_xfs))})
    for xf in cell_xfs:
        SubElement(cxfs_elem, f"{{{_MAIN_NS}}}xf", attrib={
            "numFmtId": str(xf.get("num_fmt_id", 0)),
            "fontId": str(xf.get("font_id", 0)),
            "fillId": str(xf.get("fill_id", 0)),
            "borderId": str(xf.get("border_id", 0)),
        })
    cstyles_elem = SubElement(root, f"{{{_MAIN_NS}}}cellStyles", attrib={"count": "1"})
    SubElement(cstyles_elem, f"{{{_MAIN_NS}}}cellStyle", attrib={
        "name": "Normal",
        "xfId": "0",
        "builtinId": "0",
    })
    SubElement(root, f"{{{_MAIN_NS}}}dxfs", attrib={"count": "0"})
    return _to_xml_bytes(root)


def _build_table(tbl: dict[str, Any]) -> bytes:
    root = Element(f"{{{_MAIN_NS}}}table", attrib={
        "name": tbl["name"],
        "ref": tbl["ref"],
        "displayName": tbl["name"],
    })
    style_info = SubElement(root, f"{{{_MAIN_NS}}}tableStyleInfo", attrib={
        "name": tbl.get("style", "TableStyleMedium2"),
        "showRowStripes": "1",
    })
    return _to_xml_bytes(root)


def _build_chart_reference(chart_ref: dict[str, Any]) -> bytes:
    main_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    chart_ns = "http://schemas.openxmlformats.org/drawingml/2006/chart"
    root = Element(f"{{{chart_ns}}}chartSpace")
    chart = SubElement(root, f"{{{chart_ns}}}chart")
    plot_area = SubElement(chart, f"{{{chart_ns}}}plotArea")
    bar_chart = SubElement(plot_area, f"{{{chart_ns}}}barChart")
    SubElement(bar_chart, f"{{{chart_ns}}}barDir", attrib={"val": "col"})
    ser = SubElement(bar_chart, f"{{{chart_ns}}}ser")
    tx = SubElement(ser, f"{{{chart_ns}}}tx")
    v = SubElement(tx, f"{{{chart_ns}}}v")
    v.text = chart_ref.get("title", "")
    return _to_xml_bytes(root)


def _build_drawing(chart_part: str) -> bytes:
    xdr_ns = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
    root = Element(f"{{{xdr_ns}}}wsDr")
    return _to_xml_bytes(root)


def _build_core_props(metadata: dict[str, Any]) -> bytes:
    cp_ns = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    dc_ns = "http://purl.org/dc/elements/1.1/"
    dcterms_ns = "http://purl.org/dc/terms/"
    root = Element(f"{{{cp_ns}}}coreProperties")
    SubElement(root, f"{{{dc_ns}}}title").text = metadata.get("title", "")
    SubElement(root, f"{{{dc_ns}}}creator").text = metadata.get("creator", "Elftia Document Skills")
    SubElement(root, f"{{{dc_ns}}}subject").text = metadata.get("subject", "")
    return _to_xml_bytes(root)


def _build_app_props(sheets: list[dict[str, Any]]) -> bytes:
    app_ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
    vt_ns = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
    root = Element(f"{{{app_ns}}}Properties")
    SubElement(root, f"{{{app_ns}}}Application").text = "Elftia Document Skills"
    SubElement(root, f"{{{app_ns}}}SheetCount").text = str(len(sheets))
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


def _num_to_col(num: int) -> str:
    result = ""
    while num > 0:
        num, rem = divmod(num - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def _a1_row(ref: str) -> int:
    """Extract the numeric row from an A1 reference like 'B5' -> 5."""

    digits = ""
    for char in reversed(ref):
        if char.isdigit():
            digits = char + digits
        else:
            break
    return int(digits) if digits else 0
