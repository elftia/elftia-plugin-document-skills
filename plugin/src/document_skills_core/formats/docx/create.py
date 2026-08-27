"""Original deterministic styled-report DOCX construction.

Every optional member of the report maps to an optional part: no image means
no media part and no drawing, no header/footer means no story part and no
section reference. The package contains exactly what the request described.
"""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    CONTENT_TYPES_NS,
    CT_SETTINGS,
    CT_FOOTER,
    CT_HEADER,
    HEADING_SIZES,
    MIN_HEADING_STYLES,
    NS,
    REL_CORE_PROPERTIES,
    REL_CUSTOM_PROPERTIES,
    REL_EXTENDED_PROPERTIES,
    REL_FOOTER,
    REL_HEADER,
    REL_IMAGE,
    REL_NUMBERING,
    REL_OFFICE_DOCUMENT,
    REL_SETTINGS,
    REL_STYLES,
    qn,
)
from .drawing import image_paragraph
from .document_manifest import render_document_manifest
from .equations import equation_paragraph
from .formatting import set_paragraph_style
from .image import load_image
from .package import write_deterministic_zip
from .references import attach_reference_bookmark, reference_paragraph
from .semantic_nodes import attach_semantic_node_marker
from .style_profiles import public_style_profile, render_style_profile
from .table import table_element
from .xml_utils import paragraph, text_run, xml_bytes

_CREATED = datetime(2000, 1, 1, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


def create_docx(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    inline_images, trailing_image = _load_images(report)
    images = inline_images + ([] if trailing_image is None else [trailing_image])
    header, footer = report["header"], report["footer"]
    styles_payload = _styles_for_report(report)
    manifest_payload = (
        render_document_manifest(report)
        if report.get("document_spec_version") is not None
        else None
    )
    modern_settings = manifest_payload is not None
    parts = {
        "[Content_Types].xml": _content_types(
            images,
            header=header,
            footer=footer,
            manifest=manifest_payload is not None,
            settings=modern_settings,
        ),
        "_rels/.rels": _package_relationships(manifest=manifest_payload is not None),
        "docProps/app.xml": _app_properties(),
        "docProps/core.xml": _core_properties(report["metadata"]),
        "word/_rels/document.xml.rels": _document_relationships(
            images,
            header=header,
            footer=footer,
            settings=modern_settings,
        ),
        "word/document.xml": _document(report, inline_images, trailing_image),
        "word/numbering.xml": _numbering(),
        "word/styles.xml": styles_payload,
    }
    if modern_settings:
        parts["word/settings.xml"] = _settings()
    if manifest_payload is not None:
        parts["docProps/custom.xml"] = manifest_payload
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
        "styles": {
            "sha256": sha256(styles_payload).hexdigest(),
            "style_ids": sorted(
                node.attrib.get(qn("w", "styleId"))
                for node in fromstring(styles_payload).findall(qn("w", "style"))
                if node.attrib.get(qn("w", "styleId")) is not None
            ),
            "profile": public_style_profile(report.get("style_profile")),
        },
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
    for marker_id, block in enumerate(report["blocks"], start=1):
        if block["type"] == "heading":
            rendered = paragraph(
                block["text"],
                style=block.get("style", f"Heading{block['level']}"),
            )
        elif block["type"] == "paragraph":
            rendered = paragraph(block["text"], style=block["style"])
        elif block["type"] == "image":
            rendered = _created_image_paragraph(next(pending))
            if block.get("style") is not None:
                set_paragraph_style(rendered, block["style"])
        elif block["type"] == "reference":
            rendered = reference_paragraph(block)
        elif block["type"] == "equation":
            rendered = equation_paragraph(block)
        else:
            rendered = table_element(block)
        if block.get("node_id") is not None:
            attach_semantic_node_marker(
                rendered,
                node_id=block["node_id"],
                node_type=block["node_type"],
                marker_id=marker_id,
            )
        if block.get("bookmark") is not None:
            attach_reference_bookmark(
                rendered,
                block["bookmark"],
                bookmark_id=10_000 + marker_id,
            )
        body.append(rendered)
    if trailing_image is not None:
        body.append(_created_image_paragraph(trailing_image))
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


def _created_image_paragraph(image: dict[str, Any]) -> Element:
    return image_paragraph(
        image,
        document_properties_id=image["position"],
        document_name="Report image",
        picture_properties_id=image["position"] - 1,
        picture_name=f"image{image['position']}",
    )


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
    manifest: bool,
    settings: bool,
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
    if manifest:
        overrides["/docProps/custom.xml"] = (
            "application/vnd.openxmlformats-officedocument.custom-properties+xml"
        )
    if settings:
        overrides["/word/settings.xml"] = CT_SETTINGS
    if footer is not None:
        overrides["/word/footer1.xml"] = CT_FOOTER
    if header is not None:
        overrides["/word/header1.xml"] = CT_HEADER
    for part, content_type in sorted(overrides.items()):
        SubElement(root, f"{{{CONTENT_TYPES_NS}}}Override", {"PartName": part, "ContentType": content_type})
    return xml_bytes(root)


def _relationships(entries: list[tuple[str, str, str]]) -> bytes:
    # LibreOffice rejects otherwise-valid OPC relationship parts when these
    # elements use an explicit ``rels:`` prefix.  Emit the package namespace
    # as the default namespace for broad consumer compatibility.
    root = Element("Relationships", {"xmlns": NS["rels"]})
    for relationship_id, relationship_type, target in entries:
        SubElement(
            root,
            "Relationship",
            {"Id": relationship_id, "Type": relationship_type, "Target": target},
        )
    return xml_bytes(root)


def _package_relationships(*, manifest: bool) -> bytes:
    entries = [
        ("rId1", REL_OFFICE_DOCUMENT, "word/document.xml"),
        ("rId2", REL_CORE_PROPERTIES, "docProps/core.xml"),
        ("rId3", REL_EXTENDED_PROPERTIES, "docProps/app.xml"),
    ]
    if manifest:
        entries.append(
            ("rId4", REL_CUSTOM_PROPERTIES, "docProps/custom.xml")
        )
    return _relationships(entries)


def _document_relationships(
    images: list[dict[str, Any]],
    *,
    header: str | None,
    footer: str | None,
    settings: bool,
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
    if settings:
        entries.append(("rIdSettings", REL_SETTINGS, "settings.xml"))
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


def _settings() -> bytes:
    root = Element(qn("w", "settings"))
    compatibility = SubElement(root, qn("w", "compat"))
    SubElement(
        compatibility,
        qn("w", "compatSetting"),
        {
            qn("w", "name"): "compatibilityMode",
            qn("w", "uri"): "http://schemas.microsoft.com/office/word",
            qn("w", "val"): "15",
        },
    )
    return xml_bytes(root)


def _max_heading_level(report: dict[str, Any]) -> int:
    """How many heading styles the package has to carry."""
    levels = [
        block["level"] for block in report["blocks"] if block["type"] == "heading"
    ]
    return max(MIN_HEADING_STYLES, *levels) if levels else MIN_HEADING_STYLES


def _styles_for_report(report: dict[str, Any]) -> bytes:
    profile = report.get("style_profile")
    if profile is not None:
        return render_style_profile(profile)
    return _styles(
        _max_heading_level(report),
        include_title=any(
            block.get("node_type") == "title" for block in report["blocks"]
        ),
    )


def _styles(max_heading_level: int, *, include_title: bool = False) -> bytes:
    root = Element(qn("w", "styles"))
    entries = [("Normal", "Normal", "22", False)]
    if include_title:
        entries.append(("Title", "Title", "32", True))
    entries.extend(
        (f"Heading{level}", f"heading {level}", HEADING_SIZES[level - 1], True)
        for level in range(1, max_heading_level + 1)
    )
    entries.append(("TableGrid", "Table Grid", "22", False))
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
