"""Slide-size, chart, media, and feature projection for PresentationML."""

from typing import Any

from .constants import NS, local_name

_P = NS["p"]
_C = NS["c"]
_A = NS["a"]

def P(t): return f"{{{_P}}}{t}"


def C(t): return f"{{{_C}}}{t}"


def A(t): return f"{{{_A}}}{t}"


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
        try:
            root = package.xml(name)
        except Exception:
            root = None
        result: dict[str, Any] = {
            "part": name,
            "content_type": content_type,
            "chart_type": _detect_chart_type(root),
            "title": _chart_text(root.find(f"{C('chart')}/{C('title')}") if root is not None else None),
            "series": _project_chart_series(root),
            "axes": _project_chart_axes(root),
        }
        charts.append(result)
    return charts


def _detect_chart_type(root: Any) -> str:
    if root is None:
        return "unknown"
    for child in root.iter():
        kind = local_name(child.tag)
        if kind == "barChart":
            direction = child.find(C("barDir"))
            return "bar" if direction is not None and direction.attrib.get("val") == "bar" else "column"
        if kind in {"lineChart", "pieChart", "scatterChart", "areaChart"}:
            return kind.removesuffix("Chart")
    return "unknown"


def _project_chart_series(root: Any) -> list[dict[str, Any]]:
    if root is None:
        return []
    result: list[dict[str, Any]] = []
    for node in root.iter(C("ser")):
        item: dict[str, Any] = {
            "index": _attribute_value(node.find(C("idx"))),
            "name": _chart_text(node.find(C("tx"))),
        }
        categories = _literal_values(node.find(C("cat")), numeric=False)
        values = _literal_values(node.find(C("val")), numeric=True)
        x_values = _literal_values(node.find(C("xVal")), numeric=True)
        y_values = _literal_values(node.find(C("yVal")), numeric=True)
        if categories:
            item["categories"] = categories
        if values:
            item["values"] = values
        if x_values:
            item["x_values"] = x_values
        if y_values:
            item["y_values"] = y_values
        result.append(item)
    return result


def _project_chart_axes(root: Any) -> list[dict[str, Any]]:
    if root is None:
        return []
    result: list[dict[str, Any]] = []
    for node in root.iter():
        kind = local_name(node.tag)
        if kind not in {"catAx", "dateAx", "serAx", "valAx"}:
            continue
        number_format = node.find(C("numFmt"))
        result.append({
            "axis_type": kind,
            "cross_axis_id": _attribute_value(node.find(C("crossAx"))),
            "id": _attribute_value(node.find(C("axId"))),
            "number_format": "" if number_format is None else number_format.attrib.get("formatCode", ""),
            "position": _attribute_value(node.find(C("axPos"))),
            "title": _chart_text(node.find(C("title"))),
        })
    return result


def _literal_values(parent: Any, *, numeric: bool) -> list[Any]:
    if parent is None:
        return []
    cache_names = ("numLit", "numCache") if numeric else ("strLit", "strCache", "multiLvlStrCache")
    cache = next(
        (node for node in parent.iter() if local_name(node.tag) in cache_names),
        None,
    )
    if cache is None:
        return []
    points: list[tuple[int, Any]] = []
    for point in cache.iter(C("pt")):
        value = point.find(C("v"))
        if value is None:
            continue
        text = value.text or ""
        if numeric:
            try:
                projected: Any = float(text)
            except ValueError:
                projected = text
        else:
            projected = text
        try:
            index = int(point.attrib.get("idx", len(points)))
        except ValueError:
            index = len(points)
        points.append((index, projected))
    return [value for _index, value in sorted(points)]


def _chart_text(parent: Any) -> str:
    if parent is None:
        return ""
    values = [node.text or "" for node in parent.iter() if local_name(node.tag) in {"t", "v"}]
    return "".join(values)


def _attribute_value(node: Any) -> str:
    return "" if node is None else node.attrib.get("val", "")


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
