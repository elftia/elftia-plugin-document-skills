"""Structured XLSX workbook read — deterministic sheet/row/cell projection."""

from pathlib import Path
from typing import Any

from document_skills_core.core.io.core_properties import project_core_properties

from .formula_state import build_formula_state_summary
from .mapping import map_workbook
from .package import OpcPackage
from .projection import (
    project_charts,
    project_drawings,
    project_external_links,
    project_hyperlinks,
    project_pivot_caches,
    project_tables,
)


def read_xlsx(
    path: str | Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read an XLSX workbook and return (operation_result, warnings)."""
    package = OpcPackage.open(path)
    include_formulas = arguments.get("include_formulas", True)
    max_rows = arguments.get("max_rows", 5_000)
    max_cells = arguments.get("max_cells_per_sheet", 10_000)
    sheet_filter = arguments.get("sheet")

    workbook = map_workbook(package)
    warnings: list[dict[str, Any]] = []

    # Apply sheet filter
    sheets = workbook["sheets"]
    if sheet_filter:
        sheets = [s for s in sheets if s["name"] == sheet_filter]
        if not sheets:
            warnings.append({
                "code": "DS_SHEET_NOT_FOUND",
                "message": f"Requested sheet '{sheet_filter}' was not found.",
                "details": {"available": [s["name"] for s in workbook["sheets"]]},
            })

    # Apply row/cell limits with truncation warnings
    total_cells = 0
    for sheet in sheets:
        if len(sheet["rows"]) > max_rows:
            warnings.append({
                "code": "DS_ROW_LIMIT",
                "message": f"Sheet '{sheet['name']}' exceeded row limit; truncated.",
                "details": {"total": len(sheet["rows"]), "limit": max_rows},
            })
            sheet["rows"] = sheet["rows"][:max_rows]
        for row in sheet["rows"]:
            cell_count = len(row["cells"])
            if total_cells + cell_count > max_cells:
                remaining = max_cells - total_cells
                if remaining > 0:
                    row["cells"] = row["cells"][:remaining]
                    total_cells = max_cells
                else:
                    row["cells"] = []
                warnings.append({
                    "code": "DS_CELL_LIMIT",
                    "message": f"Cell limit reached in sheet '{sheet['name']}'.",
                    "details": {"limit": max_cells},
                })
                break
            total_cells += cell_count

    # Build formula state
    formula_cells = workbook.get("formula_cells", {})
    if not include_formulas:
        for sheet in sheets:
            for row in sheet["rows"]:
                for cell in row["cells"]:
                    cell.pop("formula_state", None)
                    cell.pop("formula", None)
        formula_cells = {}

    formula_summary = build_formula_state_summary(formula_cells)

    # Project supporting structures
    tables = project_tables(package)
    charts = project_charts(package)
    pivot_caches = project_pivot_caches(package)
    external_links = project_external_links(package)
    drawings = project_drawings(package)

    # Hyperlinks per sheet
    hyperlinks: list[dict[str, Any]] = []
    for name in package.worksheet_parts():
        hyperlinks.extend(project_hyperlinks(package, name))

    operation_result: dict[str, Any] = {
        "metadata": project_core_properties(package.parts),
        "sheets": sheets,
        "sheet_count": len(sheets),
        "defined_names": workbook["defined_names"],
        "shared_strings_count": workbook["shared_strings_count"],
        "tables": tables,
        "charts": charts,
        "pivot_caches": pivot_caches,
        "external_links": external_links,
        "drawings": drawings,
        "hyperlinks": hyperlinks,
        "full_calc_on_load": workbook["full_calc_on_load"],
        "formula_state": {
            "cells": formula_cells,
            "summary": formula_summary,
        },
    }
    return operation_result, warnings
