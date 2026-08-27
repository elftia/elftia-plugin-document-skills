"""Conservative support checks for truthful PPTX scene projection."""

from __future__ import annotations

from xml.etree.ElementTree import Element

from .constants import NS, local_name

_P = NS["p"]
_A = NS["a"]


def _p(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def projection_support_issue(element: Element) -> str | None:
    """Return the first semantic field the current projection cannot preserve."""

    tag = local_name(element.tag)
    inheritance_issue = _inheritance_issue(element, tag)
    if inheritance_issue is not None:
        return inheritance_issue
    transform = _transform(element, tag)
    if transform is not None:
        if transform.attrib.get("rot", "0") not in {"", "0"}:
            return "unsupported-rotation"
        if _truthy(transform.attrib.get("flipH")) or _truthy(
            transform.attrib.get("flipV")
        ):
            return "unsupported-flip"
    if tag == "grpSp":
        properties = element.find(_p("grpSpPr"))
        if properties is None or any(local_name(child.tag) != "xfrm" for child in properties):
            return "unsupported-group-style"
        return None
    if tag == "sp":
        issue = _shape_style_issue(
            element.find(_p("spPr")),
            require_fill=True,
        )
        if issue is not None:
            return issue
        if any((node.text or "") for node in element.iter(_a("t"))):
            return _text_issue(element)
        return None
    if tag == "cxnSp":
        properties = element.find(_p("spPr"))
        line = None if properties is None else properties.find(_a("ln"))
        if line is None or line.find(_a("noFill")) is None:
            return "unsupported-visible-connector-style"
        return _shape_style_issue(properties)
    if tag == "pic":
        return _picture_issue(element)
    if tag == "graphicFrame":
        table = element.find(f"{_a('graphic')}/{_a('graphicData')}/{_a('tbl')}")
        return None if table is None else _table_issue(table)
    return None


def _transform(element: Element, tag: str) -> Element | None:
    if tag == "grpSp":
        return element.find(f"{_p('grpSpPr')}/{_a('xfrm')}")
    if tag == "graphicFrame":
        return element.find(_p("xfrm"))
    return element.find(f"{_p('spPr')}/{_a('xfrm')}")


def _inheritance_issue(element: Element, tag: str) -> str | None:
    if element.find(_p("style")) is not None:
        return "unsupported-inherited-shape-style"
    non_visual_names = {
        "cxnSp": "nvCxnSpPr",
        "graphicFrame": "nvGraphicFramePr",
        "grpSp": "nvGrpSpPr",
        "pic": "nvPicPr",
        "sp": "nvSpPr",
    }
    non_visual_name = non_visual_names.get(tag)
    if non_visual_name is None:
        return None
    placeholder = element.find(
        f"{_p(non_visual_name)}/{_p('nvPr')}/{_p('ph')}"
    )
    return (
        "unsupported-placeholder-inheritance"
        if placeholder is not None
        else None
    )


def _shape_style_issue(
    properties: Element | None,
    *,
    require_fill: bool = False,
) -> str | None:
    if properties is None:
        return "missing-shape-properties"
    allowed = {"custGeom", "ln", "noFill", "prstGeom", "solidFill", "xfrm"}
    unexpected = sorted(
        {local_name(child.tag) for child in properties} - allowed
    )
    if unexpected:
        return f"unsupported-shape-{unexpected[0].casefold()}"
    solid = properties.find(_a("solidFill"))
    no_fill = properties.find(_a("noFill"))
    if require_fill and solid is None and no_fill is None:
        return "unsupported-inherited-shape-fill"
    if solid is not None:
        color = solid.find(_a("srgbClr"))
        if color is None or list(color):
            return "unsupported-shape-fill"
    line = properties.find(_a("ln"))
    if line is not None and line.find(_a("noFill")) is None:
        return "unsupported-visible-line-style"
    return None


def _text_issue(element: Element) -> str | None:
    body = element.find(_p("txBody"))
    if body is None:
        return "unsupported-text-body"
    body_properties = body.find(_a("bodyPr"))
    if body_properties is None or list(body_properties):
        return "unsupported-text-body-properties"
    allowed_body = {"bIns", "lIns", "rIns", "tIns", "wrap"}
    if set(body_properties.attrib) != allowed_body:
        return "unsupported-inherited-text-style"
    if body_properties.attrib.get("wrap", "square") != "square":
        return "unsupported-text-wrap"
    if any(body_properties.attrib.get(name, "0") != "0" for name in ("bIns", "lIns", "rIns", "tIns")):
        return "unsupported-text-insets"
    list_style = body.find(_a("lstStyle"))
    if list_style is None or list(list_style) or list_style.attrib:
        return "unsupported-text-list-style"
    paragraphs = body.findall(_a("p"))
    if len(paragraphs) != 1:
        return "unsupported-text-paragraph-structure"
    paragraph = paragraphs[0]
    runs = paragraph.findall(_a("r"))
    if len(runs) != 1:
        return "unsupported-text-run-structure"
    allowed_paragraph_children = {"endParaRPr", "pPr", "r"}
    if any(local_name(child.tag) not in allowed_paragraph_children for child in paragraph):
        return "unsupported-text-run-structure"
    paragraph_properties = paragraph.find(_a("pPr"))
    if paragraph_properties is None or set(paragraph_properties.attrib) != {"algn"}:
        return "unsupported-inherited-text-style"
    if list(paragraph_properties):
        return "unsupported-text-paragraph-style"
    if paragraph_properties.attrib["algn"] != "l":
        return "unsupported-text-alignment"
    return _run_issue(runs[0])


def _run_issue(
    run: Element,
    *,
    allow_default: bool = False,
) -> str | None:
    if any(local_name(child.tag) not in {"rPr", "t"} for child in run):
        return "unsupported-text-run-structure"
    texts = run.findall(_a("t"))
    if len(texts) != 1:
        return "unsupported-text-run-structure"
    properties = run.find(_a("rPr"))
    if properties is None:
        return None if allow_default else "unsupported-inherited-text-style"
    if set(properties.attrib) != {"lang", "sz"}:
        return "unsupported-inherited-text-style"
    if properties.attrib.get("lang", "en-US") != "en-US":
        return "unsupported-text-language"
    observed_children = sorted(local_name(child.tag) for child in properties)
    if observed_children != ["latin", "solidFill"]:
        return "unsupported-inherited-text-style"
    for child in properties:
        name = local_name(child.tag)
        if name == "latin" and child.attrib.get("typeface", "Arial") == "Arial":
            continue
        if name == "solidFill":
            color = child.find(_a("srgbClr"))
            if color is not None and not list(color):
                continue
        return "unsupported-text-run-style"
    return None


def _picture_issue(element: Element) -> str | None:
    non_visual = element.find(f"{_p('nvPicPr')}/{_p('cNvPr')}")
    if non_visual is not None and any(
        non_visual.attrib.get(name) for name in ("descr", "title")
    ):
        return "unsupported-picture-metadata"
    fill = element.find(_p("blipFill"))
    if fill is None or fill.find(_a("srcRect")) is not None:
        return "unsupported-picture-crop"
    blip = fill.find(_a("blip"))
    stretch = fill.find(_a("stretch"))
    if blip is None or list(blip) or stretch is None:
        return "unsupported-picture-effects"
    if stretch.find(_a("fillRect")) is None:
        return "unsupported-picture-fit"
    return _shape_style_issue(element.find(_p("spPr")))


def _table_issue(table: Element) -> str | None:
    properties = table.find(_a("tblPr"))
    if properties is None or list(properties):
        return "unsupported-table-style"
    if properties.attrib.get("firstRow") != "1":
        return "unsupported-table-header"
    if set(properties.attrib) - {"bandRow", "firstRow"}:
        return "unsupported-table-style"
    grid = table.find(_a("tblGrid"))
    widths = [] if grid is None else [column.attrib.get("w") for column in grid]
    if not widths or len(set(widths)) != 1:
        return "unsupported-table-column-widths"
    rows = table.findall(_a("tr"))
    heights = [row.attrib.get("h") for row in rows]
    if not rows or len(set(heights)) != 1:
        return "unsupported-table-row-heights"
    for row in rows:
        for cell in row.findall(_a("tc")):
            if cell.attrib:
                return "unsupported-table-merge"
            cell_properties = cell.find(_a("tcPr"))
            if cell_properties is None or cell_properties.attrib or list(cell_properties):
                return "unsupported-table-cell-style"
            body = cell.find(_a("txBody"))
            if body is None or len(body.findall(_a("p"))) != 1:
                return "unsupported-table-cell-text"
            paragraph = body.find(_a("p"))
            if paragraph is None or len(paragraph.findall(_a("r"))) != 1:
                return "unsupported-table-cell-text"
            if _run_issue(
                paragraph.find(_a("r")),
                allow_default=True,
            ) is not None:
                return "unsupported-table-cell-text"
    return None


def _truthy(value: str | None) -> bool:
    return value is not None and value.casefold() not in {"", "0", "false", "off"}


__all__ = ["projection_support_issue"]
