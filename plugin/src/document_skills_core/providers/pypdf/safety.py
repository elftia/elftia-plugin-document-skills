"""Core-equivalent fail-closed safety gate for pypdf mutation inputs."""

from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.actions import (
    classify_actions,
    has_dangerous_actions,
    has_executable_embedded_files,
)
from document_skills_core.formats.pdf.byte_preflight import PdfByteLimits, preflight_pdf
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages


def assert_core_safe_pdf(path: Path) -> None:
    """Fully parse an unencrypted PDF and reject active/executable content."""
    limits = PdfByteLimits()
    preflight = preflight_pdf(path, limits)
    if preflight.encrypted:
        _unsafe("pypdf mutation safety validation requires an unencrypted PDF.")
    model = parse_pdf(path, limits)
    if model.trailer.encrypt is not None:
        _unsafe("pypdf mutation safety validation found an encryption dictionary.")
    actions = classify_actions(model)
    if has_dangerous_actions(actions) or has_executable_embedded_files(model):
        _unsafe("pypdf mutation rejects active, external, or executable content.")
    walk_pages(model)


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
