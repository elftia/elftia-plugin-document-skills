"""Public-facade closure for advanced native chart authoring."""

from pathlib import Path

from test_xlsx_chart_advanced import _advanced_workbook
from test_xlsx_public import _public, _request


def test_public_advanced_native_charts_reopen_and_read_back(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    output = tmp_path / "public-advanced-charts.xlsx"
    create_request = _request(
        tmp_path,
        "public-advanced-chart-create.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(output),
            "arguments": {"workbook": _advanced_workbook()},
        },
    )

    created = _public(project_root, "run", "--request", str(create_request))

    assert created["status"] == "success"
    reopened = load_workbook(output, data_only=False)
    assert len(reopened["Data"]._charts) == 4
    reopened.close()
    read_request = _request(
        tmp_path,
        "public-advanced-chart-read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read = _public(project_root, "run", "--request", str(read_request))
    charts = read["diagnostics"]["operation_result"]["charts"]
    assert [chart["type"] for chart in charts] == ["area", "radar", "bubble", "combo"]
    assert charts[2]["series"][0]["trendline"]["type"] == "linear"
    assert charts[2]["series"][0]["error_bars"][0]["type"] == "custom"
    assert charts[3]["series"][1]["axis"] == "secondary"
    assert charts[3]["secondary_y_axis_title"] == "Cost"
