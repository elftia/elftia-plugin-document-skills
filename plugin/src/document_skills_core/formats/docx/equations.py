"""Closed editable-OMML equation construction and projection."""

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .formatting import set_paragraph_style
from .mapping import Story, iter_paragraphs
from .semantic_nodes import semantic_node_for
from .xml_utils import set_text


def equation_paragraph(block: dict[str, Any]) -> Element:
    paragraph = Element(qn("w", "p"))
    if block.get("style") is not None:
        set_paragraph_style(paragraph, block["style"])
    math_paragraph = SubElement(paragraph, qn("m", "oMathPara"))
    math = SubElement(math_paragraph, qn("m", "oMath"))
    run = SubElement(math, qn("m", "r"))
    text = SubElement(run, qn("m", "t"))
    set_text(text, block["linear"])
    return paragraph


def project_equations(body: Story) -> list[dict[str, Any]]:
    result = []
    for paragraph in iter_paragraphs(body.root):
        semantic = semantic_node_for(
            paragraph,
            allowed_types=frozenset({"equation"}),
        )
        if semantic is None:
            continue
        math = paragraph.find(f"./{qn('m', 'oMathPara')}/{qn('m', 'oMath')}")
        if math is None:
            continue
        result.append(
            {
                "node_id": semantic.node_id,
                "node_type": semantic.node_type,
                "linear": "".join(node.text or "" for node in math.iter(qn("m", "t"))),
                "editable_omml": True,
            }
        )
    return result
