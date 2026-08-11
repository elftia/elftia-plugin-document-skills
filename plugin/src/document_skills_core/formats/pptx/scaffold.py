"""Shared Office-valid PresentationML scaffold vocabulary.

Owns the complete minimal OOXML structures common to both typed
``pptx.create`` and the HTML scene emitter: theme, slide master,
slide layout, root relationships, and document properties.
"""

from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS

_P = NS["p"]
_A = NS["a"]
_R = NS["r"]
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_SLIDE_CX_DEFAULT = 9_144_000
_SLIDE_CY_DEFAULT = 6_858_000


def _to_xml_bytes(root: Element) -> bytes:
    """Serialize an Element tree to deterministic UTF-8 XML bytes."""
    return tostring(root, encoding="UTF-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def _build_theme() -> bytes:
    """Complete minimal Office theme with clrScheme, fontScheme, and fmtScheme."""
    root = Element(f"{{{_A}}}theme", attrib={"name": "Office Theme"})
    elements = SubElement(root, f"{{{_A}}}themeElements")

    clr_scheme = SubElement(elements, f"{{{_A}}}clrScheme", attrib={"name": "Office"})
    _sys_color(clr_scheme, "dk1", "windowText", "000000")
    _sys_color(clr_scheme, "lt1", "window", "FFFFFF")
    _srgb_color(clr_scheme, "dk2", "44546A")
    _srgb_color(clr_scheme, "lt2", "E7E6E6")
    _srgb_color(clr_scheme, "accent1", "4472C4")
    _srgb_color(clr_scheme, "accent2", "ED7D31")
    _srgb_color(clr_scheme, "accent3", "A5A5A5")
    _srgb_color(clr_scheme, "accent4", "FFC000")
    _srgb_color(clr_scheme, "accent5", "5B9BD5")
    _srgb_color(clr_scheme, "accent6", "70AD47")
    _srgb_color(clr_scheme, "hlink", "0563C1")
    _srgb_color(clr_scheme, "folHlink", "954F72")

    font_scheme = SubElement(elements, f"{{{_A}}}fontScheme", attrib={"name": "Office"})
    _font_collection(font_scheme, "majorFont", "Calibri Light")
    _font_collection(font_scheme, "minorFont", "Calibri")

    fmt_scheme = SubElement(elements, f"{{{_A}}}fmtScheme")
    fill_lst = SubElement(fmt_scheme, f"{{{_A}}}fillStyleLst")
    _ph_solid_fill(fill_lst)
    _ph_grad_fill(fill_lst)
    _ph_grad_fill(fill_lst)
    ln_lst = SubElement(fmt_scheme, f"{{{_A}}}lnStyleLst")
    _ph_line(ln_lst, "9100")
    _ph_line(ln_lst, "9100")
    _ph_line(ln_lst, "9100")
    effect_lst = SubElement(fmt_scheme, f"{{{_A}}}effectStyleLst")
    for _ in range(3):
        SubElement(SubElement(effect_lst, f"{{{_A}}}effectStyle"), f"{{{_A}}}effectLst")
    bg_lst = SubElement(fmt_scheme, f"{{{_A}}}bgFillStyleLst")
    _ph_solid_fill(bg_lst)
    _ph_solid_fill(bg_lst)
    _ph_solid_fill(bg_lst)

    return _to_xml_bytes(root)


def _sys_color(parent: Element, name: str, val: str, last_clr: str) -> None:
    child = SubElement(parent, f"{{{_A}}}{name}")
    SubElement(child, f"{{{_A}}}sysClr", attrib={"val": val, "lastClr": last_clr})


def _srgb_color(parent: Element, name: str, val: str) -> None:
    child = SubElement(parent, f"{{{_A}}}{name}")
    SubElement(child, f"{{{_A}}}srgbClr", attrib={"val": val})


def _font_collection(parent: Element, tag: str, typeface: str) -> None:
    font = SubElement(parent, f"{{{_A}}}{tag}")
    SubElement(font, f"{{{_A}}}latin", attrib={"typeface": typeface})
    SubElement(font, f"{{{_A}}}ea", attrib={"typeface": ""})
    SubElement(font, f"{{{_A}}}cs", attrib={"typeface": ""})


def _ph_solid_fill(parent: Element) -> None:
    solid = SubElement(parent, f"{{{_A}}}solidFill")
    SubElement(solid, f"{{{_A}}}schemeClr", attrib={"val": "phClr"})


def _ph_grad_fill(parent: Element) -> None:
    grad = SubElement(parent, f"{{{_A}}}gradFill")
    SubElement(grad, f"{{{_A}}}gsLst")
    lin = SubElement(grad, f"{{{_A}}}lin", attrib={"ang": "0", "scaled": "0"})


def _ph_line(parent: Element, w: str) -> None:
    ln = SubElement(
        parent,
        f"{{{_A}}}ln",
        attrib={"w": w, "cap": "flat", "cmpd": "sng", "algn": "ctr"},
    )
    solid = SubElement(ln, f"{{{_A}}}solidFill")
    SubElement(solid, f"{{{_A}}}schemeClr", attrib={"val": "phClr"})
    SubElement(ln, f"{{{_A}}}prstDash", attrib={"val": "solid"})


# ---------------------------------------------------------------------------
# Slide master / slide layout
# ---------------------------------------------------------------------------


def _build_slide_master(
    layout_count: int,
    cx: int = _SLIDE_CX_DEFAULT,
    cy: int = _SLIDE_CY_DEFAULT,
) -> bytes:
    root = Element(f"{{{_P}}}sldMaster")
    c_sld = SubElement(root, f"{{{_P}}}cSld")
    _complete_sp_tree(c_sld, cx, cy)
    SubElement(root, f"{{{_P}}}clrMap", attrib=_CLR_MAP)
    layout_id_lst = SubElement(root, f"{{{_P}}}sldLayoutIdLst")
    for i in range(1, layout_count + 1):
        SubElement(
            layout_id_lst,
            f"{{{_P}}}sldLayoutId",
            attrib={"id": str(2_147_483_648 + i), f"{{{_R}}}id": f"rIdLayout{i}"},
        )
    SubElement(root, f"{{{_P}}}txStyles")
    return _to_xml_bytes(root)


def _build_slide_master_rels(layout_count: int) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(
        root,
        f"{{{_RELS_NS}}}Relationship",
        attrib={
            "Id": "rIdTheme",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
            "Target": "../theme/theme1.xml",
        },
    )
    for i in range(1, layout_count + 1):
        SubElement(
            root,
            f"{{{_RELS_NS}}}Relationship",
            attrib={
                "Id": f"rIdLayout{i}",
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                "Target": f"../slideLayouts/slideLayout{i}.xml",
            },
        )
    return _to_xml_bytes(root)


def _build_slide_layout(
    layout_idx: int,
    cx: int = _SLIDE_CX_DEFAULT,
    cy: int = _SLIDE_CY_DEFAULT,
) -> bytes:
    layout_names = {1: "Title Slide", 2: "Title and Content"}
    root = Element(f"{{{_P}}}sldLayout")
    c_sld = SubElement(root, f"{{{_P}}}cSld", attrib={"name": layout_names.get(layout_idx, "Custom")})
    _complete_sp_tree(c_sld, cx, cy)
    SubElement(SubElement(root, f"{{{_P}}}clrMapOvr"), f"{{{_A}}}masterClrMapping")
    return _to_xml_bytes(root)


def _build_slide_layout_rels(layout_idx: int) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(
        root,
        f"{{{_RELS_NS}}}Relationship",
        attrib={
            "Id": "rIdMaster",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
            "Target": "../slideMasters/slideMaster1.xml",
        },
    )
    return _to_xml_bytes(root)


def _complete_sp_tree(parent: Element, cx: int, cy: int) -> None:
    """Emit a schema-complete spTree with nvGrpSpPr and grpSpPr."""
    sp_tree = SubElement(parent, f"{{{_P}}}spTree")
    non_visual = SubElement(sp_tree, f"{{{_P}}}nvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}cNvPr", attrib={"id": "1", "name": ""})
    SubElement(non_visual, f"{{{_P}}}cNvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    group = SubElement(sp_tree, f"{{{_P}}}grpSpPr")
    xfrm = SubElement(group, f"{{{_A}}}xfrm")
    SubElement(xfrm, f"{{{_A}}}off", attrib={"x": "0", "y": "0"})
    SubElement(xfrm, f"{{{_A}}}ext", attrib={"cx": str(cx), "cy": str(cy)})
    SubElement(xfrm, f"{{{_A}}}chOff", attrib={"x": "0", "y": "0"})
    SubElement(xfrm, f"{{{_A}}}chExt", attrib={"cx": str(cx), "cy": str(cy)})


# ---------------------------------------------------------------------------
# Root relationships / document properties
# ---------------------------------------------------------------------------


def _build_root_rels() -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(
        root,
        f"{{{_RELS_NS}}}Relationship",
        attrib={
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "ppt/presentation.xml",
        },
    )
    SubElement(
        root,
        f"{{{_RELS_NS}}}Relationship",
        attrib={
            "Id": "rId2",
            "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
            "Target": "docProps/core.xml",
        },
    )
    SubElement(
        root,
        f"{{{_RELS_NS}}}Relationship",
        attrib={
            "Id": "rId3",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
            "Target": "docProps/app.xml",
        },
    )
    return _to_xml_bytes(root)


def _build_core_props(metadata: dict[str, Any]) -> bytes:
    cp_ns = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    dc_ns = "http://purl.org/dc/elements/1.1/"
    root = Element(f"{{{cp_ns}}}coreProperties")
    SubElement(root, f"{{{dc_ns}}}title").text = metadata.get("title", "")
    SubElement(root, f"{{{dc_ns}}}creator").text = metadata.get("creator", "Elftia Document Skills")
    SubElement(root, f"{{{dc_ns}}}subject").text = metadata.get("subject", "")
    return _to_xml_bytes(root)


def _build_app_props(slides: list[dict[str, Any]]) -> bytes:
    app_ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
    root = Element(f"{{{app_ns}}}Properties")
    SubElement(root, f"{{{app_ns}}}Application").text = "Elftia Document Skills"
    SubElement(root, f"{{{app_ns}}}Slides").text = str(len(slides))
    return _to_xml_bytes(root)


_CLR_MAP = {
    "bg1": "lt1",
    "tx1": "dk1",
    "bg2": "lt2",
    "tx2": "dk2",
    "accent1": "accent1",
    "accent2": "accent2",
    "accent3": "accent3",
    "accent4": "accent4",
    "accent5": "accent5",
    "accent6": "accent6",
    "hlink": "hlink",
    "folHlink": "folHlink",
}
