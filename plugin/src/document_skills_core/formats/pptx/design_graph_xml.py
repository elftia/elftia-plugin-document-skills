"""PresentationML builders for authored layouts and design relationships."""

import posixpath
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS
from .scaffold import _background, _complete_sp_tree

_P = NS["p"]
_A = NS["a"]
_RELS = NS["rels"]


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def A(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def RELS(tag: str) -> str:
    return f"{{{_RELS}}}{tag}"


def build_layout(value: dict[str, Any], width: int, height: int) -> bytes:
    attributes = {
        "preserve": "1",
        "showMasterSp": "1" if value["show_master_shapes"] else "0",
        "type": value["type"],
    }
    root = Element(P("sldLayout"), attributes)
    common = SubElement(root, P("cSld"), {"name": value["name"]})
    if value["background"] is not None:
        _background(common, value["background"])
    _complete_sp_tree(common, width, height)
    tree = common.find(P("spTree"))
    assert tree is not None
    shape_id = 2
    for placeholder in value["placeholders"]:
        _append_placeholder(tree, placeholder, shape_id)
        shape_id += 1
    footer_types = {
        "date": ("dt", 10_000),
        "footer": ("ftr", 10_001),
        "slide_number": ("sldNum", 10_002),
    }
    for key, (placeholder_type, idx) in footer_types.items():
        slot = value[key]
        if slot["enabled"]:
            _append_placeholder(
                tree,
                {
                    "frame": slot["frame"],
                    "idx": idx,
                    "name": key.replace("_", " ").title(),
                    "text": slot["text"],
                    "type": placeholder_type,
                },
                shape_id,
            )
            shape_id += 1
    SubElement(SubElement(root, P("clrMapOvr")), A("masterClrMapping"))
    SubElement(root, P("hf"), {
        "dt": "1" if value["date"]["enabled"] else "0",
        "ftr": "1" if value["footer"]["enabled"] else "0",
        "sldNum": "1" if value["slide_number"]["enabled"] else "0",
    })
    return xml_bytes(root)


def master_relationships(master: str, layout: str, theme: str) -> bytes:
    root = Element(RELS("Relationships"))
    directory = posixpath.dirname(master)
    SubElement(root, RELS("Relationship"), {
        "Id": "rIdTheme",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        "Target": posixpath.relpath(theme, directory),
    })
    SubElement(root, RELS("Relationship"), {
        "Id": "rIdLayout1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
        "Target": posixpath.relpath(layout, directory),
    })
    return xml_bytes(root)


def layout_relationships(layout: str, master: str) -> bytes:
    root = Element(RELS("Relationships"))
    SubElement(root, RELS("Relationship"), {
        "Id": "rIdMaster",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
        "Target": posixpath.relpath(master, posixpath.dirname(layout)),
    })
    return xml_bytes(root)


def xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _append_placeholder(
    tree: Element,
    value: dict[str, Any],
    shape_id: int,
) -> None:
    shape = SubElement(tree, P("sp"))
    non_visual = SubElement(shape, P("nvSpPr"))
    SubElement(non_visual, P("cNvPr"), {"id": str(shape_id), "name": value["name"]})
    SubElement(non_visual, P("cNvSpPr"), {"txBox": "1"})
    application = SubElement(non_visual, P("nvPr"))
    SubElement(application, P("ph"), {"idx": str(value["idx"]), "type": value["type"]})
    properties = SubElement(shape, P("spPr"))
    transform = SubElement(properties, A("xfrm"))
    frame = value["frame"]
    SubElement(transform, A("off"), {"x": str(frame["x"]), "y": str(frame["y"])})
    SubElement(transform, A("ext"), {"cx": str(frame["cx"]), "cy": str(frame["cy"])})
    geometry = SubElement(properties, A("prstGeom"), {"prst": "rect"})
    SubElement(geometry, A("avLst"))
    body = SubElement(shape, P("txBody"))
    SubElement(body, A("bodyPr"))
    SubElement(body, A("lstStyle"))
    paragraph = SubElement(body, A("p"))
    text = value.get("text", "")
    if text:
        run = SubElement(paragraph, A("r"))
        SubElement(run, A("rPr"), {"lang": "en-US"})
        SubElement(run, A("t")).text = text
    SubElement(paragraph, A("endParaRPr"), {"lang": "en-US"})
