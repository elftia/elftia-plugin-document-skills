from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement

from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.template_content_fonts import (
    resolved_font_sizes,
)
from document_skills_core.formats.pptx.template_content_metrics import (
    content_hierarchy_finding,
    group_child_transform,
    object_frame,
)

_A = f"{{{NS['a']}}}"
_P = f"{{{NS['p']}}}"


def test_visible_runs_do_not_inherit_end_paragraph_properties() -> None:
    shape = Element(f"{_P}sp")
    body = SubElement(shape, f"{_P}txBody")
    paragraph = _paragraph(body, "Visible text")
    SubElement(paragraph, f"{_A}endParaRPr", {"sz": "4000"})

    assert resolved_font_sizes(
        shape,
        context=_font_context(other=18.0),
        slot=None,
    ) == [18.0]


def test_table_list_styles_remain_scoped_to_each_text_body() -> None:
    table = Element(f"{_P}graphicFrame")
    first = SubElement(table, f"{_A}txBody")
    style = SubElement(first, f"{_A}lstStyle")
    level = SubElement(style, f"{_A}lvl1pPr")
    SubElement(level, f"{_A}defRPr", {"sz": "4000"})
    _paragraph(first, "First cell")
    second = SubElement(table, f"{_A}txBody")
    _paragraph(second, "Second cell")

    assert resolved_font_sizes(
        table,
        context=_font_context(other=18.0),
        slot=None,
    ) == [18.0, 40.0]


def test_signed_shape_and_group_offsets_preserve_geometry() -> None:
    shape = Element(f"{_P}sp")
    properties = SubElement(shape, f"{_P}spPr")
    transform = SubElement(properties, f"{_A}xfrm")
    SubElement(transform, f"{_A}off", {"x": "-100", "y": "-200"})
    SubElement(transform, f"{_A}ext", {"cx": "300", "cy": "400"})
    assert object_frame(shape) == {"x": -100, "y": -200, "cx": 300, "cy": 400}

    group = Element(f"{_P}grpSp")
    group_properties = SubElement(group, f"{_P}grpSpPr")
    group_transform = SubElement(group_properties, f"{_A}xfrm")
    SubElement(group_transform, f"{_A}off", {"x": "-100", "y": "-200"})
    SubElement(group_transform, f"{_A}ext", {"cx": "1000", "cy": "1000"})
    SubElement(group_transform, f"{_A}chOff", {"x": "0", "y": "0"})
    SubElement(group_transform, f"{_A}chExt", {"cx": "500", "cy": "500"})
    assert group_child_transform(group, (1.0, 1.0, 0.0, 0.0)) == (
        2.0,
        2.0,
        -100.0,
        -200.0,
    )


def test_title_role_outranks_subtitle_regardless_of_shape_order() -> None:
    records = [
        _record("subtitle", 24.0, placeholder="subTitle", y=0),
        _record("title", 44.0, placeholder="title", y=100),
        _record("body", 18.0, placeholder=None, y=200),
    ]
    assert content_hierarchy_finding(records, "ppt/slides/slide1.xml", 1) is None

    records[2]["font_sizes"] = [50.0]
    finding = content_hierarchy_finding(records, "ppt/slides/slide1.xml", 1)
    assert finding is not None
    assert finding["title_name"] == "title"
    assert finding["title_maximum_pt"] == 44.0
    assert finding["body_maximum_pt"] == 50.0


def _paragraph(body: Element, text: str) -> Element:
    paragraph = SubElement(body, f"{_A}p")
    run = SubElement(paragraph, f"{_A}r")
    SubElement(run, f"{_A}t").text = text
    return paragraph


def _font_context(*, other: float) -> dict[str, object]:
    return {
        "layout": [],
        "master": [],
        "styles": {("otherStyle", 0): other},
    }


def _record(
    name: str,
    size: float,
    *,
    placeholder: str | None,
    y: int,
) -> dict[str, object]:
    return {
        "font_sizes": [size],
        "frame": {"x": 0, "y": y, "cx": 100, "cy": 100},
        "name": name,
        "placeholder_role": placeholder,
        "shape_id": name,
        "slot": None,
    }
