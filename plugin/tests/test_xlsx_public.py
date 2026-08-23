"""XLSX public command surface tests — frozen uv subprocess boundary."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.xlsx.create import create_xlsx


def _strip_style_children(path: Path) -> None:
    """Replace styles.xml with an empty-container form that fails the style gate."""

    with zipfile.ZipFile(path, "r") as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["xl/styles.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        b'<fonts count="1"/><fills count="2"/><borders count="1"/>'
        b'<cellStyleXfs count="1"/><cellXfs count="1"/>'
        b'<cellStyles count="1"/><dxfs count="0"/></styleSheet>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(parts.items()):
            archive.writestr(name, data)


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
    cwd: Path | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-xlsx/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=30,
    )
    if check:
        assert process.returncode == 0, (
            process.stderr.decode("utf-8", errors="replace")
            or process.stdout.decode("utf-8", errors="replace")
        )
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    payload, end = decoder.raw_decode(text)
    assert text[end:].strip() == ""
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _workbook() -> dict[str, object]:
    return {
        "metadata": {"title": "Public XLSX", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "10", "type": "n"},
                            {"ref": "B2", "formula": "B1*2", "type": "n"},
                        ],
                    }
                ],
                "number_formats": [],
            }
        ],
        "defined_names": [],
        "tables": [],
        "chart_reference": None,
        "page_setup": None,
    }


def _claimed_create_features_workbook() -> dict[str, object]:
    return {
        "metadata": {"title": "Claimed XLSX features", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Data",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Name", "type": "s"},
                            {"ref": "B1", "value": "12", "type": "n"},
                            {
                                "ref": "B2",
                                "formula": "B1*2",
                                "cached_value": "24",
                                "type": "n",
                            },
                            {"ref": "D1", "value": "Item", "type": "s"},
                            {"ref": "E1", "value": "Amount", "type": "s"},
                            {"ref": "D2", "value": "Alpha", "type": "s"},
                            {"ref": "E2", "value": "12", "type": "n"},
                        ]
                    }
                ],
                "number_formats": [],
                "data_validations": [
                    {
                        "ref": "C2:C20",
                        "type": "list",
                        "formula1": "\"Low,High\"",
                        "allow_blank": True,
                        "show_input_message": True,
                        "show_error_message": True,
                        "prompt_title": "Level",
                        "prompt": "Choose a level",
                        "error_title": "Invalid",
                        "error": "Choose Low or High",
                        "error_style": "stop",
                    }
                ],
                "conditional_formats": [
                    {
                        "ref": "E2:E20",
                        "type": "cellIs",
                        "operator": "greaterThan",
                        "formulas": ["10"],
                        "style": {
                            "fill": {"pattern": "solid", "color": "#FFCC00"}
                        },
                    }
                ],
            },
            {
                "name": "Summary",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Total", "type": "s"},
                        ]
                    }
                ],
                "number_formats": [],
            },
        ],
        "defined_names": [
            {"name": "TotalValue", "ref": "Data!$B$2", "scope": "workbook"},
        ],
        "tables": [
            {
                "name": "PublicData",
                "ref": "D1:E2",
                "sheet": "Data",
                "style": "TableStyleMedium2",
            }
        ],
        "charts": [
            {
                "name": "PublicChart",
                "sheet": "Data",
                "type": "column",
                "title": "Public native chart",
                "anchor": "G2:N16",
                "series": [
                    {
                        "name": "Amount",
                        "categories": "Data!$D$2:$D$2",
                        "values": "Data!$E$2:$E$2",
                        "color": "#4472C4",
                    }
                ],
                "show_legend": True,
                "legend_position": "r",
                "x_axis_title": "Item",
                "y_axis_title": "Amount",
                "y_axis_number_format": "#,##0",
                "data_labels": {"show_value": True},
            }
        ],
        "chart_reference": None,
        "page_setup": None,
    }


@pytest.fixture
def public_created(project_root: Path, tmp_path: Path) -> Path:
    from openpyxl import Workbook

    output = tmp_path / "public-created.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet["A1"] = "Name"
    sheet["B1"] = 10
    sheet["B2"] = "=B1*2"
    workbook.save(output)
    return output


def test_public_create_is_truthful_and_promotes_bounded_artifact(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bounded.xlsx"
    request = _request(
        tmp_path,
        "create-bounded.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _workbook()},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] in {"success", "degraded"}
    assert output.is_file()
    assert any(
        item["path"] == str(output.resolve())
        for item in result["artifacts"]
    )
    assert any(
        gate["id"] == "operation.consumer-package-conformance"
        and gate["outcome"] == "pass"
        for gate in result["validation"]["gates"]
    )


def test_public_feature_truth_table_is_asserted(project_root: Path) -> None:
    truth_table_path = project_root / "skills/document-xlsx/references/feature-truth-table.json"
    truth_table = json.loads(truth_table_path.read_text(encoding="utf-8"))

    assert truth_table == {
        "schema_version": "1.0",
        "operations": {
            "xlsx.create": {
                "available": [
                    "multiple_sheets",
                    "typed_cell_values",
                    "formulas_with_optional_cached_values",
                    "defined_names",
                    "cell_style",
                    "row_style",
                    "column_style",
                    "custom_number_format",
                    "row_height_and_hidden",
                    "column_width_and_hidden",
                    "native_table",
                    "data_validation",
                    "conditional_formatting",
                    "native_chart",
                ],
                "enhancement_required": [
                    "page_setup",
                ],
            },
            "xlsx.edit": {
                "available": [
                    "cell_value",
                    "cell_formula",
                    "sheet_rename",
                    "cell_style",
                    "row_style",
                    "column_style",
                    "custom_number_format",
                    "row_insert",
                    "row_delete",
                    "column_insert",
                    "column_delete",
                    "row_height",
                    "row_hidden",
                    "column_width",
                    "column_hidden",
                    "sheet_add",
                    "sheet_delete",
                    "sheet_copy_plain_worksheet",
                    "sheet_reorder",
                    "cells_merge",
                    "cells_unmerge",
                    "range_clear",
                    "freeze_panes",
                    "auto_filter",
                    "print_area",
                    "manual_page_breaks",
                    "defined_name_crud",
                    "native_table_add",
                    "native_table_resize",
                    "native_table_rename",
                    "native_table_style",
                    "native_table_delete",
                    "data_validation_crud",
                    "conditional_formatting_crud",
                    "native_chart_crud",
                ],
                "enhancement_required": [
                    "sheet_copy_with_related_objects",
                    "sheet_delete_with_related_objects",
                    "sheet_delete_with_inbound_references",
                    "shared_array_or_data_table_formula_structural_edit",
                    "external_workbook_reference_structural_edit",
                    "pivot_structural_edit",
                ],
            },
        },
    }


def test_public_create_claimed_features_reopen(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "claimed-create-features.xlsx"
    request = _request(
        tmp_path,
        "claimed-create-features.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _claimed_create_features_workbook()},
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] in {"success", "degraded"}
    reopened = load_workbook(output, data_only=False)
    assert reopened.sheetnames == ["Data", "Summary"]
    assert reopened["Data"]["A1"].value == "Name"
    assert reopened["Data"]["B1"].value == 12
    assert reopened["Data"]["B2"].value == "=B1*2"
    assert reopened.defined_names["TotalValue"].attr_text == "Data!$B$2"
    assert reopened["Data"].tables["PublicData"].ref == "D1:E2"
    validations = list(reopened["Data"].data_validations.dataValidation)
    assert len(validations) == 1
    assert str(validations[0].sqref) == "C2:C20"
    conditional_rules = [
        rule
        for conditional_format in reopened["Data"].conditional_formatting
        for rule in reopened["Data"].conditional_formatting[conditional_format]
    ]
    assert [rule.type for rule in conditional_rules] == ["cellIs"]
    assert [type(chart).__name__ for chart in reopened["Data"]._charts] == ["BarChart"]
    assert reopened["Data"]._charts[0].type == "col"


def test_public_native_object_edits_reopen(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import Workbook, load_workbook
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    from openpyxl.styles import PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table, TableStyleInfo

    source = tmp_path / "native-objects-source.xlsx"
    first_output = tmp_path / "native-objects-first.xlsx"
    renamed_output = tmp_path / "native-objects-renamed.xlsx"
    deleted_output = tmp_path / "native-objects-deleted.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    for row in [
        ["Name", "Amount", "Category", "Code", "Score"],
        ["Alpha", 10, "A", "X", 1],
        ["Beta", 20, "B", "Y", 2],
        ["Gamma", 30, "C", "Z", 3],
    ]:
        sheet.append(row)
    table = Table(displayName="DataTable", ref="A1:C3")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)
    for ref, validation_type, formula in (
        ("A2:A4", "whole", "1"),
        ("C2:C4", "list", '"A,B,C"'),
    ):
        validation = DataValidation(
            type=validation_type,
            operator="greaterThanOrEqual" if validation_type == "whole" else None,
            formula1=formula,
        )
        validation.add(ref)
        sheet.add_data_validation(validation)
    red = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")
    sheet.conditional_formatting.add(
        "A2:A4", CellIsRule(operator="greaterThan", formula=["1"], fill=red)
    )
    sheet.conditional_formatting.add(
        "B2:B4", FormulaRule(formula=["MOD(B2,2)=0"], fill=red)
    )
    workbook.save(source)

    edits = [
        {"sheet": "Data", "type": "table_resize", "name": "DataTable", "ref": "A1:C4"},
        {
            "sheet": "Data",
            "type": "table_style",
            "name": "DataTable",
            "table_style": "TableStyleLight1",
        },
        {
            "sheet": "Data",
            "type": "table_add",
            "name": "ScoreTable",
            "ref": "D1:E4",
            "table_style": "TableStyleDark1",
        },
        {
            "sheet": "Data",
            "type": "data_validation_update",
            "ref": "A2:A4",
            "validation": {
                "ref": "A2:A4",
                "type": "decimal",
                "operator": "greaterThanOrEqual",
                "formula1": "0",
            },
        },
        {
            "sheet": "Data",
            "type": "data_validation_add",
            "validation": {"ref": "B2:B4", "type": "list", "formula1": '"Low,High"'},
        },
        {"sheet": "Data", "type": "data_validation_delete", "ref": "C2:C4"},
        {
            "sheet": "Data",
            "type": "conditional_format_update",
            "ref": "A2:A4",
            "priority": 1,
            "rule": {
                "ref": "A2:A4",
                "type": "cellIs",
                "operator": "lessThan",
                "formulas": ["4"],
                "style": {"font": {"bold": True, "color": "#008000"}},
            },
        },
        {
            "sheet": "Data",
            "type": "conditional_format_delete",
            "ref": "B2:B4",
            "priority": 2,
        },
        {
            "sheet": "Data",
            "type": "conditional_format_add",
            "rule": {
                "ref": "C2:C4",
                "type": "dataBar",
                "thresholds": [{"type": "min"}, {"type": "max"}],
                "color": "#638EC6",
            },
        },
    ]
    request = _request(
        tmp_path,
        "native-object-edits.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(first_output),
            "arguments": {"edits": edits, "expected_edits": len(edits)},
        },
    )
    assert _public(project_root, "run", "--request", str(request))["status"] == "success"
    reopened = load_workbook(first_output)
    assert reopened["Data"].tables["DataTable"].ref == "A1:C4"
    assert reopened["Data"].tables["DataTable"].tableStyleInfo.name == "TableStyleLight1"
    assert reopened["Data"].tables["ScoreTable"].ref == "D1:E4"
    assert {str(item.sqref) for item in reopened["Data"].data_validations.dataValidation} == {
        "A2:A4",
        "B2:B4",
    }
    rules = [
        item
        for conditional_format in reopened["Data"].conditional_formatting
        for item in reopened["Data"].conditional_formatting[conditional_format]
    ]
    assert {(item.type, item.priority) for item in rules} == {("cellIs", 1), ("dataBar", 2)}

    rename_request = _request(
        tmp_path,
        "native-object-rename.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(first_output),
            "output": str(renamed_output),
            "arguments": {
                "edits": [
                    {
                        "sheet": "Data",
                        "type": "table_rename",
                        "name": "DataTable",
                        "value": "SalesTable",
                    }
                ]
            },
        },
    )
    assert _public(project_root, "run", "--request", str(rename_request))["status"] == "success"
    assert "SalesTable" in load_workbook(renamed_output)["Data"].tables

    delete_request = _request(
        tmp_path,
        "native-object-delete.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(renamed_output),
            "output": str(deleted_output),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "table_delete", "name": "SalesTable"},
                    {"sheet": "Data", "type": "table_delete", "name": "ScoreTable"},
                ]
            },
        },
    )
    assert _public(project_root, "run", "--request", str(delete_request))["status"] == "success"
    assert not load_workbook(deleted_output)["Data"].tables


def test_public_native_chart_edits_reopen(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    source = tmp_path / "public-chart-source.xlsx"
    edited = tmp_path / "public-chart-edited.xlsx"
    deleted = tmp_path / "public-chart-deleted.xlsx"
    workbook = _workbook()
    cells = workbook["sheets"][0]["rows"][0]["cells"]
    cells[2] = {"ref": "B2", "value": "20", "type": "n"}
    cells.append({"ref": "A2", "value": "Beta", "type": "s"})

    def chart(name: str, chart_type: str, anchor: str) -> dict[str, object]:
        return {
            "name": name,
            "sheet": "Sheet1",
            "type": chart_type,
            "title": name,
            "anchor": anchor,
            "series": [
                {
                    "name": "Amount",
                    "categories": "Sheet1!$A$1:$A$2",
                    "values": "Sheet1!$B$1:$B$2",
                    "color": "#4472C4",
                }
            ],
            "show_legend": True,
            "legend_position": "r",
            "data_labels": {"show_value": True},
        }

    workbook["charts"] = [chart("OriginalChart", "column", "D2:K16")]
    create_request = _request(
        tmp_path,
        "public-chart-create.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(source),
            "arguments": {"workbook": workbook},
        },
    )
    assert _public(project_root, "run", "--request", str(create_request))["status"] == "success"

    update = chart("UpdatedChart", "line", "E3:L17")
    added = chart("AddedPie", "pie", "M3:T17")
    edit_request = _request(
        tmp_path,
        "public-chart-edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(edited),
            "arguments": {
                "edits": [
                    {
                        "sheet": "Sheet1",
                        "type": "chart_update",
                        "name": "OriginalChart",
                        "chart": update,
                    },
                    {"sheet": "Sheet1", "type": "chart_add", "chart": added},
                ],
                "expected_edits": 2,
            },
        },
    )
    assert _public(project_root, "run", "--request", str(edit_request))["status"] == "success"
    assert [type(item).__name__ for item in load_workbook(edited)["Sheet1"]._charts] == [
        "LineChart",
        "PieChart",
    ]

    delete_request = _request(
        tmp_path,
        "public-chart-delete.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(edited),
            "output": str(deleted),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "chart_delete", "name": "UpdatedChart"},
                    {"sheet": "Sheet1", "type": "chart_delete", "name": "AddedPie"},
                ],
                "expected_edits": 2,
            },
        },
    )
    assert _public(project_root, "run", "--request", str(delete_request))["status"] == "success"
    assert not load_workbook(deleted)["Sheet1"]._charts


def test_public_edit_claimed_features_reopen(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "claimed-edit-features.xlsx"
    request = _request(
        tmp_path,
        "claimed-edit-features.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "42"},
                    {
                        "sheet": "Sheet1",
                        "type": "cell_formula",
                        "ref": "B2",
                        "value": "B1*3",
                    },
                    {
                        "sheet": "Sheet1",
                        "type": "sheet_rename",
                        "ref": "A1",
                        "value": "Renamed",
                    },
                ],
                "expected_edits": 3,
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "degraded"
    reopened = load_workbook(output, data_only=False)
    assert reopened.sheetnames == ["Renamed"]
    assert reopened["Renamed"]["B1"].value == 42
    assert reopened["Renamed"]["B2"].value == "=B1*3"


def test_public_edit_structural_sheet_and_range_features_reopen(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import Workbook, load_workbook
    from openpyxl.workbook.defined_name import DefinedName

    source = tmp_path / "structural-public-source.xlsx"
    output = tmp_path / "structural-public-output.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Main"
    sheet["A1"] = "Name"
    sheet["B1"] = 10
    sheet["B2"] = "=B1*2"
    sheet["E1"] = "Merged"
    sheet.merge_cells("E1:F1")
    workbook.create_sheet("DeleteMe")["A1"] = "delete"
    workbook.defined_names.add(
        DefinedName("ExistingName", attr_text="Main!$A$1")
    )
    workbook.defined_names.add(
        DefinedName("DeleteName", attr_text="Main!$B$1")
    )
    workbook.save(source)
    edits = [
        {"sheet": "Main", "type": "row_insert", "ref": "2", "count": 1},
        {"sheet": "Main", "type": "row_delete", "ref": "4", "count": 1},
        {"sheet": "Main", "type": "column_insert", "ref": "C", "count": 1},
        {"sheet": "Main", "type": "column_delete", "ref": "D", "count": 1},
        {"sheet": "Main", "type": "row_height", "ref": "2:3", "height": 25},
        {"sheet": "Main", "type": "row_hidden", "ref": "2", "hidden": True},
        {"sheet": "Main", "type": "column_width", "ref": "B", "width": 18},
        {"sheet": "Main", "type": "column_hidden", "ref": "C", "hidden": True},
        {"sheet": "Main", "type": "cells_unmerge", "ref": "E1:F1"},
        {"sheet": "Main", "type": "cells_merge", "ref": "C1:D1"},
        {"sheet": "Main", "type": "range_clear", "ref": "A1", "clear": "contents"},
        {"sheet": "Main", "type": "freeze_panes", "ref": "C3"},
        {"sheet": "Main", "type": "auto_filter", "ref": "A1:D3"},
        {"sheet": "Main", "type": "print_area", "ref": "A1:G5"},
        {"sheet": "Main", "type": "row_page_break", "ref": "4"},
        {"sheet": "Main", "type": "column_page_break", "ref": "E"},
        {
            "sheet": "Main",
            "type": "defined_name_add",
            "name": "NewName",
            "ref": "Main!$A$1",
        },
        {
            "sheet": "Main",
            "type": "defined_name_update",
            "name": "ExistingName",
            "ref": "Main!$B$1",
        },
        {
            "sheet": "Main",
            "type": "defined_name_delete",
            "name": "DeleteName",
        },
        {"sheet": "Main", "type": "sheet_copy", "name": "Clone", "position": 1},
        {"sheet": "Added", "type": "sheet_add", "position": 2},
        {"sheet": "Added", "type": "cell_value", "ref": "A1", "value": "7"},
        {"sheet": "Added", "type": "sheet_reorder", "position": 0},
        {"sheet": "DeleteMe", "type": "sheet_delete"},
    ]
    request = _request(
        tmp_path,
        "structural-edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"edits": edits, "expected_edits": len(edits)},
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "degraded"
    reopened = load_workbook(output, data_only=False)
    assert reopened.sheetnames == ["Added", "Main", "Clone"]
    main = reopened["Main"]
    assert main["B3"].value == "=B1*2"
    assert main["A1"].value is None
    assert main.row_dimensions[2].height == 25
    assert main.row_dimensions[2].hidden is True
    assert main.column_dimensions["B"].width == 18
    assert main.column_dimensions["C"].hidden is True
    assert [str(item) for item in main.merged_cells.ranges] == ["C1:D1"]
    assert main.freeze_panes == "C3"
    assert main.auto_filter.ref == "A1:D3"
    assert main.print_area == "'Main'!$A$1:$G$5"
    assert [item.id for item in main.row_breaks.brk] == [4]
    assert [item.id for item in main.col_breaks.brk] == [5]
    assert reopened["Clone"]["B3"].value == "=B1*2"
    assert reopened["Added"]["A1"].value == 7
    assert reopened.defined_names["ExistingName"].attr_text == "Main!$B$1"
    assert reopened.defined_names["NewName"].attr_text == "Main!$A$1"
    assert "DeleteName" not in reopened.defined_names


def test_public_create_styles_and_number_formats_reopen(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "styled.xlsx"
    workbook = {
        "metadata": {"title": "Styled XLSX", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Styled",
                "columns": [
                    {
                        "ref": "A",
                        "width": 20,
                        "hidden": False,
                        "style": {"font": {"color": "#008800"}},
                    },
                    {"ref": "C", "hidden": True, "style": None},
                ],
                "rows": [
                    {
                        "height": 24,
                        "hidden": True,
                        "style": {
                            "font": {"name": "Aptos", "size": 12, "bold": True},
                            "fill": {"pattern": "solid", "color": "#DDEEFF"},
                            "border": {
                                "bottom": {"style": "thin", "color": "#112233"}
                            },
                            "alignment": {
                                "horizontal": "center",
                                "vertical": "top",
                                "wrap": True,
                            },
                            "protection": {"locked": True, "hidden": False},
                        },
                        "cells": [
                            {
                                "ref": "A1",
                                "value": "Header",
                                "type": "s",
                                "style": {
                                    "font": {
                                        "italic": True,
                                        "underline": "single",
                                        "color": "#FF0000",
                                    },
                                    "alignment": {"rotation": 45},
                                },
                            },
                            {"ref": "B1", "value": "Amount", "type": "s"},
                        ],
                    },
                    {
                        "cells": [
                            {
                                "ref": "B2",
                                "value": "1234.5",
                                "type": "n",
                                "style": {
                                    "number_format": {"id": 165},
                                    "alignment": {"horizontal": "right"},
                                    "protection": {"locked": False},
                                },
                            },
                            {
                                "ref": "C2",
                                "value": "8.25",
                                "type": "n",
                                "style": {
                                    "number_format": {"id": 165},
                                    "alignment": {"horizontal": "right"},
                                    "protection": {"locked": False},
                                },
                            },
                        ]
                    },
                ],
                "number_formats": [{"id": 165, "code": "$#,##0.00"}],
            }
        ],
        "defined_names": [],
        "tables": [],
        "chart_reference": None,
        "page_setup": None,
    }
    request = _request(
        tmp_path,
        "styled.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": workbook},
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success"
    reopened = load_workbook(output, data_only=False)
    sheet = reopened["Styled"]
    header = sheet["A1"]
    assert header.font.name == "Aptos"
    assert header.font.sz == 12
    assert header.font.bold is True
    assert header.font.italic is True
    assert header.font.underline == "single"
    assert header.font.color.rgb == "FFFF0000"
    assert header.fill.fill_type == "solid"
    assert header.fill.fgColor.rgb == "FFDDEEFF"
    assert header.border.bottom.style == "thin"
    assert header.border.bottom.color.rgb == "FF112233"
    assert header.alignment.horizontal == "center"
    assert header.alignment.vertical == "top"
    assert header.alignment.wrap_text is True
    assert header.alignment.text_rotation == 45
    assert header.protection.locked is True
    assert sheet["B2"].number_format == "$#,##0.00"
    assert sheet["B2"].protection.locked is False
    assert sheet["B2"].style_id == sheet["C2"].style_id
    assert sheet.row_dimensions[1].height == 24
    assert sheet.row_dimensions[1].hidden is True
    assert sheet.column_dimensions["A"].width == 20
    assert sheet.column_dimensions["C"].hidden is True

    read_request = _request(
        tmp_path,
        "styled-read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    cells = {
        cell["ref"]: cell
        for row in read_result["diagnostics"]["operation_result"]["sheets"][0]["rows"]
        for cell in row["cells"]
    }
    assert cells["A1"]["style_index"] > 0
    assert cells["A1"]["style"]["font"]["bold"] is True
    assert cells["A1"]["style"]["font"]["italic"] is True
    assert cells["A1"]["style"]["alignment"]["rotation"] == 45
    assert cells["B2"]["number_format"] == "$#,##0.00"


def test_public_edit_styles_and_number_format_reopen(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "styled-edit.xlsx"
    request = _request(
        tmp_path,
        "styled-edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "sheet": "Sheet1",
                        "type": "cell_style",
                        "ref": "A1",
                        "style": {
                            "font": {"bold": True, "color": "#AA0000"},
                            "fill": {"color": "#FFFF00"},
                            "border": {
                                "right": {"style": "double", "color": "#0000AA"}
                            },
                            "alignment": {
                                "horizontal": "center",
                                "wrap": True,
                                "rotation": -30,
                            },
                            "protection": {"hidden": True},
                        },
                    },
                    {
                        "sheet": "Sheet1",
                        "type": "row_style",
                        "ref": "2",
                        "style": {"font": {"italic": True}},
                    },
                    {
                        "sheet": "Sheet1",
                        "type": "column_style",
                        "ref": "C",
                        "style": {"number_format": {"code": "0.000"}},
                    },
                ],
                "expected_edits": 3,
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] in {"success", "degraded"}
    reopened = load_workbook(output, data_only=False)
    sheet = reopened["Sheet1"]
    assert sheet["A1"].font.bold is True
    assert sheet["A1"].font.color.rgb == "FFAA0000"
    assert sheet["A1"].fill.fgColor.rgb == "FFFFFF00"
    assert sheet["A1"].border.right.style == "double"
    assert sheet["A1"].border.right.color.rgb == "FF0000AA"
    assert sheet["A1"].alignment.horizontal == "center"
    assert sheet["A1"].alignment.wrap_text is True
    assert sheet["A1"].alignment.text_rotation == 120
    assert sheet["A1"].protection.hidden is True
    assert sheet.row_dimensions[2].style_id > 0
    assert sheet.column_dimensions["C"].style_id > 0
    assert sheet.column_dimensions["C"].number_format == "0.000"


def test_public_capabilities_list_xlsx_operations(project_root: Path) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert "xlsx.read" in operations
    assert "xlsx.inspect.structure" in operations
    assert "xlsx.create" in operations
    assert "xlsx.edit" in operations
    assert all(item["available"] for item in operations.values() if "xlsx" in item["operation"])


def test_public_doctor_succeeds(project_root: Path) -> None:
    report = _public(project_root, "doctor", "--json")
    assert report["status"] == "healthy"


def test_public_create_and_read(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] in {"success", "degraded"}
    assert result["diagnostics"]["operation_result"]["sheet_count"] == 1


def test_public_inspect_inert(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(inspect_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["mutation_authorized"] is False


def test_public_edit_produces_distinct_output(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-edited.xlsx"
    edit_request = _request(
        tmp_path,
        "edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "42"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] in {"success", "degraded"}
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])
    assert any(
        gate["id"] == "operation.consumer-package-conformance"
        and gate["outcome"] == "pass"
        for gate in result["validation"]["gates"]
    )


def test_public_edit_rejects_consumer_invalid_package_and_preserves_paths(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "core-invalid.xlsx"
    create_xlsx(source, _workbook())
    _strip_style_children(source)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "existing.xlsx"
    existing = b"existing-public-destination"
    output.write_bytes(existing)
    edit_request = _request(
        tmp_path,
        "invalid-edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "42"}
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(edit_request), check=False)

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "failed"
    assert result["validation"]["status"] == "fail"
    assert any(
        gate["id"] == "operation.consumer-package-conformance"
        and gate["required"] is True
        and gate["outcome"] == "fail"
        for gate in result["validation"]["gates"]
    )
    assert result["artifacts"] == []
    assert output.read_bytes() == existing
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256


def test_public_validate_reopens_valid_xlsx(project_root: Path, public_created: Path) -> None:
    result = _public(
        project_root,
        "validate",
        "--input",
        str(public_created),
        "--json",
    )
    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "pass"
    assert outcomes["provider.reopen"] == "pass"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"


def test_public_unknown_operation_rejected(project_root: Path, tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.nonexistent",
            "input": str(tmp_path / "input.xlsx"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_OPERATION_UNKNOWN"


def test_public_formula_state_never_recalculated(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    """The core invariant: no formula is ever reported as recalculated without a provider."""
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(public_created),
            "arguments": {"include_formulas": True},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    formula_state = result["diagnostics"]["operation_result"]["formula_state"]
    for ref, cell in formula_state["cells"].items():
        assert cell["state"] != "recalculated", f"Cell {ref} falsely reports recalculated"
    assert formula_state["summary"]["no_unverified_claimed_recalculated"] is True
    assert formula_state["summary"]["recalculation_provider"] == "unavailable"


def test_public_edit_invalidates_dependents(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    """Editing a precedent marks dependent formulas as recalculation_required."""
    output = tmp_path / "invalidated.xlsx"
    edit_request = _request(
        tmp_path,
        "edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_value", "ref": "B1", "value": "99"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    formula_cells = result["diagnostics"]["operation_result"].get("formula_state", {}).get("cells", {})
    # The formula B2=B1*2 should be invalidated because B1 was edited
    invalidated = [
        ref for ref, c in formula_cells.items()
        if c.get("state") == "recalculation_required"
    ]
    assert len(invalidated) > 0, "Expected dependent invalidation"
