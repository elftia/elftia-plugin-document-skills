"""Slide-size, chart, media, and feature projection for PresentationML."""

from typing import Any

from .constants import NS

_P = NS["p"]

def P(t): return f"{{{_P}}}{t}"


def project_slide_size(package: Any) -> dict[str, str] | None:
    presentation = package.xml("ppt/presentation.xml")
    size = presentation.find(P("sldSz"))
    if size is None:
        return None
    cx = size.attrib.get("cx", "")
    cy = size.attrib.get("cy", "")
    ratio = float(cy) / float(cx) if cx and cx != "0" else 0.0
    orientation = "landscape" if ratio < 1.0 else "portrait"
    return {"cx": cx, "cy": cy, "type": size.attrib.get("type", "custom"), "orientation": orientation}


def project_defined_names(package: Any) -> list[dict[str, str]]:
    presentation = package.xml("ppt/presentation.xml")
    result: list[dict[str, str]] = []
    ext_lst = presentation.find(P("extLst"))
    return result


def project_charts(package: Any) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for name in package.chart_parts():
        content_type = package.content_type_for(name) or ""
        result: dict[str, Any] = {
            "part": name,
            "content_type": content_type,
            "chart_type": _detect_chart_type(package, name),
        }
        charts.append(result)
    return charts


def _detect_chart_type(package: Any, chart_part: str) -> str:
    try:
        root = package.xml(chart_part)
    except Exception:
        return "unknown"
    for child in root.iter():
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


def project_media(package: Any) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    for name in package.media_parts():
        media.append({
            "part": name,
            "content_type": package.content_type_for(name) or "",
            "bytes": len(package.parts[name]),
        })
    return media


def project_image_references(package: Any, slide_part: str) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for rel in package.relationships:
        if rel.source_part == slide_part and "image" in rel.relationship_type:
            images.append({
                "relationship_id": rel.relationship_id,
                "target": rel.resolved_target,
                "content_type": package.content_type_for(rel.resolved_target) if rel.resolved_target else "",
            })
    return images


def project_external_links(package: Any) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for rel in package.relationships:
        if rel.target_mode == "External":
            links.append({
                "source_part": rel.source_part,
                "relationship_id": rel.relationship_id,
                "type": rel.relationship_type,
                "target": rel.target,
            })
    return links


def project_custom_xml(package: Any) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for name in package.parts:
        if name.startswith("customXml/"):
            parts.append({
                "part": name,
                "bytes": len(package.parts[name]),
            })
    return parts
