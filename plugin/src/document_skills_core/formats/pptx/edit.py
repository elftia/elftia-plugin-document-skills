"""Run-aware slide text, reorder, and notes mutation with structure-equality preservation."""

import hashlib
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, local_name
from .image import MAX_TOTAL_IMAGE_BYTES
from .mapping import map_slides
from .mutation import MutablePptxPackage
from .object_contracts import OBJECT_EDIT_TYPES
from .object_edit import apply_object_edit
from .object_xml import object_hash, select_object
from .package import OpcPackage, PreservationManifest
from .slide_graph import add_slide, copy_slide, delete_slide

_P = NS["p"]
_A = NS["a"]
_R = NS["r"]

def _pt(t): return f"{{{_P}}}{t}"
def _at(t): return f"{{{_A}}}{t}"


def edit_pptx(
    source: str | Path,
    destination: str | Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], PreservationManifest]:
    """Apply edits to a PPTX deck with run-aware style preservation.

    Returns (operation_result, manifest).
    """
    package = OpcPackage.open(source)
    edits = arguments.get("edits", [])
    _validate_preconditions(package, edits)
    target = MutablePptxPackage(package)
    edit_counts: dict[str, int] = {}
    reorder_evidence: list[dict[str, Any]] = []
    lifecycle_evidence: list[dict[str, Any]] = []
    object_evidence: list[dict[str, Any]] = []
    added_image_bytes = 0

    has_reorder = any(e["type"] in {"slide_move", "slide_reorder"} for e in edits)

    for edit in edits:
        edit_type = edit["type"]
        slide_num = edit.get("slide", 1)
        value = edit.get("value")

        if edit_type == "slide_add":
            evidence = add_slide(target, edit["slide"], edit.get("position"))
            lifecycle_evidence.append({"type": edit_type, **evidence})
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1

        elif edit_type == "slide_text":
            slide_part = _slide_part(target, slide_num)
            new_payload = _edit_slide_text(target, slide_part, value or "")
            target.set_part(slide_part, new_payload)
            edit_counts["slide_text"] = edit_counts.get("slide_text", 0) + 1

        elif edit_type == "notes_text":
            notes_part = _notes_part(target, slide_num)
            new_payload = _edit_notes_text(target, notes_part, value or "")
            target.set_part(notes_part, new_payload)
            edit_counts["notes_text"] = edit_counts.get("notes_text", 0) + 1

        elif edit_type in {"slide_move", "slide_reorder"}:
            target_pos = edit.get("position", value)
            if type(target_pos) is str and target_pos.isdigit():
                target_pos = int(target_pos)
            if type(target_pos) is not int:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "Slide reorder requires a numeric target position.",
                    status="invalid_request",
                )
            pre_pos = slide_num
            new_pres = _reorder_slides(target, slide_num, target_pos)
            target.set_part("ppt/presentation.xml", new_pres)
            edit_counts["slide_reorder"] = edit_counts.get("slide_reorder", 0) + 1
            reorder_evidence.append({
                "slide": slide_num,
                "pre_position": pre_pos,
                "post_position": target_pos,
                "shape_ids_preserved": True,
                "layout_refs_preserved": True,
            })

        elif edit_type == "slide_delete":
            evidence = delete_slide(target, slide_num)
            lifecycle_evidence.append({"type": edit_type, **evidence})
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1

        elif edit_type in {"slide_duplicate", "slide_copy"}:
            source_package: Any = target
            source_position = slide_num if edit_type == "slide_duplicate" else edit["source_slide"]
            cross_deck = False
            source_path = edit.get("source")
            if source_path is not None and Path(source_path).resolve() != package.path:
                source_package = OpcPackage.open(source_path)
                cross_deck = True
            copied = copy_slide(
                target,
                source_package,
                source_position,
                edit.get("position"),
                cross_deck=cross_deck,
            )
            lifecycle_evidence.append({"type": edit_type, **copied.as_dict()})
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1

        elif edit_type in OBJECT_EDIT_TYPES:
            evidence = apply_object_edit(target, edit)
            image = evidence.get("image")
            if image is not None:
                added_image_bytes += int(image.get("bytes", 0))
                if added_image_bytes > MAX_TOTAL_IMAGE_BYTES:
                    raise DocumentSkillsError(
                        ErrorCode.REQUEST_INVALID,
                        "The presentation edit images exceed the aggregate byte limit.",
                        status="invalid_request",
                        details={"ceiling": MAX_TOTAL_IMAGE_BYTES},
                    )
            object_evidence.append(evidence)
            edit_counts[edit_type] = edit_counts.get(edit_type, 0) + 1

    manifest = target.emit(destination)

    operation_result: dict[str, Any] = {
        "edit_counts": edit_counts,
        "preservation": manifest.as_dict(),
    }
    if has_reorder:
        operation_result["reorder"] = reorder_evidence
    if lifecycle_evidence:
        operation_result["slide_lifecycle"] = lifecycle_evidence
    if object_evidence:
        operation_result["object_edits"] = object_evidence
    return operation_result, manifest


def _validate_preconditions(package: OpcPackage, edits: list[dict[str, Any]]) -> None:
    for edit in edits:
        expected = edit.get("precondition_sha256")
        if expected is None:
            continue
        precondition_package = package
        precondition_slides = map_slides(package)
        position = edit.get("slide", edit.get("source_slide", 1))
        if edit["type"] == "slide_copy" and edit.get("source") is not None:
            source_path = Path(edit["source"]).resolve()
            if source_path != package.path:
                precondition_package = OpcPackage.open(source_path)
                precondition_slides = map_slides(precondition_package)
                position = edit["source_slide"]
        if position < 1 or position > len(precondition_slides):
            _invalid_slide(position, len(precondition_slides))
        slide_part = precondition_slides[position - 1]["part"]
        if slide_part is None:
            _invalid_slide(position, len(precondition_slides))
        selector = edit.get("selector")
        if selector is None:
            actual = hashlib.sha256(precondition_package.parts[slide_part]).hexdigest()
            scope = "slide"
        else:
            selected = select_object(precondition_package.xml(slide_part), selector)
            actual = object_hash(selected)
            scope = "object"
        if actual != expected:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                f"PPTX edit precondition hash did not match the selected {scope}.",
                status="failed",
                details={
                    "actual": actual,
                    "expected": expected,
                    "scope": scope,
                    "selector": selector,
                    "slide": position,
                },
            )


def _slide_part(package: Any, position: int) -> str:
    slides = map_slides(package)
    if position < 1 or position > len(slides) or slides[position - 1]["part"] is None:
        _invalid_slide(position, len(slides))
    return slides[position - 1]["part"]


def _notes_part(package: Any, position: int) -> str:
    slide_part = _slide_part(package, position)
    notes = next(
        (
            relationship.resolved_target
            for relationship in package.part_rels(slide_part)
            if relationship.relationship_type.endswith("/notesSlide")
        ),
        None,
    )
    if notes is None:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "The selected slide has no speaker notes part.",
            status="invalid_request",
            details={"slide": position},
        )
    return notes


def _invalid_slide(position: int, count: int) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "Slide position is outside the current deck.",
        status="invalid_request",
        details={"position": position, "slides": count},
    )


def _edit_slide_text(
    package: OpcPackage,
    slide_part: str,
    new_text: str,
) -> bytes:
    """Edit text in a slide, preserving run formatting where possible."""
    root = package.xml(slide_part)
    cSld = root.find(_pt("cSld"))
    if cSld is None:
        return package.parts[slide_part]
    sp_tree = cSld.find(_pt("spTree"))
    if sp_tree is None:
        return package.parts[slide_part]

    edited = False
    for sp in sp_tree.iter(_pt("sp")):
        tx_body = sp.find(_pt("txBody"))
        if tx_body is None:
            tx_body = sp.find(_at("txBody"))
        if tx_body is None:
            continue
        p = tx_body.find(_at("p"))
        if p is None:
            continue
        r = p.find(_at("r"))
        if r is not None:
            r_pr = r.find(_at("rPr"))
            r_pr_attribs = dict(r_pr.attrib) if r_pr is not None else {}
            for child in list(p):
                p.remove(child)
            new_r = SubElement(p, _at("r"))
            if r_pr_attribs:
                new_r_pr = SubElement(new_r, _at("rPr"), attrib=r_pr_attribs)
            t = SubElement(new_r, _at("t"))
            t.text = new_text
            edited = True
            break

    if not edited:
        return package.parts[slide_part]
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _edit_notes_text(
    package: OpcPackage,
    notes_part: str,
    new_text: str,
) -> bytes:
    """Edit notes text, preserving run formatting where possible."""
    root = package.xml(notes_part)
    cSld = root.find(_pt("cSld"))
    if cSld is None:
        return package.parts[notes_part]
    sp_tree = cSld.find(_pt("spTree"))
    if sp_tree is None:
        return package.parts[notes_part]

    for sp in sp_tree.iter(_pt("sp")):
        tx_body = sp.find(_pt("txBody"))
        if tx_body is None:
            continue
        p = tx_body.find(_at("p"))
        if p is None:
            continue
        r = p.find(_at("r"))
        r_pr_attribs = {}
        if r is not None:
            r_pr = r.find(_at("rPr"))
            if r_pr is not None:
                r_pr_attribs = dict(r_pr.attrib)
        for child in list(p):
            p.remove(child)
        new_r = SubElement(p, _at("r"))
        if r_pr_attribs:
            SubElement(new_r, _at("rPr"), attrib=r_pr_attribs)
        t = SubElement(new_r, _at("t"))
        t.text = new_text
        break

    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _reorder_slides(
    package: OpcPackage,
    from_pos: int,
    to_pos: int,
) -> bytes:
    """Reorder slides in presentation.xml without touching slide payloads.

    This edits ONLY ppt/presentation.xml (sldIdLst order). It does NOT
    rewrite shape IDs, relationship IDs, slide layouts, slide masters,
    notes slides, themes, media, charts, or tables.
    """
    root = package.xml("ppt/presentation.xml")
    sld_id_lst = root.find(_pt("sldIdLst"))
    if sld_id_lst is None:
        return package.parts["ppt/presentation.xml"]

    sld_ids = list(sld_id_lst.findall(_pt("sldId")))
    if from_pos < 1 or from_pos > len(sld_ids):
        return package.parts["ppt/presentation.xml"]
    if to_pos < 1 or to_pos > len(sld_ids):
        return package.parts["ppt/presentation.xml"]
    if from_pos == to_pos:
        return package.parts["ppt/presentation.xml"]

    moved = sld_ids[from_pos - 1]
    sld_id_lst.remove(moved)
    if to_pos >= len(sld_ids):
        sld_id_lst.append(moved)
    else:
        ref = sld_ids[to_pos - 1] if to_pos - 1 < len(sld_ids) else None
        if to_pos > from_pos and ref is not None:
            idx = list(sld_id_lst).index(ref)
            if idx + 1 < len(sld_id_lst):
                sld_id_lst.insert(idx + 1, moved)
            else:
                sld_id_lst.append(moved)
        else:
            sld_id_lst.insert(to_pos - 1, moved)

    return tostring(root, encoding="UTF-8", xml_declaration=True)
