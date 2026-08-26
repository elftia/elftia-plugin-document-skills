"""Black-box helpers for exercising the freshly built XLSX distribution."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from xml.etree.ElementTree import fromstring, register_namespace, tostring
import zipfile


XLSX_OPERATIONS = {
    "xlsx.convert",
    "xlsx.create",
    "xlsx.edit",
    "xlsx.inspect.structure",
    "xlsx.pivot.create",
    "xlsx.read",
    "xlsx.recalculate",
    "xlsx.render",
    "xlsx.summary.aggregate",
    "xlsx.template.instantiate",
    "xlsx.validate.schema",
}


class DistXlsx:
    """Invoke the shipped XLSX launcher without importing production modules."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runner = self.root / "skills" / "document-xlsx" / "scripts" / "run.py"
        if not self.runner.is_file():
            raise AssertionError(f"missing built XLSX runner: {self.runner}")

    def invoke(self, *arguments: str, check: bool = True) -> dict[str, Any]:
        environment = os.environ.copy()
        environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] = "0"
        process = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(self.root),
                "--frozen",
                "python",
                str(self.runner),
                *arguments,
            ],
            cwd=self.root,
            env=environment,
            check=False,
            capture_output=True,
            text=False,
            shell=False,
            timeout=90,
        )
        if check:
            assert process.returncode == 0, _failure_text(process)
        assert process.stderr == b"", _failure_text(process)
        decoded = process.stdout.decode("utf-8", errors="strict")
        payload, end = json.JSONDecoder().raw_decode(decoded)
        assert decoded[end:].strip() == ""
        assert type(payload) is dict
        return payload

    def run(self, request: Path, *, check: bool = True) -> dict[str, Any]:
        return self.invoke("run", "--request", str(request), check=check)


def write_request(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_xltx(source: Path, destination: Path) -> Path:
    """Turn a public-created XLSX into an inert template for the template seam."""

    assert source.suffix.casefold() == ".xlsx"
    assert destination.suffix.casefold() == ".xltx"
    with zipfile.ZipFile(source, "r") as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    content_types = "http://schemas.openxmlformats.org/package/2006/content-types"
    register_namespace("", content_types)
    root = fromstring(parts["[Content_Types].xml"])
    workbook_override = next(
        item
        for item in root.findall(f"{{{content_types}}}Override")
        if item.attrib.get("PartName") == "/xl/workbook.xml"
    )
    assert workbook_override.attrib["ContentType"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    workbook_override.attrib["ContentType"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml"
    )
    parts["[Content_Types].xml"] = tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
    )
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)
    return destination


def canonical_document() -> dict[str, Any]:
    """Canonical typed values whose expected XLSX losses are independently known."""

    headers = [
        "Code",
        "Amount",
        "Approved",
        "Date",
        "Time",
        "Local datetime",
        "Offset datetime",
        "Null",
        "Empty",
        "Dangerous text",
        "Cached formula",
    ]
    return {
        "schema_version": "1.0",
        "format": "document-skills-tabular",
        "sheets": [
            {
                "name": "Typed",
                "rows": [
                    [{"type": "string", "value": value} for value in headers],
                    [
                        {"type": "string", "value": "00123"},
                        {"type": "number", "value": "12.50"},
                        {"type": "boolean", "value": True},
                        {"type": "date", "value": "2026-08-24"},
                        {"type": "time", "value": "12:30:15"},
                        {"type": "datetime", "value": "2026-08-24T12:30:15"},
                        {
                            "type": "datetime",
                            "value": "2026-08-24T12:30:15+08:00",
                        },
                        {"type": "null", "value": None},
                        {"type": "empty", "value": ""},
                        {"type": "string", "value": "=1+1"},
                        {
                            "type": "formula",
                            "formula": "B2*2",
                            "cached": {"type": "number", "value": "25"},
                        },
                    ],
                ],
            }
        ],
    }


def rich_workbook() -> dict[str, Any]:
    """Return a bounded typed workbook spanning the risky native-object seams."""

    numeric_style = {"number_format": {"id": 165}}
    rows = [
        {
            "height": 22,
            "style": {
                "font": {"bold": True, "color": "#FFFFFF"},
                "fill": {"pattern": "solid", "color": "#4472C4"},
            },
            "cells": [
                {"ref": "A1", "value": "Region", "type": "s"},
                {"ref": "B1", "value": "Revenue", "type": "s"},
                {"ref": "C1", "value": "Cost", "type": "s"},
                {"ref": "D1", "value": "Approved", "type": "s"},
                {"ref": "E1", "value": "Margin", "type": "s"},
            ],
        }
    ]
    for row_number, (region, revenue, cost, approved) in enumerate(
        [
            ("East", 10, 7, True),
            ("West", 20, 12, False),
            ("East", 15, 9, True),
            ("West", 5, 4, True),
        ],
        start=2,
    ):
        cells: list[dict[str, Any]] = [
            {"ref": f"A{row_number}", "value": region, "type": "s"},
            {
                "ref": f"B{row_number}",
                "value": str(revenue),
                "type": "n",
                "style": numeric_style,
            },
            {
                "ref": f"C{row_number}",
                "value": str(cost),
                "type": "n",
                "style": numeric_style,
            },
            {"ref": f"D{row_number}", "value": "1" if approved else "0", "type": "b"},
            {
                "ref": f"E{row_number}",
                "formula": f"B{row_number}-C{row_number}",
                "cached_value": str(revenue - cost),
                "type": "n",
                "style": numeric_style,
            },
        ]
        rows.append({"cells": cells})

    return {
        "metadata": {
            "title": "XLSX dist E2E",
            "creator": "Elftia",
            "subject": "Release artifact",
            "description": "Public seam coverage",
            "keywords": "xlsx,e2e",
            "category": "Test",
            "last_modified_by": "Dist E2E",
            "company": "Elftia",
            "manager": "Quality",
        },
        "sheets": [
            {
                "name": "Data",
                "rows": rows,
                "columns": [
                    {"ref": "A", "width": 16, "hidden": False, "style": None},
                    {"ref": "G", "width": 14, "hidden": False, "style": None},
                ],
                "number_formats": [{"id": 165, "code": "$#,##0.00"}],
                "view": {
                    "show_grid_lines": False,
                    "zoom_scale": 110,
                    "selected_cell": "B2",
                },
                "page_setup": {
                    "orientation": "landscape",
                    "paper_size": "a4",
                    "fit_to_width": 1,
                    "fit_to_height": 0,
                    "margins": {
                        "left": 0.5,
                        "right": 0.5,
                        "top": 0.6,
                        "bottom": 0.6,
                        "header": 0.2,
                        "footer": 0.2,
                    },
                    "horizontal_centered": True,
                    "vertical_centered": False,
                },
                "header_footer": {
                    "odd_header": "&CXLSX dist E2E",
                    "odd_footer": "&RPage &P of &N",
                    "even_header": "",
                    "even_footer": "",
                    "first_header": "",
                    "first_footer": "",
                    "different_first": False,
                    "different_odd_even": False,
                    "scale_with_doc": True,
                    "align_with_margins": True,
                },
                "print_area": "A1:O20",
                "print_titles": {"rows": "1:1", "columns": "A:A"},
                "hyperlinks": [
                    {
                        "ref": "A2",
                        "location": "Details!A1",
                        "display": "East details",
                        "tooltip": "Internal target",
                    }
                ],
                "comments": [
                    {"ref": "E2", "text": "Check margin", "author": "Dist E2E"}
                ],
                "data_validations": [
                    {
                        "ref": "D2:D5",
                        "type": "list",
                        "formula1": '"TRUE,FALSE"',
                        "allow_blank": False,
                    }
                ],
                "conditional_formats": [
                    {
                        "ref": "E2:E5",
                        "type": "cellIs",
                        "operator": "greaterThan",
                        "formulas": ["5"],
                        "style": {"fill": {"pattern": "solid", "color": "#C6EFCE"}},
                    }
                ],
                "sparklines": [
                    {
                        "location": "G2",
                        "data": "Data!B2:C2",
                        "type": "line",
                        "markers": True,
                        "color": "#4472C4",
                    },
                    {
                        "location": "G3",
                        "data": "Data!B3:C3",
                        "type": "column",
                        "markers": True,
                        "color": "#70AD47",
                    },
                ],
            },
            {
                "name": "Details",
                "rows": [
                    {"cells": [{"ref": "A1", "value": "Detail target", "type": "s"}]}
                ],
                "columns": [],
                "number_formats": [],
            },
        ],
        "defined_names": [
            {"name": "RevenueRange", "ref": "Data!$B$2:$B$5", "scope": "workbook"}
        ],
        "tables": [
            {
                "name": "SalesTable",
                "ref": "A1:C5",
                "sheet": "Data",
                "style": "TableStyleMedium2",
            }
        ],
        "charts": [
            {
                "name": "RevenueChart",
                "sheet": "Data",
                "type": "column",
                "title": "Revenue by region",
                "anchor": "H2:O16",
                "series": [
                    {
                        "name": "Revenue",
                        "categories": "Data!$A$2:$A$5",
                        "values": "Data!$B$2:$B$5",
                        "color": "#4472C4",
                    }
                ],
                "show_legend": True,
                "legend_position": "r",
                "x_axis_title": "Region",
                "y_axis_title": "Revenue",
                "y_axis_number_format": "$#,##0",
                "data_labels": {"show_value": True},
            }
        ],
        "chart_reference": None,
        "page_setup": None,
    }


def _failure_text(process: subprocess.CompletedProcess[bytes]) -> str:
    return (
        process.stderr.decode("utf-8", errors="replace")
        or process.stdout.decode("utf-8", errors="replace")
        or f"public XLSX process exited {process.returncode}"
    )
