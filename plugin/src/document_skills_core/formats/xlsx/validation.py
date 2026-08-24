"""XLSX reopen, semantic, and preservation validation gates."""

from pathlib import Path
import re
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation import validate_artifact

from .annotations import project_comments
from .formula_state import assert_invariant
from .constants import NS
from .format_policy import (
    allowed_inert_categories,
    assert_package_matches_path,
    format_id,
)
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest
from .projection import (
    project_conditional_formats,
    project_charts,
    project_data_validations,
    project_hyperlinks,
    project_tables,
)
from .sparkline import project_sparklines
from .sparkline_validation import (
    missing_created_sparklines,
    sparkline_edit_matches,
)
from .styles import read_styles
from .structural_refs import AxisMutation, shift_coordinate
from .worksheet_metadata import project_worksheet_metadata
from .workbook_properties import project_workbook_properties

_MAIN_NS = NS["main"]


def validate_created(
    path: Path,
    workbook: dict[str, Any],
    *,
    creation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assertions = [
        ("consumer-package-conformance", _assert_consumer_package),
        (
            "create-semantics",
            lambda candidate: _assert_created(candidate, workbook, creation=creation),
        ),
    ]
    return _required_report(path, assertions=assertions)


def validate_converted(path: Path) -> dict[str, Any]:
    """Reopen a provider-converted workbook without assuming authored semantics."""

    return _required_report(
        path,
        assertions=[("consumer-package-conformance", _assert_consumer_package)],
    )


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: PreservationManifest,
    allowed_removed_parts: set[str] | None = None,
    assertion: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("consumer-package-conformance", _assert_consumer_package),
        (
            "part-preservation",
            lambda _candidate: _assert_preservation(
                manifest,
                allowed_removed_parts=allowed_removed_parts or set(),
            ),
        )
    ]
    if assertion is not None:
        assertions.append(("mutation-semantics", assertion))
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
    )


def reopen_xlsx(path: Path) -> dict[str, Any]:
    """Reopen an XLSX package and verify its required structures."""
    package = _open_candidate(path)
    workbook = map_workbook(package)
    return {
        "parts": len(package.parts),
        "relationships": len(package.relationships),
        "sheets": len(workbook["sheets"]),
        "formula_cells": len(workbook.get("formula_cells", {})),
    }


def assert_formula_state_invariant(
    formula_cells: dict[str, dict[str, Any]],
    *,
    recalculation_provider: str | None = None,
) -> dict[str, Any]:
    """Assert the formula-state invariant gate."""
    assert_invariant(formula_cells, recalculation_provider=recalculation_provider)
    return {"no_unverified_claimed_recalculated": True}


def assert_edits_applied(
    path: Path,
    edits: list[dict[str, Any]],
    *,
    source: Path | None = None,
) -> dict[str, Any]:
    """Reopen a staged mutation and prove every bounded edit took effect."""

    package = _open_candidate(path)
    mapped = map_workbook(package)
    sheets = {sheet["name"]: sheet for sheet in mapped.get("sheets", [])}
    rename_map = {
        edit["sheet"]: edit.get("value", "")
        for edit in edits
        if edit["type"] == "sheet_rename" and edit.get("value")
    }
    failures: list[str] = []
    matched = 0
    projected_tables = project_tables(package)
    projected_validations = project_data_validations(package)
    projected_conditional_formats = project_conditional_formats(package)
    projected_charts = project_charts(package)
    projected_sparklines = project_sparklines(package)
    projected_hyperlinks = [
        hyperlink
        for sheet in mapped.get("sheets", [])
        if sheet.get("part")
        for hyperlink in project_hyperlinks(package, sheet["part"], sheet["name"])
    ]
    projected_comments = project_comments(package)
    projected_properties = project_workbook_properties(package.parts)
    projected_worksheet_metadata = {
        item["sheet"]: item for item in project_worksheet_metadata(package)
    }
    expected_cells = _expected_cell_refs(source, edits) if source is not None else None
    for edit in edits:
        edit_type = edit["type"]
        if edit_type == "sheet_rename":
            if edit.get("value") not in sheets:
                failures.append(f"sheet_rename:{edit['sheet']}")
            else:
                matched += 1
            continue
        if edit_type == "sheet_add":
            if edit["sheet"] in sheets:
                matched += 1
            else:
                failures.append(f"sheet_add:{edit['sheet']}")
            continue
        if edit_type == "sheet_copy":
            if edit["name"] in sheets:
                matched += 1
            else:
                failures.append(f"sheet_copy:{edit['sheet']}->{edit['name']}")
            continue
        if edit_type == "sheet_delete":
            if edit["sheet"] not in sheets:
                matched += 1
            else:
                failures.append(f"sheet_delete:{edit['sheet']}")
            continue
        if edit_type == "sheet_reorder":
            order = list(sheets)
            expected_position = min(edit["position"], len(order) - 1)
            if edit["sheet"] in sheets and order.index(edit["sheet"]) == expected_position:
                matched += 1
            else:
                failures.append(f"sheet_reorder:{edit['sheet']}")
            continue
        if edit_type in {
            "table_add",
            "table_resize",
            "table_rename",
            "table_style",
            "table_delete",
        }:
            expected_name = edit.get("value") if edit_type == "table_rename" else edit["name"]
            table = next(
                (
                    item
                    for item in projected_tables
                    if item["name"].casefold() == expected_name.casefold()
                    and item.get("sheet") == rename_map.get(edit["sheet"], edit["sheet"])
                ),
                None,
            )
            if edit_type == "table_delete":
                if table is None:
                    matched += 1
                else:
                    failures.append(f"table_delete:{edit['name']}")
                continue
            expected_ref = edit.get("ref") if edit_type in {"table_add", "table_resize"} else None
            expected_style = edit.get("table_style") if edit_type in {"table_add", "table_style"} else None
            if (
                table is None
                or (expected_ref is not None and table.get("ref") != expected_ref)
                or (expected_style is not None and table.get("style") != expected_style)
            ):
                failures.append(f"{edit_type}:{expected_name}")
            else:
                matched += 1
            continue
        if edit_type in {
            "data_validation_add",
            "data_validation_update",
            "data_validation_delete",
        }:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            if edit_type == "data_validation_delete":
                exists = any(
                    item["sheet"] == sheet_name
                    and item["ref"].casefold() == edit["ref"].casefold()
                    for item in projected_validations
                )
                if exists:
                    failures.append(f"data_validation_delete:{sheet_name}!{edit['ref']}")
                else:
                    matched += 1
                continue
            expected = {"sheet": sheet_name, **edit["validation"]}
            if any(
                _data_validation_matches(item, expected)
                for item in projected_validations
            ):
                matched += 1
            else:
                failures.append(
                    f"{edit_type}:{sheet_name}!{edit['validation']['ref']}"
                )
            continue
        if edit_type in {
            "conditional_format_add",
            "conditional_format_update",
            "conditional_format_delete",
        }:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            if edit_type == "conditional_format_delete":
                exists = any(
                    item["sheet"] == sheet_name
                    and item["ref"].casefold() == edit["ref"].casefold()
                    and item["priority"] == edit["priority"]
                    for item in projected_conditional_formats
                )
                if exists:
                    failures.append(
                        f"conditional_format_delete:{sheet_name}!{edit['ref']}#{edit['priority']}"
                    )
                else:
                    matched += 1
                continue
            expected_rule = {"sheet": sheet_name, **edit["rule"]}
            if edit_type == "conditional_format_update":
                expected_rule["priority"] = edit["priority"]
            if any(
                _conditional_format_matches(item, expected_rule)
                for item in projected_conditional_formats
            ):
                matched += 1
            else:
                failures.append(
                    f"{edit_type}:{sheet_name}!{edit['rule']['ref']}"
                )
            continue
        if edit_type in {"chart_add", "chart_update", "chart_delete"}:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            if edit_type == "chart_delete":
                exists = any(
                    item["sheet"] == sheet_name
                    and item["name"].casefold() == edit["name"].casefold()
                    for item in projected_charts
                )
                if exists:
                    failures.append(f"chart_delete:{sheet_name}!{edit['name']}")
                else:
                    matched += 1
                continue
            expected_chart = {**edit["chart"], "sheet": sheet_name}
            if any(_chart_matches(item, expected_chart) for item in projected_charts):
                matched += 1
            else:
                failures.append(f"{edit_type}:{sheet_name}!{edit['chart']['name']}")
            continue
        if edit_type in {"sparkline_add", "sparkline_update", "sparkline_delete"}:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            if sparkline_edit_matches(projected_sparklines, edit, sheet_name):
                matched += 1
            else:
                ref = edit["ref"] if edit_type == "sparkline_delete" else edit["sparkline"]["location"]
                failures.append(f"{edit_type}:{sheet_name}!{ref}")
            continue
        if edit_type in {"hyperlink_add", "hyperlink_update", "hyperlink_delete"}:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            expected_ref = (
                edit["ref"] if edit_type == "hyperlink_delete" else edit["hyperlink"]["ref"]
            )
            matches = [
                item
                for item in projected_hyperlinks
                if item["sheet"] == sheet_name
                and item["ref"].casefold() == expected_ref.casefold()
            ]
            if edit_type == "hyperlink_delete":
                if matches:
                    failures.append(f"hyperlink_delete:{sheet_name}!{expected_ref}")
                else:
                    matched += 1
            elif any(_hyperlink_matches(item, edit["hyperlink"]) for item in matches):
                matched += 1
            else:
                failures.append(f"{edit_type}:{sheet_name}!{expected_ref}")
            continue
        if edit_type in {"comment_add", "comment_update", "comment_delete"}:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            expected_ref = (
                edit["ref"] if edit_type == "comment_delete" else edit["comment"]["ref"]
            )
            matches = [
                item
                for item in projected_comments
                if item["sheet"] == sheet_name
                and item["ref"].casefold() == expected_ref.casefold()
            ]
            if edit_type == "comment_delete":
                if matches:
                    failures.append(f"comment_delete:{sheet_name}!{expected_ref}")
                else:
                    matched += 1
            elif any(_comment_matches(item, edit["comment"]) for item in matches):
                matched += 1
            else:
                failures.append(f"{edit_type}:{sheet_name}!{expected_ref}")
            continue
        if edit_type == "workbook_properties":
            if all(
                projected_properties.get(field) == value
                for field, value in edit["properties"].items()
            ):
                matched += 1
            else:
                failures.append("workbook_properties")
            continue
        if edit_type in {
            "page_setup",
            "header_footer",
            "sheet_view",
            "print_titles",
            "print_titles_clear",
        }:
            sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
            metadata = projected_worksheet_metadata.get(sheet_name)
            if metadata is not None and _worksheet_metadata_edit_matches(metadata, edit):
                matched += 1
            else:
                failures.append(f"{edit_type}:{sheet_name}")
            continue
        sheet_name = rename_map.get(edit["sheet"], edit["sheet"])
        sheet = sheets.get(sheet_name)
        if sheet is None:
            failures.append(f"{edit_type}:{edit['sheet']}")
            continue
        if edit_type in {"cell_value", "cell_formula", "cell_style"}:
            cell = _find_mapped_cell(sheet, edit["ref"])
            if cell is None:
                failures.append(f"{edit_type}:{sheet_name}!{edit['ref']}")
                continue
            if edit_type == "cell_value" and cell.get("value") != edit.get("value"):
                failures.append(f"cell_value:{sheet_name}!{edit['ref']}")
                continue
            if edit_type == "cell_formula" and cell.get("formula") != edit.get("value"):
                failures.append(f"cell_formula:{sheet_name}!{edit['ref']}")
                continue
            if edit.get("style") and not _style_contains(cell["style"], edit["style"]):
                failures.append(f"cell_style:{sheet_name}!{edit['ref']}")
                continue
            matched += 1
            continue
        if edit_type == "row_style":
            first, last = _numeric_range(edit["ref"])
            rows = {int(row["ref"]): row for row in sheet.get("rows", [])}
            if any(
                row_number not in rows
                or not _style_contains(rows[row_number]["style"], edit["style"])
                for row_number in range(first, last + 1)
            ):
                failures.append(f"row_style:{sheet_name}!{edit['ref']}")
            else:
                matched += 1
            continue
        if edit_type == "column_style":
            column = next(
                (
                    column
                    for column in sheet.get("columns", [])
                    if column["ref"].casefold() == edit["ref"].casefold()
                ),
                None,
            )
            if column is None or not _style_contains(column["style"], edit["style"]):
                failures.append(f"column_style:{sheet_name}!{edit['ref']}")
            else:
                matched += 1
            continue
        if edit_type in {
            "row_height",
            "row_hidden",
            "column_width",
            "column_hidden",
            "cells_merge",
            "cells_unmerge",
            "range_clear",
            "freeze_panes",
            "auto_filter",
            "auto_filter_clear",
            "row_page_break",
            "column_page_break",
        }:
            if _worksheet_edit_matches(package, sheet, edit):
                matched += 1
            else:
                failures.append(f"{edit_type}:{sheet_name}!{edit['ref']}")
            continue
        if edit_type in {
            "print_area",
            "print_area_clear",
            "defined_name_add",
            "defined_name_update",
            "defined_name_delete",
        }:
            if _defined_name_edit_matches(mapped, sheet_name, edit):
                matched += 1
            else:
                failures.append(f"{edit_type}:{sheet_name}!{edit.get('name') or edit.get('ref')}")
            continue
        if edit_type in {
            "row_insert",
            "row_delete",
            "column_insert",
            "column_delete",
        }:
            if expected_cells is None or _mapped_cell_refs(sheet) != expected_cells.get(
                sheet_name,
                set(),
            ):
                failures.append(f"{edit_type}:{sheet_name}!{edit['ref']}")
            else:
                matched += 1
            continue
        matched += 1
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited XLSX does not satisfy every requested mutation.",
            details={"missing_or_mismatched": failures},
        )
    return {"requested_edits": len(edits), "matched_edits": matched}


def _expected_cell_refs(
    source: Path,
    edits: list[dict[str, Any]],
) -> dict[str, set[str]]:
    mapped = map_workbook(_open_candidate(source))
    expected = {
        sheet["name"]: _mapped_cell_refs(sheet)
        for sheet in mapped.get("sheets", [])
    }
    for edit in edits:
        edit_type = edit["type"]
        sheet_name = edit["sheet"]
        if edit_type == "sheet_rename":
            new_name = edit.get("value")
            if new_name and sheet_name in expected:
                expected[new_name] = expected.pop(sheet_name)
            continue
        if edit_type == "sheet_add":
            expected[edit["sheet"]] = set()
            continue
        if edit_type == "sheet_copy":
            expected[edit["name"]] = set(expected.get(sheet_name, set()))
            continue
        if edit_type == "sheet_delete":
            expected.pop(sheet_name, None)
            continue
        if edit_type == "sheet_reorder":
            continue
        if edit_type in {"cell_value", "cell_formula", "cell_style"}:
            expected.setdefault(sheet_name, set()).add(edit["ref"].upper())
            continue
        if edit_type not in {
            "row_insert",
            "row_delete",
            "column_insert",
            "column_delete",
        }:
            continue
        axis = "row" if edit_type.startswith("row") else "column"
        index = int(edit["ref"]) if axis == "row" else _column_number(edit["ref"])
        mutation = AxisMutation(
            sheet=sheet_name,
            axis=axis,
            index=index,
            count=edit["count"],
            delete=edit_type.endswith("delete"),
        )
        shifted: set[str] = set()
        for ref in expected.get(sheet_name, set()):
            column, row = _split_cell_ref(ref)
            coordinate = shift_coordinate(column, row, mutation)
            if coordinate is not None:
                shifted.add(f"{_column_name(coordinate[0])}{coordinate[1]}")
        expected[sheet_name] = shifted
    return expected


def _worksheet_edit_matches(
    package: OpcPackage,
    sheet: dict[str, Any],
    edit: dict[str, Any],
) -> bool:
    edit_type = edit["type"]
    if edit_type in {"row_height", "row_hidden"}:
        first, last = _numeric_range(edit["ref"])
        rows = {int(row["ref"]): row for row in sheet.get("rows", [])}
        key = "height" if edit_type == "row_height" else "hidden"
        return all(rows.get(index, {}).get(key) == edit[key] for index in range(first, last + 1))
    if edit_type in {"column_width", "column_hidden"}:
        first, last = _column_range(edit["ref"])
        key = "width" if edit_type == "column_width" else "hidden"
        return all(
            next(
                (
                    column.get(key) == edit[key]
                    for column in sheet.get("columns", [])
                    if column["min"] <= index <= column["max"]
                ),
                False,
            )
            for index in range(first, last + 1)
        )
    part = sheet.get("part")
    if not part:
        return False
    root = package.xml(part)
    if edit_type in {"cells_merge", "cells_unmerge"}:
        merged = {
            item.attrib.get("ref", "").casefold()
            for item in root.findall(f".//{{{_MAIN_NS}}}mergeCell")
        }
        exists = edit["ref"].casefold() in merged
        return exists if edit_type == "cells_merge" else not exists
    if edit_type == "range_clear":
        cells = _cells_in_range(root, edit["ref"])
        if edit["clear"] == "all":
            return not cells
        if edit["clear"] == "styles":
            return all("s" not in cell.attrib for cell in cells)
        return all(
            "t" not in cell.attrib
            and not any(child.tag.rsplit("}", 1)[-1] in {"f", "v", "is"} for child in cell)
            for cell in cells
        )
    if edit_type == "freeze_panes":
        pane = root.find(f".//{{{_MAIN_NS}}}pane")
        return pane is None if edit["ref"].upper() == "A1" else (
            pane is not None and pane.attrib.get("topLeftCell", "").casefold() == edit["ref"].casefold()
        )
    if edit_type in {"auto_filter", "auto_filter_clear"}:
        auto_filter = root.find(f"{{{_MAIN_NS}}}autoFilter")
        return auto_filter is None if edit_type.endswith("_clear") else (
            auto_filter is not None and auto_filter.attrib.get("ref", "").casefold() == edit["ref"].casefold()
        )
    if edit_type in {"row_page_break", "column_page_break"}:
        is_row = edit_type.startswith("row")
        tag = "rowBreaks" if is_row else "colBreaks"
        expected_id = int(edit["ref"]) if is_row else _column_number(edit["ref"])
        ids = {
            int(item.attrib.get("id", "0"))
            for item in root.findall(f".//{{{_MAIN_NS}}}{tag}/{{{_MAIN_NS}}}brk")
        }
        return (expected_id in ids) == edit["enabled"]
    return False


def _defined_name_edit_matches(
    mapped: dict[str, Any],
    sheet_name: str,
    edit: dict[str, Any],
) -> bool:
    sheets = [sheet["name"] for sheet in mapped.get("sheets", [])]
    local_id = str(sheets.index(sheet_name))
    name = "_xlnm.Print_Area" if edit["type"].startswith("print_area") else edit["name"]
    scope = local_id if edit["type"].startswith("print_area") or edit.get("scope") == "sheet" else "workbook"
    match = next(
        (
            item
            for item in mapped.get("defined_names", [])
            if item["name"].casefold() == name.casefold() and item["scope"] == scope
        ),
        None,
    )
    if edit["type"] in {"print_area_clear", "defined_name_delete"}:
        return match is None
    if match is None:
        return False
    if edit["type"] == "print_area":
        expected = f"'{sheet_name.replace(chr(39), chr(39) * 2)}'!{_absolute_range(edit['ref'])}"
    else:
        expected = edit["ref"]
    return match["ref"] == expected


def _cells_in_range(root: Any, ref: str) -> list[Any]:
    first, separator, last = ref.partition(":")
    first_column, first_row = _split_cell_ref(first.replace("$", "").upper())
    last_column, last_row = _split_cell_ref((last if separator else first).replace("$", "").upper())
    return [
        cell
        for cell in root.findall(f".//{{{_MAIN_NS}}}c")
        if (
            first_column
            <= _split_cell_ref(cell.attrib.get("r", ""))[0]
            <= last_column
            and first_row <= _split_cell_ref(cell.attrib.get("r", ""))[1] <= last_row
        )
    ]


def _column_range(ref: str) -> tuple[int, int]:
    first, separator, last = ref.partition(":")
    return _column_number(first), _column_number(last) if separator else _column_number(first)


def _absolute_range(ref: str) -> str:
    def absolute_cell(cell: str) -> str:
        match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", cell)
        assert match is not None
        return f"${match.group(1).upper()}${match.group(2)}"

    return ":".join(absolute_cell(cell) for cell in ref.split(":"))


def _mapped_cell_refs(sheet: dict[str, Any]) -> set[str]:
    return {
        cell["ref"].upper()
        for row in sheet.get("rows", [])
        for cell in row.get("cells", [])
    }


def _split_cell_ref(ref: str) -> tuple[int, int]:
    letters = ref.rstrip("0123456789")
    return _column_number(letters), int(ref[len(letters):])


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _assert_created(
    path: Path,
    workbook: dict[str, Any],
    *,
    creation: dict[str, Any] | None,
) -> dict[str, Any]:
    package = _open_candidate(path)
    mapped = map_workbook(package)
    failures: list[str] = []

    # Check sheet names
    expected_sheets = [s["name"] for s in workbook["sheets"]]
    actual_sheets = [s["name"] for s in mapped["sheets"]]
    if expected_sheets != actual_sheets:
        failures.append("sheet-names")

    # Check defined names
    expected_dn = {dn["name"] for dn in workbook.get("defined_names", [])}
    actual_dn = {dn["name"] for dn in mapped.get("defined_names", [])}
    if not expected_dn.issubset(actual_dn):
        failures.append("defined-names")

    # Check tables
    tables = project_tables(package)
    actual_tables = {table["name"]: table for table in tables}
    for expected in workbook.get("tables", []):
        actual = actual_tables.get(expected["name"])
        if actual is None:
            failures.append(f"table:{expected['name']}")
            continue
        for field in ("ref", "sheet", "style", "columns"):
            if actual.get(field) != expected.get(field):
                failures.append(f"table-{field}:{expected['name']}")
        if actual.get("auto_filter_ref") != expected["ref"]:
            failures.append(f"table-auto-filter:{expected['name']}")

    data_validations = project_data_validations(package)
    for sheet in workbook.get("sheets", []):
        for expected_validation in sheet.get("data_validations", []):
            expected = {"sheet": sheet["name"], **expected_validation}
            if not any(
                _data_validation_matches(actual, expected)
                for actual in data_validations
            ):
                failures.append(
                    f"data-validation:{sheet['name']}!{expected_validation['ref']}"
                )

    conditional_formats = project_conditional_formats(package)
    for sheet in workbook.get("sheets", []):
        for expected_rule in sheet.get("conditional_formats", []):
            expected = {"sheet": sheet["name"], **expected_rule}
            if not any(
                _conditional_format_matches(actual, expected)
                for actual in conditional_formats
            ):
                failures.append(
                    f"conditional-format:{sheet['name']}!{expected_rule['ref']}"
                )

    charts = project_charts(package)
    actual_charts = {chart["name"]: chart for chart in charts}
    for expected_chart in workbook.get("charts", []):
        actual_chart = actual_charts.get(expected_chart["name"])
        if actual_chart is None or not _chart_matches(actual_chart, expected_chart):
            failures.append(f"chart:{expected_chart['name']}")

    sparklines = project_sparklines(package)
    failures.extend(missing_created_sparklines(sparklines, workbook))

    worksheet_metadata = {
        item["sheet"]: item for item in project_worksheet_metadata(package)
    }
    for sheet in workbook.get("sheets", []):
        actual_metadata = worksheet_metadata.get(sheet["name"], {})
        for field in ("view", "header_footer", "print_area", "print_titles"):
            if sheet.get(field) is not None and actual_metadata.get(field) != sheet.get(field):
                failures.append(f"worksheet-{field}:{sheet['name']}")
        if sheet.get("page_setup") is not None:
            expected_page_setup = {
                **sheet["page_setup"],
                "fit_to_page": sheet["page_setup"]["fit_to_width"] is not None,
            }
            if actual_metadata.get("page_setup") != expected_page_setup:
                failures.append(f"worksheet-page-setup:{sheet['name']}")

    hyperlinks = [
        hyperlink
        for sheet in mapped.get("sheets", [])
        if sheet.get("part")
        for hyperlink in project_hyperlinks(package, sheet["part"], sheet["name"])
    ]
    for sheet in workbook.get("sheets", []):
        for expected_hyperlink in sheet.get("hyperlinks", []):
            if not any(
                item["sheet"] == sheet["name"]
                and _hyperlink_matches(item, expected_hyperlink)
                for item in hyperlinks
            ):
                failures.append(
                    f"hyperlink:{sheet['name']}!{expected_hyperlink['ref']}"
                )

    comments = project_comments(package)
    for sheet in workbook.get("sheets", []):
        for expected_comment in sheet.get("comments", []):
            if not any(
                item["sheet"] == sheet["name"]
                and _comment_matches(item, expected_comment)
                for item in comments
            ):
                failures.append(f"comment:{sheet['name']}!{expected_comment['ref']}")

    workbook_properties = project_workbook_properties(package.parts)
    for field, expected_value in workbook.get("metadata", {}).items():
        if workbook_properties.get(field) != expected_value:
            failures.append(f"workbook-property:{field}")

    expected_styles = (creation or {}).get("styles", {})
    assignments = expected_styles.get("assignments", {})
    actual_assignments = _mapped_style_assignments(mapped)
    for assignment_type in ("cells", "rows", "columns"):
        for ref, style_id in assignments.get(assignment_type, {}).items():
            if actual_assignments[assignment_type].get(ref) != style_id:
                failures.append(f"{assignment_type}-style:{ref}")
    actual_number_formats = read_styles(package.parts).get("num_fmts", {})
    for format_id, code in expected_styles.get("number_formats", {}).items():
        if actual_number_formats.get(int(format_id)) != code:
            failures.append(f"number-format:{format_id}")

    # Check formula state invariant
    formula_cells = mapped.get("formula_cells", {})
    try:
        assert_invariant(formula_cells)
    except ValueError:
        failures.append("formula-state-invariant")

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Created XLSX does not satisfy the workbook semantics.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "sheets": len(actual_sheets),
        "tables": len(tables),
        "data_validations": len(data_validations),
        "conditional_formats": len(conditional_formats),
        "sparklines": len(sparklines),
        "charts": len(charts),
        "worksheet_metadata": len(worksheet_metadata),
        "hyperlinks": len(hyperlinks),
        "comments": len(comments),
        "workbook_properties": len(workbook_properties),
        "formula_cells": len(formula_cells),
        "cell_styles": len(assignments.get("cells", {})),
        "row_styles": len(assignments.get("rows", {})),
        "column_styles": len(assignments.get("columns", {})),
        "number_formats": len(actual_number_formats),
        "requested_structure": True,
    }


def _mapped_style_assignments(mapped: dict[str, Any]) -> dict[str, dict[str, int]]:
    assignments: dict[str, dict[str, int]] = {
        "cells": {},
        "rows": {},
        "columns": {},
    }
    for sheet in mapped.get("sheets", []):
        sheet_name = sheet["name"]
        for column in sheet.get("columns", []):
            assignments["columns"][f"{sheet_name}!{column['ref']}"] = column[
                "style_index"
            ]
        for row in sheet.get("rows", []):
            assignments["rows"][f"{sheet_name}!{row['ref']}"] = row["style_index"]
            for cell in row.get("cells", []):
                assignments["cells"][f"{sheet_name}!{cell['ref']}"] = cell[
                    "resolved_style_index"
                ]
    return assignments


def _data_validation_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    return all(
        actual.get(field) == expected.get(field)
        for field in (
            "sheet",
            "ref",
            "type",
            "operator",
            "formula1",
            "formula2",
            "allow_blank",
            "show_input_message",
            "show_error_message",
            "prompt_title",
            "prompt",
            "error_title",
            "error",
            "error_style",
        )
    )


def _conditional_format_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    fields = [
        "sheet",
        "ref",
        "type",
        "operator",
        "formulas",
        "style",
        "stop_if_true",
        "thresholds",
        "colors",
        "color",
        "show_value",
        "icon_set",
        "reverse",
    ]
    if "priority" in expected:
        fields.append("priority")
    return actual.get("dxf_valid") is True and all(
        actual.get(field) == expected.get(field) for field in fields
    )


def _chart_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(
        actual.get(field) == expected.get(field)
        for field in (
            "name",
            "sheet",
            "type",
            "title",
            "anchor",
            "series",
            "show_legend",
            "legend_position",
            "x_axis_title",
            "y_axis_title",
            "x_axis_number_format",
            "y_axis_number_format",
            "secondary_x_axis_title",
            "secondary_y_axis_title",
            "secondary_x_axis_number_format",
            "secondary_y_axis_number_format",
            "data_labels",
            "style",
            "radar_style",
            "bubble_scale",
        )
    ) and all(
        actual.get(field)
        for field in ("part", "drawing_part", "content_type")
    )


def _hyperlink_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(
        actual.get(field) == expected.get(field)
        for field in ("ref", "location", "display", "tooltip")
    ) and actual.get("external") is False


def _comment_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(
        actual.get(field) == expected.get(field)
        for field in ("ref", "text", "author")
    ) and bool(actual.get("part")) and bool(actual.get("vml_part"))


def _worksheet_metadata_edit_matches(
    actual: dict[str, Any],
    edit: dict[str, Any],
) -> bool:
    edit_type = edit["type"]
    if edit_type == "page_setup":
        expected = {
            **edit["page_setup"],
            "fit_to_page": edit["page_setup"]["fit_to_width"] is not None,
        }
        return actual.get("page_setup") == expected
    if edit_type == "header_footer":
        return actual.get("header_footer") == edit["header_footer"]
    if edit_type == "sheet_view":
        return actual.get("view") == edit["view"]
    if edit_type == "print_titles":
        return actual.get("print_titles") == edit["print_titles"]
    return actual.get("print_titles") is None


def _find_mapped_cell(sheet: dict[str, Any], ref: str) -> dict[str, Any] | None:
    return next(
        (
            cell
            for row in sheet.get("rows", [])
            for cell in row.get("cells", [])
            if cell["ref"].casefold() == ref.casefold()
        ),
        None,
    )


def _style_contains(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if key == "number_format":
            if "id" in expected_value and actual.get("num_fmt_id") != expected_value["id"]:
                return False
            if (
                "code" in expected_value
                and actual.get("num_fmt_code") != expected_value["code"]
            ):
                return False
            continue
        actual_value = actual.get(key)
        if type(expected_value) is dict:
            if type(actual_value) is not dict or not _style_contains(
                actual_value,
                expected_value,
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _numeric_range(ref: str) -> tuple[int, int]:
    first_text, separator, last_text = ref.partition(":")
    first = int(first_text)
    return first, int(last_text) if separator else first


def _assert_consumer_package(path: Path) -> dict[str, Any]:
    """Reject the known malformed style table that Excel repairs/rejects."""

    package = _open_candidate(path)
    styles = package.xml("xl/styles.xml")
    expected_children = {
        "fonts": ("font", 1),
        "fills": ("fill", 2),
        "borders": ("border", 1),
        "cellStyleXfs": ("xf", 1),
        "cellXfs": ("xf", 1),
        "cellStyles": ("cellStyle", 1),
    }
    failures: list[dict[str, Any]] = []
    evidence: dict[str, int] = {}
    for container_name, (child_name, minimum) in expected_children.items():
        container = next(
            (item for item in styles if item.tag.rsplit("}", 1)[-1] == container_name),
            None,
        )
        actual = (
            0
            if container is None
            else sum(1 for item in container if item.tag.rsplit("}", 1)[-1] == child_name)
        )
        declared = int(container.attrib.get("count", "-1")) if container is not None else -1
        evidence[container_name] = actual
        if actual < minimum or declared != actual:
            failures.append(
                {
                    "container": container_name,
                    "declared": declared,
                    "actual": actual,
                    "minimum": minimum,
                }
            )
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "XLSX style package is not consumer-conformant.",
            details={"style_table_failures": failures},
        )
    return {"style_table_counts": evidence, "consumer_conformant": True}


def _assert_preservation(
    manifest: PreservationManifest,
    *,
    allowed_removed_parts: set[str],
) -> dict[str, Any]:
    unexpected_removed = sorted(set(manifest.removed) - allowed_removed_parts)
    if unexpected_removed:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "An XLSX mutation removed package parts.",
            details={"removed_parts": unexpected_removed},
        )
    mismatched = [
        name
        for name in manifest.preserved
        if manifest.input_hashes[name] != manifest.output_hashes[name]
    ]
    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A preserved XLSX part changed.",
            details={"parts": mismatched},
        )
    return {
        "changed_parts": list(manifest.changed),
        "added_parts": list(manifest.added),
        "removed_parts": list(manifest.removed),
        "preserved_parts": len(manifest.preserved),
    }


def _required_report(
    path: Path,
    *,
    source: Path | None = None,
    source_sha256: str | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    report = validate_artifact(
        path,
        expected_format="xlsx",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen_xlsx,
        assertions=assertions,
        visual_available=False,
        schema_available=False,
    )
    if report["status"] != "pass":
        failed = [
            gate["id"]
            for gate in report["gates"]
            if gate["required"] and gate["outcome"] != "pass"
        ]
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Staged XLSX failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report


def _open_candidate(path: Path) -> OpcPackage:
    package = OpcPackage.open(
        path,
        allowed_inert_categories=allowed_inert_categories(format_id(path)),
    )
    assert_package_matches_path(path, package.workbook_format)
    return package
