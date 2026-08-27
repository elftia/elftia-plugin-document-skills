"""Apply already-validated section and header/footer edit plans."""

from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .section_editing import SectionEditPlan


def apply_section_plan(plan: SectionEditPlan) -> None:
    if plan.kind == "section_update":
        _apply_section_updates(plan.section, plan.value)
        return
    if plan.reference is not None:
        plan.section.remove(plan.reference)
    if plan.value["link_to_previous"]:
        return
    assert plan.relationship_id is not None
    reference = Element(
        qn("w", f"{plan.value['kind']}Reference"),
        {
            qn("w", "type"): plan.value["variant"],
            qn("r", "id"): plan.relationship_id,
        },
    )
    position = 0
    children = list(plan.section)
    while position < len(children) and children[position].tag in {
        qn("w", "headerReference"),
        qn("w", "footerReference"),
    }:
        position += 1
    plan.section.insert(position, reference)
    if (
        plan.value["variant"] == "first"
        and plan.section.find(qn("w", "titlePg")) is None
    ):
        plan.section.append(Element(qn("w", "titlePg")))


def _apply_section_updates(section: Element, updates: dict[str, object]) -> None:
    size = section.find(qn("w", "pgSz"))
    if size is None and ("page_size" in updates or "orientation" in updates):
        size = SubElement(section, qn("w", "pgSz"))
    page_size = updates.get("page_size")
    if size is not None and isinstance(page_size, dict):
        size.attrib[qn("w", "w")] = str(page_size["width_twips"])
        size.attrib[qn("w", "h")] = str(page_size["height_twips"])
    orientation = updates.get("orientation")
    if size is not None and isinstance(orientation, str):
        width = int(size.attrib.get(qn("w", "w"), "12240"))
        height = int(size.attrib.get(qn("w", "h"), "15840"))
        if (orientation == "landscape" and width < height) or (
            orientation == "portrait" and width > height
        ):
            width, height = height, width
        size.attrib[qn("w", "w")] = str(width)
        size.attrib[qn("w", "h")] = str(height)
        if orientation == "landscape":
            size.attrib[qn("w", "orient")] = "landscape"
        else:
            size.attrib.pop(qn("w", "orient"), None)
    margins = updates.get("margins")
    if isinstance(margins, dict):
        node = section.find(qn("w", "pgMar"))
        if node is None:
            node = SubElement(section, qn("w", "pgMar"))
        for name, value in margins.items():
            node.attrib[qn("w", name.removesuffix("_twips"))] = str(value)
    break_type = updates.get("break_type")
    if isinstance(break_type, str):
        node = section.find(qn("w", "type"))
        if node is None:
            node = SubElement(section, qn("w", "type"))
        node.attrib[qn("w", "val")] = break_type
