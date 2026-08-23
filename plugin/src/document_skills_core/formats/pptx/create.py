"""Styled PPTX deck construction from bounded typed data."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart import build_chart_part, prepare_chart, public_chart_record
from .constants import NS
from .image import (
    MAX_TOTAL_IMAGE_BYTES,
    load_pptx_image,
    public_image_record,
)
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

def create_pptx(destination: Path, deck: dict[str, Any]) -> dict[str, Any]:
    """Create a styled PPTX deck from the parsed deck model."""
    metadata = deck.get("metadata", {})
    slides_data: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    total_image_bytes = 0
    for source_slide in deck.get("slides", []):
        slide = dict(source_slide)
        if source_slide.get("image_reference"):
            image = load_pptx_image(source_slide["image_reference"], len(images) + 1)
            total_image_bytes += len(image["bytes"])
            if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "The presentation images exceed the aggregate byte limit.",
                    status="invalid_request",
                    details={"ceiling": MAX_TOTAL_IMAGE_BYTES},
                )
            images.append(image)
            slide["_image"] = image
        if source_slide.get("chart_reference"):
            chart = prepare_chart(source_slide["chart_reference"], len(charts) + 1)
            charts.append(chart)
            slide["_chart"] = chart
        slides_data.append(slide)
    slide_size = deck.get("slide_size") or {"cx": "9144000", "cy": "6858000", "type": "screen4x3"}

    parts: dict[str, bytes] = {}
    has_chart = bool(charts)
    has_image = bool(images)
    has_table = any(s.get("table") for s in slides_data)
    has_notes = any(s.get("notes") for s in slides_data)
    layout_count = 2

    parts["[Content_Types].xml"] = _build_content_types(
        len(slides_data), images, charts, has_notes, layout_count
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
    for chart in charts:
        parts[chart["part"]] = build_chart_part(chart)
    for image in images:
        parts[image["part"]] = image["bytes"]

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
        "charts": [public_chart_record(chart) for chart in charts],
        "images": [public_image_record(image) for image in images],
        "metadata": metadata,
        "slide_size": slide_size,
    }


def _build_content_types(
    slide_count: int,
    images: list[dict[str, Any]],
    charts: list[dict[str, Any]],
    has_notes: bool,
    layout_count: int,
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
    for extension, content_type in sorted({
        (image["extension"], image["content_type"]) for image in images
    }):
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Default", attrib={
            "Extension": extension,
            "ContentType": content_type,
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
    for chart in charts:
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": f"/{chart['part']}",
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
    drawables: list[tuple[int, int, Element]] = []
    ordinal = 0
    title = slide.get("title")
    if title:
        title_shape = _build_title_shape(sp_tree, shape_id, title)
        drawables.append((9_000, ordinal, title_shape))
        ordinal += 1
        shape_id += 1
    for shape in slide.get("shapes", []):
        sp = SubElement(sp_tree, f"{{{_P_NS}}}sp")
        drawables.append((100 + ordinal, ordinal, sp))
        ordinal += 1
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
        drawables.append((500, ordinal, gf))
        ordinal += 1
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

    chart = slide.get("_chart")
    if chart:
        gf = SubElement(sp_tree, f"{{{_P_NS}}}graphicFrame")
        drawables.append((600, ordinal, gf))
        ordinal += 1
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
            f"{{{_R_NS}}}id": chart["relationship_id"],
        })
        shape_id += 1

    image = slide.get("_image")
    if image:
        pic = SubElement(sp_tree, f"{{{_P_NS}}}pic")
        drawables.append((image["z_order"], ordinal, pic))
        ordinal += 1
        nv_pic_pr = SubElement(pic, f"{{{_P_NS}}}nvPicPr")
        SubElement(nv_pic_pr, f"{{{_P_NS}}}cNvPr", attrib={
            "id": str(shape_id),
            "name": f"Picture{shape_id}",
            "descr": image["alt_text"],
        })
        c_nv_pic_pr = SubElement(nv_pic_pr, f"{{{_P_NS}}}cNvPicPr")
        SubElement(
            c_nv_pic_pr,
            f"{{{_A_NS}}}picLocks",
            attrib={"noChangeAspect": "1" if image["fit"] != "stretch" else "0"},
        )
        SubElement(nv_pic_pr, f"{{{_P_NS}}}nvPr")
        blip_fill = SubElement(pic, f"{{{_P_NS}}}blipFill")
        blip = SubElement(
            blip_fill,
            f"{{{_A_NS}}}blip",
            attrib={f"{{{_R_NS}}}embed": image["relationship_id"]},
        )
        if image["opacity"] < 1.0:
            SubElement(
                blip,
                f"{{{_A_NS}}}alphaModFix",
                attrib={"amt": str(round(image["opacity"] * 100_000))},
            )
        if any(image["crop"].values()):
            SubElement(
                blip_fill,
                f"{{{_A_NS}}}srcRect",
                attrib={side[0]: str(round(value * 100_000)) for side, value in image["crop"].items()},
            )
        SubElement(SubElement(blip_fill, f"{{{_A_NS}}}stretch"), f"{{{_A_NS}}}fillRect")
        sp_pr = SubElement(pic, f"{{{_P_NS}}}spPr")
        frame = image["frame"]
        xfrm = SubElement(
            sp_pr,
            f"{{{_A_NS}}}xfrm",
            attrib={
                **({"rot": str(round(image["rotation"] * 60_000))} if image["rotation"] else {}),
                **({"flipH": "1"} if image["flip_h"] else {}),
                **({"flipV": "1"} if image["flip_v"] else {}),
            },
        )
        SubElement(xfrm, f"{{{_A_NS}}}off", attrib={"x": str(frame["x"]), "y": str(frame["y"])})
        SubElement(xfrm, f"{{{_A_NS}}}ext", attrib={"cx": str(frame["cx"]), "cy": str(frame["cy"])})
        SubElement(SubElement(sp_pr, f"{{{_A_NS}}}prstGeom", attrib={"prst": "rect"}), f"{{{_A_NS}}}avLst")
        shape_id += 1

    for _z_order, _ordinal, element in sorted(drawables, key=lambda item: (item[0], item[1])):
        sp_tree.remove(element)
        sp_tree.append(element)
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
    chart = slide.get("_chart")
    if chart:
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": chart["relationship_id"],
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
            "Target": chart["target"],
        })
    image = slide.get("_image")
    if image:
        SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
            "Id": image["relationship_id"],
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": image["target"],
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
