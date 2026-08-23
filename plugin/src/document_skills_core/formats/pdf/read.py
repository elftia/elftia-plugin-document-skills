"""Structured PDF read operation.

Reads page count, page boxes, metadata, outlines, fonts, images, text content,
AcroForm fields, annotations, and embedded files into a deterministic structured
result.  Uses normal reject-mode security policy.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
from .byte_preflight import PdfByteLimits, preflight_pdf
from .mapping import (
    map_acroform_fields,
    map_annotations,
    map_embedded_files,
    map_outlines,
    map_text_blocks,
)
from .object_model import parse_pdf
from .page_labels import project_page_labels
from .page_tree import walk_pages
from .projection import (
    project_document_info,
    project_font_summary,
    project_image_summary,
    project_info_dictionary,
    project_page_info,
    project_xmp_presence,
)
from .resources import inventory_fonts, inventory_images


def read_pdf(path, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a PDF into a structured projection.

    Returns (operation_result, warnings).
    Raises ARCHIVE_UNSAFE for active/external content.
    """
    limits = PdfByteLimits()
    preflight = preflight_pdf(path, limits)
    if preflight.encrypted:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF is encrypted; use explicit pdf.decrypt before structured reading.",
        )
    model = parse_pdf(path, limits)
    # Security check: reject documents with dangerous actions
    actions = classify_actions(model)
    if has_dangerous_actions(actions):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF contains JavaScript/Launch/URI/GoToR actions; use pdf.inspect.structure for inert inventory.",
            details={"action_count": len(actions)},
        )
    if has_executable_embedded_files(model):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF contains an embedded executable.",
        )

    pages = walk_pages(model)
    max_pages = arguments.get("max_pages", 10_000)
    max_blocks = arguments.get("max_blocks_per_page", 5_000)
    include_annotations = arguments.get("include_annotations", True)
    include_forms = arguments.get("include_forms", True)
    include_embedded = arguments.get("include_embedded_files", True)

    warnings: list[dict[str, Any]] = []
    if len(pages) > max_pages:
        pages = pages[:max_pages]
        warnings.append({
            "code": "truncation",
            "message": "Page count exceeded the caller-selected limit.",
            "affected": "pages",
        })

    page_infos = [project_page_info(p) for p in pages]
    document_info = project_document_info(model)
    info_dict = project_info_dictionary(model)
    xmp_present = project_xmp_presence(model)

    # Fonts and images per page
    fonts_by_page: list[list[dict[str, Any]]] = []
    images_by_page: list[list[dict[str, Any]]] = []
    for page in pages:
        fonts = inventory_fonts(model, page.resources)
        images = inventory_images(model, page.resources)
        fonts_by_page.append(project_font_summary(fonts))
        images_by_page.append(project_image_summary(images))

    # Text content
    text_blocks = map_text_blocks(model, pages, max_blocks_per_page=max_blocks)
    text_by_page: list[dict[str, Any]] = []
    for page in pages:
        page_blocks = [b for b in text_blocks if b.page == page.page_number]
        if page_blocks:
            text_by_page.append({
                "page": page.page_number,
                "text": "\n".join(b.text for b in page_blocks),
                "block_count": len(page_blocks),
                "text_extraction": "embedded",
            })
        else:
            text_by_page.append({
                "page": page.page_number,
                "text": "",
                "block_count": 0,
                "text_extraction": "text_extraction_unavailable",
            })

    # AcroForm
    fields = []
    if include_forms:
        field_infos = map_acroform_fields(model)
        fields = [
            {
                "qualified_name": f.qualified_name,
                "field_type": f.field_type,
                "flags": f.flags,
                "value_type": f.value_type,
                "value": f.value,
                "default_value": f.default_value,
                "required": f.required,
                "readonly": f.readonly,
                "options": list(f.options),
                "page": f.page,
                "widget": f.widget,
                "has_appearance": f.has_appearance,
                "annotation_rect": list(f.annotation_rect) if f.annotation_rect else None,
            }
            for f in field_infos
        ]

    # Annotations
    annotations = []
    if include_annotations:
        annot_infos = map_annotations(model, pages)
        annotations = [
            {
                "page": a.page,
                "index": a.index,
                "subtype": a.subtype,
                "rectangle": list(a.rectangle) if a.rectangle else None,
                "contents": a.contents,
                "title": a.title,
                "color": list(a.color) if a.color else None,
                "action_kind": a.action_kind,
            }
            for a in annot_infos
        ]

    # Outlines
    outlines = map_outlines(model)
    outline_list = [{"title": o.title, "destination_page": o.destination_page} for o in outlines]

    # Embedded files
    embedded_files = []
    if include_embedded:
        ef_infos = map_embedded_files(model)
        embedded_files = [
            {
                "relationship": e.relationship,
                "filename": e.filename,
                "mime_type": e.mime_type,
                "size": e.size,
            }
            for e in ef_infos
        ]

    operation_result: dict[str, Any] = {
        "metadata": _project_uniform_metadata(info_dict),
        "document": document_info,
        "info_dictionary": info_dict,
        "xmp_present": xmp_present,
        "page_count": len(pages),
        "pages": page_infos,
        "fonts_by_page": fonts_by_page,
        "images_by_page": images_by_page,
        "text_blocks": [
            {
                "page": block.page,
                "bbox": list(block.bbox),
                "text": block.text,
                "font": block.font_name,
                "size": block.font_size,
                "color": list(block.color),
            }
            for block in text_blocks
        ],
        "text_by_page": text_by_page,
        "acroform_fields": fields,
        "annotations": annotations,
        "outlines": outline_list,
        "page_labels": project_page_labels(model, len(pages)),
        "embedded_files": embedded_files,
    }
    return operation_result, warnings


def _project_uniform_metadata(info_dict: dict[str, Any]) -> dict[str, str | None]:
    """Project the uniform metadata block from the PDF Info dictionary.

    Maps the PDF-specific keys (``title``, ``author``, ``subject``,
    ``keywords``, ``creation_date``, ``mod_date``) into the uniform shape
    (``title``, ``creator``, ``created``, ``modified``, ``subject``,
    ``keywords``).  Missing fields are ``None``.
    """
    return {
        "title": info_dict.get("title") or None,
        "creator": info_dict.get("author") or info_dict.get("creator") or None,
        "created": info_dict.get("creation_date") or None,
        "modified": info_dict.get("mod_date") or None,
        "subject": info_dict.get("subject") or None,
        "keywords": info_dict.get("keywords") or None,
    }
