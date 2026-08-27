"""Closed planning, OOXML emission, and projection for stable references."""

from hashlib import sha256
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .contracts import _invalid
from .mapping import Story, iter_paragraphs
from .semantic_nodes import semantic_node_for
from .xml_utils import set_text

_TARGET_TAG_PREFIX = "elftia.reference-target/1:"
_REFERENCE_TARGET_TYPES = frozenset({"equation", "figure", "heading", "table"})
_REF_INSTRUCTION = re.compile(r"^REF ([A-Za-z_][A-Za-z0-9_]{0,39}) \\h$")


def plan_document_references(nodes: list[dict[str, Any]]) -> None:
    by_id = {node["node_id"]: node for node in nodes}
    caption_hosts = {
        node["target_id"]: node
        for node in nodes
        if node.get("node_type")
        in {"equation_caption", "figure_caption", "table_caption"}
    }
    requested_targets: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.get("node_type") != "reference":
            continue
        target_id = node["target_id"]
        target = by_id.get(target_id)
        if target is None or target.get("node_type") not in _REFERENCE_TARGET_TYPES:
            _invalid(
                "Reference target is missing or has the wrong semantic type.",
                reference=node["node_id"],
                target=target_id,
            )
        target_type = target["node_type"]
        bookmark = requested_targets.get(target_id)
        if bookmark is None:
            bookmark = {
                "name": bookmark_name(target_id),
                "target_id": target_id,
                "target_type": target_type,
            }
            requested_targets[target_id] = bookmark
            host = caption_hosts.get(target_id, target)
            host["bookmark"] = bookmark
        node["reference"] = {
            "bookmark": bookmark["name"],
            "target_id": target_id,
            "display_text": node["text"],
        }


def bookmark_name(node_id: str) -> str:
    return f"_Elftia_{sha256(node_id.encode('ascii')).hexdigest()[:16]}"


def attach_reference_bookmark(
    container: Element,
    bookmark: dict[str, str],
    *,
    bookmark_id: int,
) -> None:
    paragraph = (
        container
        if container.tag == qn("w", "p")
        else next(container.iter(qn("w", "p")), None)
    )
    if paragraph is None:
        raise ValueError("A reference target must contain a paragraph.")
    start = Element(
        qn("w", "bookmarkStart"),
        {
            qn("w", "id"): str(bookmark_id),
            qn("w", "name"): bookmark["name"],
        },
    )
    end = Element(qn("w", "bookmarkEnd"), {qn("w", "id"): str(bookmark_id)})
    marker = _reference_target_marker(
        bookmark["target_id"],
        bookmark["target_type"],
        marker_id=bookmark_id,
    )
    position = 1 if paragraph.find(qn("w", "pPr")) is not None else 0
    paragraph.insert(position, start)
    paragraph.insert(position + 1, marker)
    paragraph.append(end)


def reference_paragraph(block: dict[str, Any]) -> Element:
    paragraph = Element(qn("w", "p"))
    if block.get("style"):
        properties = SubElement(paragraph, qn("w", "pPr"))
        SubElement(properties, qn("w", "pStyle"), {qn("w", "val"): block["style"]})
    field = SubElement(
        paragraph,
        qn("w", "fldSimple"),
        {
            qn("w", "instr"): f"REF {block['reference']['bookmark']} \\h",
            qn("w", "dirty"): "1",
        },
    )
    run = SubElement(field, qn("w", "r"))
    text = SubElement(run, qn("w", "t"))
    set_text(text, block["reference"]["display_text"])
    return paragraph


def project_references(body: Story) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for paragraph in iter_paragraphs(body.root):
        target = _reference_target_for(paragraph)
        for start in paragraph.iter(qn("w", "bookmarkStart")):
            name = start.attrib.get(qn("w", "name"))
            if target is not None and name is not None:
                targets.append(
                    {
                        "node_id": target["node_id"],
                        "node_type": target["node_type"],
                        "bookmark": name,
                    }
                )
        semantic = semantic_node_for(
            paragraph,
            allowed_types=frozenset({"reference"}),
        )
        for field in paragraph.iter(qn("w", "fldSimple")):
            instruction = " ".join(field.attrib.get(qn("w", "instr"), "").split())
            match = _REF_INSTRUCTION.fullmatch(instruction)
            if semantic is None or match is None:
                continue
            bindings.append(
                {
                    "node_id": semantic.node_id,
                    "target_bookmark": match.group(1),
                    "display_text": "".join(
                        text.text or "" for text in field.iter(qn("w", "t"))
                    ),
                    "update_required": field.attrib.get(qn("w", "dirty"))
                    in {"1", "true"},
                }
            )
    target_names = {target["bookmark"] for target in targets}
    valid = all(binding["target_bookmark"] in target_names for binding in bindings)
    pending = bool(bindings) and all(binding["update_required"] for binding in bindings)
    return {
        "status": (
            "update_required"
            if valid and pending
            else "pass" if valid else "fail"
        ),
        "targets": targets,
        "bindings": bindings,
    }


def expected_reference_projection(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    targets = []
    seen: set[str] = set()
    bindings = []
    for node in nodes:
        bookmark = node.get("bookmark")
        if bookmark is not None and bookmark["name"] not in seen:
            seen.add(bookmark["name"])
            targets.append(
                {
                    "node_id": bookmark["target_id"],
                    "node_type": bookmark["target_type"],
                    "bookmark": bookmark["name"],
                }
            )
        reference = node.get("reference")
        if reference is not None:
            bindings.append(
                {
                    "node_id": node["node_id"],
                    "target_bookmark": reference["bookmark"],
                    "display_text": reference["display_text"],
                    "update_required": True,
                }
            )
    return {
        "status": "update_required" if bindings else "pass",
        "targets": targets,
        "bindings": bindings,
    }


def _reference_target_marker(
    node_id: str,
    node_type: str,
    *,
    marker_id: int,
) -> Element:
    marker = Element(qn("w", "sdt"))
    properties = SubElement(marker, qn("w", "sdtPr"))
    SubElement(properties, qn("w", "id"), {qn("w", "val"): str(marker_id)})
    SubElement(
        properties,
        qn("w", "tag"),
        {qn("w", "val"): f"{_TARGET_TAG_PREFIX}{node_type}:{node_id}"},
    )
    SubElement(properties, qn("w", "lock"), {qn("w", "val"): "sdtLocked"})
    content = SubElement(marker, qn("w", "sdtContent"))
    SubElement(content, qn("w", "r"))
    return marker


def _reference_target_for(container: Element) -> dict[str, str] | None:
    for marker in container.iter(qn("w", "sdt")):
        properties = marker.find(qn("w", "sdtPr"))
        tag = properties.find(qn("w", "tag")) if properties is not None else None
        value = tag.attrib.get(qn("w", "val"), "") if tag is not None else ""
        if not value.startswith(_TARGET_TAG_PREFIX):
            continue
        node_type, separator, node_id = value[len(_TARGET_TAG_PREFIX) :].partition(":")
        if separator and node_type in _REFERENCE_TARGET_TYPES and node_id:
            return {"node_id": node_id, "node_type": node_type}
    return None
