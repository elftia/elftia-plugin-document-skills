"""Original deterministic styled-report DOCX construction.

Every optional member of the report maps to an optional part: no image means
no media part and no drawing, no header/footer means no story part and no
section reference. The package contains exactly what the request described.
"""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES_NS,
    CT_FOOTER,
    CT_HEADER,
    HEADING_SIZES,
    MIN_HEADING_STYLES,
    NS,
    REL_CORE_PROPERTIES,
    REL_EXTENDED_PROPERTIES,
    REL_FOOTER,
    REL_HEADER,
    REL_IMAGE,
    REL_NUMBERING,
    REL_OFFICE_DOCUMENT,
    REL_STYLES,
    qn,
)
from .image import load_image
from .package import write_deterministic_zip
from .xml_utils import paragraph, text_run, xml_bytes

_CREATED = datetime(2000, 1, 1, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_EMU_PER_INCH = 914_400
_MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


def create_docx(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    inline_images, trailing_image = _load_images(report)
    images = inline_images + ([] if trailing_image is None else [trailing_image])
    header, footer = report["header"], report["footer"]
    parts = {
        "[Content_Types].xml": _content_types(images, header=header, footer=footer),
        "_rels/.rels": _package_relationships(),
        "docProps/app.xml": _app_properties(),
        "docProps/core.xml": _core_properties(report["metadata"]),
        "word/_rels/document.xml.rels": _document_relationships(
            images, header=header, footer=footer
        ),
        "word/document.xml": _document(report, inline_images, trailing_image),
        "word/numbering.xml": _numbering(),
        "word/styles.xml": _styles(_max_heading_level(report)),
    }
    if footer is not None:
        parts["word/footer1.xml"] = _story("ftr", footer)
    if header is not None:
        parts["word/header1.xml"] = _story("hdr", header)
    for image in images:
        parts[image["part"]] = image["bytes"]
    write_deterministic_zip(path, parts)
    # This is the immutable oracle the required validation gate checks against.
    # It must NOT re-read the caller's source paths: those can change between
    # creation and validation, which would fail a correctly built package.
    records = [
        {
            "alt_text": image["alt_text"],
            "content_type": image["content_type"],
            "extension": image["extension"],
            "bytes": len(image["bytes"]),
            "sha256": sha256(image["bytes"]).hexdigest(),
            "width_px": image["width_px"],
            "height_px": image["height_px"],
        }
        for image in images
    ]
    return {
        "images": records,
        # Retained so a caller written against the single-image result keeps
        # working; for the previously-mandatory report shape this is the same
        # record it always was.
        "image": records[0] if records else None,
        "section_count": len(report["sections"]),
        "part_count": len(parts),
    }


def _load_images(
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Load inline image blocks, then the optional trailing report image."""
    requests = [block for block in report["blocks"] if block["type"] == "image"]
    trailing = report["image"]
    if trailing is not None:
        requests.append(trailing)
    loaded: list[dict[str, Any]] = []
    total_bytes = 0
    for position, request in enumerate(requests, start=1):
        image = load_image(request)
        total_bytes += len(image["bytes"])
        if total_bytes > _MAX_TOTAL_IMAGE_BYTES:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "The report images exceed the aggregate byte limit.",
                status="invalid_request",
                details={"ceiling": _MAX_TOTAL_IMAGE_BYTES},
            )
        image["position"] = position
        image["relationship_id"] = f"rIdImage{position}"
        image["target"] = f"media/image{position}.{image['extension']}"
        image["part"] = f"word/{image['target']}"
        loaded.append(image)
    if trailing is None:
        return loaded, None
    return loaded[:-1], loaded[-1]


def _document(
    report: dict[str, Any],
    inline_images: list[dict[str, Any]],
    trailing_image: dict[str, Any] | None,
) -> bytes:
    root = Element(qn("w", "document"))
    body = SubElement(root, qn("w", "body"))
    pending = iter(inline_images)
    for block in report["blocks"]:
        if block["type"] == "heading":
            body.append(paragraph(block["text"], style=f"Heading{block['level']}"))
        elif block["type"] == "paragraph":
            body.append(paragraph(block["text"], style=block["style"]))
        elif block["type"] == "image":
            body.append(_image_paragraph(next(pending)))
        else:
            body.append(_table(block))
    if trailing_image is not None:
        body.append(_image_paragraph(trailing_image))
    references = _section_references(report)
    for section in report["sections"][:-1]:
        boundary = SubElement(body, qn("w", "p"))
        properties = SubElement(boundary, qn("w", "pPr"))
        properties.append(
            _section_properties(section, references, next_page=True)
        )
    body.append(
        _section_properties(report["sections"][-1], references, next_page=False)
    )
    return xml_bytes(root)


def _section_references(report: dict[str, Any]) -> list[tuple[str, str]]:
    references = []
    if report["header"] is not None:
        references.append(("headerReference", "rIdHeader1"))
    if report["footer"] is not None:
        references.append(("footerReference", "rIdFooter1"))
    return references


def _table(block: dict[str, Any]) -> Element:
    table = Element(qn("w", "tbl"))
    properties = SubElement(table, qn("w", "tblPr"))
    SubElement(properties, qn("w", "tblStyle"), {qn("w", "val"): block["style"]})
    for row_index, row in enumerate(block["rows"]):
        row_node = SubElement(table, qn("w", "tr"))
        for cell in row:
            cell_node = SubElement(row_node, qn("w", "tc"))
            paragraph_node = SubElement(cell_node, qn("w", "p"))
            text_run(paragraph_node, cell, bold=row_index == 0)
    return table


def _image_paragraph(image: dict[str, Any]) -> Element:
    width = int(image["width_inches"] * _EMU_PER_INCH)
    height = int(width * image["height_px"] / image["width_px"])
    paragraph_node = Element(qn("w", "p"))
    run = SubElement(paragraph_node, qn("w", "r"))
    drawing = SubElement(run, qn("w", "drawing"))
    inline = SubElement(drawing, qn("wp", "inline"))
    SubElement(inline, qn("wp", "extent"), {"cx": str(width), "cy": str(height)})
    SubElement(
        inline,
        qn("wp", "docPr"),
        {
            "id": str(image["position"]),
            "name": "Report image",
            "descr": image["alt_text"],
        },
    )
    graphic = SubElement(inline, qn("a", "graphic"))
    graphic_data = SubElement(
        graphic,
        qn("a", "graphicData"),
        {"uri": "http://schemas.openxmlformats.org/drawingml/2006/picture"},
    )
    picture = SubElement(graphic_data, qn("pic", "pic"))
    non_visual = SubElement(picture, qn("pic", "nvPicPr"))
    # Distinct non-visual drawing id per picture. Zero-based so the first image
    # keeps the id earlier versions emitted and single-image packages stay
    # byte-identical.
    SubElement(
        non_visual,
        qn("pic", "cNvPr"),
        {"id": str(image["position"] - 1), "name": f"image{image['position']}"},
    )
    SubElement(non_visual, qn("pic", "cNvPicPr"))
    fill = SubElement(picture, qn("pic", "blipFill"))
    SubElement(fill, qn("a", "blip"), {qn("r", "embed"): image["relationship_id"]})
    stretch = SubElement(fill, qn("a", "stretch"))
    SubElement(stretch, qn("a", "fillRect"))
    shape = SubElement(picture, qn("pic", "spPr"))
    transform = SubElement(shape, qn("a", "xfrm"))
    SubElement(transform, qn("a", "off"), {"x": "0", "y": "0"})
    SubElement(transform, qn("a", "ext"), {"cx": str(width), "cy": str(height)})
    geometry = SubElement(shape, qn("a", "prstGeom"), {"prst": "rect"})
    SubElement(geometry, qn("a", "avLst"))
    return paragraph_node


def _section_properties(
    section: dict[str, Any],
    references: list[tuple[str, str]],
    *,
    next_page: bool,
) -> Element:
    properties = Element(qn("w", "sectPr"))
    for name, relationship_id in references:
        SubElement(
            properties,
            qn("w", name),
            {qn("w", "type"): "default", qn("r", "id"): relationship_id},
        )
    if next_page:
        SubElement(properties, qn("w", "type"), {qn("w", "val"): "nextPage"})
    landscape = section["orientation"] == "landscape"
    width, height = ("15840", "12240") if landscape else ("12240", "15840")
    size_attributes = {qn("w", "w"): width, qn("w", "h"): height}
    if landscape:
        size_attributes[qn("w", "orient")] = "landscape"
    SubElement(properties, qn("w", "pgSz"), size_attributes)
    SubElement(
        properties,
        qn("w", "pgMar"),
        {
            qn("w", "top"): "1440",
            qn("w", "right"): "1440",
            qn("w", "bottom"): "1440",
            qn("w", "left"): "1440",
            qn("w", "header"): "720",
            qn("w", "footer"): "720",
            qn("w", "gutter"): "0",
        },
    )
    return properties


def _story(kind: str, text: str) -> bytes:
    root = Element(qn("w", kind))
    root.append(paragraph(text))
    return xml_bytes(root)


def _content_types(
    images: list[dict[str, Any]],
    *,
    header: str | None,
    footer: str | None,
) -> bytes:
    root = Element(f"{{{CONTENT_TYPES_NS}}}Types")
    defaults = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
    }
    for image in images:
        defaults[image["extension"]] = image["content_type"]
    for suffix, content_type in sorted(defaults.items()):
        SubElement(root, f"{{{CONTENT_TYPES_NS}}}Default", {"Extension": suffix, "ContentType": content_type})
    overrides = {
        "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "/word/numbering.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
        "/word/styles.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    }
    if footer is not None:
        overrides["/word/footer1.xml"] = CT_FOOTER
    if header is not None:
        overrides["/word/header1.xml"] = CT_HEADER
    for part, content_type in sorted(overrides.items()):
        SubElement(root, f"{{{CONTENT_TYPES_NS}}}Override", {"PartName": part, "ContentType": content_type})
    return xml_bytes(root)


def _relationships(entries: list[tuple[str, str, str]]) -> bytes:
    root = Element(qn("rels", "Relationships"))
    for relationship_id, relationship_type, target in entries:
        SubElement(
            root,
            qn("rels", "Relationship"),
            {"Id": relationship_id, "Type": relationship_type, "Target": target},
        )
    return xml_bytes(root)


def _package_relationships() -> bytes:
    return _relationships(
        [
            ("rId1", REL_OFFICE_DOCUMENT, "word/document.xml"),
            ("rId2", REL_CORE_PROPERTIES, "docProps/core.xml"),
            ("rId3", REL_EXTENDED_PROPERTIES, "docProps/app.xml"),
        ]
    )


def _document_relationships(
    images: list[dict[str, Any]],
    *,
    header: str | None,
    footer: str | None,
) -> bytes:
    entries: list[tuple[str, str, str]] = []
    if footer is not None:
        entries.append(("rIdFooter1", REL_FOOTER, "footer1.xml"))
    if header is not None:
        entries.append(("rIdHeader1", REL_HEADER, "header1.xml"))
    entries.extend(
        (image["relationship_id"], REL_IMAGE, image["target"]) for image in images
    )
    entries.append(("rIdNumbering", REL_NUMBERING, "numbering.xml"))
    entries.append(("rIdStyles", REL_STYLES, "styles.xml"))
    return _relationships(entries)


def _core_properties(metadata: dict[str, str]) -> bytes:
    root = Element(qn("cp", "coreProperties"))
    for prefix, name, value in (
        ("dc", "title", metadata["title"]),
        ("dc", "subject", metadata["subject"]),
        ("dc", "creator", metadata["creator"] or "Elftia Document Skills"),
        ("cp", "keywords", metadata["keywords"]),
    ):
        SubElement(root, qn(prefix, name)).text = value
    created = SubElement(root, qn("dcterms", "created"), {qn("xsi", "type"): "dcterms:W3CDTF"})
    created.text = _CREATED
    return xml_bytes(root)


def _app_properties() -> bytes:
    root = Element("Properties", {"xmlns": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties", "xmlns:vt": NS["vt"]})
    SubElement(root, "Application").text = "Elftia Document Skills"
    return xml_bytes(root)


def _max_heading_level(report: dict[str, Any]) -> int:
    """How many heading styles the package has to carry."""
    levels = [
        block["level"] for block in report["blocks"] if block["type"] == "heading"
    ]
    return max(MIN_HEADING_STYLES, *levels) if levels else MIN_HEADING_STYLES


def _styles(max_heading_level: int) -> bytes:
    root = Element(qn("w", "styles"))
    entries = [
        ("Normal", "Normal", "22", False),
        *(
            (f"Heading{level}", f"heading {level}", HEADING_SIZES[level - 1], True)
            for level in range(1, max_heading_level + 1)
        ),
        ("TableGrid", "Table Grid", "22", False),
    ]
    for style_id, name, size, bold in entries:
        style = SubElement(root, qn("w", "style"), {qn("w", "type"): "paragraph" if style_id != "TableGrid" else "table", qn("w", "styleId"): style_id})
        SubElement(style, qn("w", "name"), {qn("w", "val"): name})
        run_properties = SubElement(style, qn("w", "rPr"))
        if bold:
            SubElement(run_properties, qn("w", "b"))
        SubElement(run_properties, qn("w", "sz"), {qn("w", "val"): size})
    return xml_bytes(root)


def _numbering() -> bytes:
    root = Element(qn("w", "numbering"))
    abstract = SubElement(root, qn("w", "abstractNum"), {qn("w", "abstractNumId"): "1"})
    level = SubElement(abstract, qn("w", "lvl"), {qn("w", "ilvl"): "0"})
    SubElement(level, qn("w", "numFmt"), {qn("w", "val"): "bullet"})
    SubElement(level, qn("w", "lvlText"), {qn("w", "val"): "•"})
    number = SubElement(root, qn("w", "num"), {qn("w", "numId"): "1"})
    SubElement(number, qn("w", "abstractNumId"), {qn("w", "val"): "1"})
    return xml_bytes(root)
