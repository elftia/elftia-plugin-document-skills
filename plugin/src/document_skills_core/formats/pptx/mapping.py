"""Shape, text-frame, run, table, and connector mapping for PresentationML."""

from typing import Any

from .constants import NS, local_name
from .equation_omml import is_equation_element, project_equation
from .object_xml import object_hash

_P = NS["p"]
_A = NS["a"]
_R = NS["r"]

def P(tag: str) -> str:
    """Clark notation for PresentationML namespace."""
    return f"{{{_P}}}{tag}"

def A(tag: str) -> str:
    """Clark notation for DrawingML namespace."""
    return f"{{{_A}}}{tag}"

def R(tag: str) -> str:
    """Clark notation for Relationships namespace."""
    return f"{{{_R}}}{tag}"


def map_slides(package: Any) -> list[dict[str, Any]]:
    """Map all slides in presentation order from the package."""
    presentation = package.xml("ppt/presentation.xml")
    sld_id_lst = presentation.find(P("sldIdLst"))
    if sld_id_lst is None:
        return []
    pres_rels = {
        r.relationship_id: r
        for r in package.relationships
        if r.source_part == "ppt/presentation.xml"
    }
    slide_size = _extract_slide_size(presentation)
    slides: list[dict[str, Any]] = []
    for idx, sld_id_elem in enumerate(sld_id_lst.findall(P("sldId"))):
        rid = sld_id_elem.attrib.get(R("id"), "")
        rel = pres_rels.get(rid)
        slide_part = rel.resolved_target if rel else None
        slide_data: dict[str, Any] = {
            "order": idx,
            "number": idx + 1,
            "part": slide_part,
            "relationship_id": rid,
            "shapes": [],
            "layout": None,
            "master": None,
            "notes": None,
        }
        if slide_part and slide_part in package.parts:
            _fill_slide_data(package, slide_part, slide_data)
        slides.append(slide_data)
    if slide_size:
        for slide_data in slides:
            slide_data["slide_size"] = slide_size
    return slides


def _extract_slide_size(presentation: Any) -> dict[str, str] | None:
    size = presentation.find(P("sldSz"))
    if size is None:
        return None
    cx = size.attrib.get("cx", "")
    cy = size.attrib.get("cy", "")
    ratio = float(cy) / float(cx) if cx and cx != "0" else 0.0
    orientation = "landscape" if ratio < 1.0 else "portrait"
    return {"cx": cx, "cy": cy, "type": size.attrib.get("type", "custom"), "orientation": orientation}


def _fill_slide_data(
    package: Any,
    slide_part: str,
    slide_data: dict[str, Any],
) -> None:
    root = package.xml(slide_part)
    cSld = root.find(P("cSld"))
    if cSld is None:
        return
    sp_tree = cSld.find(P("spTree"))
    if sp_tree is None:
        return
    slide_data["shapes"] = _map_shapes(sp_tree)
    slide_data["layout"] = _resolve_layout_ref(package, slide_part)
    slide_data["master"] = _resolve_master_ref(package, slide_part)
    slide_data["notes"] = _resolve_notes(package, slide_part)


def _map_shapes(sp_tree: Any) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    for child in sp_tree:
        tag = local_name(child.tag)
        if is_equation_element(child):
            shapes.append(_map_equation(child))
        elif tag == "sp":
            shapes.append(_map_shape(child, "shape"))
        elif tag == "pic":
            shapes.append(_map_shape(child, "picture"))
        elif tag == "graphicFrame":
            shapes.append(_map_graphic_frame(child))
        elif tag == "cxnSp":
            shapes.append(_map_connector(child))
        elif tag == "grpSp":
            shapes.extend(_map_group(child))
    return shapes


def _map_equation(element: Any) -> dict[str, Any]:
    nv_pr = next(iter(element.iter(P("cNvPr"))), None)
    shape_id = "" if nv_pr is None else nv_pr.get("id", "")
    name = "" if nv_pr is None else nv_pr.get("name", "")
    return {
        "type": "equation",
        "id": shape_id,
        "name": name,
        "precondition_sha256": object_hash(element),
        "selector": {"id": shape_id, "name": name, "type": "equation"},
        "equation": project_equation(element, strict=False),
    }


def _map_shape(elem: Any, shape_type: str) -> dict[str, Any]:
    nv_pr = _get_nv_pr(elem)
    shape_id = nv_pr.get("id", "")
    name = nv_pr.get("name", "")
    text_frames = _map_text_frames(elem)
    return {
        "type": shape_type,
        "id": shape_id,
        "name": name,
        "precondition_sha256": object_hash(elem),
        "selector": {
            "id": shape_id,
            "name": name,
            "type": "image" if shape_type == "picture" else "shape",
        },
        "text_frames": text_frames,
    }


def _map_graphic_frame(elem: Any) -> dict[str, Any]:
    nv_pr = _get_nv_pr(elem)
    shape_id = nv_pr.get("id", "")
    name = nv_pr.get("name", "")
    table_info: dict[str, Any] | None = None
    chart_info: dict[str, Any] | None = None
    graphic_data = elem.find(f"{A('graphic')}/{A('graphicData')}")
    if graphic_data is not None:
        if graphic_data.find(A("tbl")) is not None:
            table_info = _map_table(graphic_data.find(A("tbl")))
        for child in graphic_data:
            if local_name(child.tag) == "chart":
                rid = child.attrib.get(R("id"), "")
                chart_info = {"relationship_id": rid}
    return {
        "type": "graphicFrame",
        "id": shape_id,
        "name": name,
        "precondition_sha256": object_hash(elem),
        "selector": {
            "id": shape_id,
            "name": name,
            "type": "table" if table_info is not None else "chart" if chart_info is not None else "shape",
        },
        "table": table_info,
        "chart_ref": chart_info,
    }


def _map_connector(elem: Any) -> dict[str, Any]:
    nv_pr = _get_nv_pr(elem)
    shape_id = nv_pr.get("id", "")
    name = nv_pr.get("name", "")
    return {
        "type": "connector",
        "id": shape_id,
        "name": name,
        "precondition_sha256": object_hash(elem),
        "selector": {"id": shape_id, "name": name, "type": "shape"},
        "geometry": _map_connector_geometry(elem),
    }


def _map_connector_geometry(elem: Any) -> dict[str, Any]:
    """Extract connector geometry (preset shape, offset, extent) for reorder equality."""
    sp_pr = elem.find(P("spPr"))
    if sp_pr is None:
        sp_pr = elem.find(A("spPr"))
    if sp_pr is None:
        return {}
    result: dict[str, Any] = {}
    xfrm = sp_pr.find(A("xfrm"))
    if xfrm is not None:
        off = xfrm.find(A("off"))
        ext = xfrm.find(A("ext"))
        if off is not None:
            result["offset"] = {"x": off.attrib.get("x", ""), "y": off.attrib.get("y", "")}
        if ext is not None:
            result["extent"] = {"cx": ext.attrib.get("cx", ""), "cy": ext.attrib.get("cy", "")}
    prst_geom = sp_pr.find(A("prstGeom"))
    if prst_geom is not None:
        result["preset"] = prst_geom.attrib.get("prst", "")
    return result


def _map_group(elem: Any) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    for child in elem:
        tag = local_name(child.tag)
        if tag in ("sp", "pic", "graphicFrame", "cxnSp", "grpSp"):
            if tag == "sp":
                shapes.append(_map_shape(child, "shape"))
            elif tag == "pic":
                shapes.append(_map_shape(child, "picture"))
            elif tag == "graphicFrame":
                shapes.append(_map_graphic_frame(child))
            elif tag == "cxnSp":
                shapes.append(_map_connector(child))
            elif tag == "grpSp":
                shapes.extend(_map_group(child))
    return shapes


def _map_text_frames(parent: Any) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    seen_xml: set[int] = set()
    for txBody in parent.iter(P("txBody")):
        if id(txBody) not in seen_xml:
            frames.append(_map_tx_body(txBody))
            seen_xml.add(id(txBody))
    for txBody in parent.iter(A("txBody")):
        if id(txBody) not in seen_xml:
            frames.append(_map_tx_body(txBody))
            seen_xml.add(id(txBody))
    return frames


def _map_tx_body(tx_body: Any) -> dict[str, Any]:
    paragraphs: list[dict[str, Any]] = []
    for p_elem in tx_body.findall(A("p")):
        paragraphs.append(_map_paragraph(p_elem))
    return {"paragraphs": paragraphs}


def _map_paragraph(p_elem: Any) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for r_elem in p_elem.findall(A("r")):
        runs.append(_map_run(r_elem))
    return {"runs": runs}


def _map_run(r_elem: Any) -> dict[str, Any]:
    r_pr = r_elem.find(A("rPr"))
    style: dict[str, Any] = {}
    if r_pr is not None:
        style = {
            "lang": r_pr.attrib.get("lang", ""),
            "sz": r_pr.attrib.get("sz", ""),
            "b": r_pr.attrib.get("b", ""),
            "i": r_pr.attrib.get("i", ""),
            "u": r_pr.attrib.get("u", ""),
        }
        solid_fill = r_pr.find(A("solidFill"))
        if solid_fill is not None:
            srgb = solid_fill.find(A("srgbClr"))
            if srgb is not None:
                style["color"] = srgb.attrib.get("val", "")
        latin = r_pr.find(A("latin"))
        if latin is not None:
            style["font"] = latin.attrib.get("typeface", "")
    t_elem = r_elem.find(A("t"))
    text = t_elem.text if t_elem is not None else ""
    return {"text": text or "", "style": style}


def _map_table(tbl_elem: Any) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for tr in tbl_elem.findall(A("tr")):
        cells: list[dict[str, Any]] = []
        for tc in tr.findall(A("tc")):
            text_parts: list[str] = []
            for t_elem in tc.iter(A("t")):
                if t_elem.text:
                    text_parts.append(t_elem.text)
            cells.append({
                "text": "".join(text_parts),
                "row_span": tc.attrib.get("rowSpan", "1"),
                "grid_span": tc.attrib.get("gridSpan", "1"),
                "h_merge": tc.attrib.get("hMerge") is not None,
                "v_merge": tc.attrib.get("vMerge") is not None,
            })
        rows.append({"cells": cells})
    return {"rows": rows}


def _get_nv_pr(elem: Any) -> dict[str, str]:
    tag = local_name(elem.tag)
    nv_tag = {
        "cxnSp": "nvCxnSpPr",
        "graphicFrame": "nvGraphicFramePr",
        "grpSp": "nvGrpSpPr",
        "pic": "nvPicPr",
        "sp": "nvSpPr",
    }.get(tag, f"nv{tag.capitalize()}Pr")
    nv_pr_elem = elem.find(P(nv_tag))
    if nv_pr_elem is None:
        for child in elem:
            if local_name(child.tag) == nv_tag:
                nv_pr_elem = child
                break
    if nv_pr_elem is None:
        return {}
    c_nv_pr = nv_pr_elem.find(P("cNvPr"))
    if c_nv_pr is None:
        for child in nv_pr_elem:
            if local_name(child.tag) == "cNvPr":
                c_nv_pr = child
                break
    if c_nv_pr is None:
        return {}
    return {"id": c_nv_pr.attrib.get("id", ""), "name": c_nv_pr.attrib.get("name", "")}


def _resolve_layout_ref(
    package: Any,
    slide_part: str,
) -> dict[str, Any] | None:
    for rel in package.relationships:
        if rel.source_part == slide_part and "slideLayout" in rel.relationship_type:
            layout_part = rel.resolved_target
            layout_name = ""
            if layout_part and layout_part in package.parts:
                try:
                    layout_root = package.xml(layout_part)
                    cSld = layout_root.find(P("cSld"))
                    if cSld is not None:
                        layout_name = cSld.attrib.get("name", "")
                except Exception:
                    pass
            return {
                "relationship_id": rel.relationship_id,
                "part": layout_part,
                "name": layout_name,
            }
    return None


def _resolve_master_ref(
    package: Any,
    slide_part: str,
) -> dict[str, Any] | None:
    layout = _resolve_layout_ref(package, slide_part)
    if layout is None or layout.get("part") is None:
        return None
    layout_part = layout["part"]
    for rel in package.relationships:
        if rel.source_part == layout_part and "slideMaster" in rel.relationship_type:
            master_part = rel.resolved_target
            master_name = ""
            if master_part and master_part in package.parts:
                try:
                    master_root = package.xml(master_part)
                    cSld = master_root.find(P("cSld"))
                    if cSld is not None:
                        master_name = cSld.attrib.get("name", "")
                except Exception:
                    pass
            return {
                "relationship_id": rel.relationship_id,
                "part": master_part,
                "name": master_name,
            }
    return None


def _resolve_notes(
    package: Any,
    slide_part: str,
) -> dict[str, Any] | None:
    for rel in package.relationships:
        if rel.source_part == slide_part and "notesSlide" in rel.relationship_type:
            notes_part = rel.resolved_target
            text_frames: list[dict[str, Any]] = []
            if notes_part and notes_part in package.parts:
                try:
                    notes_root = package.xml(notes_part)
                    for sp in notes_root.iter(P("sp")):
                        for txBody in sp.iter(P("txBody")):
                            paragraphs: list[dict[str, Any]] = []
                            for p_elem in txBody.findall(A("p")):
                                runs: list[dict[str, Any]] = []
                                for r_elem in p_elem.findall(A("r")):
                                    t_elem = r_elem.find(A("t"))
                                    runs.append({"text": t_elem.text if t_elem is not None and t_elem.text else ""})
                                paragraphs.append({"runs": runs})
                            text_frames.append({"paragraphs": paragraphs})
                except Exception:
                    pass
            return {
                "relationship_id": rel.relationship_id,
                "part": notes_part,
                "text_frames": text_frames,
            }
    return None
