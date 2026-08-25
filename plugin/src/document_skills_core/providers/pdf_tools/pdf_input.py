"""Shared reject-mode PDF page selection for optional external providers."""

from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.actions import (
    classify_actions,
    has_dangerous_actions,
    has_executable_embedded_files,
)
from document_skills_core.formats.pdf.byte_preflight import PdfByteLimits, preflight_pdf
from document_skills_core.formats.pdf.object_model import PdfDict, PdfObjectModel, parse_pdf
from document_skills_core.formats.pdf.page_tree import PageInfo, walk_pages


def safe_selected_pages(
    source: Path,
    requested: list[int] | None,
    *,
    max_selected_pages: int,
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
        selected = pages
    else:
        by_number = {page.page_number: page for page in pages}
        missing = [number for number in requested if number not in by_number]
        if missing:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Requested page is outside the document.",
                status="invalid_request",
                details={"pages": missing, "page_count": len(pages)},
            )
        selected = [by_number[number] for number in requested]
    if len(selected) > max_selected_pages:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Selected page count exceeds the optional provider limit.",
            status="invalid_request",
            details={
                "selected_page_count": len(selected),
                "max_selected_pages": max_selected_pages,
            },
        )
    _reject_nondefault_user_units(model, selected)
    return model, selected


def _reject_nondefault_user_units(
    model: PdfObjectModel,
    pages: list[PageInfo],
) -> None:
    unsupported: list[int] = []
    for page in pages:
        page_object = model.objects.get(page.obj_num)
        value = page_object.value if page_object is not None else None
        if not isinstance(value, PdfDict) or "/UserUnit" not in value:
            continue
        user_unit = value.get("/UserUnit")
        if (
            (type(user_unit) is not int and type(user_unit) is not float)
            or float(user_unit) != 1.0
        ):
            unsupported.append(page.page_number)
    if unsupported:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Optional PDF providers do not accept non-default /UserUnit pages.",
            status="enhancement_required",
            details={"pages": unsupported},
        )
