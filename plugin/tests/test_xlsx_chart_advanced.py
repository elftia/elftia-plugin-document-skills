"""Advanced native chart contract, emission, readback, and edit coverage."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.xlsx.contracts import parse_xlsx_request
from document_skills_core.formats.xlsx.service import XlsxService

from test_xlsx_chart_create import _chart, _series, _workbook


def _advanced_workbook() -> dict:
    workbook = _workbook()
    cells = workbook["sheets"][0]["rows"][0]["cells"]
    cells.append({"ref": "D1", "value": "Size", "type": "s"})
    cells.extend(
        {"ref": f"D{row}", "value": str(row * 3), "type": "n"}
        for row in range(2, 6)
    )
    area = _chart("AreaChart", "area", "E2:L16")
    area["style"] = 10
    radar = _chart("RadarChart", "radar", "M2:T16", value_column="C")
    radar.pop("x_axis_title")
    radar.pop("y_axis_title")
    radar.pop("y_axis_number_format")
    radar["radar_style"] = "marker"
    bubble = {
        "name": "BubbleChart",
        "sheet": "Data",
        "type": "bubble",
        "title": "Bubble chart",
        "anchor": "U2:AB16",
        "series": [
            {
                "name": "Bubble",
                "x_values": "Data!$B$2:$B$5",
                "y_values": "Data!$C$2:$C$5",
                "bubble_sizes": "Data!$D$2:$D$5",
                "color": "#70AD47",
                "trendline": {
                    "type": "linear",
                    "display_equation": True,
                    "display_r_squared": True,
                },
                "error_bars": [
                    {
                        "direction": "y",
                        "type": "custom",
                        "plus": "Data!$D$2:$D$5",
                        "minus": "Data!$D$2:$D$5",
                    }
                ],
            }
        ],
        "show_legend": True,
        "legend_position": "r",
        "x_axis_title": "Revenue",
        "y_axis_title": "Cost",
        "data_labels": {"show_value": False},
        "bubble_scale": 125,
    }
    combo = {
        "name": "ComboChart",
        "sheet": "Data",
        "type": "combo",
        "title": "Revenue and cost",
        "anchor": "E18:L32",
        "series": [
            {
                **_series("Revenue", "B", "#4472C4"),
                "chart_type": "column",
            },
            {
                **_series("Cost", "C", "#ED7D31"),
                "chart_type": "line",
                "axis": "secondary",
                "trendline": {"type": "polynomial", "order": 2},
                "error_bars": [
                    {"direction": "y", "type": "fixed", "value": 2}
                ],
            },
        ],
        "show_legend": True,
        "legend_position": "b",
        "x_axis_title": "Quarter",
        "y_axis_title": "Revenue",
        "secondary_y_axis_title": "Cost",
        "secondary_y_axis_number_format": "0.0",
        "data_labels": {"show_value": True},
    }
    workbook["charts"] = [area, radar, bubble, combo]
    return workbook


def test_advanced_charts_reopen_and_project_typed_details(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "advanced-charts.xlsx"
    result = XlsxService(project_root).execute(
        "xlsx.create",
        {
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _advanced_workbook()},
        },
    )

    assert result["status"] == "success", result
    reopened = load_workbook(output, data_only=False)
    assert len(reopened["Data"]._charts) == 4
    reopened.close()
    with zipfile.ZipFile(output) as archive:
        chart_xml = [
            archive.read(f"xl/charts/chart{index}.xml").decode("utf-8")
            for index in range(1, 5)
        ]
    assert "<c:areaChart>" in chart_xml[0]
    assert "<c:radarChart>" in chart_xml[1]
    assert "<c:bubbleChart>" in chart_xml[2]
    assert "<c:trendline>" in chart_xml[2]
    assert "<c:errBars>" in chart_xml[2]
    assert "<c:barChart>" in chart_xml[3] and "<c:lineChart>" in chart_xml[3]

    read = XlsxService(project_root).execute(
        "xlsx.read",
        {"operation": "xlsx.read", "input": str(output), "arguments": {}},
    )
    charts = read["diagnostics"]["operation_result"]["charts"]
    assert [chart["type"] for chart in charts] == ["area", "radar", "bubble", "combo"]
    assert charts[0]["style"] == 10
    assert charts[1]["radar_style"] == "marker"
    assert charts[2]["bubble_scale"] == 125
    assert charts[2]["series"][0]["bubble_sizes"] == "'Data'!$D$2:$D$5"
    assert charts[2]["series"][0]["trendline"]["display_equation"] is True
    assert charts[2]["series"][0]["error_bars"][0]["type"] == "custom"
    assert charts[3]["secondary_y_axis_title"] == "Cost"
    assert charts[3]["secondary_y_axis_number_format"] == "0.0"
    assert [series["chart_type"] for series in charts[3]["series"]] == [
        "column",
        "line",
    ]
    assert charts[3]["series"][1]["axis"] == "secondary"
    assert charts[3]["series"][1]["trendline"]["order"] == 2
    assert charts[3]["series"][1]["error_bars"][0]["value"] == 2


def test_advanced_chart_update_replaces_basic_chart(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "basic.xlsx"
    workbook = _workbook()
    workbook["charts"] = [workbook["charts"][0]]
    created = XlsxService(project_root).execute(
        "xlsx.create",
        {
            "operation": "xlsx.create",
            "output": str(source),
            "arguments": {"workbook": workbook},
        },
    )
    assert created["status"] == "success"
    advanced = _advanced_workbook()["charts"][3]
    output = tmp_path / "advanced-edit.xlsx"
    result = XlsxService(project_root).execute(
        "xlsx.edit",
        {
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "sheet": "Data",
                        "type": "chart_update",
                        "name": "ColumnChart",
                        "chart": advanced,
                    }
                ],
                "expected_edits": 1,
            },
        },
    )

    assert result["status"] == "success", result
    read = XlsxService(project_root).execute(
        "xlsx.read",
        {"operation": "xlsx.read", "input": str(output), "arguments": {}},
    )
    assert read["diagnostics"]["operation_result"]["charts"][0]["type"] == "combo"


def test_advanced_chart_references_and_style_survive_structural_edit(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "advanced-source.xlsx"
    workbook = _advanced_workbook()
    workbook["charts"] = [workbook["charts"][0], workbook["charts"][2]]
    created = XlsxService(project_root).execute(
        "xlsx.create",
        {
            "operation": "xlsx.create",
            "output": str(source),
            "arguments": {"workbook": workbook},
        },
    )
    assert created["status"] == "success"
    output = tmp_path / "advanced-structural-edit.xlsx"
    result = XlsxService(project_root).execute(
        "xlsx.edit",
        {
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "row_insert", "ref": "2", "count": 1}
                ],
                "expected_edits": 1,
            },
        },
    )

    assert result["status"] == "success", result
    read = XlsxService(project_root).execute(
        "xlsx.read",
        {"operation": "xlsx.read", "input": str(output), "arguments": {}},
    )
    charts = read["diagnostics"]["operation_result"]["charts"]
    assert charts[0]["style"] == 10
    assert charts[0]["series"][0]["values"] == "'Data'!$B$3:$B$6"
    assert charts[0]["anchor"] == "E3:L17"
    bubble = charts[1]["series"][0]
    assert bubble["bubble_sizes"] == "'Data'!$D$3:$D$6"
    assert bubble["error_bars"][0]["plus"] == "'Data'!$D$3:$D$6"
    assert bubble["error_bars"][0]["minus"] == "'Data'!$D$3:$D$6"
    assert bubble["color"] == "FF70AD47"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda chart: chart["series"][1].update({"chart_type": "column"}),
        lambda chart: chart["series"][0].update({"axis": "secondary"}),
        lambda chart: chart["series"][1]["trendline"].pop("order"),
        lambda chart: chart["series"][1]["error_bars"][0].update(
            {"direction": "x"}
        ),
    ],
)
def test_advanced_chart_contract_rejects_invalid_boundaries(mutate) -> None:
    workbook = _advanced_workbook()
    workbook["charts"] = [workbook["charts"][3]]
    mutate(workbook["charts"][0])
    with pytest.raises(DocumentSkillsError) as exc:
        parse_xlsx_request(
            {
                "operation": "xlsx.create",
                "output": "advanced-chart.xlsx",
                "arguments": {"workbook": workbook},
            }
        )
    assert exc.value.code.value == "DS_REQUEST_INVALID"
