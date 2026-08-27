"""Styled PPTX deck construction from bounded typed data."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart import build_chart_part, prepare_chart, public_chart_record
from .constants import NS
from .design_contracts import DEFAULT_LAYOUT_TOKENS, DEFAULT_THEME, LAYOUT_RECIPES
from .equation_contracts import equation_records
from .equation_omml import build_equation
from .image import (
    MAX_TOTAL_IMAGE_BYTES,
    load_pptx_image,
    public_image_record,
)
from .package import write_deterministic_zip
from .layout_recipes import layout_index, layout_recipe
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

def create_pptx(
    destination: Path,
    deck: dict[str, Any],
    template: Path | None = None,
) -> dict[str, Any]:
    """Create a styled PPTX deck from the parsed deck model."""
    if template is not None:
        from .template_create import create_pptx_from_template

        return create_pptx_from_template(destination, deck, template)
    metadata = deck.get("metadata", {})
    slides_data: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    total_image_bytes = 0
    slide_size = deck.get("slide_size") or {"cx": "9144000", "cy": "6858000", "type": "screen4x3"}
    theme = deck.get("theme") or DEFAULT_THEME
    layout_tokens = deck.get("layout_tokens") or DEFAULT_LAYOUT_TOKENS
    for source_slide in deck.get("slides", []):
        slide = dict(source_slide)
        recipe = layout_recipe(
            slide.get("recipe", "cover" if slide.get("layout") == "title" else "content"),
            slide_size,
            layout_tokens,
            len(slide.get("shapes", [])),
        )
        slide["_layout_recipe"] = recipe
        slide["_theme"] = theme
        if source_slide.get("image_reference"):
            image_reference = dict(source_slide["image_reference"])
            if image_reference.get("frame") is None:
                image_reference["frame"] = recipe["media"]
            image = load_pptx_image(image_reference, len(images) + 1)
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
            chart_reference = dict(source_slide["chart_reference"])
            if not chart_reference.get("colors"):
                chart_reference["colors"] = list(theme["default_chart"]["colors"])
            chart = prepare_chart(chart_reference, len(charts) + 1)
            charts.append(chart)
            slide["_chart"] = chart
        slides_data.append(slide)
    parts: dict[str, bytes] = {}
    has_chart = bool(charts)
    equations = equation_records(slides_data)
    has_image = bool(images)
    has_table = any(s.get("table") for s in slides_data)
    note_slide_numbers = [
        index
        for index, slide in enumerate(slides_data, 1)
        if slide.get("notes")
    ]
    has_notes = bool(note_slide_numbers)
    layout_count = len(LAYOUT_RECIPES)

    parts["[Content_Types].xml"] = _build_content_types(
        len(slides_data), images, charts, note_slide_numbers, layout_count
    )
    parts["_rels/.rels"] = _build_root_rels()
    parts["ppt/_rels/presentation.xml.rels"] = _build_presentation_rels(
        slides_data, layout_count, has_notes
    )
    parts["ppt/presentation.xml"] = _build_presentation(slides_data, slide_size, has_notes)
    parts["ppt/theme/theme1.xml"] = _build_theme(theme)
    parts["ppt/slideMasters/slideMaster1.xml"] = _build_slide_master(
        layout_count,
        int(slide_size.get("cx", "9144000")),
        int(slide_size.get("cy", "6858000")),
        theme,
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
        "has_equation": bool(equations),
        "has_image": has_image,
        "has_table": has_table,
        "has_notes": has_notes,
        "charts": [public_chart_record(chart) for chart in charts],
        "equations": equations,
        "images": [public_image_record(image) for image in images],
        "layout_recipes": [
            {
                "name": slide["_layout_recipe"]["name"],
                "placeholder_mapping": slide["_layout_recipe"]["placeholder_mapping"],
                "slide": index,
            }
            for index, slide in enumerate(slides_data, 1)
        ],
        "metadata": metadata,
        "slide_size": slide_size,
        "theme": {
            "background": theme["background"],
            "effects": theme["effects"],
            "fonts": dict(theme["fonts"]),
            "name": theme["name"],
            "palette": dict(theme["palette"]),
        },
    }


def _build_content_types(
    slide_count: int,
    images: list[dict[str, Any]],
    charts: list[dict[str, Any]],
    note_slide_numbers: list[int],
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
    if note_slide_numbers:
        SubElement(root, f"{{{_CONTENT_TYPES_NS}}}Override", attrib={
            "PartName": "/ppt/notesMasters/notesMaster1.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml",
        })
        for i in note_slide_numbers:
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
            "Id": "rIdNotes",
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
    recipe = slide.get("_layout_recipe") or layout_recipe(
        slide.get("recipe", "cover" if slide.get("layout") == "title" else "content"),
        {"cx": "9144000", "cy": "6858000"},
        DEFAULT_LAYOUT_TOKENS,
        len(slide.get("shapes", [])),
    )
    theme = slide.get("_theme") or DEFAULT_THEME
    title = slide.get("title")
    if title:
        title_shape = _build_title_shape(
            sp_tree,
            shape_id,
            title,
            recipe["title"],
            theme,
        )
        drawables.append((9_000, ordinal, title_shape))
        ordinal += 1
        shape_id += 1
    for shape_index, shape in enumerate(slide.get("shapes", [])):
        if shape.get("type") == "equation":
            equation = build_equation(shape_id, shape)
            sp_tree.append(equation)
            drawables.append((shape["z_order"], ordinal, equation))
            ordinal += 1
            shape_id += 1
            continue
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
        body_frames = recipe["body"]
        frame = body_frames[min(shape_index, len(body_frames) - 1)]
        _shape_sp_pr(sp, frame, theme)
        tx_body = SubElement(sp, f"{{{_P_NS}}}txBody")
        SubElement(tx_body, f"{{{_A_NS}}}bodyPr")
        SubElement(tx_body, f"{{{_A_NS}}}lstStyle")
        for run in shape.get("runs", []):
            p = SubElement(tx_body, f"{{{_A_NS}}}p")
            r = SubElement(p, f"{{{_A_NS}}}r")
            run_text = run.get("text") or ""
            r_pr = SubElement(r, f"{{{_A_NS}}}rPr")
            style = run.get("style") or {}
            _apply_text_defaults(r_pr, theme, style, title=False)
            t = SubElement(r, f"{{{_A_NS}}}t")
            t.text = run_text
        if not shape.get("runs") and shape.get("text"):
            p = SubElement(tx_body, f"{{{_A_NS}}}p")
            r = SubElement(p, f"{{{_A_NS}}}r")
            r_pr = SubElement(r, f"{{{_A_NS}}}rPr")
            _apply_text_defaults(r_pr, theme, {}, title=False)
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
        table_frame = recipe["data"]
        _graphic_frame_xfrm(
            gf,
            table_frame["x"],
            table_frame["y"],
            table_frame["cx"],
            table_frame["cy"],
        )
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
                r_pr = SubElement(r, f"{{{_A_NS}}}rPr")
                _apply_text_defaults(r_pr, theme, {}, title=False)
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
        chart_frame = recipe["data"]
        _graphic_frame_xfrm(
            gf,
            chart_frame["x"],
            chart_frame["y"],
            chart_frame["cx"],
            chart_frame["cy"],
        )
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


def _build_title_shape(
    sp_tree: Any,
    shape_id: int,
    title: str,
    frame: dict[str, int],
    theme: dict[str, Any],
) -> Any:
    sp = SubElement(sp_tree, f"{{{_P_NS}}}sp")
    nv_sp_pr = SubElement(sp, f"{{{_P_NS}}}nvSpPr")
    SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvPr", attrib={
        "id": str(shape_id),
        "name": "Title",
    })
    SubElement(nv_sp_pr, f"{{{_P_NS}}}cNvSpPr")
    SubElement(nv_sp_pr, f"{{{_P_NS}}}nvPr")
    sp_pr = SubElement(sp, f"{{{_P_NS}}}spPr")
    _frame_xfrm(sp_pr, frame["x"], frame["y"], frame["cx"], frame["cy"])
    SubElement(SubElement(sp_pr, f"{{{_A_NS}}}prstGeom", attrib={"prst": "rect"}), f"{{{_A_NS}}}avLst")
    tx_body = SubElement(sp, f"{{{_P_NS}}}txBody")
    SubElement(tx_body, f"{{{_A_NS}}}bodyPr")
    SubElement(tx_body, f"{{{_A_NS}}}lstStyle")
    p = SubElement(tx_body, f"{{{_A_NS}}}p")
    r = SubElement(p, f"{{{_A_NS}}}r")
    r_pr = SubElement(r, f"{{{_A_NS}}}rPr")
    _apply_text_defaults(r_pr, theme, {}, title=True)
    t = SubElement(r, f"{{{_A_NS}}}t")
    t.text = title
    return sp


def _build_slide_rels(slide: dict[str, Any], slide_num: int, layout_count: int) -> bytes:
    root = Element(f"{{{_RELS_NS}}}Relationships")
    recipe = slide.get("_layout_recipe", {}).get(
        "name",
        "cover" if slide.get("layout") == "title" else "content",
    )
    SubElement(root, f"{{{_RELS_NS}}}Relationship", attrib={
        "Id": "rIdLayout",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
        "Target": f"../slideLayouts/slideLayout{layout_index(recipe)}.xml",
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


def _shape_sp_pr(
    parent: Element,
    frame: dict[str, int],
    theme: dict[str, Any],
) -> None:
    """Emit a minimal spPr with transform and rect geometry for body shapes."""
    sp_pr = SubElement(parent, f"{{{_P_NS}}}spPr")
    _frame_xfrm(sp_pr, frame["x"], frame["y"], frame["cx"], frame["cy"])
    geometry = SubElement(sp_pr, f"{{{_A_NS}}}prstGeom", attrib={"prst": "rect"})
    SubElement(geometry, f"{{{_A_NS}}}avLst")
    default_shape = theme["default_shape"]
    fill = SubElement(sp_pr, f"{{{_A_NS}}}solidFill")
    color = SubElement(
        fill,
        f"{{{_A_NS}}}srgbClr",
        attrib={"val": default_shape["fill"]},
    )
    if default_shape["opacity"] < 1.0:
        SubElement(
            color,
            f"{{{_A_NS}}}alpha",
            attrib={"val": str(round(default_shape["opacity"] * 100_000))},
        )
    line = SubElement(sp_pr, f"{{{_A_NS}}}ln")
    line_fill = SubElement(line, f"{{{_A_NS}}}solidFill")
    SubElement(
        line_fill,
        f"{{{_A_NS}}}srgbClr",
        attrib={"val": default_shape["line"]},
    )


def _frame_xfrm(parent: Element, x: Any, y: Any, cx: Any, cy: Any) -> None:
    xfrm = SubElement(parent, f"{{{_A_NS}}}xfrm")
    SubElement(xfrm, f"{{{_A_NS}}}off", attrib={"x": str(x), "y": str(y)})
    SubElement(xfrm, f"{{{_A_NS}}}ext", attrib={"cx": str(cx), "cy": str(cy)})


def _graphic_frame_xfrm(
    parent: Element,
    x: Any,
    y: Any,
    cx: Any,
    cy: Any,
) -> None:
    xfrm = SubElement(parent, f"{{{_P_NS}}}xfrm")
    SubElement(xfrm, f"{{{_A_NS}}}off", attrib={"x": str(x), "y": str(y)})
    SubElement(xfrm, f"{{{_A_NS}}}ext", attrib={"cx": str(cx), "cy": str(cy)})


def _apply_text_defaults(
    properties: Element,
    theme: dict[str, Any],
    style: dict[str, Any],
    *,
    title: bool,
) -> None:
    default_text = theme["default_text"]
    size = style.get(
        "font_size",
        default_text["title_size"] if title else default_text["body_size"],
    )
    properties.set("sz", str(round(float(size) * 100)))
    bold = style.get("bold", style.get("b", default_text["bold_titles"] if title else False))
    italic = style.get("italic", style.get("i", False))
    if bold:
        properties.set("b", "1")
    if italic:
        properties.set("i", "1")
    color_value = style.get(
        "color",
        default_text["title_color"] if title else default_text["body_color"],
    )
    solid = SubElement(properties, f"{{{_A_NS}}}solidFill")
    SubElement(
        solid,
        f"{{{_A_NS}}}srgbClr",
        attrib={"val": str(color_value).lstrip("#").upper()},
    )
    typeface = style.get(
        "font",
        theme["fonts"]["major" if title else "minor"],
    )
    SubElement(properties, f"{{{_A_NS}}}latin", attrib={"typeface": str(typeface)})
