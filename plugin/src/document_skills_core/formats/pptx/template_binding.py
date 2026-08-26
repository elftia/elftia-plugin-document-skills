"""Semantic-slot binding while preserving template-owned object styling."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, NS
from .mapping import map_slides
from .mutation import MutablePptxPackage
from .object_contracts import parse_object_edit
from .object_edit import _element_frame, apply_object_edit
from .object_xml import (
    A,
    non_visual_properties,
    object_hash,
    object_type,
    select_object,
    slide_shape_tree,
)
from .presentation_contracts import PresentationContractConsumer
from .template_descriptor import TemplateDescriptor

_P = NS["p"]


def apply_template_bindings(
    target: MutablePptxPackage,
    *,
    target_position: int,
    page: dict[str, Any],
    descriptor: TemplateDescriptor,
    expected_hashes: dict[str, str],
    image_byte_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    slots = descriptor.slots_by_id
    receipts: list[dict[str, Any]] = []
    added_image_bytes = 0
    for binding in page["bindings"]:
        slot = slots.get(binding["slot_id"])
        if slot is None:
            _invalid("Binding references an unknown semantic slot.", slot_id=binding["slot_id"])
        source_object_id = slot["sourceObjectId"]
        expected = expected_hashes.get(binding["slot_id"])
        if expected is None or binding["expected_hash"] != expected:
            raise DocumentSkillsError(
                ErrorCode.STALE_PRECONDITION,
                "Semantic slot hash no longer matches the inspected template object.",
                status="invalid_request",
                details={
                    "actual": expected,
                    "expected": binding["expected_hash"],
                    "slot_id": binding["slot_id"],
                },
            )
        before, after, outcome, image_bytes = _apply_value(
            target,
            target_position,
            source_object_id,
            slot["dataType"],
            binding["value"],
            expected,
        )
        added_image_bytes += image_bytes
        if added_image_bytes > image_byte_limit:
            _resource_limit(
                "Template binding images exceed the aggregate byte budget.",
                actual=added_image_bytes,
                ceiling=image_byte_limit,
            )
        receipts.append({
            "after_sha256": after,
            "before_sha256": before,
            "outcome": outcome,
            "slot_id": binding["slot_id"],
            "source_object_id": source_object_id,
            "value_type": slot["dataType"],
        })
    object_mapping = _assign_output_object_ids(
        target,
        target_position,
        page["output_slide_id"],
        descriptor,
    )
    _refresh_receipt_hashes(target, target_position, receipts, object_mapping)
    return receipts, object_mapping, added_image_bytes


def _apply_value(
    target: MutablePptxPackage,
    slide: int,
    object_id: str,
    data_type: str,
    value: dict[str, Any],
    expected_hash: str,
) -> tuple[str, str, str, int]:
    slide_part = map_slides(target)[slide - 1]["part"]
    if slide_part is None:
        _invalid("Copied template slide part is missing.")
    root = target.xml(slide_part)
    element = select_object(root, {"id": None, "name": object_id, "type": None})
    before = object_hash(element)
    if before != expected_hash:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "Copied semantic object differs from its inspected source.",
            status="invalid_request",
            details={"actual": before, "expected": expected_hash, "object_id": object_id},
        )
    payload_type = value.get("type")
    if payload_type != data_type:
        _invalid(
            "Binding value type does not match the semantic slot data type.",
            actual=payload_type,
            expected=data_type,
        )
    if data_type in {"date", "number", "rich-text", "text"}:
        paragraphs = _text_value(value, data_type)
        _replace_text_preserving_style(element, paragraphs)
        target.set_part(slide_part, _xml_bytes(root))
        return before, object_hash(element), "native", 0
    if data_type == "table-data":
        rows = _table_value(value)
        _replace_table_text(element, rows)
        target.set_part(slide_part, _xml_bytes(root))
        return before, object_hash(element), "native", 0
    if data_type == "image-ref":
        edit = _image_edit(value, slide, object_id, expected_hash)
        evidence = apply_object_edit(target, parse_object_edit(edit, 0))
        image = evidence.get("image")
        image_bytes = 0 if image is None else int(image.get("bytes", 0))
        return before, evidence["after_sha256"], "native", image_bytes
    if data_type == "chart-data":
        edit = _chart_edit(
            value,
            slide,
            object_id,
            expected_hash,
            frame=_element_frame(element),
            z_order=list(slide_shape_tree(root)).index(element),
        )
        evidence = apply_object_edit(target, parse_object_edit(edit, 0))
        return before, evidence["after_sha256"], "native", 0
    _invalid("Semantic slot data type is unsupported for template binding.", data_type=data_type)


def _text_value(value: dict[str, Any], data_type: str) -> list[str]:
    if data_type == "text":
        _exact(value, {"text", "type"})
        return [_text(value.get("text"), "value.text")]
    if data_type == "rich-text":
        _exact(value, {"paragraphs", "type"})
        paragraphs = value.get("paragraphs")
        if type(paragraphs) is not list or not paragraphs or len(paragraphs) > 64:
            _invalid("rich-text paragraphs must be a non-empty bounded array.")
        return [_text(item, "value.paragraphs") for item in paragraphs]
    if data_type == "number":
        _exact(value, {"type", "value"})
        number = value.get("value")
        if isinstance(number, bool) or type(number) not in {int, float}:
            _invalid("number binding value must be numeric.")
        return [str(number)]
    _exact(value, {"type", "value"})
    date = _text(value.get("value"), "value.value")
    try:
        datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError as error:
        _invalid("date binding value must use ISO-8601.", reason=type(error).__name__)
    return [date]


def _table_value(value: dict[str, Any]) -> list[list[str]]:
    _exact(value, {"rows", "type"})
    rows = value.get("rows")
    if type(rows) is not list or not rows or len(rows) > 256:
        _invalid("table-data rows must be a non-empty bounded array.")
    parsed: list[list[str]] = []
    width = None
    for row in rows:
        if type(row) is not list or not row or len(row) > 64:
            _invalid("Each table-data row must be a non-empty bounded array.")
        converted = ["" if item is None else _text(str(item), "value.rows") for item in row]
        width = len(converted) if width is None else width
        if len(converted) != width:
            _invalid("table-data rows must be rectangular.")
        parsed.append(converted)
    return parsed


def _image_edit(
    value: dict[str, Any],
    slide: int,
    object_id: str,
    expected_hash: str,
) -> dict[str, Any]:
    _exact(value, {"alt_text", "content_type", "fit", "path", "type"})
    return {
        "type": "image_replace",
        "slide": slide,
        "selector": {"name": object_id, "type": "image"},
        "precondition_sha256": expected_hash,
        "object": {
            "alt_text": _text(value.get("alt_text"), "value.alt_text"),
            "content_type": _text(value.get("content_type"), "value.content_type"),
            "fit": _text(value.get("fit", "contain"), "value.fit"),
            "name": object_id,
            "path": _text(value.get("path"), "value.path"),
        },
    }


def _chart_edit(
    value: dict[str, Any],
    slide: int,
    object_id: str,
    expected_hash: str,
    *,
    frame: dict[str, int],
    z_order: int,
) -> dict[str, Any]:
    _exact(value, {"chart", "type"})
    chart = value.get("chart")
    if type(chart) is not dict:
        _invalid("chart-data value requires a chart object.")
    return {
        "type": "chart_update",
        "slide": slide,
        "selector": {"name": object_id, "type": "chart"},
        "precondition_sha256": expected_hash,
        "object": {
            **chart,
            "frame": frame,
            "name": object_id,
            "z_order": z_order,
        },
    }


def _replace_text_preserving_style(element: Element, paragraphs: list[str]) -> None:
    body = next(
        (
            node
            for node in element.iter()
            if node.tag in {A("txBody"), f"{{{_P}}}txBody"}
        ),
        None,
    )
    if body is None:
        _invalid("Selected semantic object has no editable text body.")
    existing = body.findall(A("p"))
    if existing:
        prototype = existing[0]
    else:
        prototype = Element(A("p"))
        SubElement(SubElement(prototype, A("r")), A("t"))
    for paragraph in existing:
        body.remove(paragraph)
    for text in paragraphs:
        paragraph = deepcopy(prototype)
        nodes = list(paragraph.iter(A("t")))
        if not nodes:
            nodes = [SubElement(SubElement(paragraph, A("r")), A("t"))]
        nodes[0].text = text
        for node in nodes[1:]:
            node.text = ""
        body.append(paragraph)


def _replace_table_text(element: Element, rows: list[list[str]]) -> None:
    table = next((node for node in element.iter() if node.tag == A("tbl")), None)
    if table is None:
        _invalid("Selected semantic object is not an editable native table.")
    table_rows = table.findall(A("tr"))
    if len(table_rows) != len(rows) or any(
        len(row.findall(A("tc"))) != len(values)
        for row, values in zip(table_rows, rows, strict=True)
    ):
        _invalid("table-data dimensions must match the template table.")
    for row, values in zip(table_rows, rows, strict=True):
        for cell, text in zip(row.findall(A("tc")), values, strict=True):
            _replace_text_preserving_style(cell, [text])


def _assign_output_object_ids(
    target: MutablePptxPackage,
    position: int,
    output_slide_id: str,
    descriptor: TemplateDescriptor,
) -> list[dict[str, Any]]:
    slide_part = map_slides(target)[position - 1]["part"]
    root = target.xml(slide_part)
    common = root.find(f"{{{_P}}}cSld")
    if common is None:
        _invalid("Copied template slide has no common slide data.")
    common.set("name", output_slide_id)
    slot_by_object = {
        item["sourceObjectId"]: item["slotId"]
        for item in descriptor.semantic_slots["slots"]
    }
    mapping = []
    output_ids: set[str] = set()
    for element in root.iter():
        if element.tag != f"{{{_P}}}cNvPr":
            continue
        source_id = element.attrib.get("name", "")
        if not source_id.startswith("object_"):
            continue
        slot_id = slot_by_object.get(source_id)
        semantic_key = source_id if slot_id is None else slot_id
        output_id = PresentationContractConsumer.stable_object_id(
            slide_id=output_slide_id,
            semantic_key=semantic_key,
        )
        if output_id in output_ids:
            _invalid(
                "Template output object addresses would collide.",
                output_object_id=output_id,
            )
        output_ids.add(output_id)
        element.set("name", output_id)
        mapping.append({"output_object_id": output_id, "source_object_id": source_id})
    target.set_part(slide_part, _xml_bytes(root))
    return mapping


def _refresh_receipt_hashes(
    target: MutablePptxPackage,
    position: int,
    receipts: list[dict[str, Any]],
    object_mapping: list[dict[str, Any]],
) -> None:
    """Bind receipts to the final object identity written to the candidate."""

    slide_part = map_slides(target)[position - 1]["part"]
    if slide_part is None:
        _invalid("Copied template slide part is missing.")
    root = target.xml(slide_part)
    output_by_source = {
        item["source_object_id"]: item["output_object_id"]
        for item in object_mapping
    }
    for receipt in receipts:
        output_id = output_by_source.get(receipt["source_object_id"])
        if output_id is None:
            _invalid(
                "Bound template object is absent from the output mapping.",
                source_object_id=receipt["source_object_id"],
            )
        element = select_object(
            root,
            {"id": None, "name": output_id, "type": None},
        )
        receipt["after_sha256"] = object_hash(element)


def _text(value: Any, field: str) -> str:
    if type(value) is not str:
        _invalid("Template binding text must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Template binding text exceeds the byte limit.", field=field)
    return value


def _exact(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Template binding value contains unknown fields.", unknown=unknown)


def _xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _resource_limit(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.RESOURCE_LIMIT,
        message,
        status="failed",
        details=details,
    )
