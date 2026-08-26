"""Apply already-validated immutable DOCX table edit plans."""

from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .mapping import map_paragraph
from .table import table_cell, table_element, table_row
from .table_editing import TableEditPlan
from .xml_utils import set_text, text_run


def apply_table_plan(plan: TableEditPlan) -> None:
    if plan.kind == "table_insert":
        assert plan.parent is not None and plan.anchor is not None
        position = list(plan.parent).index(plan.anchor)
        if plan.position == "after":
            position += 1
        plan.parent.insert(position, table_element(plan.value))
        return
    if plan.kind == "table_cell_update":
        assert plan.cell is not None
        _set_cell_text(plan.cell, plan.value)
        return
    if plan.kind == "table_row_insert":
        assert plan.parent is not None and plan.anchor is not None
        position = list(plan.parent).index(plan.anchor)
        if plan.position == "after":
            position += 1
        plan.parent.insert(position, table_row(plan.value))
        return
    if plan.kind == "table_row_delete":
        assert plan.parent is not None and plan.row is not None
        plan.parent.remove(plan.row)
        return
    if plan.kind == "table_cells_merge":
        _apply_merge(plan)
        return
    if plan.kind == "table_cell_split":
        _apply_split(plan)
        return
    raise AssertionError(f"Unexpected table edit type: {plan.kind}")


def _apply_merge(plan: TableEditPlan) -> None:
    assert plan.table is not None
    selection = plan.value["selection"]
    table_rows = plan.table.findall(qn("w", "tr"))
    height = len(plan.rows)
    for offset, cells in enumerate(plan.rows):
        row = table_rows[selection["start_row"] + offset]
        survivor = cells[0]
        properties = _cell_properties(survivor)
        _set_property(properties, "gridSpan", str(len(cells)) if len(cells) > 1 else None)
        _set_property(
            properties,
            "vMerge",
            ("restart" if offset == 0 else "continue") if height > 1 else None,
        )
        _set_cell_text(survivor, plan.value["text"] if offset == 0 else "")
        for removed in cells[1:]:
            row.remove(removed)


def _apply_split(plan: TableEditPlan) -> None:
    assert plan.parent is not None and plan.cell is not None
    properties = _cell_properties(plan.cell)
    _set_property(properties, "gridSpan", None)
    _set_cell_text(plan.cell, plan.value[0])
    position = list(plan.parent).index(plan.cell) + 1
    for text in plan.value[1:]:
        plan.parent.insert(position, table_cell(text))
        position += 1


def _set_cell_text(cell: Element, text: str) -> None:
    paragraph = cell.findall(qn("w", "p"))[0]
    mapped = map_paragraph(paragraph)
    references = [reference for group in mapped.groups for reference in group.refs]
    if not references:
        text_run(paragraph, text)
        return
    set_text(references[0].node, text)
    for reference in references[1:]:
        set_text(reference.node, "")


def _cell_properties(cell: Element) -> Element:
    properties = cell.find(qn("w", "tcPr"))
    if properties is None:
        properties = Element(qn("w", "tcPr"))
        cell.insert(0, properties)
    return properties


def _set_property(properties: Element, name: str, value: str | None) -> None:
    tag = qn("w", name)
    for node in list(properties.findall(tag)):
        properties.remove(node)
    if value is not None:
        SubElement(properties, tag, {qn("w", "val"): value})
