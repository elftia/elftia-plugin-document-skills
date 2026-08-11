"""Styled PPTX deck construction from bounded typed data."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import NS
from .package import write_deterministic_zip
from .scaffold import (
    _CLR_MAP,
    _build_app_props,
    _build_core_props,
    _build_root_rels,
    _build_slide_layout,
    _build_slide_layout_rels,
    _build_slide_master,
    _build_slide_master_rels,
    _build_theme,
    _to_xml_bytes,
)

_P_NS = NS["p"]
_A_NS = NS["a"]
_R_NS = NS["r"]
_C_NS = NS["c"]
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Minimal valid 1x1 PNG (67 bytes)
_PLACEHOLDER_PNG = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
    0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, 0x00, 0x00, 0x00,
    0x0C, 0x49, 0x44, 0x41, 0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
    0x00, 0x00, 0x03, 0x00, 0x01, 0x5D, 0xCC, 0xDB, 0x22, 0x41, 0x00, 0x00,
    0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
])


def create_pptx(destination: Path, deck: dict[str, Any]) -> dict[str, Any]:
    """Create a styled PPTX deck from the parsed deck model."""
    metadata = deck.get("metadata", {})
    slides_data = deck.get("slides", [])
    slide_size = deck.get("slide_size") or {"cx": "9144000", "cy": "6858000", "type": "screen4x3"}

    parts: dict[str, bytes] = {}
    has_chart = any(s.get("chart_reference") for s in slides_data)
    has_image = any(s.get("image_reference") for s in slides_data)
    has_table = any(s.get("table") for s in slides_data)
    has_notes = any(s.get("notes") for s in slides_data)
    layout_count = 2

    parts["[Content_Types].xml"] = _build_content_types(
        len(slides_data), has_chart, has_image, has_table, has_notes, layout_count
    )
    parts["_rels/.rels"] = _build_root_rels()
    parts["ppt/_rels/presentation.xml.rels"] = _build_presentation_rels(
        slides_data, layout_count, has_notes
    )
    parts["ppt/presentation.xml"] = _build_presentation(slides_data, slide_size, has_notes)
    parts["ppt/theme/theme1.xml"] = _build_theme()
    parts["ppt/slideMasters/slideMaster1.xml"] = _build_slide_master(
        layout_count, int(slide_size.get("cx", "9144000")), int(slide_size.get("cy", "6858000"))
    )
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _build_slide_master_rels(layout_count)
    for layout_idx in range(1, layout_count + 1):
        parts[f"ppt/slideLayouts/slideLayout{layout_idx}.xml"] = _build_slide_layout(
            layout_idx, int(slide_size.get("cx", "9144000")), int(slide_size.get("cy", "6858000"))
        )
        parts[f"ppt/slideLayouts/_rels/slideLayout{layout_idx}.xml.rels"] = _build_slide_layout_rels(layout_idx)
    for idx, slide in enumerate(slides_data):
        slide_num = idx + 1
        parts[f"ppt/slides/slide{slide_num}.xml"] = _build_slide(slide, slide_num)
        parts[f"ppt/slides/_rels/slide{slide_num}.xml.rels"] = _build_slide_rels(slide, slide_num, layout_count)
    if has_notes:
        parts["ppt/notesMasters/notesMaster1.xml"] = _build_notes_master()
        parts["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = _build_notes_master_rels()
        for idx, slide in enumerate(slides_data):
            slide_num = idx + 1
            if slide.get("notes"):
                parts[f"ppt/notesSlides/notesSlide{slide_num}.xml"] = _build_notes_slide(slide_num, slide["notes"])
                parts[f"ppt/notesSlides/_rels/notesSlide{slide_num}.xml.rels"] = _build_notes_slide_rels(slide_num)
    if has_chart:
        chart_slide = next((s for s in slides_data if s.get("chart_reference")), {})
        parts["ppt/charts/chart1.xml"] = _build_chart_reference(
            chart_slide.get("chart_reference") or {}
        )
    if has_image:
        parts["ppt/media/image1.png"] = _PLACEHOLDER_PNG

    parts["docProps/core.xml"] = _build_core_props(metadata)
    parts["docProps/app.xml"] = _build_app_props(slides_data)

    write_deterministic_zip(destination, parts)

    return {
        "slides": len(slides_data),
        "layouts": layout_count,
        "has_chart": has_chart,
        "has_image": has_image,
        "has_table": has_table,
        "has_notes": has_notes,
        "metadata": metadata,
        "slide_size": slide_size,
    }


def _build_content_types(
    slide_count: int, has_chart: bool, has_image: bool, has_table: bool, has_notes: bool, layout_count: int
) -> bytes:
    root = Element(f"{{{_CONTENT_TYPES_NS}}}Types")
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
        "Extension": "rels",
        "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
        "Extension": "xml",
        "ContentType": "application/xml",
    })
    if has_image:
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
            "Extension": "png",
            "ContentType": "image/png",
        })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/ppt/presentation.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/ppt/slideMasters/slideMaster1.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
    })
    for i in range(1, layout_count + 1):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/ppt/slideLayouts/slideLayout{i}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
        })
    for i in range(1, slide_count + 1):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/ppt/slides/slide{i}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
        })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/ppt/theme/theme1.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.theme+xml",
    })
    if has_notes:
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": "/ppt/notesMasters/notesMaster1.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml",
        })
        for i in range(1, slide_count + 1):
            SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
                "PartName": f"/ppt/notesSlides/notesSlide{i}.xml",
                "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml",
            })
    if has_chart:
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": "/ppt/charts/chart1.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/docProps/core.xml",
        "ContentType": "application/vnd.openxmlformats-package.core-properties+xml",
    })
    SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
        "PartName": "/docProps/app.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    })
    return _to_xml_bytes(root)


def _build_presentation_rels(slides: list[dict[str, Any]], layout_count: int, has_notes: bool) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
        "Target": "slideMasters/slideMaster1.xml",
    })
    for idx in range(len(slides)):
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": f"rIdSlide{idx + 1}",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            "Target": f"slides/slide{idx + 1}.xml",
        })
    if has_notes:
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": f"rIdNotes",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
            "Target": "notesMasters/notesMaster1.xml",
        })
    return _to_xml_bytes(root)


def _build_presentation(slides: list[dict[str, Any]], slide_size: dict[str, str], has_notes: bool) -> bytes:
    root = Element(f"{{{_P_NS}}}presentation", attrib={
        "saveSubsetFonts": "1",
    })
    master_id_lst = SubElement(root, f"{{{_P_NS}}}sldMasterIdLst")
    SubElement(master_id_lst, f"{{{_P_NS}}}sldMasterId", attrib={
        f"{{{_R_NS}}}id": "rId1",
        "id": "2147483648",
    })
    if has_notes:
        notes_id_lst = SubElement(root, f"{{{_P_NS}}}notesMasterIdLst")
        SubElement(notes_id_lst, f"{{{_P_NS}}}notesMasterId", attrib={
            f"{{{_R_NS}}}id": "rIdNotes",
        })
    sld_id_lst = SubElement(root, f"{{{_P_NS}}}sldIdLst")
    for idx in range(len(slides)):
        SubElement(sld_id_lst, f"{{{_P_NS}}}sldId", attrib={
            "id": str(256 + idx),
            f"{{{_R_NS}}}id": f"rIdSlide{idx + 1}",
        })
    SubElement(root, f"{{{_P_NS}}}sldSz", attrib={
        "cx": slide_size.get("cx", "9144000"),
        "cy": slide_size.get("cy", "6858000"),
        "type": slide_size.get("type", "screen4x3"),
    })
    SubElement(root, f"{{{_P_NS}}}notesSz", attrib={
        "cx": "6858000",
        "cy": "9144000",
    })
    return _to_xml_bytes(root)



def _build_slide(slide: dict[str, Any], slide_num: int) -> bytes:
    root = Element(f"{{{_P_NS}}}sld")
    cSld = SubElement(root, f"{{{_P_NS}}}cSld")
    sp_tree = SubElement(cSld, f"{{{_P_NS}}}spTree")
    _nv_grp_sp_pr(sp_tree)
    _grp_sp_pr(sp_tree)

    shape_id = 2
    title = slide.get("title")
    if title:
        _build_title_shape(sp_tree, shape_id, title)
        shape_id += 1
    for shape in slide.get("shapes", []):
        sp = SubElement(sp_tree, f"{{{_P_NS}}}sp")
        nv_sp_pr = SubElement(sp, f"{{{_P_NS}}}nvSpPr")
        SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvPr", attrib={
            "id": str(shape_id),
            "name": f"Shape{shape_id}",
        })
        SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvSpPr")
        SubElement(nv_sp_pr, f"{{{_P_NS}}}nvPr")
        _shape_sp_pr(sp)
        tx_body = SubElement(sp, f"{{{_P_NS}}}txBody")
        SubElement(tx_body, f"{{{_A_NS}}}bodyPr")
        SubElement(tx_body, f"{{{_A_NS}}}lstStyle")
        for run in shape.get("runs", []):
            p = SubElement(tx_body, f"{{{_A_NS}}}p")
            r = SubElement(p, f"{{{_A_NS}}}r")
            run_text = run.get("text") or ""
            r_pr = SubElement(r, f"{{{_A_NS}}}rPr")
            style = run.get("style") or {}
            if style.get("b"):
                r_pr.set("b", style["b"])
            if style.get("i"):
                r_pr.set("i", style["i"])
            t = SubElement(r, f"{{{_A_NS}}}t")
            t.text = run_text
        if not shape.get("runs") and shape.get("text"):
            p = SubElement(tx_body, f"{{{_A_NS}}}p")
            r = SubElement(p, f"{{{_A_NS}}}r")
            t = SubElement(r, f"{{{_A_NS}}}t")
            t.text = shape["text"]
        shape_id += 1

    table = slide.get("table")
    if table:
        gf = SubElement(sp_tree, f"{{{_P_NS}}}graphicFrame")
        nv_gf_pr = SubElement(gf, f"{{{_P_NS}}}nvGraphicFramePr")
        SubElement(nv_gf_pr, f"{{{_P_NS}}}cNvPr", attrib={
            "id": str(shape_id),
            "name": f"Table{shape_id}",
        })
        SubElement(nv_gf_pr, f"{{{_P_NS}}}cNvGraphicFramePr")
        SubElement(nv_gf_pr, f"{{{_P_NS}}}nvPr")
        _frame_xfrm(gf, "457200", "1746250", "8229600", "2746380")
        graphic = SubElement(gf, f"{{{_A_NS}}}graphic")
        graphic_data = SubElement(graphic, f"{{{_A_NS}}}graphicData", attrib={
            "uri": "http://schemas.openxmlformats.org/drawingml/2006/table",
        })
        tbl = SubElement(graphic_data, f"{{{_A_NS}}}tbl")
        SubElement(tbl, f"{{{_A_NS}}}tblPr", attrib={"firstRow": "1", "bandRow": "1"})
        rows = table.get("rows", [])
        col_count = max((len(row.get("cells", [])) for row in rows), default=1)
        col_w = str(8_229_600 // max(col_count, 1))
        tbl_grid = SubElement(tbl, f"{{{_A_NS}}}tblGrid")
        for _ in range(col_count):
            SubElement(tbl_grid, f"{{{_A_NS}}}gridCol", attrib={"w": col_w})
        for row in rows:
            tr = SubElement(tbl, f"{{{_A_NS}}}tr", attrib={"h": "370840"})
            for cell in row.get("cells", []):
                tc = SubElement(tr, f"{{{_A_NS}}}tc")
                txBody = SubElement(tc, f"{{{_A_NS}}}txBody")
                SubElement(txBody, f"{{{_A_NS}}}bodyPr")
                SubElement(txBody, f"{{{_A_NS}}}lstStyle")
                p = SubElement(txBody, f"{{{_A_NS}}}p")
                r = SubElement(p, f"{{{_A_NS}}}r")
                t = SubElement(r, f"{{{_A_NS}}}t")
                t.text = cell or ""
                SubElement(tc, f"{{{_A_NS}}}tcPr")
        shape_id += 1

    chart_ref = slide.get("chart_reference")
    if chart_ref:
        gf = SubElement(sp_tree, f"{{{_P_NS}}}graphicFrame")
        nv_gf_pr = SubElement(gf, f"{{{_P_NS}}}nvGraphicFramePr")
        SubElement(nv_gf_pr, f"{{{_P_NS}}}cNvPr", attrib={
            "id": str(shape_id),
            "name": f"Chart{shape_id}",
        })
        SubElement(nv_gf_pr, f"{{{_P_NS}}}cNvGraphicFramePr")
        SubElement(nv_gf_pr, f"{{{_P_NS}}}nvPr")
        _frame_xfrm(gf, "457200", "1746250", "8229600", "4572000")
        graphic = SubElement(gf, f"{{{_A_NS}}}graphic")
        graphic_data = SubElement(graphic, f"{{{_A_NS}}}graphicData", attrib={
            "uri": "http://schemas.openxmlformats.org/drawingml/2006/chart",
        })
        SubElement(graphic_data, f"{{{_C_NS}}}chart", attrib={
            f"{{{_R_NS}}}id": "rIdChart",
        })
        shape_id += 1

    image_ref = slide.get("image_reference")
    if image_ref:
        pic = SubElement(sp_tree, f"{{{_P_NS}}}pic")
        nv_pic_pr = SubElement(pic, f"{{{_P_NS}}}nvPicPr")
        SubElement(nv_pic_pr, f"{{{_P_NS}}}cNvPr", attrib={
            "id": str(shape_id),
            "name": f"Picture{shape_id}",
        })
        SubElement(nv_pic_pr, f"{{{_P_NS}}}cNvPicPr")
        SubElement(nv_pic_pr, f"{{{_P_NS}}}nvPr")
        blip_fill = SubElement(pic, f"{{{_P_NS}}}blipFill")
        SubElement(blip_fill, f"{{{_A_NS}}}blip", attrib={f"{{{_R_NS}}}embed": "rIdImage"})
        SubElement(SubElement(blip_fill, f"{{{_A_NS}}}stretch"), f"{{{_A_NS}}}fillRect")
        sp_pr = SubElement(pic, f"{{{_P_NS}}}spPr")
        _frame_xfrm(sp_pr, "457200", "1746250", "4572000", "4572000")
        SubElement(SubElement(sp_pr, f"{{{_A_NS}}}prstGeom", attrib={"prst": "rect"}), f"{{{_A_NS}}}avLst")
        shape_id += 1

    SubElement(SubElement(root, f"{{{_P_NS}}}clrMapOvr"), f"{{{_A_NS}}}masterClrMapping")
    return _to_xml_bytes(root)


def _build_title_shape(sp_tree: Any, shape_id: int, title: str) -> Any:
    sp = SubElement(sp_tree, f"{{{_P_NS}}}sp")
    nv_sp_pr = SubElement(sp, f"{{{_P_NS}}}nvSpPr")
    SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvPr", attrib={
        "id": str(shape_id),
        "name": "Title",
    })
    SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvSpPr")
    SubElement(nv_sp_pr, f"{{{_P_NS}}}nvPr")
    sp_pr = SubElement(sp, f"{{{_P_NS}}}spPr")
    _frame_xfrm(sp_pr, "457200", "274638", "8229600", "1143000")
    SubElement(SubElement(sp_pr, f"{{{_A_NS}}}prstGeom", attrib={"prst": "rect"}), f"{{{_A_NS}}}avLst")
    tx_body = SubElement(sp, f"{{{_P_NS}}}txBody")
    SubElement(tx_body, f"{{{_A_NS}}}bodyPr")
    SubElement(tx_body, f"{{{_A_NS}}}lstStyle")
    p = SubElement(tx_body, f"{{{_A_NS}}}p")
    r = SubElement(p, f"{{{_A_NS}}}r")
    t = SubElement(r, f"{{{_A_NS}}}t")
    t.text = title
    return sp


def _build_slide_rels(slide: dict[str, Any], slide_num: int, layout_count: int) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rIdLayout",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
        "Target": f"../slideLayouts/slideLayout1.xml",
    })
    if slide.get("chart_reference"):
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": "rIdChart",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
            "Target": "../charts/chart1.xml",
        })
    if slide.get("image_reference"):
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": "rIdImage",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": "../media/image1.png",
        })
    if slide.get("notes"):
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": "rIdNotes",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide",
            "Target": f"../notesSlides/notesSlide{slide_num}.xml",
        })
    return _to_xml_bytes(root)


def _build_notes_master() -> bytes:
    root = Element(f"{{{_P_NS}}}notesMaster")
    cSld = SubElement(root, f"{{{_P_NS}}}cSld")
    sp_tree = SubElement(cSld, f"{{{_P_NS}}}spTree")
    _nv_grp_sp_pr(sp_tree)
    _grp_sp_pr(sp_tree)
    SubElement(root, f"{{{_P_NS}}}clrMap", attrib=_CLR_MAP)
    return _to_xml_bytes(root)


def _build_notes_master_rels() -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rIdNotes",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        "Target": "../theme/theme1.xml",
    })
    return _to_xml_bytes(root)


def _build_notes_slide(slide_num: int, notes_text: str) -> bytes:
    root = Element(f"{{{_P_NS}}}notes")
    cSld = SubElement(root, f"{{{_P_NS}}}cSld")
    sp_tree = SubElement(cSld, f"{{{_P_NS}}}spTree")
    _nv_grp_sp_pr(sp_tree)
    _grp_sp_pr(sp_tree)
    sp = SubElement(sp_tree, f"{{{_P_NS}}}sp")
    nv_sp_pr = SubElement(sp, f"{{{_P_NS}}}nvSpPr")
    SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvPr", attrib={
        "id": "3",
        "name": f"NotesPlaceholder{slide_num}",
    })
    SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvSpPr")
    SubElement(nv_sp_pr, f"{{{_P_NS}}}nvPr")
    SubElement(sp, f"{{{_P_NS}}}spPr")
    tx_body = SubElement(sp, f"{{{_P_NS}}}txBody")
    SubElement(tx_body, f"{{{_A_NS}}}bodyPr")
    SubElement(tx_body, f"{{{_A_NS}}}lstStyle")
    p = SubElement(tx_body, f"{{{_A_NS}}}p")
    r = SubElement(p, f"{{{_A_NS}}}r")
    t = SubElement(r, f"{{{_A_NS}}}t")
    t.text = notes_text
    return _to_xml_bytes(root)


def _build_notes_slide_rels(slide_num: int) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rIdSlide",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
        "Target": f"../slides/slide{slide_num}.xml",
    })
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rIdNotesMaster",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
        "Target": "../notesMasters/notesMaster1.xml",
    })
    return _to_xml_bytes(root)


def _build_chart_reference(chart_ref: dict[str, Any]) -> bytes:
    chart_ns = NS["c"]
    root = Element(f"{{{chart_ns}}}chartSpace")
    chart = SubElement(root, f"{{{chart_ns}}}chart")
    plot_area = SubElement(chart, f"{{{chart_ns}}}plotArea")
    bar_chart = SubElement(plot_area, f"{{{chart_ns}}}barChart")
    SubElement(bar_chart, f"{{{chart_ns}}}barDir", attrib={"val": "col"})
    ser = SubElement(bar_chart, f"{{{chart_ns}}}ser")
    tx = SubElement(ser, f"{{{chart_ns}}}tx")
    v = SubElement(tx, f"{{{chart_ns}}}v")
    v.text = chart_ref.get("title", "")
    return _to_xml_bytes(root)


# ---------------------------------------------------------------------------
# Shape-property helpers for the typed-create path
# ---------------------------------------------------------------------------


def _nv_grp_sp_pr(sp_tree: Element) -> None:
    nv = SubElement(sp_tree, f"{{{_P_NS}}}nvGrpSpPr")
    SubElement(nv, f"{{{_P_NS}}}cNvPr", attrib={"id": "1", "name": ""})
    SubElement(nv, f"{{{_P_NS}}}cNvGrpSpPr")
    SubElement(nv, f"{{{_P_NS}}}nvPr")


def _grp_sp_pr(sp_tree: Element) -> None:
    group = SubElement(sp_tree, f"{{{_P_NS}}}grpSpPr")
    SubElement(group, f"{{{_A_NS}}}xfrm")


def _shape_sp_pr(parent: Element) -> None:
    """Emit a minimal spPr with transform and rect geometry for body shapes."""
    sp_pr = SubElement(parent, f"{{{_P_NS}}}spPr")
    _frame_xfrm(sp_pr, "457200", "1600200", "8229600", "4572000")
    SubElement(SubElement(sp_pr, f"{{{_A_NS}}}prstGeom", attrib={"prst": "rect"}), f"{{{_A_NS}}}avLst")


def _frame_xfrm(parent: Element, x: str, y: str, cx: str, cy: str) -> None:
    xfrm = SubElement(parent, f"{{{_A_NS}}}xfrm")
    SubElement(xfrm, f"{{{_A_NS}}}off", attrib={"x": x, "y": y})
    SubElement(xfrm, f"{{{_A_NS}}}ext", attrib={"cx": cx, "cy": cy})
