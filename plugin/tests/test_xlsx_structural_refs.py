"""Unit tests for bounded row/column A1 reference migration."""

import pytest

from document_skills_core.formats.xlsx.structural_refs import (
    AxisMutation,
    has_external_workbook_reference,
    rename_sheet_references,
    rewrite_formula,
    rewrite_reference,
)


@pytest.mark.parametrize(
    ("formula", "current_sheet", "mutation", "expected"),
    [
        (
            "SUM(B2:B5)+B8",
            "Data",
            AxisMutation("Data", "row", 3, 2, False),
            "SUM(B2:B7)+B10",
        ),
        (
            "'Data Set'!$A$2+Other!A2",
            "Summary",
            AxisMutation("Data Set", "row", 2, 1, False),
            "'Data Set'!$A$3+Other!A2",
        ),
        (
            'IF(A2="A2",B2,C2)',
            "Data",
            AxisMutation("Data", "column", 2, 1, False),
            'IF(A2="A2",C2,D2)',
        ),
        (
            "SUM(A2:A6)",
            "Data",
            AxisMutation("Data", "row", 3, 2, True),
            "SUM(A2:A4)",
        ),
        (
            "B3+C8",
            "Data",
            AxisMutation("Data", "row", 3, 1, True),
            "#REF!+C7",
        ),
        (
            "SUM(B:B)+SUM(2:4)",
            "Data",
            AxisMutation("Data", "column", 2, 2, False),
            "SUM(D:D)+SUM(2:4)",
        ),
    ],
)
def test_formula_reference_migration(
    formula: str,
    current_sheet: str,
    mutation: AxisMutation,
    expected: str,
) -> None:
    assert rewrite_formula(
        formula,
        current_sheet=current_sheet,
        mutation=mutation,
    ) == expected


def test_sqref_and_defined_name_migration() -> None:
    mutation = AxisMutation("Data", "row", 2, 1, False)
    assert rewrite_reference(
        "Data!$A$1:$C$3 Data!E2:E4",
        current_sheet=None,
        mutation=mutation,
    ) == "Data!$A$1:$C$4 Data!E3:E5"


def test_external_workbook_reference_detection() -> None:
    assert has_external_workbook_reference("'[1]Data'!A1") is True
    assert has_external_workbook_reference("[Book.xlsx]Data!A1") is True
    assert has_external_workbook_reference("Table1[Amount]") is False


def test_sheet_rename_preserves_formula_string_literals() -> None:
    assert rename_sheet_references(
        'IF(Data!A1="Data!A1",Data!B1,0)',
        "Data",
        "Renamed Data",
    ) == 'IF(\'Renamed Data\'!A1="Data!A1",\'Renamed Data\'!B1,0)'
