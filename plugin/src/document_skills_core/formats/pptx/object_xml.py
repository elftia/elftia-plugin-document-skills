"""Native PresentationML object builders and stable-selector XML helpers."""

from hashlib import sha256
from typing import Any
from xml.etree.ElementTree import canonicalize, Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, local_name

_P = NS["p"]
_A = NS["a"]
_C = NS["c"]
_R = NS["r"]


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def A(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def C(tag: str) -> str:
    return f"{{{_C}}}{tag}"


def R(tag: str) -> str:
    return f"{{{_R}}}{tag}"


def slide_shape_tree(root: Element) -> Element:
    common = root.find(P("cSld"))
    tree = None if common is None else common.find(P("spTree"))
    if tree is None:
        _invalid("Slide shape tree is missing.")
    return tree


def select_object(root: Element, selector: dict[str, Any]) -> Element:
    matches = []
    for element in drawable_elements(slide_shape_tree(root)):
        properties = non_visual_properties(element)
        if selector.get("id") is not None and properties.attrib.get("id") != selector["id"]:
            continue
        if selector.get("name") is not None and properties.attrib.get("name") != selector["name"]:
            continue
        if selector.get("type") is not None and object_type(element) != selector["type"]:
            continue
        matches.append(element)
    if len(matches) != 1:
        _invalid(
            "Object selector must match exactly one slide object.",
            matches=len(matches),
            selector=selector,
        )
    return matches[0]


def drawable_elements(tree: Element) -> list[Element]:
    return [
        element
        for element in list(tree)
        if local_name(element.tag) in {"cxnSp", "graphicFrame", "grpSp", "pic", "sp"}
    ]


def object_type(element: Element) -> str:
    kind = local_name(element.tag)
    if kind == "pic":
        return "image"
    if kind == "graphicFrame":
        data = element.find(f"{A('graphic')}/{A('graphicData')}")
        if data is not None and data.find(A("tbl")) is not None:
            return "table"
        if data is not None and data.find(C("chart")) is not None:
            return "chart"
    return "shape"


def non_visual_properties(element: Element) -> Element:
    for child in element.iter(P("cNvPr")):
        return child
    _invalid("Slide object lacks non-visual properties.")


def object_hash(element: Element) -> str:
    serialized = tostring(element, encoding="unicode")
    canonical = canonicalize(serialized, rewrite_prefixes=True)
    return sha256(canonical.encode("UTF-8")).hexdigest()


def next_shape_id(tree: Element) -> int:
    ids = []
    for element in drawable_elements(tree):
        value = non_visual_properties(element).attrib.get("id", "")
        if value.isdigit():
            ids.append(int(value))
    return max(ids, default=1) + 1


def place_at_z_order(tree: Element, element: Element, z_order: int) -> None:
    if element in list(tree):
        tree.remove(element)
    prefix = len(list(tree)) - len(drawable_elements(tree))
    index = min(max(z_order, 0), len(drawable_elements(tree)))
    tree.insert(prefix + index, element)


def build_shape(shape_id: int, value: dict[str, Any]) -> Element:
    shape = Element(P("sp"))
    non_visual = SubElement(shape, P("nvSpPr"))
    SubElement(non_visual, P("cNvPr"), {"id": str(shape_id), "name": value["name"]})
    SubElement(non_visual, P("cNvSpPr"))
    SubElement(non_visual, P("nvPr"))
    properties = SubElement(shape, P("spPr"))
    apply_shape_properties(properties, value)
    body = SubElement(shape, P("txBody"))
    SubElement(body, A("bodyPr"))
    SubElement(body, A("lstStyle"))
    _append_text_paragraph(body, value.get("text", ""))
    return shape


def apply_shape_update(element: Element, value: dict[str, Any]) -> None:
    non_visual = non_visual_properties(element)
    if "name" in value:
        non_visual.set("name", value["name"])
    properties = element.find(P("spPr"))
    if properties is None:
        properties = SubElement(element, P("spPr"))
    apply_shape_properties(properties, value, partial=True)
    if "text" in value:
        update_text(element, {"text": value["text"]})


def apply_shape_properties(
    properties: Element,
    value: dict[str, Any],
    *,
    partial: bool = False,
) -> None:
    if "frame" in value:
        _replace_transform(properties, value["frame"], value.get("rotation"))
    elif "rotation" in value:
        transform = properties.find(A("xfrm"))
        if transform is None:
            _invalid("Shape rotation update requires existing geometry.")
        transform.set("rot", str(round(value["rotation"] * 60_000)))
    if "geometry" in value:
        existing = properties.find(A("prstGeom"))
        if existing is not None:
            properties.remove(existing)
        geometry = SubElement(properties, A("prstGeom"), {"prst": value["geometry"]})
        SubElement(geometry, A("avLst"))
    if "fill" in value or (not partial and value.get("fill") is None):
        _replace_fill(properties, value.get("fill"), value.get("opacity", 1.0))
    elif "opacity" in value:
        _update_fill_opacity(properties, value["opacity"])
    if "line" in value:
        _replace_line(properties, value["line"])
    if "shadow" in value:
        _replace_shadow(properties, value["shadow"])


def build_picture(shape_id: int, image: dict[str, Any]) -> Element:
    picture = Element(P("pic"))
    non_visual = SubElement(picture, P("nvPicPr"))
    SubElement(
        non_visual,
        P("cNvPr"),
        {"id": str(shape_id), "name": image.get("name", f"Image{shape_id}"), "descr": image["alt_text"]},
    )
    locks = SubElement(non_visual, P("cNvPicPr"))
    SubElement(locks, A("picLocks"), {"noChangeAspect": "1" if image["fit"] != "stretch" else "0"})
    SubElement(non_visual, P("nvPr"))
    fill = SubElement(picture, P("blipFill"))
    blip = SubElement(fill, A("blip"), {R("embed"): image["relationship_id"]})
    if image["opacity"] < 1.0:
        SubElement(blip, A("alphaModFix"), {"amt": str(round(image["opacity"] * 100_000))})
    _set_source_rect(fill, image["crop"])
    SubElement(SubElement(fill, A("stretch")), A("fillRect"))
    properties = SubElement(picture, P("spPr"))
    _replace_transform(
        properties,
        image["frame"],
        image["rotation"],
        flip_h=image.get("flip_h", False),
        flip_v=image.get("flip_v", False),
    )
    geometry = SubElement(properties, A("prstGeom"), {"prst": "rect"})
    SubElement(geometry, A("avLst"))
    return picture


def update_picture_geometry(element: Element, value: dict[str, Any]) -> None:
    fill = element.find(P("blipFill"))
    properties = element.find(P("spPr"))
    if fill is None or properties is None:
        _invalid("Selected image lacks native picture geometry.")
    if "crop" in value:
        _set_source_rect(fill, value["crop"])
    if "opacity" in value:
        blip = fill.find(A("blip"))
        if blip is None:
            _invalid("Selected image lacks an embedded blip.")
        for child in list(blip):
            if child.tag == A("alphaModFix"):
                blip.remove(child)
        if value["opacity"] < 1.0:
            SubElement(blip, A("alphaModFix"), {"amt": str(round(value["opacity"] * 100_000))})
    if "frame" in value:
        _replace_transform(properties, value["frame"], value.get("rotation"))
    elif "rotation" in value:
        transform = properties.find(A("xfrm"))
        if transform is None:
            _invalid("Selected image lacks a transform.")
        transform.set("rot", str(round(value["rotation"] * 60_000)))


def build_table(shape_id: int, value: dict[str, Any]) -> Element:
    frame = Element(P("graphicFrame"))
    non_visual = SubElement(frame, P("nvGraphicFramePr"))
    SubElement(non_visual, P("cNvPr"), {"id": str(shape_id), "name": value["name"]})
    SubElement(non_visual, P("cNvGraphicFramePr"))
    SubElement(non_visual, P("nvPr"))
    _append_frame_transform(frame, value["frame"])
    graphic = SubElement(frame, A("graphic"))
    data = SubElement(graphic, A("graphicData"), {"uri": "http://schemas.openxmlformats.org/drawingml/2006/table"})
    table = SubElement(data, A("tbl"))
    SubElement(table, A("tblPr"), {"firstRow": "1", "bandRow": "1"})
    rows = value["rows"]
    column_count = len(rows[0])
    widths = value.get("widths") or [value["frame"]["cx"] // column_count] * column_count
    if len(widths) != column_count:
        _invalid("Table width count must match its columns.")
    grid = SubElement(table, A("tblGrid"))
    for width in widths:
        SubElement(grid, A("gridCol"), {"w": str(width)})
    heights = value.get("heights") or [max(1, value["frame"]["cy"] // len(rows))] * len(rows)
    if len(heights) != len(rows):
        _invalid("Table height count must match its rows.")
    cells: list[list[Element]] = []
    for row_index, row in enumerate(rows):
        row_node = SubElement(table, A("tr"), {"h": str(heights[row_index])})
        cell_nodes = []
        for cell in row:
            cell_node = SubElement(row_node, A("tc"))
            body = SubElement(cell_node, A("txBody"))
            SubElement(body, A("bodyPr"))
            SubElement(body, A("lstStyle"))
            _append_text_paragraph(body, cell)
            SubElement(cell_node, A("tcPr"))
            cell_nodes.append(cell_node)
        cells.append(cell_nodes)
    _apply_merges(cells, value.get("merges", []))
    return frame


def build_chart_frame(shape_id: int, value: dict[str, Any], relationship_id: str) -> Element:
    frame = Element(P("graphicFrame"))
    non_visual = SubElement(frame, P("nvGraphicFramePr"))
    SubElement(non_visual, P("cNvPr"), {"id": str(shape_id), "name": value["name"]})
    SubElement(non_visual, P("cNvGraphicFramePr"))
    SubElement(non_visual, P("nvPr"))
    _append_frame_transform(frame, value["frame"])
    graphic = SubElement(frame, A("graphic"))
    data = SubElement(graphic, A("graphicData"), {"uri": "http://schemas.openxmlformats.org/drawingml/2006/chart"})
    SubElement(data, C("chart"), {R("id"): relationship_id})
    return frame


def update_graphic_frame(element: Element, value: dict[str, Any]) -> None:
    non_visual = non_visual_properties(element)
    if "name" in value:
        non_visual.set("name", value["name"])
    if "frame" not in value:
        return
    transform = element.find(P("xfrm"))
    if transform is None:
        transform = Element(P("xfrm"))
        insertion = 1 if element.find(P("nvGraphicFramePr")) is not None else 0
        element.insert(insertion, transform)
    for child in list(transform):
        transform.remove(child)
    SubElement(transform, A("off"), {
        "x": str(value["frame"]["x"]),
        "y": str(value["frame"]["y"]),
    })
    SubElement(transform, A("ext"), {
        "cx": str(value["frame"]["cx"]),
        "cy": str(value["frame"]["cy"]),
    })


def update_text(element: Element, value: dict[str, Any]) -> None:
    body = element.find(P("txBody"))
    if body is None:
        body = element.find(A("txBody"))
    if body is None:
        body = element.find(f".//{A('txBody')}")
    if body is None:
        _invalid("Selected object has no editable text body.")
    for child in list(body):
        if child.tag == A("p"):
            body.remove(child)
    paragraphs = value.get("paragraphs", [value.get("text", "")])
    for paragraph in paragraphs:
        _append_text_paragraph(body, paragraph)


def style_text(element: Element, value: dict[str, Any]) -> None:
    body = element.find(P("txBody"))
    if body is None:
        body = element.find(A("txBody"))
    if body is None:
        body = element.find(f".//{A('txBody')}")
    if body is None:
        _invalid("Selected object has no editable text body.")
    body_properties = body.find(A("bodyPr"))
    if body_properties is not None and "autofit" in value:
        for child in list(body_properties):
            if child.tag in {A("noAutofit"), A("normAutofit"), A("spAutoFit")}:
                body_properties.remove(child)
        SubElement(body_properties, A("spAutoFit" if value["autofit"] else "noAutofit"))
    for paragraph in body.findall(A("p")):
        paragraph_properties = paragraph.find(A("pPr"))
        if paragraph_properties is None:
            paragraph_properties = Element(A("pPr"))
            paragraph.insert(0, paragraph_properties)
        if "alignment" in value:
            paragraph_properties.set("algn", {"center": "ctr", "justify": "just", "left": "l", "right": "r"}[value["alignment"]])
        if "line_spacing" in value:
            spacing = paragraph_properties.find(A("lnSpc"))
            if spacing is None:
                spacing = SubElement(paragraph_properties, A("lnSpc"))
            for child in list(spacing):
                spacing.remove(child)
            SubElement(spacing, A("spcPct"), {"val": str(round(value["line_spacing"] * 100_000))})
        if "bullet" in value or "numbering" in value:
            for child in list(paragraph_properties):
                if child.tag in {A("buChar"), A("buAutoNum"), A("buNone")}:
                    paragraph_properties.remove(child)
            if value.get("bullet") is True:
                SubElement(paragraph_properties, A("buChar"), {"char": "•"})
            elif value.get("numbering") is True:
                SubElement(paragraph_properties, A("buAutoNum"), {"type": "arabicPeriod"})
            else:
                SubElement(paragraph_properties, A("buNone"))
        for run in paragraph.findall(A("r")):
            run_properties = run.find(A("rPr"))
            if run_properties is None:
                run_properties = Element(A("rPr"))
                run.insert(0, run_properties)
            _apply_run_style(run_properties, value)


def _apply_run_style(properties: Element, value: dict[str, Any]) -> None:
    attributes = {
        "bold": "b",
        "italic": "i",
    }
    for key, attribute in attributes.items():
        if key in value:
            properties.set(attribute, "1" if value[key] else "0")
    if "underline" in value:
        properties.set("u", "sng" if value["underline"] else "none")
    if "font_size" in value:
        properties.set("sz", str(round(value["font_size"] * 100)))
    if "font" in value:
        existing = properties.find(A("latin"))
        if existing is None:
            existing = SubElement(properties, A("latin"))
        existing.set("typeface", value["font"])
    if "color" in value:
        _replace_fill(properties, value["color"], 1.0)


def _replace_transform(
    parent: Element,
    frame: dict[str, int],
    rotation: float | None,
    *,
    flip_h: bool | None = None,
    flip_v: bool | None = None,
) -> None:
    current = parent.find(A("xfrm"))
    current_rotation = None if current is None else current.attrib.get("rot")
    current_flip_h = None if current is None else current.attrib.get("flipH")
    current_flip_v = None if current is None else current.attrib.get("flipV")
    if current is not None:
        parent.remove(current)
    attributes = {}
    if rotation is not None:
        attributes["rot"] = str(round(rotation * 60_000))
    elif current_rotation is not None:
        attributes["rot"] = current_rotation
    if flip_h is True or (flip_h is None and current_flip_h == "1"):
        attributes["flipH"] = "1"
    if flip_v is True or (flip_v is None and current_flip_v == "1"):
        attributes["flipV"] = "1"
    transform = Element(A("xfrm"), attributes)
    SubElement(transform, A("off"), {"x": str(frame["x"]), "y": str(frame["y"])})
    SubElement(transform, A("ext"), {"cx": str(frame["cx"]), "cy": str(frame["cy"])})
    parent.insert(0, transform)


def _append_frame_transform(parent: Element, frame: dict[str, int]) -> None:
    transform = SubElement(parent, P("xfrm"))
    SubElement(transform, A("off"), {"x": str(frame["x"]), "y": str(frame["y"])})
    SubElement(transform, A("ext"), {"cx": str(frame["cx"]), "cy": str(frame["cy"])})


def _replace_fill(parent: Element, value: Any, opacity: float) -> None:
    for child in list(parent):
        if child.tag in {A("blipFill"), A("gradFill"), A("grpFill"), A("noFill"), A("pattFill"), A("solidFill")}:
            parent.remove(child)
    if value is None or value == "none":
        SubElement(parent, A("noFill"))
        return
    color = value if type(value) is str else value.get("color", "000000")
    solid = SubElement(parent, A("solidFill"))
    color_node = SubElement(solid, A("srgbClr"), {"val": _rgb(color)})
    if opacity < 1.0:
        SubElement(color_node, A("alpha"), {"val": str(round(opacity * 100_000))})


def _update_fill_opacity(parent: Element, opacity: float) -> None:
    fill = parent.find(A("solidFill"))
    if fill is None or not list(fill):
        _invalid("Shape opacity update requires an existing solid fill.")
    color = list(fill)[0]
    for child in list(color):
        if child.tag == A("alpha"):
            color.remove(child)
    if opacity < 1.0:
        SubElement(color, A("alpha"), {"val": str(round(opacity * 100_000))})


def _replace_line(parent: Element, value: Any) -> None:
    current = parent.find(A("ln"))
    if current is not None:
        parent.remove(current)
    if value == "none":
        line = SubElement(parent, A("ln"))
        SubElement(line, A("noFill"))
        return
    settings = {"color": value} if type(value) is str else value
    line = SubElement(parent, A("ln"), {"w": str(int(settings.get("width", 12_700)))})
    _replace_fill(line, settings.get("color", "000000"), float(settings.get("opacity", 1.0)))
    if settings.get("dash"):
        SubElement(line, A("prstDash"), {"val": str(settings["dash"])})


def _replace_shadow(parent: Element, value: Any) -> None:
    current = parent.find(A("effectLst"))
    if current is not None:
        parent.remove(current)
    if value is None or value == "none":
        return
    settings = value if type(value) is dict else {"color": value}
    effects = SubElement(parent, A("effectLst"))
    shadow = SubElement(effects, A("outerShdw"), {
        "blurRad": str(int(settings.get("blur", 50_800))),
        "dist": str(int(settings.get("distance", 25_400))),
        "dir": str(round(float(settings.get("angle", 45.0)) * 60_000)),
        "rotWithShape": "0",
    })
    color = SubElement(shadow, A("srgbClr"), {"val": _rgb(settings.get("color", "000000"))})
    SubElement(color, A("alpha"), {"val": str(round(float(settings.get("opacity", 0.35)) * 100_000))})


def _set_source_rect(fill: Element, crop: dict[str, float] | None) -> None:
    current = fill.find(A("srcRect"))
    if current is not None:
        fill.remove(current)
    if crop is not None and any(crop.values()):
        attributes = {
            name[0]: str(round(value * 100_000))
            for name, value in crop.items()
        }
        children = list(fill)
        source_rect = Element(A("srcRect"), attributes)
        fill.insert(1 if children else 0, source_rect)


def _apply_merges(cells: list[list[Element]], merges: list[dict[str, int]]) -> None:
    row_count = len(cells)
    column_count = len(cells[0]) if cells else 0
    occupied: set[tuple[int, int]] = set()
    for merge in merges:
        row = merge["row"] - 1
        column = merge["column"] - 1
        row_span = merge["row_span"]
        column_span = merge["column_span"]
        if row + row_span > row_count or column + column_span > column_count:
            _invalid("Table merge exceeds table bounds.")
        region = {
            (r, c)
            for r in range(row, row + row_span)
            for c in range(column, column + column_span)
        }
        if occupied.intersection(region):
            _invalid("Table merge regions overlap.")
        occupied.update(region)
        origin = cells[row][column]
        if row_span > 1:
            origin.set("rowSpan", str(row_span))
        if column_span > 1:
            origin.set("gridSpan", str(column_span))
        for r, c in sorted(region - {(row, column)}):
            if c > column:
                cells[r][c].set("hMerge", "1")
            if r > row:
                cells[r][c].set("vMerge", "1")


def _append_text_paragraph(body: Element, text: str) -> None:
    paragraph = SubElement(body, A("p"))
    run = SubElement(paragraph, A("r"))
    node = SubElement(run, A("t"))
    node.text = text


def _rgb(value: str) -> str:
    normalized = value.lstrip("#").upper()
    if len(normalized) != 6 or any(character not in "0123456789ABCDEF" for character in normalized):
        _invalid("Color must be a six-digit RGB value.", color=value)
    return normalized


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
