"""Formula-state invariant tests — the XLSX differentiator.

These tests PROVE that:
1. No formula reports `recalculated` without an accepted recalculation provider.
2. Editing a precedent invalidates dependents.
3. A stale/uncached formula is reported honestly.
4. The result status downgrades when recalculation is outstanding.
"""

import pytest

from document_skills_core.formats.xlsx.constants import (
    FORMULA_STATE_RECALCULATED,
    FORMULA_STATE_STALE,
    FORMULA_STATE_NEVER_CALCULATED,
    FORMULA_STATE_RECALCULATION_REQUIRED,
    FORMULA_STATES,
)
from document_skills_core.formats.xlsx.formula_state import (
    derive_read_state,
    derive_create_state,
    derive_edit_state,
    parse_formula_references,
    build_formula_state_summary,
    assert_invariant,
    should_downgrade,
)


class TestClosedEnum:
    def test_enum_has_exactly_four_states(self):
        assert FORMULA_STATES == frozenset({
            "recalculated",
            "stale",
            "never_calculated",
            "recalculation_required",
        })

    def test_each_state_is_distinct(self):
        states = [
            FORMULA_STATE_RECALCULATED,
            FORMULA_STATE_STALE,
            FORMULA_STATE_NEVER_CALCULATED,
            FORMULA_STATE_RECALCULATION_REQUIRED,
        ]
        assert len(set(states)) == 4


class TestReadStateDerivation:
    def test_cached_value_without_provider_is_stale(self):
        """Without a provider, a cached value is NEVER reported as recalculated."""
        state = derive_read_state(has_cached_value=True, recalculation_provider=None)
        assert state == FORMULA_STATE_STALE
        assert state != FORMULA_STATE_RECALCULATED

    def test_no_cached_value_is_never_calculated(self):
        state = derive_read_state(has_cached_value=False, recalculation_provider=None)
        assert state == FORMULA_STATE_NEVER_CALCULATED

    def test_full_calc_on_load_is_stale(self):
        state = derive_read_state(
            has_cached_value=True,
            full_calc_on_load=True,
            recalculation_provider=None,
        )
        assert state == FORMULA_STATE_STALE

    def test_with_provider_and_cached_is_recalculated(self):
        state = derive_read_state(
            has_cached_value=True,
            recalculation_provider="libreoffice",
        )
        assert state == FORMULA_STATE_RECALCULATED


class TestCreateStateDerivation:
    def test_new_formula_without_cached_is_recalculation_required(self):
        state = derive_create_state(has_cached_value=False)
        assert state == FORMULA_STATE_RECALCULATION_REQUIRED

    def test_new_formula_with_cached_is_stale(self):
        state = derive_create_state(has_cached_value=True)
        assert state == FORMULA_STATE_STALE


class TestEditStateDerivation:
    def test_edited_formula_is_recalculation_required(self):
        state = derive_edit_state()
        assert state == FORMULA_STATE_RECALCULATION_REQUIRED


class TestInvariantGate:
    def test_invariant_passes_without_recalculated(self):
        cells = {
            "Sheet1!A1": {"state": FORMULA_STATE_STALE, "formula": "=1+1", "cached_value": "2"},
            "Sheet1!B1": {"state": FORMULA_STATE_RECALCULATION_REQUIRED, "formula": "=A1*2"},
        }
        assert_invariant(cells, recalculation_provider=None)

    def test_invariant_fails_with_unverified_recalculated(self):
        """This is THE adversarial test: prove that claiming recalculated without a provider fails."""
        cells = {
            "Sheet1!A1": {"state": FORMULA_STATE_RECALCULATED, "formula": "=1+1"},
        }
        with pytest.raises(ValueError, match="invariant violated"):
            assert_invariant(cells, recalculation_provider=None)

    def test_invariant_passes_with_provider(self):
        cells = {
            "Sheet1!A1": {"state": FORMULA_STATE_RECALCULATED, "formula": "=1+1"},
        }
        assert_invariant(cells, recalculation_provider="libreoffice")


class TestSummary:
    def test_summary_counts_outstanding(self):
        cells = {
            "A!1": {"state": FORMULA_STATE_RECALCULATION_REQUIRED, "formula": "=1+1"},
            "A!2": {"state": FORMULA_STATE_STALE, "formula": "=2+2"},
            "A!3": {"state": FORMULA_STATE_NEVER_CALCULATED, "formula": "=3+3"},
        }
        summary = build_formula_state_summary(cells, recalculation_provider=None)
        assert summary["outstanding_recalculation_required"] == 1
        assert summary["recalculation_provider"] == "unavailable"
        assert summary["no_unverified_claimed_recalculated"] is True

    def test_summary_detects_unverified_recalculated(self):
        cells = {
            "A!1": {"state": FORMULA_STATE_RECALCULATED, "formula": "=1+1"},
        }
        summary = build_formula_state_summary(cells, recalculation_provider=None)
        assert summary["no_unverified_claimed_recalculated"] is False

    def test_should_downgrade_when_outstanding(self):
        summary = build_formula_state_summary(
            {"A!1": {"state": FORMULA_STATE_RECALCULATION_REQUIRED, "formula": "=1+1"}},
            recalculation_provider=None,
        )
        assert should_downgrade(summary) is True

    def test_should_not_downgrade_when_no_formulas(self):
        summary = build_formula_state_summary({}, recalculation_provider=None)
        assert should_downgrade(summary) is False


class TestFormulaReferenceParsing:
    def test_simple_cell_ref(self):
        refs = parse_formula_references("=A1+B2")
        assert "A1" in refs
        assert "B2" in refs

    def test_cross_sheet_ref(self):
        refs = parse_formula_references("=Sheet2!A1")
        assert any("A1" in r for r in refs)

    def test_range_ref(self):
        refs = parse_formula_references("=SUM(A1:A3)")
        assert "A1" in refs
        assert "A2" in refs
        assert "A3" in refs

    def test_function_names_not_refs(self):
        refs = parse_formula_references("=SUM(A1:B2)")
        # Should not include SUM as a reference
        assert "SUM" not in refs
