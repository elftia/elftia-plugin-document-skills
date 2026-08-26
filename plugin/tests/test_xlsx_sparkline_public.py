"""Public-facade closure for native worksheet sparklines."""

from pathlib import Path
import zipfile

from test_xlsx_public import _public, _request
from test_xlsx_sparkline import _workbook


def test_public_sparklines_create_edit_and_read_back(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "public-sparklines.xlsx"
    create_request = _request(
        tmp_path,
        "public-sparkline-create.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.create",
            "output": str(source),
            "arguments": {"workbook": _workbook()},
        },
    )
    assert _public(project_root, "run", "--request", str(create_request))["status"] == "success"

    output = tmp_path / "public-sparklines-edited.xlsx"
    edit_request = _request(
        tmp_path,
        "public-sparkline-edit.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"sheet": "Data", "type": "sparkline_delete", "ref": "E3"}
                ],
                "expected_edits": 1,
            },
        },
    )
    assert _public(project_root, "run", "--request", str(edit_request))["status"] == "success"
    with zipfile.ZipFile(output) as archive:
        worksheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "x14:sparklineGroups" in worksheet

    read_request = _request(
        tmp_path,
        "public-sparkline-read.json",
        {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read = _public(project_root, "run", "--request", str(read_request))
    sparklines = read["diagnostics"]["operation_result"]["sparklines"]
    assert [(item["location"], item["type"]) for item in sparklines] == [
        ("E2", "line"),
        ("E4", "win_loss"),
    ]
