"""Static XLSX formula analysis tests."""

from pathlib import Path
from xml.etree.ElementTree import tostring

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.xlsx.constants import NS
from document_skills_core.formats.xlsx.contracts import parse_xlsx_request
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.formula_analysis import (
    analyze_formulas,
    validate_formula_analysis,
)
from document_skills_core.formats.xlsx.package import OpcPackage
from document_skills_core.formats.xlsx.service import XlsxService

_MAIN_NS = NS["main"]


def _workbook(
    formulas: list[tuple[str, str]],
    *,
    defined_names: list[dict[str, str]] | None = None,
    tables: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    cells = [
        {"ref": "A1", "value": "Amount", "type": "s"},
        {"ref": "A2", "value": "10", "type": "n"},
    ]
    cells.extend(
        {"ref": ref, "formula": formula, "type": "n"}
        for ref, formula in formulas
    )
    return {
        "metadata": {},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [{"cells": cells}],
                "number_formats": [],
            }
        ],
        "defined_names": defined_names or [],
        "tables": tables or [],
    }


def _write(
    path: Path,
    formulas: list[tuple[str, str]],
    **options: object,
) -> Path:
    parsed = parse_xlsx_request({
        "operation": "xlsx.create",
        "output": str(path),
        "arguments": {"workbook": _workbook(formulas, **options)},
    })
    create_xlsx(path, parsed.arguments["workbook"])
    return path


def test_static_analysis_accepts_local_refs_defined_names_and_table_columns(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path / "valid.xlsx",
        [
            ("B2", "SUM(A2:A2)"),
            ("C2", "KnownAmount+1"),
            ("D2", "SUM(DataTable[Amount])"),
            ("E2", "IF(A1=\"(\",1,0)"),
            ("F2", "SUM('Sheet1'!A2)"),
        ],
        defined_names=[
            {"name": "KnownAmount", "ref": "Sheet1!$A$2", "scope": "workbook"}
        ],
        tables=[
            {
                "name": "DataTable",
                "ref": "A1:A2",
                "sheet": "Sheet1",
                "style": "TableStyleMedium2",
            }
        ],
    )

    report = analyze_formulas(path)

    assert report["valid"] is True
    assert report["formula_cells"] == 5
    assert report["references"]["defined_name"] == 1
    assert report["categories"]["structured_reference"] == 1
    assert report["calculation_engine"] is False


@pytest.mark.parametrize(
    ("formula", "code"),
    [
        ("MissingSheet!A1", "formula-sheet-missing"),
        ("XFE1+1", "formula-reference-out-of-bounds"),
        ("UnknownAmount+1", "formula-defined-name-missing"),
        ("SUM(DataTable[Missing])", "formula-table-column-missing"),
        ("SUM(A1:A2", "formula-unbalanced-parentheses"),
        ("=A1+1", "formula-leading-equals"),
        ("A1+#REF!", "formula-error-token"),
    ],
)
def test_static_analysis_reports_invalid_syntax_and_references(
    tmp_path: Path,
    formula: str,
    code: str,
) -> None:
    tables = [
        {
            "name": "DataTable",
            "ref": "A1:A2",
            "sheet": "Sheet1",
            "style": "TableStyleMedium2",
        }
    ]
    path = _write(tmp_path / f"invalid-{code}.xlsx", [("B2", formula)], tables=tables)

    report = analyze_formulas(path)

    assert report["valid"] is False
    assert code in {issue["code"] for issue in report["issues"]}
    cell = next(item for item in report["cells"] if item["ref"] == "Sheet1!B2")
    assert cell["formula_type"] == "normal"
    assert cell["categories"]
    assert cell["valid"] is False
    assert "issues" not in cell
    assert {issue["ref"] for issue in report["issues"]} == {cell["ref"]}


def test_analysis_classifies_special_dynamic_external_and_structured_formulas(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "source.xlsx",
        [
            ("B1", "1+1"),
            ("B2", "1+1"),
            ("B3", "SUM(A1:A2)"),
            ("B4", "TABLE(A1,)"),
            ("B5", "_xlfn.SEQUENCE(2)#"),
            ("B6", "[Book.xlsx]Sheet1!A1"),
            ("B7", "SUM(DataTable[Amount])"),
            ("B8", "'[Book.xlsx]Sheet 1'!A1"),
        ],
        tables=[
            {
                "name": "DataTable",
                "ref": "A1:A2",
                "sheet": "Sheet1",
                "style": "TableStyleMedium2",
            }
        ],
    )
    package = OpcPackage.open(source)
    root = package.xml("xl/worksheets/sheet1.xml")
    formulas = {
        cell.attrib["r"]: cell.find(f"{{{_MAIN_NS}}}f")
        for cell in root.findall(f".//{{{_MAIN_NS}}}c")
        if cell.find(f"{{{_MAIN_NS}}}f") is not None
    }
    formulas["B1"].attrib.update({"t": "shared", "si": "0", "ref": "B1:B2"})
    formulas["B2"].attrib.update({"t": "shared", "si": "0"})
    formulas["B2"].text = None
    formulas["B3"].attrib.update({"t": "array", "ref": "B3"})
    formulas["B4"].attrib.update({"t": "dataTable", "ref": "B4"})
    patched = tmp_path / "special.xlsx"
    package.write_copy(
        patched,
        changed_parts={
            "xl/worksheets/sheet1.xml": tostring(
                root,
                encoding="UTF-8",
                xml_declaration=True,
            )
        },
    )

    report = analyze_formulas(patched)

    assert report["valid"] is False
    assert report["formula_cells"] == 8
    assert report["categories"]["shared"] == 2
    assert report["categories"]["array"] == 1
    assert report["categories"]["data_table"] == 1
    assert report["categories"]["dynamic_array"] == 1
    assert report["categories"]["external_reference"] == 2
    assert report["categories"]["structured_reference"] == 1
    assert "formula-external-reference-unsupported" in {
        issue["code"] for issue in report["issues"]
    }


def test_formula_analysis_gate_is_optional_for_read_and_required_for_mutation(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "invalid.xlsx", [("B2", "Missing!A1")])
    validation = {"schema_version": "1.0", "status": "pass", "gates": []}

    report, optional = validate_formula_analysis(path, validation, required=False)

    assert report["valid"] is False
    assert optional["status"] == "pass"
    with pytest.raises(DocumentSkillsError) as caught:
        validate_formula_analysis(path, validation, required=True)
    assert caught.value.validation["status"] == "fail"


@pytest.mark.parametrize(
    "formula",
    [
        'WEBSERVICE("http://127.0.0.1:9/secret")',
        '_xlfn._xlws.WEBSERVICE("http://127.0.0.1:9/secret")',
        (
            '_xlws._xlfn._xlws._xlfn.WEBSERVICE('
            '"http://127.0.0.1:9/secret")'
        ),
        'RTD("server",,"topic")',
        'HYPERLINK("https://example.invalid", "click")',
        "cmd|' /C calc'!A1",
        "cmd|" + ("A" * 513) + "!A1",
    ],
)
def test_active_provider_formulas_fail_closed_before_mutation(
    tmp_path: Path,
    formula: str,
) -> None:
    path = _write(tmp_path / "active.xlsx", [("B2", formula)])
    report = analyze_formulas(path)
    assert report["valid"] is False
    assert report["categories"]["active_provider"] == 1
    assert "formula-active-provider-unsupported" in {
        issue["code"] for issue in report["issues"]
    }
    with pytest.raises(DocumentSkillsError) as caught:
        validate_formula_analysis(
            path,
            {"schema_version": "1.0", "status": "pass", "gates": []},
            required=True,
        )
    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_create_static_formula_failure_prevents_promotion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "invalid-create.xlsx"
    request = {
        "operation": "xlsx.create",
        "output": str(output),
        "arguments": {"workbook": _workbook([("B2", "Missing!A1")])},
    }

    result = XlsxService(project_root).execute("xlsx.create", request)

    assert result["status"] == "failed"
    assert not output.exists()
    assert any(
        gate["id"] == "operation.formula-static-analysis"
        and gate["outcome"] == "fail"
        for gate in result["validation"]["gates"]
    )


def test_read_reports_static_formula_issues_without_claiming_engine_validation(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "invalid-read.xlsx", [("B2", "Missing!A1")])
    result = XlsxService(project_root).execute(
        "xlsx.read",
        {"operation": "xlsx.read", "input": str(source), "arguments": {}},
    )
    analysis = result["diagnostics"]["operation_result"]["formula_analysis"]

    assert result["status"] == "success"
    assert analysis["valid"] is False
    assert analysis["calculation_engine"] is False
    assert analysis["cells"][0]["formula_type"] == "normal"
    assert analysis["issues"][0]["code"] == "formula-sheet-missing"


def test_external_formula_read_fails_closed_but_inspect_reports_inertly(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "external.xlsx",
        [("B2", "'[Book.xlsx]Sheet 1'!A1")],
    )
    class RecordingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def recalculate_xlsx_artifact(
            self,
            _input_path: Path,
            *,
            policy: str,
        ) -> None:
            assert policy in {"auto", "required"}
            self.calls += 1

    provider = RecordingProvider()
    service = XlsxService(project_root, libreoffice=provider)

    read_result = service.execute(
        "xlsx.read",
        {"operation": "xlsx.read", "input": str(source), "arguments": {}},
    )
    inspect_result = service.execute(
        "xlsx.inspect.structure",
        {
            "operation": "xlsx.inspect.structure",
            "input": str(source),
            "arguments": {},
        },
    )

    assert read_result["status"] == "failed"
    assert read_result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert provider.calls == 0
    assert inspect_result["status"] == "success"
    assert inspect_result["diagnostics"]["operation_result"]["formula_analysis"][
        "cells"
    ][0]["formula_type"] == "normal"
    assert inspect_result["diagnostics"]["operation_result"]["formula_analysis"][
        "categories"
    ]["external_reference"] == 1
