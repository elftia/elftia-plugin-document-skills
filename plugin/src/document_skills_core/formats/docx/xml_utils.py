"""Deterministic XML construction helpers."""

from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import qn


def xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)


def text_run(parent: Element, text: str, *, bold: bool = False) -> Element:
    run = SubElement(parent, qn("w", "r"))
    if bold:
        properties = SubElement(run, qn("w", "rPr"))
        SubElement(properties, qn("w", "b"))
    node = SubElement(run, qn("w", "t"))
    set_text(node, text)
    return run


def set_text(node: Element, text: str) -> None:
    node.text = text
    space = "{http://www.w3.org/XML/1998/namespace}space"
    if text.startswith((" ", "\t", "\n")) or text.endswith((" ", "\t", "\n")):
        node.set(space, "preserve")
    else:
        node.attrib.pop(space, None)


def paragraph(text: str = "", *, style: str | None = None) -> Element:
    node = Element(qn("w", "p"))
    if style:
        properties = SubElement(node, qn("w", "pPr"))
        SubElement(properties, qn("w", "pStyle"), {qn("w", "val"): style})
    text_run(node, text)
    return node
