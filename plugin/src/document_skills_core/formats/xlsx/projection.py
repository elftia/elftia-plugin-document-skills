"""Table, defined-name, hyperlink, and chart-reference projection for SpreadsheetML."""

from typing import Any

from .constants import NS
from .relationships import relationship_map

_MAIN_NS = NS["main"]


def project_tables(package: Any) -> list[dict[str, Any]]:
    """Project table definitions from all table parts."""
    tables: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if not name.startswith("xl/tables/") or not name.endswith(".xml"):
            continue
        root = package.xml(name)
        result: dict[str, Any] = {
            "name": root.attrib.get("name", ""),
            "ref": root.attrib.get("ref", ""),
            "part": name,
            "style": root.attrib.get("tableStyleInfo", {}).get("name", "")
                if hasattr(root.attrib, "get") else "",
            "header_row": root.attrib.get("headerRowCount", "1") != "0",
            "totals_row": root.attrib.get("totalsRowCount", "0") != "0",
        }
        # tableStyleInfo child
        style_info = root.find(f"{{{_MAIN_NS}}}tableStyleInfo")
        if style_info is not None:
            result["style"] = style_info.attrib.get("name", "TableStyleMedium2")
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
