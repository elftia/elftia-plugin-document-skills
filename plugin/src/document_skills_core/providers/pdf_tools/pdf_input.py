"""Shared reject-mode PDF page selection for optional external providers."""

from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.actions import (
    classify_actions,
    has_dangerous_actions,
    has_executable_embedded_files,
)
from document_skills_core.formats.pdf.byte_preflight import PdfByteLimits, preflight_pdf
from document_skills_core.formats.pdf.object_model import PdfObjectModel, parse_pdf
from document_skills_core.formats.pdf.page_tree import PageInfo, walk_pages


def safe_selected_pages(
    source: Path,
    requested: list[int] | None,
) -> tuple[PdfObjectModel, list[PageInfo]]:
    limits = PdfByteLimits()
    preflight = preflight_pdf(source, limits)
    if preflight.encrypted:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Explicit decryption is required before render or OCR.",
        )
    model = parse_pdf(source, limits)
    actions = classify_actions(model)
    if has_dangerous_actions(actions) or has_executable_embedded_files(model):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF contains active or executable content and is rejected in normal mode.",
        )
    pages = walk_pages(model)
    if requested is None:
        return model, pages
    by_number = {page.page_number: page for page in pages}
    missing = [number for number in requested if number not in by_number]
    if missing:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Requested page is outside the document.",
            status="invalid_request",
            details={"pages": missing, "page_count": len(pages)},
        )
    return model, [by_number[number] for number in requested]
