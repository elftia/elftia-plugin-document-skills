"""Small shared helpers for XLSX service result orchestration."""

from typing import Any

from .recalculation_service import RecalculationOutcome


def outcome_provider(outcome: RecalculationOutcome) -> str | None:
    return "libreoffice" if outcome.provider_chain else None


def formula_degradations(
    degraded: bool,
    semantic_difference: str,
) -> list[dict[str, Any]]:
    if not degraded:
        return []
    return [{
        "code": "outstanding-formula-recalculation",
        "semantic_difference": semantic_difference,
        "missing_capabilities": ["recalculation"],
        "recommended_providers": ["libreoffice"],
    }]


def allowed_removed_parts(
    edits: list[dict[str, Any]],
    removed_parts: tuple[str, ...],
) -> set[str]:
    removable = {"sheet_delete", "table_delete", "chart_delete", "comment_delete"}
    return (
        set(removed_parts)
        if any(edit["type"] in removable for edit in edits)
        else set()
    )
