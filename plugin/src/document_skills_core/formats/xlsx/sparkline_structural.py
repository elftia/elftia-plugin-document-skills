"""Reference migration for native x14 worksheet sparklines."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .structural_refs import (
    AxisMutation,
    has_external_workbook_reference,
    rewrite_reference,
)

_XM_NS = "http://schemas.microsoft.com/office/excel/2006/main"


def rewrite_sparkline_references(context: Any, mutation: AxisMutation) -> None:
    for sheet_name, part in sorted(context.sheet_parts.items()):
        root = context.worksheet(part)
        changed = False
        for formula in root.findall(f".//{{{_XM_NS}}}f"):
            original = formula.text or ""
            if has_external_workbook_reference(original):
                _enhancement(
                    "Structural edits do not rewrite external-workbook sparkline formulas.",
                    capability="xlsx.external-reference-structural-edit",
                    part=part,
                )
            rewritten = rewrite_reference(
                original,
                current_sheet=None,
                mutation=mutation,
            )
            if "#REF!" in rewritten:
                _enhancement(
                    "Structural edit would invalidate a sparkline data range.",
                    capability="xlsx.sparkline-structural-edit",
                    part=part,
                )
            if rewritten != original:
                formula.text = rewritten
                changed = True
        if sheet_name.casefold() == mutation.sheet.casefold():
            changed = _rewrite_locations(root, sheet_name, part, mutation) or changed
        if changed:
            context.mark_dirty(part)


def _rewrite_locations(
    root: Any,
    sheet_name: str,
    part: str,
    mutation: AxisMutation,
) -> bool:
    changed = False
    for location in root.findall(f".//{{{_XM_NS}}}sqref"):
        original = location.text or ""
        rewritten = rewrite_reference(
            original,
            current_sheet=sheet_name,
            mutation=mutation,
        )
        if rewritten == "#REF!":
            _enhancement(
                "Structural edit would remove a sparkline location.",
                capability="xlsx.sparkline-structural-edit",
                part=part,
            )
        if rewritten != original:
            location.text = rewritten
            changed = True
    return changed


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
