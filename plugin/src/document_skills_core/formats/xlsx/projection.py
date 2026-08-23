"""Table, defined-name, hyperlink, and chart-reference projection for SpreadsheetML."""

from typing import Any

from .constants import NS
from .relationships import relationship_map
from .styles import read_styles

_MAIN_NS = NS["main"]


def project_conditional_formats(package: Any) -> list[dict[str, Any]]:
    """Project standard conditional-format rules and resolved dxf styles."""

    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    dxfs = read_styles(package.parts).get("dxfs", [])
    result: list[dict[str, Any]] = []
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is None or not relationship.resolved_target:
            continue
        root = package.xml(relationship.resolved_target)
        for container in root.findall(f"{{{_MAIN_NS}}}conditionalFormatting"):
            for rule in container.findall(f"{{{_MAIN_NS}}}cfRule"):
                dxf_text = rule.attrib.get("dxfId")
                dxf_id = int(dxf_text) if dxf_text is not None and dxf_text.isdigit() else None
                projected = {
                    "sheet": sheet.attrib.get("name", ""),
                    "ref": container.attrib.get("sqref", ""),
                    "type": rule.attrib.get("type", ""),
                    "priority": int(rule.attrib.get("priority", "0")),
                    "operator": rule.attrib.get("operator"),
                    "formulas": [
                        formula.text or ""
                        for formula in rule.findall(f"{{{_MAIN_NS}}}formula")
                    ],
                    "style": dxfs[dxf_id] if dxf_id is not None and dxf_id < len(dxfs) else None,
                    "dxf_id": dxf_id,
                    "dxf_valid": dxf_id is None or 0 <= dxf_id < len(dxfs),
                    "stop_if_true": _xml_bool(rule.attrib.get("stopIfTrue")),
                    "thresholds": [],
                    "colors": [],
                    "color": None,
                    "show_value": True,
                    "icon_set": None,
                    "reverse": False,
                }
                visual = next(
                    (
                        rule.find(f"{{{_MAIN_NS}}}{name}")
                        for name in ("colorScale", "dataBar", "iconSet")
                        if rule.find(f"{{{_MAIN_NS}}}{name}") is not None
                    ),
                    None,
                )
                if visual is not None:
                    projected["thresholds"] = [
                        {
                            "type": threshold.attrib.get("type", ""),
                            "value": threshold.attrib.get("val"),
                            "gte": threshold.attrib.get("gte", "1") not in {"0", "false", "off"},
                        }
                        for threshold in visual.findall(f"{{{_MAIN_NS}}}cfvo")
                    ]
                    colors = [
                        _project_color(color)
                        for color in visual.findall(f"{{{_MAIN_NS}}}color")
                    ]
                    if projected["type"] == "colorScale":
                        projected["colors"] = colors
                    elif projected["type"] == "dataBar":
                        projected["color"] = colors[0] if colors else None
                    projected["show_value"] = visual.attrib.get("showValue", "1") not in {
                        "0",
                        "false",
                        "off",
                    }
                    if projected["type"] == "iconSet":
                        projected["icon_set"] = visual.attrib.get("iconSet", "3TrafficLights1")
                        projected["reverse"] = _xml_bool(visual.attrib.get("reverse"))
                result.append(projected)
    return result


def project_data_validations(package: Any) -> list[dict[str, Any]]:
    """Project standard worksheet data-validation rules with their details."""

    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    result: list[dict[str, Any]] = []
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is None or not relationship.resolved_target:
            continue
        root = package.xml(relationship.resolved_target)
        for validation in root.findall(
            f".//{{{_MAIN_NS}}}dataValidations/{{{_MAIN_NS}}}dataValidation"
        ):
            formula1 = validation.find(f"{{{_MAIN_NS}}}formula1")
            formula2 = validation.find(f"{{{_MAIN_NS}}}formula2")
            result.append(
                {
                    "sheet": sheet.attrib.get("name", ""),
                    "ref": validation.attrib.get("sqref", ""),
                    "type": validation.attrib.get("type", "none"),
                    "operator": validation.attrib.get("operator"),
                    "formula1": None if formula1 is None else formula1.text or "",
                    "formula2": None if formula2 is None else formula2.text or "",
                    "allow_blank": _xml_bool(validation.attrib.get("allowBlank")),
                    "show_input_message": _xml_bool(
                        validation.attrib.get("showInputMessage")
                    ),
                    "show_error_message": _xml_bool(
                        validation.attrib.get("showErrorMessage")
                    ),
                    "prompt_title": validation.attrib.get("promptTitle"),
                    "prompt": validation.attrib.get("prompt"),
                    "error_title": validation.attrib.get("errorTitle"),
                    "error": validation.attrib.get("error"),
                    "error_style": validation.attrib.get("errorStyle", "stop"),
                }
            )
    return result


def project_tables(package: Any) -> list[dict[str, Any]]:
    """Project table definitions from all table parts."""
    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    sheet_names_by_part: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is not None and relationship.resolved_target:
            sheet_names_by_part[relationship.resolved_target] = sheet.attrib.get("name", "")
    table_sheets = {
        relationship.resolved_target: sheet_names_by_part.get(relationship.source_part, "")
        for relationship in package.relationships
        if relationship.relationship_type.rsplit("/", 1)[-1] == "table"
        and relationship.resolved_target
    }
    tables: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if not name.startswith("xl/tables/") or not name.endswith(".xml"):
            continue
        root = package.xml(name)
        result: dict[str, Any] = {
            "name": root.attrib.get("name", ""),
            "ref": root.attrib.get("ref", ""),
            "part": name,
            "sheet": table_sheets.get(name, ""),
            "display_name": root.attrib.get("displayName", ""),
            "style": "",
            "header_row": root.attrib.get("headerRowCount", "1") != "0",
            "totals_row": root.attrib.get("totalsRowCount", "0") != "0",
            "columns": [
                column.attrib.get("name", "")
                for column in root.findall(
                    f".//{{{_MAIN_NS}}}tableColumns/{{{_MAIN_NS}}}tableColumn"
                )
            ],
        }
        # tableStyleInfo child
        style_info = root.find(f"{{{_MAIN_NS}}}tableStyleInfo")
        if style_info is not None:
            result["style"] = style_info.attrib.get("name", "TableStyleMedium2")
            result["style_options"] = {
                "show_first_column": style_info.attrib.get("showFirstColumn", "0") == "1",
                "show_last_column": style_info.attrib.get("showLastColumn", "0") == "1",
                "show_row_stripes": style_info.attrib.get("showRowStripes", "0") == "1",
                "show_column_stripes": style_info.attrib.get("showColumnStripes", "0") == "1",
            }
        auto_filter = root.find(f"{{{_MAIN_NS}}}autoFilter")
        result["auto_filter_ref"] = (
            auto_filter.attrib.get("ref", "") if auto_filter is not None else ""
        )
        tables.append(result)
    return tables


def project_hyperlinks(
    package: Any,
    sheet_part: str,
) -> list[dict[str, Any]]:
    """Project hyperlinks from a worksheet's relationship targets."""
    rels = package.sheet_rels(sheet_part)
    result: list[dict[str, Any]] = []
    root = package.xml(sheet_part)
    main_ns = _MAIN_NS
    for hl in root.iter(f"{{{main_ns}}}hyperlink"):
        ref = hl.attrib.get("ref", "")
        rel_id = hl.attrib.get(f"{{{NS['r']}}}id", "")
        rel = next((r for r in rels if r.relationship_id == rel_id), None)
        result.append({
            "ref": ref,
            "relationship_id": rel_id,
            "target": rel.target if rel else None,
            "external": (rel.target_mode == "External") if rel else False,
        })
    return result


def project_charts(package: Any) -> list[dict[str, Any]]:
    """Project chart references without embedding chart bytes."""
    charts: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if not name.startswith("xl/charts/") or not name.endswith(".xml"):
            continue
        content_type = package.content_type_for(name) or ""
        result: dict[str, Any] = {
            "part": name,
            "content_type": content_type,
            "chart_type": _detect_chart_type(package, name),
        }
        charts.append(result)
    return charts


def _detect_chart_type(package: Any, chart_part: str) -> str:
    """Detect the chart type from the chart XML root."""
    try:
        root = package.xml(chart_part)
    except Exception:
        return "unknown"
    main_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    for child in root:
        tag = child.tag
        if "barChart" in tag:
            return "bar"
        if "lineChart" in tag:
            return "line"
        if "pieChart" in tag:
            return "pie"
        if "scatterChart" in tag:
            return "scatter"
        if "areaChart" in tag:
            return "area"
    return "unknown"


def project_pivot_caches(package: Any) -> list[dict[str, Any]]:
    """Project pivot cache definitions as references."""
    caches: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if "pivotCacheDefinition" in name and name.endswith(".xml"):
            caches.append({"part": name, "content_type": package.content_type_for(name) or ""})
    return caches


def project_external_links(package: Any) -> list[dict[str, Any]]:
    """Project external link references with their targets without fetching.

    Each entry includes the source part and the external target URL (when the
    package records one via the externalLink relationship target).  No
    connection is fetched or refreshed.
    """
    # Build a map of externalLink source part → external target URL.
    external_targets: dict[str, str] = {}
    for rel in package.relationships:
        if (
            rel.source_part.startswith("xl/externalLinks/")
            and rel.target_mode == "External"
        ):
            external_targets[rel.source_part] = rel.target
    links: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if name.startswith("xl/externalLinks/") and name.endswith(".xml"):
            entry: dict[str, Any] = {"part": name, "source_part": name}
            target = external_targets.get(name)
            if target is not None:
                entry["target"] = target
            links.append(entry)
    return links


def project_drawings(package: Any) -> list[dict[str, Any]]:
    """Project drawing part references."""
    drawings: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if name.startswith("xl/drawings/") and name.endswith(".xml"):
            drawings.append({"part": name, "content_type": package.content_type_for(name) or ""})
    return drawings


def _xml_bool(value: str | None) -> bool:
    return value in {"1", "true", "on"}


def _project_color(element: Any) -> Any:
    if "rgb" in element.attrib:
        return element.attrib["rgb"]
    if "theme" in element.attrib:
        result: dict[str, Any] = {"theme": int(element.attrib["theme"])}
        if "tint" in element.attrib:
            result["tint"] = float(element.attrib["tint"])
        return result
    if "indexed" in element.attrib:
        return {"indexed": int(element.attrib["indexed"])}
    if element.attrib.get("auto") in {"1", "true", "on"}:
        return {"auto": True}
    return None
