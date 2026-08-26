"""Native XLSX chart creation and detailed readback tests."""

from pathlib import Path
import zipfile

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.xlsx.contracts import parse_xlsx_request
from document_skills_core.formats.xlsx.service import XlsxService


def _series(name: str, value_column: str, color: str = "#4472C4") -> dict:
    return {
        "name": name,
        "categories": "Data!$A$2:$A$5",
        "values": f"Data!${value_column}$2:${value_column}$5",
        "color": color,
    }


def _chart(name: str, chart_type: str, anchor: str, *, value_column: str = "B") -> dict:
    series = (
        [
            {
                "name": "Trend",
                "x_values": "Data!$B$2:$B$5",
                "y_values": "Data!$C$2:$C$5",
                "color": "#ED7D31",
            }
        ]
        if chart_type == "scatter"
        else [_series("Revenue", value_column)]
    )
    result = {
        "name": name,
        "sheet": "Data",
        "type": chart_type,
        "title": f"{chart_type.title()} chart",
        "anchor": anchor,
        "series": series,
        "show_legend": True,
        "legend_position": "r",
        "data_labels": {"show_value": True},
    }
    if chart_type != "pie":
        result.update(
            {
                "x_axis_title": "Category",
                "y_axis_title": "Value",
                "y_axis_number_format": "#,##0.00",
            }
        )
    return result


def _workbook() -> dict:
    return {
        "metadata": {"title": "Charts", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Data",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "Quarter", "type": "s"},
                            {"ref": "B1", "value": "Revenue", "type": "s"},
                            {"ref": "C1", "value": "Cost", "type": "s"},
                            *[
                                {"ref": f"A{row}", "value": f"Q{row - 1}", "type": "s"}
                                for row in range(2, 6)
                            ],
                            *[
                                {"ref": f"B{row}", "value": str(row * 10), "type": "n"}
                                for row in range(2, 6)
                            ],
                            *[
                                {"ref": f"C{row}", "value": str(row * 7), "type": "n"}
                                for row in range(2, 6)
                            ],
                        ]
                    }
                ],
                "columns": [],
                "number_formats": [],
            }
        ],
        "defined_names": [],
        "tables": [],
        "charts": [
            _chart("ColumnChart", "column", "E2:L16"),
            _chart("BarChart", "bar", "M2:T16", value_column="C"),
            _chart("LineChart", "line", "E18:L32"),
            _chart("PieChart", "pie", "M18:T32"),
            _chart("ScatterChart", "scatter", "U2:AB16"),
        ],
        "chart_reference": None,
        "page_setup": None,
    }


def test_native_chart_create_reopens_and_projects_full_details(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "charts.xlsx"
    result = XlsxService(project_root).execute(
        "xlsx.create",
        {
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _workbook()},
        },
    )

    assert result["status"] == "success", result
    reopened = load_workbook(output, data_only=False)
    assert [type(chart).__name__ for chart in reopened["Data"]._charts] == [
        "BarChart",
        "BarChart",
        "LineChart",
        "PieChart",
        "ScatterChart",
    ]
    assert [chart.type for chart in reopened["Data"]._charts[:2]] == ["col", "bar"]
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert {f"xl/charts/chart{index}.xml" for index in range(1, 6)} <= names
    assert "xl/drawings/drawing1.xml" in names
    assert "xl/drawings/_rels/drawing1.xml.rels" in names

    read_result = XlsxService(project_root).execute(
        "xlsx.read",
        {"operation": "xlsx.read", "input": str(output), "arguments": {}},
    )
    projected = read_result["diagnostics"]["operation_result"]["charts"]
    assert [chart["type"] for chart in projected] == [
        "column",
        "bar",
        "line",
        "pie",
        "scatter",
    ]
    assert projected[0]["name"] == "ColumnChart"
    assert projected[0]["anchor"] == "E2:L16"
    assert projected[0]["series"][0]["categories"] == "'Data'!$A$2:$A$5"
    assert projected[0]["series"][0]["color"] == "FF4472C4"
    assert projected[0]["y_axis_number_format"] == "#,##0.00"
    assert projected[3]["x_axis_title"] is None
    assert projected[4]["series"][0]["x_values"] == "'Data'!$B$2:$B$5"
    assert all(chart["content_type"].endswith("drawingml.chart+xml") for chart in projected)


def test_native_chart_create_is_deterministic(
    project_root: Path,
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / "first.xlsx", tmp_path / "second.xlsx"]
    for output in outputs:
        result = XlsxService(project_root).execute(
            "xlsx.create",
            {
                "operation": "xlsx.create",
                "output": str(output),
                "arguments": {"workbook": _workbook()},
            },
        )
        assert result["status"] == "success"
    assert outputs[0].read_bytes() == outputs[1].read_bytes()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda chart: chart.update({"type": "radar"}),
        lambda chart: chart.update({"anchor": "E2:E16"}),
        lambda chart: chart["series"][0].update({"values": "Data!$B$2:$B$4"}),
        lambda chart: chart["series"][0].update({"values": "Missing!$B$2:$B$5"}),
        lambda chart: chart["series"][0].update({"values": "[Book.xlsx]Data!$B$2:$B$5"}),
    ],
)
def test_native_chart_contract_rejects_invalid_boundaries(mutate) -> None:
    workbook = _workbook()
    workbook["charts"] = [workbook["charts"][0]]
    mutate(workbook["charts"][0])
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request(
            {
                "operation": "xlsx.create",
                "output": "chart.xlsx",
                "arguments": {"workbook": workbook},
            }
        )
    assert exc.value.code.value == "DS_REQUEST_INVALID"
