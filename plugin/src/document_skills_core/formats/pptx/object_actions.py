"""Speaker notes and contained click actions for PPTX object edits."""

from hashlib import sha256
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .create import _build_notes_slide
from .mapping import map_slides
from .mutation import MutablePptxPackage
from .object_parts import add_part_relationship, remove_relationship
from .object_xml import A, R, non_visual_properties
from .slide_graph import _allocate_part_name, _ensure_notes_master, _rewrite_content_types

_A = NS["a"]


def edit_hyperlink(
    target: MutablePptxPackage,
    slide_part: str,
    element: Element,
    edit: dict[str, Any],
) -> None:
    properties = non_visual_properties(element)
    current = properties.find(A("hlinkClick"))
    _require_link_state(current, edit["type"])
    if current is not None:
        relationship_id = current.attrib.get(R("id"))
        properties.remove(current)
        if relationship_id:
            remove_relationship(target, slide_part, relationship_id)
    if edit["type"] == "hyperlink_remove":
        return
    target_slide_part = _slide_part(target, edit["target_slide"])
    relationship_id = add_part_relationship(
        target,
        slide_part,
        target_slide_part,
        "slide",
        "rIdHyperlink",
    )
    SubElement(properties, A("hlinkClick"), {
        R("id"): relationship_id,
        "action": "ppaction://hlinksldjump",
    })


def edit_action(
    target: MutablePptxPackage,
    slide_part: str,
    element: Element,
    edit: dict[str, Any],
) -> None:
    properties = non_visual_properties(element)
    current = properties.find(A("hlinkClick"))
    _require_link_state(current, edit["type"])
    if current is not None:
        relationship_id = current.attrib.get(R("id"))
        properties.remove(current)
        if relationship_id:
            remove_relationship(target, slide_part, relationship_id)
    if edit["type"] == "action_remove":
        return
    jumps = {
        "first": "firstslide",
        "last": "lastslide",
        "next": "nextslide",
        "previous": "previousslide",
    }
    SubElement(properties, A("hlinkClick"), {
        "action": f"ppaction://hlinkshowjump?jump={jumps[edit['action']]}",
    })


def update_notes(
    target: MutablePptxPackage,
    slide_part: str,
    edit: dict[str, Any],
) -> dict[str, Any]:
    notes_part = next(
        (
            relationship.resolved_target
            for relationship in target.part_rels(slide_part)
            if relationship.relationship_type.endswith("/notesSlide")
        ),
        None,
    )
    added_parts: list[str] = []
    if notes_part is None:
        additions: dict[str, str] = {}
        notes_master = _ensure_notes_master(target, additions, added_parts)
        notes_part = _allocate_part_name(
            "ppt/notesSlides/notesSlide1.xml",
            set(target.parts),
        )
        target.set_part(notes_part, _build_notes_slide(edit["slide"], edit["value"]))
        additions[notes_part] = (
            "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
        )
        added_parts.append(notes_part)
        add_part_relationship(
            target,
            slide_part,
            notes_part,
            "notesSlide",
            "rIdNotes",
        )
        add_part_relationship(
            target,
            notes_part,
            slide_part,
            "slide",
            "rIdSlide",
        )
        add_part_relationship(
            target,
            notes_part,
            notes_master,
            "notesMaster",
            "rIdNotesMaster",
        )
        _rewrite_content_types(target, removed=set(), additions=additions)
    else:
        root = target.xml(notes_part)
        body = next(iter(root.iter(f"{{{_A}}}txBody")), None)
        if body is None:
            _invalid("Speaker notes have no editable text body.")
        for paragraph in list(body.findall(f"{{{_A}}}p")):
            body.remove(paragraph)
        paragraph = SubElement(body, f"{{{_A}}}p")
        run = SubElement(paragraph, f"{{{_A}}}r")
        text = SubElement(run, f"{{{_A}}}t")
        text.text = edit["value"]
        target.set_part(notes_part, _xml_bytes(root))
    return {
        "added_parts": sorted(added_parts),
        "after_sha256": sha256(target.parts[notes_part]).hexdigest(),
        "notes_part": notes_part,
        "slide": edit["slide"],
        "slide_part": slide_part,
        "type": edit["type"],
    }


def _require_link_state(current: Element | None, edit_type: str) -> None:
    if edit_type.endswith("_add") and current is not None:
        _invalid("Selected object already has a click action.")
    if (edit_type.endswith("_update") or edit_type.endswith("_remove")) and current is None:
        _invalid("Selected object has no click action to update or remove.")
    if current is None or edit_type.endswith("_add"):
        return
    current_kind = "hyperlink" if current.attrib.get(R("id")) else "action"
    expected_kind = "hyperlink" if edit_type.startswith("hyperlink_") else "action"
    if current_kind != expected_kind:
        _invalid(
            "Selected click action type does not match the edit primitive.",
            actual=current_kind,
            expected=expected_kind,
        )


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


def _xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
