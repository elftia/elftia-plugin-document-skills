"""Office-compatible speaker-notes PresentationML scaffold."""

from xml.etree.ElementTree import Element, SubElement

from .constants import NS
from .scaffold import _CLR_MAP, _to_xml_bytes

_P = NS["p"]
_A = NS["a"]
_RELS = NS["rels"]


def _build_notes_master() -> bytes:
    root = Element(f"{{{_P}}}notesMaster")
    common = SubElement(root, f"{{{_P}}}cSld")
    tree = SubElement(common, f"{{{_P}}}spTree")
    _group_shape_properties(tree)
    SubElement(root, f"{{{_P}}}clrMap", attrib=_CLR_MAP)
    return _to_xml_bytes(root)


def _build_notes_master_rels(theme_target: str) -> bytes:
    root = Element(f"{{{_RELS}}}Relationships")
    SubElement(
        root,
        f"{{{_RELS}}}Relationship",
        attrib={
            "Id": "rIdNotes",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
            "Target": theme_target,
        },
    )
    return _to_xml_bytes(root)


def _build_notes_slide(slide_num: int, notes_text: str) -> bytes:
    root = Element(f"{{{_P}}}notes")
    common = SubElement(root, f"{{{_P}}}cSld")
    tree = SubElement(common, f"{{{_P}}}spTree")
    _group_shape_properties(tree)
    shape = SubElement(tree, f"{{{_P}}}sp")
    non_visual = SubElement(shape, f"{{{_P}}}nvSpPr")
    SubElement(
        non_visual,
        f"{{{_P}}}cNvPr",
        attrib={"id": "3", "name": f"NotesPlaceholder{slide_num}"},
    )
    SubElement(non_visual, f"{{{_P}}}cNvSpPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    SubElement(shape, f"{{{_P}}}spPr")
    text_body = SubElement(shape, f"{{{_P}}}txBody")
    SubElement(text_body, f"{{{_A}}}bodyPr")
    SubElement(text_body, f"{{{_A}}}lstStyle")
    paragraph = SubElement(text_body, f"{{{_A}}}p")
    run = SubElement(paragraph, f"{{{_A}}}r")
    SubElement(run, f"{{{_A}}}t").text = notes_text
    return _to_xml_bytes(root)


def _build_notes_slide_rels(slide_num: int) -> bytes:
    root = Element(f"{{{_RELS}}}Relationships")
    SubElement(
        root,
        f"{{{_RELS}}}Relationship",
        attrib={
            "Id": "rIdSlide",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            "Target": f"../slides/slide{slide_num}.xml",
        },
    )
    SubElement(
        root,
        f"{{{_RELS}}}Relationship",
        attrib={
            "Id": "rIdNotesMaster",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
            "Target": "../notesMasters/notesMaster1.xml",
        },
    )
    return _to_xml_bytes(root)


def _group_shape_properties(tree: Element) -> None:
    non_visual = SubElement(tree, f"{{{_P}}}nvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}cNvPr", attrib={"id": "1", "name": ""})
    SubElement(non_visual, f"{{{_P}}}cNvGrpSpPr")
    SubElement(non_visual, f"{{{_P}}}nvPr")
    group = SubElement(tree, f"{{{_P}}}grpSpPr")
    SubElement(group, f"{{{_A}}}xfrm")
