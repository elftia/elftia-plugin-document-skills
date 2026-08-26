"""Apply already-validated bookmark and internal hyperlink plans."""

from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .link_editing import LinkEditPlan
from .xml_utils import set_text


def apply_link_plan(plan: LinkEditPlan) -> None:
    if plan.kind == "bookmark_insert":
        assert plan.bookmark_id is not None
        start = Element(
            qn("w", "bookmarkStart"),
            {
                qn("w", "id"): str(plan.bookmark_id),
                qn("w", "name"): plan.value["name"],
            },
        )
        end = Element(qn("w", "bookmarkEnd"), {qn("w", "id"): str(plan.bookmark_id)})
        position = 1 if plan.paragraph.find(qn("w", "pPr")) is not None else 0
        plan.paragraph.insert(position, start)
        plan.paragraph.append(end)
        return
    if plan.kind == "hyperlink_insert":
        hyperlink = _hyperlink(plan.value["bookmark_name"], plan.value["text"])
        if plan.value["placement"] == "append":
            plan.paragraph.append(hyperlink)
        else:
            position = 1 if plan.paragraph.find(qn("w", "pPr")) is not None else 0
            plan.paragraph.insert(position, hyperlink)
        return
    assert plan.hyperlink is not None
    if plan.value["bookmark_name"] is not None:
        plan.hyperlink.attrib[qn("w", "anchor")] = plan.value["bookmark_name"]
    if plan.value["text"] is not None:
        set_text(next(plan.hyperlink.iter(qn("w", "t"))), plan.value["text"])


def _hyperlink(bookmark_name: str, text: str) -> Element:
    hyperlink = Element(
        qn("w", "hyperlink"),
        {qn("w", "anchor"): bookmark_name, qn("w", "history"): "1"},
    )
    run = SubElement(hyperlink, qn("w", "r"))
    properties = SubElement(run, qn("w", "rPr"))
    SubElement(properties, qn("w", "rStyle"), {qn("w", "val"): "Hyperlink"})
    node = SubElement(run, qn("w", "t"))
    set_text(node, text)
    return hyperlink
