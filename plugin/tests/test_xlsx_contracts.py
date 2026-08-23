"""XLSX operation argument contract tests."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.xlsx.contracts import (
    XLSX_OPERATIONS,
    parse_xlsx_request,
)


def test_xlsx_operations_set_is_exactly_four():
    assert XLSX_OPERATIONS == frozenset(
        {"xlsx.read", "xlsx.inspect.structure", "xlsx.create", "xlsx.edit"}
    )


def test_parse_read_rejects_unknown_argument():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": "test.xlsx",
            "arguments": {"unknown": True},
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_read_requires_input():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "arguments": {},
        })


def test_parse_read_rejects_output():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": "test.xlsx",
            "output": "out.xlsx",
            "arguments": {},
        })


def test_parse_create_requires_output():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "arguments": {"workbook": {"metadata": {}, "sheets": []}},
        })


def test_parse_edit_requires_distinct_paths():
    same = str(Path("same.xlsx").resolve())
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": same,
            "output": same,
            "arguments": {"edits": [{"sheet": "Sheet1", "type": "cell_value", "ref": "A1", "value": "x"}]},
        })
    assert exc.value.code.value == "DS_OUTPUT_EQUALS_INPUT"


def test_parse_edit_requires_edits():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": "in.xlsx",
            "output": "out.xlsx",
            "arguments": {"edits": []},
        })


def test_parse_edit_rejects_unknown_edit_type():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": "in.xlsx",
            "output": "out.xlsx",
            "arguments": {"edits": [{"sheet": "S1", "type": "invalid_type", "ref": "A1"}]},
        })


def test_parse_edit_accepts_cell_row_and_column_styles():
    parsed = parse_xlsx_request({
        "schema_version": "1.0",
        "operation": "xlsx.edit",
        "input": "in.xlsx",
        "output": "out.xlsx",
        "arguments": {
            "edits": [
                {
                    "sheet": "Sheet1",
                    "type": "cell_style",
                    "ref": "A1",
                    "style": {"font": {"bold": True}},
                },
                {
                    "sheet": "Sheet1",
                    "type": "row_style",
                    "ref": "1:2",
                    "style": {"fill": {"color": "#DDEEFF"}},
                },
                {
                    "sheet": "Sheet1",
                    "type": "column_style",
                    "ref": "B:C",
                    "style": {"number_format": {"code": "0.000"}},
                },
            ]
        },
    })

    edits = parsed.arguments["edits"]
    assert [edit["type"] for edit in edits] == [
        "cell_style",
        "row_style",
        "column_style",
    ]
    assert edits[1]["style"]["fill"]["color"] == "FFDDEEFF"


def test_parse_edit_style_primitive_requires_style():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": "in.xlsx",
            "output": "out.xlsx",
            "arguments": {
                "edits": [
                    {"sheet": "Sheet1", "type": "cell_style", "ref": "A1"},
                ]
            },
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_edit_accepts_bounded_worksheet_and_sheet_primitives():
    parsed = parse_xlsx_request({
        "schema_version": "1.0",
        "operation": "xlsx.edit",
        "input": "in.xlsx",
        "output": "out.xlsx",
        "arguments": {
            "edits": [
                {"sheet": "Data", "type": "row_height", "ref": "2:4", "height": 27.5},
                {"sheet": "Data", "type": "column_hidden", "ref": "B:C", "hidden": True},
                {"sheet": "Data", "type": "range_clear", "ref": "A2:C9", "clear": "styles"},
                {"sheet": "Data", "type": "freeze_panes", "ref": "C3"},
                {"sheet": "Data", "type": "row_page_break", "ref": "20"},
                {
                    "sheet": "Data",
                    "type": "defined_name_add",
                    "name": "InputArea",
                    "ref": "Data!$A$1:$C$3",
                    "scope": "workbook",
                },
                {"sheet": "Archive", "type": "sheet_add", "position": 1},
                {"sheet": "Data", "type": "sheet_copy", "name": "Data Copy", "position": 2},
            ]
        },
    })

    edits = parsed.arguments["edits"]
    assert edits[0]["height"] == 27.5
    assert edits[1]["hidden"] is True
    assert edits[2]["clear"] == "styles"
    assert edits[4]["enabled"] is True
    assert edits[5]["scope"] == "workbook"
    assert edits[7]["name"] == "Data Copy"


@pytest.mark.parametrize(
    "edit",
    [
        {"sheet": "Data", "type": "row_height", "ref": "2", "height": 410},
        {"sheet": "Data", "type": "column_width", "ref": "A", "width": 256},
        {"sheet": "Data", "type": "cells_merge", "ref": "C3:A1"},
        {"sheet": "Bad/Name", "type": "sheet_add"},
        {"sheet": "Data", "type": "sheet_copy", "name": "x" * 32},
        {"sheet": "Data", "type": "row_insert", "ref": "1048576", "count": 2},
    ],
)
def test_parse_edit_rejects_new_primitive_boundaries(edit: dict[str, object]):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": "in.xlsx",
            "output": "out.xlsx",
            "arguments": {"edits": [edit]},
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_edit_rejects_conflicting_defined_name_writes():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": "in.xlsx",
            "output": "out.xlsx",
            "arguments": {
                "edits": [
                    {
                        "sheet": "Data",
                        "type": "defined_name_update",
                        "name": "InputArea",
                        "ref": "Data!$A$1",
                    },
                    {
                        "sheet": "Data",
                        "type": "defined_name_delete",
                        "name": "InputArea",
                    },
                ]
            },
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_input_must_have_xlsx_extension():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": "test.docx",
            "arguments": {},
        })


def test_parse_create_rejects_input():
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "input": "in.xlsx",
            "output": "out.xlsx",
            "arguments": {"workbook": {"metadata": {}, "sheets": []}},
        })


def test_parse_read_defaults():
    parsed = parse_xlsx_request({
        "schema_version": "1.0",
        "operation": "xlsx.read",
        "input": "test.xlsx",
        "arguments": {},
    })
    assert parsed.arguments["include_formulas"] is True
    assert parsed.arguments["max_rows"] == 5_000


def test_parse_create_accepts_bounded_styles_and_number_formats():
    parsed = parse_xlsx_request({
        "schema_version": "1.0",
        "operation": "xlsx.create",
        "output": "styled.xlsx",
        "arguments": {
            "workbook": {
                "metadata": {},
                "sheets": [
                    {
                        "name": "Styled",
                        "columns": [
                            {
                                "ref": "A:B",
                                "width": 18.5,
                                "hidden": False,
                                "style": {"number_format": {"id": 165}},
                            }
                        ],
                        "rows": [
                            {
                                "height": 24,
                                "hidden": True,
                                "style": {
                                    "font": {
                                        "name": "Aptos",
                                        "size": 12,
                                        "bold": True,
                                        "italic": False,
                                        "underline": "single",
                                        "color": "#112233",
                                    },
                                    "fill": {"pattern": "solid", "color": "DDEEFF"},
                                    "border": {
                                        "bottom": {"style": "thin", "color": "#445566"}
                                    },
                                    "alignment": {
                                        "horizontal": "center",
                                        "vertical": "top",
                                        "wrap": True,
                                        "rotation": 45,
                                    },
                                    "protection": {"locked": False, "hidden": True},
                                    "number_format": {"code": "yyyy-mm-dd"},
                                },
                                "cells": [
                                    {
                                        "ref": "A1",
                                        "value": "45292",
                                        "type": "n",
                                        "style": {"font": {"italic": True}},
                                    }
                                ],
                            }
                        ],
                        "number_formats": [{"id": 165, "code": "yyyy-mm-dd"}],
                    }
                ],
                "defined_names": [],
                "tables": [],
                "chart_reference": None,
                "page_setup": None,
            }
        },
    })

    sheet = parsed.arguments["workbook"]["sheets"][0]
    assert sheet["columns"][0]["width"] == 18.5
    assert sheet["rows"][0]["style"]["font"]["color"] == "FF112233"
    assert sheet["rows"][0]["style"]["alignment"]["rotation"] == 45
    assert sheet["number_formats"] == [{"id": 165, "code": "yyyy-mm-dd"}]


@pytest.mark.parametrize(
    "style",
    [
        {"font": {"color": "not-a-color"}},
        {"font": {"unknown": True}},
        {"alignment": {"horizontal": "diagonal"}},
        {"alignment": {"rotation": 91}},
        {"number_format": {"id": 165, "code": "0.00"}},
    ],
)
def test_parse_create_rejects_invalid_style_boundaries(style: dict[str, object]):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": "styled.xlsx",
            "arguments": {
                "workbook": {
                    "metadata": {},
                    "sheets": [
                        {
                            "name": "Styled",
                            "rows": [
                                {
                                    "cells": [
                                        {"ref": "A1", "value": "x", "type": "s", "style": style}
                                    ]
                                }
                            ],
                            "number_formats": [{"id": 165, "code": "0.00"}],
                        }
                    ],
                    "defined_names": [],
                    "tables": [],
                    "chart_reference": None,
                    "page_setup": None,
                }
            },
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_create_rejects_undeclared_custom_number_format_id():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request({
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": "styled.xlsx",
            "arguments": {
                "workbook": {
                    "metadata": {},
                    "sheets": [
                        {
                            "name": "Styled",
                            "rows": [
                                {
                                    "cells": [
                                        {
                                            "ref": "A1",
                                            "value": "1",
                                            "type": "n",
                                            "style": {"number_format": {"id": 165}},
                                        }
                                    ]
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
            },
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"
