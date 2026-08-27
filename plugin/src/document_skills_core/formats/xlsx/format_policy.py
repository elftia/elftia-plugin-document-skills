"""SpreadsheetML extension, template transition, and inert-content policy."""

from __future__ import annotations

from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


READ_FORMATS = frozenset({"xlsx", "xlsm"})
TEMPLATE_OUTPUTS = {"xltx": "xlsx", "xltm": "xlsm"}


def format_id(path: str | Path) -> str:
    return Path(path).suffix.casefold().lstrip(".")


def allowed_inert_categories(workbook_format: str) -> frozenset[str] | None:
    if workbook_format == "xlsm":
        return frozenset({"vba"})
    if workbook_format == "xltx":
        return frozenset({"templates"})
    if workbook_format == "xltm":
        return frozenset({"templates", "vba"})
    return None


def assert_package_matches_path(path: str | Path, package_format: str) -> None:
    declared = format_id(path)
    if declared != package_format:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "SpreadsheetML extension does not match its workbook main content type.",
            details={
                "path_format": declared,
                "package_format": package_format,
            },
        )
