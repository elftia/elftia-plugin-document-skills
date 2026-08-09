"""Formula/cached-value recalculation-state model — the XLSX differentiator.

Closed four-state enum: recalculated, stale, never_calculated, recalculation_required.
`recalculated` is FORBIDDEN unless an accepted recalculation provider (LibreOffice)
actually recomputed the formula. Without it, recalculation reports `unavailable`.
"""

import re
from typing import Any

from .constants import (
    FORMULA_STATE_RECALCULATED,
    FORMULA_STATE_STALE,
    FORMULA_STATE_NEVER_CALCULATED,
    FORMULA_STATE_RECALCULATION_REQUIRED,
    FORMULA_STATES,
)


def is_valid_state(state: str) -> bool:
    return state in FORMULA_STATES


def derive_read_state(
    *,
    has_cached_value: bool,
    full_calc_on_load: bool = False,
    recalculation_provider: str | None = None,
) -> str:
    """Derive the recalculation state for a formula cell on read.

    Without an accepted recalculation provider, no formula ever reports `recalculated`.
    """
    if recalculation_provider is not None:
        if has_cached_value and not full_calc_on_load:
            return FORMULA_STATE_RECALCULATED
    if not has_cached_value:
        return FORMULA_STATE_NEVER_CALCULATED
    if full_calc_on_load:
        return FORMULA_STATE_STALE
    # Has cached value, no provider, no staleness signal — report stale because
    # we cannot verify the cached value was recalculated by an accepted provider.
    return FORMULA_STATE_STALE


def derive_create_state(*, has_cached_value: bool) -> str:
    """Derive the recalculation state for a newly created formula."""
    if has_cached_value:
        return FORMULA_STATE_STALE
    return FORMULA_STATE_RECALCULATION_REQUIRED


def derive_edit_state() -> str:
    """Derive the recalculation state for an edited formula or invalidated dependent."""
    return FORMULA_STATE_RECALCULATION_REQUIRED


# Formula reference parsing for dependent invalidation
_CELL_REF_RE = re.compile(
    r"(?:(?P<sheet>'[^']*'|[A-Za-z_][A-Za-z0-9_.]*)!)?"  # optional sheet
    r"\$?(?P<col>[A-Z]{1,3})"  # column
    r"\$?(?P<row>\d+)",  # row
    re.VERBOSE,
)
_RANGE_RE = re.compile(
    r"(?:(?P<sheet>'[^']*'|[A-Za-z_][A-Za-z0-9_.]*)!)?"  # optional sheet
    r"\$?(?P<col1>[A-Z]{1,3})\$?(?P<row1>\d+)"
    r":"
    r"\$?(?P<col2>[A-Z]{1,3})\$?(?P<row2>\d+)",
    re.VERBOSE,
)


def parse_formula_references(formula: str) -> set[str]:
    """Parse cell and range references from a formula string.

    Returns a set of normalized cell references (e.g. ``Sheet1!A1`` or ``A1``).
    """
    refs: set[str] = set()
    # Remove function names and operators to avoid false positives
    # by extracting only uppercase letter sequences followed by digits
    for match in _RANGE_RE.finditer(formula):
        sheet = match.group("sheet") or ""
        if sheet:
            sheet = sheet + "!"
        col1 = match.group("col1")
        row1 = int(match.group("row1"))
        col2 = match.group("col2")
        row2 = int(match.group("row2"))
        for col, row in _expand_range(col1, row1, col2, row2):
            refs.add(f"{sheet}{col}{row}")
    for match in _CELL_REF_RE.finditer(formula):
        # Skip if this match is part of a range (already captured)
        start = match.start()
        end = match.end()
        # Check if preceded by a colon range — heuristic: the range regex handles it
        sheet = match.group("sheet") or ""
        if sheet:
            sheet = sheet + "!"
        col = match.group("col")
        row = match.group("row")
        ref = f"{sheet}{col}{row}"
        refs.add(ref)
    return refs


def _expand_range(col1: str, row1: int, col2: str, row2: int):
    c1 = _col_to_num(col1)
    c2 = _col_to_num(col2)
    r1, r2 = min(row1, row2), max(row1, row2)
    c1, c2 = min(c1, c2), max(c1, c2)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            yield _num_to_col(c), r


def _col_to_num(col: str) -> int:
    result = 0
    for char in col.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def _num_to_col(num: int) -> str:
    result = ""
    while num > 0:
        num, rem = divmod(num - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def normalize_ref(ref: str) -> str:
    """Normalize a cell reference by removing $ markers."""
    return ref.replace("$", "")


def build_formula_cell_state(
    *,
    state: str,
    formula: str,
    cached_value: str | None = None,
    precedents_count: int = 0,
    dependents_count: int = 0,
) -> dict[str, Any]:
    """Build a per-cell formula-state record."""
    return {
        "state": state,
        "formula": formula,
        "cached_value": cached_value,
        "precedents_count": precedents_count,
        "dependents_count": dependents_count,
    }


def build_formula_state_summary(
    cells: dict[str, dict[str, Any]],
    *,
    recalculation_provider: str | None = None,
) -> dict[str, Any]:
    """Build the formula-state summary with counts and invariant flag.

    The invariant ``no_unverified_claimed_recalculated`` is ``True`` when no cell
    reports ``recalculated`` without an accepted recalculation provider.
    """
    counts: dict[str, int] = {s: 0 for s in FORMULA_STATES}
    outstanding = 0
    has_unverified_recalculated = False
    for record in cells.values():
        state = record["state"]
        counts[state] = counts.get(state, 0) + 1
        if state == FORMULA_STATE_RECALCULATION_REQUIRED:
            outstanding += 1
        if state == FORMULA_STATE_RECALCULATED and recalculation_provider is None:
            has_unverified_recalculated = True
    return {
        "counts": counts,
        "outstanding_recalculation_required": outstanding,
        "recalculation_provider": recalculation_provider or "unavailable",
        "no_unverified_claimed_recalculated": not has_unverified_recalculated,
    }


def assert_invariant(
    cells: dict[str, dict[str, Any]],
    *,
    recalculation_provider: str | None = None,
) -> None:
    """Assert the formula-state invariant: no unverified recalculated.

    Raises ValueError if any cell reports ``recalculated`` without an accepted provider.
    """
    if recalculation_provider is not None:
        return
    for ref, record in cells.items():
        if record["state"] == FORMULA_STATE_RECALCULATED:
            raise ValueError(
                f"Formula-state invariant violated: cell {ref} reports recalculated "
                "without an accepted recalculation provider."
            )


def should_downgrade(summary: dict[str, Any]) -> bool:
    """Return True if the result should be degraded due to outstanding recalculation."""
    return summary["outstanding_recalculation_required"] > 0
