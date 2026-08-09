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
