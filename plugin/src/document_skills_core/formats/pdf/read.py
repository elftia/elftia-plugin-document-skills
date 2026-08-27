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
from .constants import MAX_CONTENT_STREAM_OPERATORS
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

    all_pages = walk_pages(model)
    max_pages = arguments.get("max_pages", 10_000)
    max_blocks = arguments.get("max_blocks_per_page", 5_000)
    include_annotations = arguments.get("include_annotations", True)
    include_forms = arguments.get("include_forms", True)
    include_embedded = arguments.get("include_embedded_files", True)

    warnings: list[dict[str, Any]] = []
    requested_pages = arguments.get("pages")
    if requested_pages is None:
        pages = list(all_pages)
    else:
        by_number = {page.page_number: page for page in all_pages}
        missing = [page for page in requested_pages if page not in by_number]
        if missing:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Requested PDF read page is outside the document.",
                status="invalid_request",
                details={"pages": missing, "page_count": len(all_pages)},
            )
        pages = [by_number[page] for page in requested_pages]
    if len(pages) > max_pages:
        pages = pages[:max_pages]
        warnings.append({
            "code": "DS_PDF_READ_TRUNCATED",
            "message": "Page count exceeded the caller-selected limit.",
            "details": {"affected": "pages", "limit": max_pages},
        })

    page_infos = [project_page_info(p) for p in pages]
    document_info = project_document_info(model)
    info_dict = project_info_dictionary(model)
    xmp_present = project_xmp_presence(model)

    # Fonts and images per page
    fonts_by_page: list[list[dict[str, Any]]] = []
    images_by_page: list[list[dict[str, Any]]] = []
    type0_fonts_by_page: dict[int, set[str]] = {}
    for page in pages:
        fonts = inventory_fonts(model, page.resources)
        images = inventory_images(model, page.resources)
        fonts_by_page.append(project_font_summary(fonts))
        images_by_page.append(project_image_summary(images))
        type0_fonts_by_page[page.page_number] = {
            font.name for font in fonts if font.type == "/Type0"
        }

    # Text content
    text_blocks: list[Any] = []
    omitted_by_page: dict[int, int] = {}
    truncated_pages: set[int] = set()
    for page in pages:
        # The operator walker already enforces the bounded parser ceiling.
        # Process one page at a time so semantic filtering can precede the
        # public projection limit without retaining the raw blocks from every
        # selected page at once.
        page_blocks = map_text_blocks(
            model,
            [page],
            max_blocks_per_page=MAX_CONTENT_STREAM_OPERATORS,
        )
        page_blocks, page_omissions = _omit_unmapped_type0_text(
            page_blocks,
            type0_fonts_by_page,
        )
        omitted_by_page.update(page_omissions)
        page_blocks, page_truncations = _limit_text_blocks(page_blocks, max_blocks)
        truncated_pages.update(page_truncations)
        text_blocks.extend(page_blocks)
    if omitted_by_page:
        warnings.append({
            "code": "DS_PDF_TEXT_EXTRACTION_UNAVAILABLE",
            "message": "Text blocks without a proven semantic mapping were omitted.",
            "details": {
                "affected": "text_blocks",
                "omitted": sum(omitted_by_page.values()),
                "pages": sorted(omitted_by_page),
            },
        })
    if truncated_pages:
        warnings.append({
            "code": "DS_PDF_READ_TRUNCATED",
            "message": "Text blocks exceeded the caller-selected per-page limit.",
            "details": {
                "affected": "text_blocks",
                "limit": max_blocks,
                "pages": sorted(truncated_pages),
            },
        })
    text_blocks = _select_text_blocks(text_blocks, pages, arguments)
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
        "document_page_count": len(all_pages),
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
                "reading_order_index": index,
            }
            for index, block in enumerate(text_blocks)
        ],
        "text_by_page": text_by_page,
        "text_selection": {
            "pages": [page.page_number for page in pages],
            "bbox": arguments.get("bbox"),
            "bbox_mode": "intersects",
            "reading_order": arguments.get("reading_order", "content_stream"),
            "column_count": arguments.get("column_count"),
            "source": "content-stream-operators",
        },
        "acroform_fields": fields,
        "annotations": annotations,
        "outlines": outline_list,
        "page_labels": project_page_labels(model, len(pages)),
        "embedded_files": embedded_files,
    }
    return operation_result, warnings


def _omit_unmapped_type0_text(
    blocks: list[Any],
    type0_fonts_by_page: dict[int, set[str]],
) -> tuple[list[Any], dict[int, int]]:
    kept: list[Any] = []
    omitted_by_page: dict[int, int] = {}
    for block in blocks:
        type0_fonts = type0_fonts_by_page.get(block.page, set())
        if block.font_name in type0_fonts and not block.semantic_text:
            omitted_by_page[block.page] = omitted_by_page.get(block.page, 0) + 1
            continue
        kept.append(block)
    return kept, omitted_by_page


def _limit_text_blocks(
    blocks: list[Any],
    limit: int,
) -> tuple[list[Any], set[int]]:
    kept: list[Any] = []
    counts: dict[int, int] = {}
    truncated_pages: set[int] = set()
    for block in blocks:
        count = counts.get(block.page, 0)
        counts[block.page] = count + 1
        if count >= limit:
            truncated_pages.add(block.page)
            continue
        kept.append(block)
    return kept, truncated_pages


def _select_text_blocks(
    blocks: list[Any],
    pages: list[Any],
    arguments: dict[str, Any],
) -> list[Any]:
    bbox = arguments.get("bbox")
    if bbox is not None:
        blocks = [block for block in blocks if _intersects(block.bbox, bbox)]
    reading_order = arguments.get("reading_order", "content_stream")
    if reading_order == "content_stream":
        return blocks
    page_order = {page.page_number: index for index, page in enumerate(pages)}
    if reading_order == "geometric":
        return sorted(
            blocks,
            key=lambda block: (
                page_order[block.page],
                -float(block.bbox[3]),
                float(block.bbox[0]),
            ),
        )
    column_count = int(arguments["column_count"])
    page_boxes = {
        page.page_number: page.crop_box or page.media_box
        for page in pages
    }
    return sorted(
        blocks,
        key=lambda block: (
            page_order[block.page],
            _column_index(block.bbox, page_boxes[block.page], column_count),
            -float(block.bbox[3]),
            float(block.bbox[0]),
        ),
    )


def _intersects(
    block: tuple[float, float, float, float],
    selection: list[float],
) -> bool:
    return not (
        block[2] <= selection[0]
        or block[0] >= selection[2]
        or block[3] <= selection[1]
        or block[1] >= selection[3]
    )


def _column_index(
    block: tuple[float, float, float, float],
    page_box: tuple[float, float, float, float],
    column_count: int,
) -> int:
    left = float(page_box[0])
    width = max(float(page_box[2]) - left, 1.0)
    center = (float(block[0]) + float(block[2])) / 2.0
    normalized = min(max((center - left) / width, 0.0), 0.999999)
    return int(normalized * column_count)


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
