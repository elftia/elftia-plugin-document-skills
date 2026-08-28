"""Ownership checks for page-scoped PDF content-stream rewrites."""

from collections.abc import Iterable
from typing import Protocol

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import PdfObjectModel
from .page_tree import walk_pages


class ContentTarget(Protocol):
    """Minimal locator surface needed by the ownership gate."""

    page_number: int
    content_object: int


def require_page_exclusive_content(
    model: PdfObjectModel,
    targets: Iterable[ContentTarget],
) -> None:
    """Fail closed when a selected content object belongs to another page."""
    owners: dict[int, set[int]] = {}
    for page in walk_pages(model):
        for reference in page.contents:
            owners.setdefault(reference.obj_num, set()).add(page.page_number)
    conflicts = [
        {
            "content_object": target.content_object,
            "target_page": target.page_number,
            "owner_pages": sorted(owners.get(target.content_object, set())),
        }
        for target in targets
        if owners.get(target.content_object, set()) != {target.page_number}
    ]
    if conflicts:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Page-scoped rewrite requires an exclusively owned content stream.",
            status="enhancement_required",
            details={
                "capability": "pdf.rewrite-shared-content-clone",
                "shared_content_targets": conflicts,
            },
        )
