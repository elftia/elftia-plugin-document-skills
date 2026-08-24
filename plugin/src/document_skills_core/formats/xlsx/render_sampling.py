"""Bounded workbook-risk sampling attached to XLSX PDF renders."""

from collections import Counter
from pathlib import Path
from typing import Any

from .chart_projection import project_charts
from .format_policy import assert_package_matches_path, format_id
from .mapping import map_workbook, parse_ref
from .package import OpcPackage
from .projection import project_tables
from .worksheet_metadata import project_worksheet_metadata

_DEFAULT_COLUMN_WIDTH = 8.43
_WIDE_COLUMN_THRESHOLD = 80.0


def sample_render_source(
    input_path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Preflight a safe XLSX and report bounded layout-risk evidence."""

    package = OpcPackage.open(input_path)
    assert_package_matches_path(input_path, package.workbook_format)
    workbook = map_workbook(package)
    tables = Counter(item.get("sheet", "") for item in project_tables(package))
    charts = Counter(item.get("sheet", "") for item in project_charts(package))
    metadata = {
        item["sheet"]: item for item in project_worksheet_metadata(package)
    }
    findings: list[dict[str, Any]] = []
    finding_counts: Counter[str] = Counter()
    samples = []
    sheets = workbook.get("sheets", [])
    selected = sheets[: arguments["max_sheets"]]
    for sheet in selected:
        sample = _sample_sheet(
            sheet,
            metadata.get(sheet["name"], {}),
            table_count=tables[sheet["name"]],
            chart_count=charts[sheet["name"]],
            max_cells=arguments["max_cells_per_sheet"],
        )
        samples.append(sample)
        for finding in sample.pop("findings"):
            finding_counts[finding["kind"]] += 1
            if len(findings) < arguments["max_findings"]:
                findings.append(finding)
    truncated_sheets = max(0, len(sheets) - len(selected))
    truncated_findings = max(0, sum(finding_counts.values()) - len(findings))
    warnings = _sampling_warnings(
        finding_counts=finding_counts,
        truncated_sheets=truncated_sheets,
        truncated_findings=truncated_findings,
    )
    return (
        {
            "source_format": format_id(input_path),
            "workbook_format": package.workbook_format,
            "sheet_count": len(sheets),
            "visible_sheet_count": sum(
                sheet.get("state", "visible") == "visible" for sheet in sheets
            ),
            "sampled_sheet_count": len(samples),
            "truncated_sheet_count": truncated_sheets,
            "samples": samples,
            "risk_findings": findings,
            "risk_finding_counts": dict(sorted(finding_counts.items())),
            "truncated_finding_count": truncated_findings,
            "security": package.security,
            "scope": (
                "Workbook metadata and cell-risk sampling accompany the rendered PDF; "
                "they do not prove per-object visual parity."
            ),
        },
        warnings,
    )


def _sample_sheet(
    sheet: dict[str, Any],
    metadata: dict[str, Any],
    *,
    table_count: int,
    chart_count: int,
    max_cells: int,
) -> dict[str, Any]:
    rows = sheet.get("rows", [])
    columns = sheet.get("columns", [])
    hidden_rows = sum(bool(row.get("hidden")) for row in rows)
    hidden_columns = sum(
        column["max"] - column["min"] + 1
        for column in columns
        if column.get("hidden")
    )
    wide_columns = [
        column["ref"]
        for column in columns
        if (column.get("width") or 0) > _WIDE_COLUMN_THRESHOLD
    ]
    findings: list[dict[str, Any]] = []
    if sheet.get("state", "visible") != "visible":
        findings.append({
            "kind": "hidden-sheet",
            "sheet": sheet["name"],
            "state": sheet.get("state"),
        })
    if hidden_rows or hidden_columns:
        findings.append({
            "kind": "hidden-data",
            "sheet": sheet["name"],
            "hidden_rows": hidden_rows,
            "hidden_columns": hidden_columns,
        })
    if wide_columns:
        findings.append({
            "kind": "wide-columns",
            "sheet": sheet["name"],
            "columns": wide_columns[:32],
            "truncated_columns": max(0, len(wide_columns) - 32),
        })
    sampled_cells = 0
    potential_truncation = []
    total_cells = sum(len(row.get("cells", [])) for row in rows)
    for row in rows:
        for cell in row.get("cells", []):
            if sampled_cells >= max_cells:
                break
            sampled_cells += 1
            value = cell.get("value")
            if type(value) is not str or not value:
                continue
            alignment = cell.get("style", {}).get("alignment", {})
            width = _column_width(columns, cell.get("ref", ""))
            if (
                len(value) > max(40, int(width * 2))
                and not alignment.get("wrap", False)
                and not alignment.get("shrink_to_fit", False)
            ):
                potential_truncation.append({
                    "ref": cell.get("ref", ""),
                    "characters": len(value),
                    "column_width": width,
                })
        if sampled_cells >= max_cells:
            break
    if potential_truncation:
        findings.append({
            "kind": "potential-text-truncation",
            "sheet": sheet["name"],
            "cells": potential_truncation[:32],
            "truncated_cells": max(0, len(potential_truncation) - 32),
        })
    page_setup = metadata.get("page_setup")
    return {
        "sheet": sheet["name"],
        "state": sheet.get("state", "visible"),
        "dimension": sheet.get("dimension", ""),
        "total_cells": total_cells,
        "sampled_cells": sampled_cells,
        "cell_sampling_truncated": total_cells > sampled_cells,
        "hidden_rows": hidden_rows,
        "hidden_columns": hidden_columns,
        "wide_column_count": len(wide_columns),
        "table_count": table_count,
        "chart_count": chart_count,
        "print_area": metadata.get("print_area"),
        "print_titles": metadata.get("print_titles"),
        "page_setup": None if page_setup is None else {
            key: page_setup.get(key)
            for key in (
                "orientation",
                "paper_size",
                "fit_to_width",
                "fit_to_height",
                "scale",
                "fit_to_page",
            )
        },
        "header_footer_present": _header_footer_present(
            metadata.get("header_footer")
        ),
        "findings": findings,
    }


def _column_width(columns: list[dict[str, Any]], cell_ref: str) -> float:
    parsed = parse_ref(cell_ref)
    if parsed is None:
        return _DEFAULT_COLUMN_WIDTH
    column_number = 0
    for char in parsed[0]:
        column_number = column_number * 26 + ord(char) - ord("A") + 1
    for column in columns:
        if column["min"] <= column_number <= column["max"]:
            return column.get("width") or _DEFAULT_COLUMN_WIDTH
    return _DEFAULT_COLUMN_WIDTH


def _header_footer_present(value: dict[str, Any] | None) -> bool:
    if value is None:
        return False
    return any(
        bool(value.get(key))
        for key in (
            "odd_header",
            "odd_footer",
            "even_header",
            "even_footer",
            "first_header",
            "first_footer",
            "different_first",
            "different_odd_even",
        )
    )


def _sampling_warnings(
    *,
    finding_counts: Counter[str],
    truncated_sheets: int,
    truncated_findings: int,
) -> list[dict[str, Any]]:
    warnings = [{
        "code": "DS_XLSX_RENDER_SCOPE_LIMITED",
        "message": (
            "The PDF was reopened, but metadata sampling does not prove Excel/"
            "LibreOffice parity or per-object chart/table visibility."
        ),
        "details": {"sampling": "bounded-metadata-plus-pdf-reopen"},
    }]
    if finding_counts or truncated_sheets or truncated_findings:
        warnings.append({
            "code": "DS_XLSX_RENDER_RISK_FINDINGS",
            "message": "The bounded render sample found layout risks or omitted evidence.",
            "details": {
                "finding_counts": dict(sorted(finding_counts.items())),
                "truncated_sheets": truncated_sheets,
                "truncated_findings": truncated_findings,
            },
        })
    return warnings
