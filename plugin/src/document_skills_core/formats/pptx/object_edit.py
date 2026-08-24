"""Transactional native object edits for PresentationML slides."""

import posixpath
import re
from typing import Any
from xml.etree.ElementTree import Element, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart import build_chart_part, prepare_chart, public_chart_record
from .constants import local_name
from .image import fit_existing_image, load_pptx_image, public_image_record
from .mapping import map_slides
from .mutation import MutablePptxPackage
from .object_actions import edit_action, edit_hyperlink, update_notes
from .object_parts import (
    add_part_relationship,
    next_part_index,
    register_content_types,
    remove_relationship,
    remove_unreachable_dependencies,
    replace_relationship_target,
    require_internal_relationship,
)
from .object_xml import (
    A,
    C,
    P,
    R,
    apply_shape_update,
    build_chart_frame,
    build_picture,
    build_shape,
    build_table,
    drawable_elements,
    next_shape_id,
    non_visual_properties,
    object_hash,
    object_type,
    place_at_z_order,
    select_object,
    slide_shape_tree,
    style_text,
    update_graphic_frame,
    update_picture_geometry,
    update_text,
)
_TRAILING_NUMBER = re.compile(r"(\d+)$")


def apply_object_edit(
    target: MutablePptxPackage,
    edit: dict[str, Any],
) -> dict[str, Any]:
    edit_type = edit["type"]
    slide_part = _slide_part(target, edit["slide"])
    if edit_type == "notes_update":
        return update_notes(target, slide_part, edit)

    root = target.xml(slide_part)
    tree = slide_shape_tree(root)
    if edit_type.endswith("_add") and edit_type not in {
        "action_add",
        "hyperlink_add",
    }:
        evidence = _add_object(target, slide_part, root, tree, edit)
    else:
        element = select_object(root, edit["selector"])
        _require_object_type(element, edit_type)
        evidence = _edit_selected_object(
            target,
            slide_part,
            root,
            tree,
            element,
            edit,
        )
    target.set_part(slide_part, _xml_bytes(root))
    return evidence


def _add_object(
    target: MutablePptxPackage,
    slide_part: str,
    root: Element,
    tree: Element,
    edit: dict[str, Any],
) -> dict[str, Any]:
    edit_type = edit["type"]
    value = edit["object"]
    shape_id = next_shape_id(tree)
    added_parts: list[str] = []
    image_record = None
    chart_record = None
    if edit_type == "shape_add":
        element = build_shape(shape_id, value)
    elif edit_type == "table_add":
        element = build_table(shape_id, value)
    elif edit_type == "image_add":
        image = _load_new_image(target, value)
        relationship_id = add_part_relationship(
            target,
            slide_part,
            image["part"],
            "image",
            "rIdImage",
        )
        image["relationship_id"] = relationship_id
        image["name"] = value["name"]
        target.set_part(image["part"], image["bytes"])
        register_content_types(target, {image["part"]: image["content_type"]})
        added_parts.append(image["part"])
        image_record = public_image_record(image)
        element = build_picture(shape_id, image)
    else:
        chart = _prepare_new_chart(target, value)
        relationship_id = add_part_relationship(
            target,
            slide_part,
            chart["part"],
            "chart",
            "rIdChart",
        )
        target.set_part(chart["part"], build_chart_part(chart))
        register_content_types(target, {
            chart["part"]: (
                "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
            )
        })
        added_parts.append(chart["part"])
        chart_record = public_chart_record(chart)
        element = build_chart_frame(shape_id, value, relationship_id)
    tree.append(element)
    place_at_z_order(tree, element, value.get("z_order", 100))
    return _evidence(
        edit,
        slide_part,
        element,
        before=None,
        added_parts=added_parts,
        image=image_record,
        chart=chart_record,
    )


def _edit_selected_object(
    target: MutablePptxPackage,
    slide_part: str,
    root: Element,
    tree: Element,
    element: Element,
    edit: dict[str, Any],
) -> dict[str, Any]:
    edit_type = edit["type"]
    before = object_hash(element)
    removed_parts: list[str] = []
    added_parts: list[str] = []
    image_record = None
    chart_record = None
    if edit_type.endswith("_delete"):
        relationship_id = _object_relationship_id(element)
        tree.remove(element)
        if relationship_id is not None:
            previous = remove_relationship(target, slide_part, relationship_id)
            removed_parts.extend(remove_unreachable_dependencies(target, previous))
        return _evidence(
            edit,
            slide_part,
            None,
            before=before,
            object_id=non_visual_properties(element).attrib.get("id", ""),
            object_name=non_visual_properties(element).attrib.get("name", ""),
            object_kind=object_type(element),
            removed_parts=removed_parts,
        )
    if edit_type == "shape_update":
        properties = edit["properties"]
        apply_shape_update(element, properties)
        _apply_z_order(tree, element, properties)
    elif edit_type == "text_update":
        update_text(element, edit["properties"])
    elif edit_type == "text_style":
        style_text(element, edit["properties"])
    elif edit_type == "image_crop":
        properties = dict(edit["properties"])
        _apply_image_fit(target, slide_part, element, properties)
        update_picture_geometry(element, properties)
        _apply_z_order(tree, element, properties)
    elif edit_type == "image_replace":
        image, previous, added = _replace_image(
            target,
            slide_part,
            element,
            edit["object"],
        )
        added_parts.extend(added)
        removed_parts.extend(remove_unreachable_dependencies(target, previous))
        image_record = public_image_record(image)
        replacement = build_picture(
            int(non_visual_properties(element).attrib["id"]),
            image,
        )
        _replace_tree_element(tree, element, replacement)
        element = replacement
        place_at_z_order(tree, element, edit["object"].get("z_order", 100))
    elif edit_type == "table_update":
        element = _update_table(tree, element, edit["properties"])
    elif edit_type == "chart_update":
        chart = _update_chart(target, slide_part, element, edit["object"])
        chart_record = public_chart_record(chart)
        update_graphic_frame(element, edit["object"])
        _apply_z_order(tree, element, edit["object"])
    elif edit_type.startswith("hyperlink_"):
        edit_hyperlink(target, slide_part, element, edit)
    elif edit_type.startswith("action_"):
        edit_action(target, slide_part, element, edit)
    else:
        _invalid("Unsupported PPTX object edit.", edit_type=edit_type)
    return _evidence(
        edit,
        slide_part,
        element,
        before=before,
        added_parts=added_parts,
        removed_parts=removed_parts,
        image=image_record,
        chart=chart_record,
    )


def _replace_image(
    target: MutablePptxPackage,
    slide_part: str,
    element: Element,
    value: dict[str, Any],
) -> tuple[dict[str, Any], str | None, list[str]]:
    relationship_id = _object_relationship_id(element)
    if relationship_id is None:
        _invalid("Selected image has no embedded relationship.")
    require_internal_relationship(target, slide_part, relationship_id, "image")
    prepared_value = dict(value)
    if prepared_value.get("frame") is None:
        prepared_value["frame"] = _element_frame(element)
    image = _load_new_image(target, prepared_value)
    previous = replace_relationship_target(
        target,
        slide_part,
        relationship_id,
        image["part"],
        "image",
    )
    image["relationship_id"] = relationship_id
    image["name"] = value["name"]
    target.set_part(image["part"], image["bytes"])
    register_content_types(target, {image["part"]: image["content_type"]})
    return image, previous, [image["part"]]


def _update_chart(
    target: MutablePptxPackage,
    slide_part: str,
    element: Element,
    value: dict[str, Any],
) -> dict[str, Any]:
    relationship_id = _object_relationship_id(element)
    if relationship_id is None:
        _invalid("Selected chart has no chart relationship.")
    chart_part = require_internal_relationship(
        target,
        slide_part,
        relationship_id,
        "chart",
    )
    match = _TRAILING_NUMBER.search(posixpath.splitext(chart_part)[0])
    index = int(match.group(1)) if match is not None else next_part_index(
        target.parts,
        "ppt/charts/chart",
    )
    chart = prepare_chart(value, index)
    chart["part"] = chart_part
    target.set_part(chart_part, build_chart_part(chart))
    return chart


def _update_table(
    tree: Element,
    element: Element,
    value: dict[str, Any],
) -> Element:
    if not {"rows", "widths", "heights", "merges"}.intersection(value):
        update_graphic_frame(element, value)
        _apply_z_order(tree, element, value)
        return element
    merged = _table_state(tree, element)
    if "rows" in value:
        new_rows = value["rows"]
        if "widths" not in value and len(new_rows[0]) != len(merged["rows"][0]):
            merged.pop("widths", None)
        if "heights" not in value and len(new_rows) != len(merged["rows"]):
            merged.pop("heights", None)
    merged.update(value)
    replacement = build_table(
        int(non_visual_properties(element).attrib["id"]),
        merged,
    )
    _replace_tree_element(tree, element, replacement)
    place_at_z_order(tree, replacement, merged["z_order"])
    return replacement


def _apply_image_fit(
    target: MutablePptxPackage,
    slide_part: str,
    element: Element,
    properties: dict[str, Any],
) -> None:
    if "fit" not in properties:
        return
    relationship_id = _object_relationship_id(element)
    if relationship_id is None:
        _invalid("Selected image has no embedded relationship.")
    image_part = require_internal_relationship(
        target,
        slide_part,
        relationship_id,
        "image",
    )
    frame = properties.get("frame") or _element_frame(element)
    geometry, crop = fit_existing_image(
        target.parts[image_part],
        frame,
        properties.pop("fit"),
        properties.get("crop"),
    )
    properties["frame"] = geometry
    properties["crop"] = crop


def _table_state(tree: Element, element: Element) -> dict[str, Any]:
    table = element.find(f"{A('graphic')}/{A('graphicData')}/{A('tbl')}")
    if table is None:
        _invalid("Selected table lacks native table data.")
    rows = []
    heights = []
    merges = []
    for row_index, row in enumerate(table.findall(A("tr")), 1):
        heights.append(int(row.attrib.get("h", "1")))
        cells = []
        for column_index, cell in enumerate(row.findall(A("tc")), 1):
            cells.append("".join(node.text or "" for node in cell.iter(A("t"))))
            if "hMerge" not in cell.attrib and "vMerge" not in cell.attrib:
                row_span = int(cell.attrib.get("rowSpan", "1"))
                column_span = int(cell.attrib.get("gridSpan", "1"))
                if row_span > 1 or column_span > 1:
                    merges.append({
                        "row": row_index,
                        "column": column_index,
                        "row_span": row_span,
                        "column_span": column_span,
                    })
        rows.append(cells)
    grid = table.find(A("tblGrid"))
    widths = [] if grid is None else [
        int(column.attrib.get("w", "1"))
        for column in grid.findall(A("gridCol"))
    ]
    return {
        "frame": _element_frame(element),
        "heights": heights,
        "merges": merges,
        "name": non_visual_properties(element).attrib.get("name", "Table"),
        "rows": rows,
        "widths": widths,
        "z_order": drawable_elements(tree).index(element),
    }


def _element_frame(element: Element) -> dict[str, int]:
    properties = element.find(P("spPr"))
    transform = None if properties is None else properties.find(A("xfrm"))
    if transform is None:
        transform = element.find(P("xfrm"))
    if transform is None:
        _invalid("Selected object has no native frame.")
    offset = transform.find(A("off"))
    extent = transform.find(A("ext"))
    if offset is None or extent is None:
        _invalid("Selected object frame is incomplete.")
    return {
        "x": int(offset.attrib["x"]),
        "y": int(offset.attrib["y"]),
        "cx": int(extent.attrib["cx"]),
        "cy": int(extent.attrib["cy"]),
    }


def _object_relationship_id(element: Element) -> str | None:
    if object_type(element) == "image":
        blip = element.find(f"{P('blipFill')}/{A('blip')}")
        return None if blip is None else blip.attrib.get(R("embed"))
    if object_type(element) == "chart":
        chart = element.find(f".//{C('chart')}")
        return None if chart is None else chart.attrib.get(R("id"))
    return None


def _load_new_image(
    target: MutablePptxPackage,
    value: dict[str, Any],
) -> dict[str, Any]:
    index = next_part_index(target.parts, "ppt/media/image")
    image = load_pptx_image(value, index)
    while image["part"] in target.parts:
        index += 1
        image = load_pptx_image(value, index)
    return image


def _prepare_new_chart(
    target: MutablePptxPackage,
    value: dict[str, Any],
) -> dict[str, Any]:
    index = next_part_index(target.parts, "ppt/charts/chart")
    chart = prepare_chart(value, index)
    while chart["part"] in target.parts:
        index += 1
        chart = prepare_chart(value, index)
    return chart


def _apply_z_order(
    tree: Element,
    element: Element,
    value: dict[str, Any],
) -> None:
    if "z_order" in value:
        place_at_z_order(tree, element, value["z_order"])


def _replace_tree_element(
    tree: Element,
    current: Element,
    replacement: Element,
) -> None:
    index = list(tree).index(current)
    tree.remove(current)
    tree.insert(index, replacement)


def _require_object_type(element: Element, edit_type: str) -> None:
    if local_name(element.tag) == "grpSp":
        _invalid("Grouped object editing is not supported.")
    expected = next(
        (
            prefix
            for prefix in ("shape", "image", "table", "chart")
            if edit_type.startswith(f"{prefix}_")
        ),
        None,
    )
    if expected is not None and object_type(element) != expected:
        _invalid(
            "Selected object type does not match the edit primitive.",
            actual=object_type(element),
            expected=expected,
        )
    if expected == "shape" and local_name(element.tag) not in {"cxnSp", "sp"}:
        _invalid("Grouped or non-native shape editing is not supported.")


def _slide_part(target: MutablePptxPackage, position: int) -> str:
    slides = map_slides(target)
    if position < 1 or position > len(slides):
        _invalid(
            "Slide position is outside the current deck.",
            position=position,
            slides=len(slides),
        )
    part = slides[position - 1].get("part")
    if part is None:
        _invalid("Selected slide part is missing.", position=position)
    return part


def _evidence(
    edit: dict[str, Any],
    slide_part: str,
    element: Element | None,
    *,
    before: str | None,
    object_id: str | None = None,
    object_name: str | None = None,
    object_kind: str | None = None,
    added_parts: list[str] | None = None,
    removed_parts: list[str] | None = None,
    image: dict[str, Any] | None = None,
    chart: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if element is not None:
        properties = non_visual_properties(element)
        object_id = properties.attrib.get("id", "")
        object_name = properties.attrib.get("name", "")
        object_kind = object_type(element)
    return {
        "added_parts": sorted(added_parts or []),
        "after_sha256": None if element is None else object_hash(element),
        "before_sha256": before,
        "chart": chart,
        "image": image,
        "object_id": object_id,
        "object_name": object_name,
        "object_type": object_kind,
        "removed_parts": sorted(removed_parts or []),
        "slide": edit["slide"],
        "slide_part": slide_part,
        "type": edit["type"],
    }


def _xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
