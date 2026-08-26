"""Simple deterministic Word header/footer story emission."""

from xml.etree.ElementTree import Element

from .constants import qn
from .xml_utils import paragraph, xml_bytes


def story_bytes(kind: str, text: str) -> bytes:
    root = Element(qn("w", "hdr" if kind == "header" else "ftr"))
    root.append(paragraph(text))
    return xml_bytes(root)
