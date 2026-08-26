"""Typed, bounded, and transactional XLSX conversion tests."""

import json
from pathlib import Path
from xml.etree.ElementTree import tostring

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.xlsx.constants import NS
from document_skills_core.formats.xlsx.contracts import parse_xlsx_request
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.mapping import map_workbook
from document_skills_core.formats.xlsx.package import OpcPackage
from document_skills_core.formats.xlsx.service import XlsxService


def _request(
    source: Path,
    output: Path,
    source_format: str,
    target_format: str,
    **arguments: object,
) -> dict[str, object]:
    return {
        "operation": "xlsx.convert",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "source_format": source_format,
            "target_format": target_format,
            **arguments,
        },
    }


def _json_document(rows: list[list[dict[str, object]]]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "format": "document-skills-tabular",
        "sheets": [{"name": "Data", "rows": rows}],
    }


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _write_xlsx(path: Path) -> None:
    raw_workbook = {
        "metadata": {},
        "sheets": [
            {
                "name": "First",
                "rows": [
                    {
                        "cells": [
                            {
                                "ref": "A1",
                                "formula": "1+1",
                                "cached_value": "2",
                                "type": "n",
                            },
                            {"ref": "B1", "value": "=CMD()", "type": "s"},
                        ]
                    }
                ],
                "number_formats": [],
            },
            {
                "name": "Second",
                "rows": [{"cells": [{"ref": "A1", "value": "hidden", "type": "s"}]}],
                "number_formats": [],
            },
        ],
        "defined_names": [],
        "tables": [],
    }
    parsed = parse_xlsx_request(
        {
            "operation": "xlsx.create",
            "output": str(path),
            "arguments": {"workbook": raw_workbook},
        }
    )
    create_xlsx(path, parsed.arguments["workbook"])


def test_conversion_contract_validates_declared_formats_and_suffixes() -> None:
    parsed = parse_xlsx_request(
        {
            "operation": "xlsx.convert",
            "input": "source.csv",
            "output": "target.json",
            "arguments": {"source_format": "csv", "target_format": "json"},
        }
    )

    assert parsed.arguments["values"]["leading_zero_policy"] == "preserve-text"
    assert parsed.arguments["values"]["large_integer_policy"] == "preserve-text"
    assert parsed.arguments["values"]["csv_injection_policy"] == "escape"
    with pytest.raises(DocumentSkillsError) as caught:
        parse_xlsx_request(
            {
                "operation": "xlsx.convert",
                "input": "source.xlsx",
                "output": "target.json",
                "arguments": {"source_format": "csv", "target_format": "json"},
            }
        )
    assert caught.value.code.value == "DS_REQUEST_INVALID"
    with pytest.raises(DocumentSkillsError):
        parse_xlsx_request(
            {
                "operation": "xlsx.convert",
                "input": "source.csv",
                "output": "target.json",
                "arguments": {
                    "source_format": "csv",
                    "target_format": "json",
                    "source": {"encoding": "windows-1252", "bom": "required"},
                },
            }
        )


def test_csv_to_json_preserves_risky_numbers_and_has_stable_shape(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text(
        'code,large,amount,flag,day,empty,null,danger\n'
        '00123,1234567890123456,"1,25",TRUE,2026-08-24,,\\N,=2+2\n',
        encoding="utf-8",
        newline="\n",
    )
    output = tmp_path / "output.json"
    request = _request(
        source,
        output,
        "csv",
        "json",
        values={"decimal_separator": ","},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)
    document = json.loads(output.read_text(encoding="utf-8"))
    values = document["sheets"][0]["rows"][1]

    assert result["status"] == "degraded"
    assert document["schema_version"] == "1.0"
    assert document["format"] == "document-skills-tabular"
    assert values[0] == {"type": "string", "value": "00123"}
    assert values[1] == {"type": "string", "value": "1234567890123456"}
    assert values[2] == {"type": "number", "value": "1.25"}
    assert values[3] == {"type": "boolean", "value": True}
    assert values[4] == {"type": "date", "value": "2026-08-24"}
    assert values[5] == {"type": "empty", "value": ""}
    assert values[6] == {"type": "null", "value": None}
    assert values[7] == {"type": "string", "value": "=2+2"}
    assert "delimited-value-types-inferred" in {
        item["code"] for item in result["diagnostics"]["operation_result"]["semantic_losses"]
    }


def test_json_to_xlsx_maps_typed_values_and_formula_cache_truthfully(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "typed.json"
    _write_json(
        source,
        _json_document(
            [
                [
                    {"type": "null", "value": None},
                    {"type": "empty", "value": ""},
                    {"type": "boolean", "value": True},
                    {"type": "number", "value": "12.50"},
                    {"type": "date", "value": "2026-08-24"},
                    {"type": "time", "value": "12:30:15"},
                    {"type": "datetime", "value": "2026-08-24T12:30:15"},
                    {"type": "datetime", "value": "2026-08-24T12:30:15+08:00"},
                    {
                        "type": "formula",
                        "formula": "D1*2",
                        "cached": {"type": "number", "value": "25"},
                    },
                ]
            ]
        ),
    )
    output = tmp_path / "typed.xlsx"
    request = _request(
        source,
        output,
        "json",
        "xlsx",
        values={"formula_policy": "evaluated"},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)
    mapped = map_workbook(OpcPackage.open(output))
    cells = {
        cell["ref"]: cell
        for row in mapped["sheets"][0]["rows"]
        for cell in row["cells"]
    }
    losses = {
        item["code"] for item in result["diagnostics"]["operation_result"]["semantic_losses"]
    }

    assert result["status"] == "degraded"
    assert "A1" not in cells
    assert cells["B1"]["value"] == ""
    assert cells["C1"]["value"] == "1"
    assert cells["D1"]["value"] == "12.50"
    assert cells["E1"]["number_format"] == "yyyy-mm-dd"
    assert cells["F1"]["number_format"] == "hh:mm:ss"
    assert cells["G1"]["number_format"] == 'yyyy-mm-dd"T"hh:mm:ss'
    assert cells["H1"]["value"] == "2026-08-24T12:30:15+08:00"
    assert cells["I1"]["value"] == "25"
    assert mapped["formula_cells"] == {}
    assert {
        "formulas-replaced-with-cached-values",
        "null-values-mapped-to-blank-cells",
        "timezone-values-preserved-as-text",
    }.issubset(losses)


@pytest.mark.parametrize(
    ("policy", "expected_type", "loss_code"),
    [
        ("preserve-text", "s", "json-value-type-normalized"),
        ("number", "n", "large-integer-xlsx-precision-risk"),
    ],
)
def test_json_large_integer_policy_is_explicit_and_reported(
    project_root: Path,
    tmp_path: Path,
    policy: str,
    expected_type: str,
    loss_code: str,
) -> None:
    source = tmp_path / f"large-{policy}.json"
    _write_json(
        source,
        _json_document(
            [[{"type": "number", "value": "1234567890123456"}]]
        ),
    )
    output = tmp_path / f"large-{policy}.xlsx"
    request = _request(
        source,
        output,
        "json",
        "xlsx",
        values={"large_integer_policy": policy},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)
    cell = map_workbook(OpcPackage.open(output))["sheets"][0]["rows"][0]["cells"][0]
    losses = {
        item["code"] for item in result["diagnostics"]["operation_result"]["semantic_losses"]
    }

    assert result["status"] == "degraded"
    assert cell["type"] == expected_type
    assert loss_code in losses


def test_timezone_utc_policy_normalizes_and_reports_json_output(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "timezone.json"
    _write_json(
        source,
        _json_document(
            [[{"type": "datetime", "value": "2026-08-24T12:30:15+08:00"}]]
        ),
    )
    output = tmp_path / "timezone-utc.json"
    request = _request(
        source,
        output,
        "json",
        "json",
        values={"timezone_policy": "utc"},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)
    document = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "degraded"
    assert document["sheets"][0]["rows"][0][0]["value"] == "2026-08-24T04:30:15Z"
    assert result["diagnostics"]["operation_result"]["semantic_losses"][0][
        "code"
    ] == "timezone-normalized-to-utc"


def test_evaluated_formula_requires_cache_and_preserves_existing_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "formula.json"
    _write_json(
        source,
        _json_document([[{"type": "formula", "formula": "1+1", "cached": None}]]),
    )
    output = tmp_path / "destination.xlsx"
    output.write_bytes(b"existing-destination")
    request = _request(
        source,
        output,
        "json",
        "xlsx",
        values={"formula_policy": "evaluated"},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)

    assert result["status"] == "enhancement_required"
    assert output.read_bytes() == b"existing-destination"


def test_xlsx_to_csv_drops_extra_sheets_and_escapes_injection(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.xlsx"
    _write_xlsx(source)
    output = tmp_path / "output.csv"

    result = XlsxService(project_root).execute(
        "xlsx.convert",
        _request(source, output, "xlsx", "csv"),
    )
    losses = {
        item["code"] for item in result["diagnostics"]["operation_result"]["semantic_losses"]
    }

    assert result["status"] == "degraded"
    assert output.read_text(encoding="utf-8") == "'=1+1,'=CMD()\n"
    assert {
        "xlsx-formatting-and-objects-dropped",
        "additional-sheets-dropped",
        "formulas-preserved-as-text",
        "csv-injection-escaped",
    }.issubset(losses)


def test_csv_injection_reject_policy_does_not_promote(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "danger.json"
    _write_json(source, _json_document([[{"type": "string", "value": "=1+1"}]]))
    output = tmp_path / "danger.csv"
    output.write_bytes(b"safe-existing")
    request = _request(
        source,
        output,
        "json",
        "csv",
        values={"csv_injection_policy": "reject"},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == b"safe-existing"


def test_text_output_honors_bom_encoding_and_line_ending(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")
    output = tmp_path / "output.tsv"
    request = _request(
        source,
        output,
        "csv",
        "tsv",
        target={"encoding": "utf-16-le", "bom": True, "line_ending": "crlf"},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)
    payload = output.read_bytes()

    assert result["status"] == "degraded"
    assert payload.startswith(b"\xff\xfe")
    assert payload[2:].decode("utf-16-le") == "a\tb\r\n1\t2\r\n"


def test_conversion_input_limit_fails_before_promotion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"a,b\n")
    output = tmp_path / "output.json"
    request = _request(
        source,
        output,
        "csv",
        "json",
        limits={"max_input_bytes": 3},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)

    assert result["status"] == "failed"
    assert not output.exists()


def test_conversion_cell_limit_applies_to_canonical_json(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "large-cell.json"
    _write_json(source, _json_document([[{"type": "string", "value": "abcd"}]]))
    output = tmp_path / "large-cell.csv"
    request = _request(
        source,
        output,
        "json",
        "csv",
        limits={"max_cell_bytes": 3},
    )

    result = XlsxService(project_root).execute("xlsx.convert", request)

    assert result["status"] == "failed"
    assert not output.exists()


def test_special_formula_conversion_fails_closed(
    project_root: Path,
    tmp_path: Path,
) -> None:
    core = tmp_path / "normal.xlsx"
    _write_xlsx(core)
    package = OpcPackage.open(core)
    root = package.xml("xl/worksheets/sheet1.xml")
    formula = root.find(f".//{{{NS['main']}}}f")
    assert formula is not None
    formula.attrib.update({"t": "array", "ref": "A1"})
    source = tmp_path / "array.xlsx"
    package.write_copy(
        source,
        changed_parts={
            "xl/worksheets/sheet1.xml": tostring(
                root,
                encoding="UTF-8",
                xml_declaration=True,
            )
        },
    )
    output = tmp_path / "array.json"

    result = XlsxService(project_root).execute(
        "xlsx.convert",
        _request(
            source,
            output,
            "xlsx",
            "json",
            values={"formula_policy": "evaluated"},
        ),
    )

    assert result["status"] == "enhancement_required"
    assert not output.exists()


def test_json_conversion_is_deterministic_and_committed(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("name,value\nalpha,1\n", encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    first_result = XlsxService(project_root).execute(
        "xlsx.convert", _request(source, first, "csv", "json")
    )
    second_result = XlsxService(project_root).execute(
        "xlsx.convert", _request(source, second, "csv", "json")
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_result["artifacts"][-1]["sha256"] == second_result["artifacts"][-1]["sha256"]
    assert first_result["diagnostics"]["promotion"]["filesystem_state"].startswith("committed")
