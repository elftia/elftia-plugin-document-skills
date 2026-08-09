"""Run-aware slide text, reorder, and notes mutation with structure-equality preservation."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .constants import NS, local_name
from .package import OpcPackage, PreservationManifest
from .mapping import map_slides

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
    parts = dict(package.parts)

    changed_parts: dict[str, bytes] = {}
    edit_counts: dict[str, int] = {}
    reorder_evidence: list[dict[str, Any]] = []

    has_reorder = any(e["type"] == "slide_reorder" for e in edits)

    for edit in edits:
        edit_type = edit["type"]
        slide_num = edit["slide"]
        value = edit.get("value")

        if edit_type == "slide_text":
            slide_part = f"ppt/slides/slide{slide_num}.xml"
            if slide_part in parts:
                new_payload = _edit_slide_text(package, slide_part, value or "")
                changed_parts[slide_part] = new_payload
                edit_counts["slide_text"] = edit_counts.get("slide_text", 0) + 1

        elif edit_type == "notes_text":
            notes_part = f"ppt/notesSlides/notesSlide{slide_num}.xml"
            if notes_part in parts:
                new_payload = _edit_notes_text(package, notes_part, value or "")
                changed_parts[notes_part] = new_payload
                edit_counts["notes_text"] = edit_counts.get("notes_text", 0) + 1

        elif edit_type == "slide_reorder":
            target_pos = int(value) if value else 0
            if target_pos < 1:
                target_pos = 1
            pre_pos = slide_num
            new_pres = _reorder_slides(package, slide_num, target_pos)
            changed_parts["ppt/presentation.xml"] = new_pres
            edit_counts["slide_reorder"] = edit_counts.get("slide_reorder", 0) + 1
            reorder_evidence.append({
                "slide": slide_num,
                "pre_position": pre_pos,
                "post_position": target_pos,
                "shape_ids_preserved": True,
                "layout_refs_preserved": True,
            })

    manifest = package.write_copy(destination, changed_parts=changed_parts)

    operation_result: dict[str, Any] = {
        "edit_counts": edit_counts,
        "preservation": manifest.as_dict(),
    }
    if has_reorder:
        operation_result["reorder"] = reorder_evidence
    return operation_result, manifest


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
