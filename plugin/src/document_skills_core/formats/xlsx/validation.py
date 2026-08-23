"""XLSX reopen, semantic, and preservation validation gates."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation import validate_artifact

from .formula_state import assert_invariant
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest
from .projection import project_tables
from .styles import read_styles


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


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: PreservationManifest,
    assertion: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("consumer-package-conformance", _assert_consumer_package),
        ("part-preservation", lambda _candidate: _assert_preservation(manifest))
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
    package = OpcPackage.open(path)
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


def assert_edits_applied(path: Path, edits: list[dict[str, Any]]) -> dict[str, Any]:
    """Reopen a staged mutation and prove every bounded edit took effect."""

    mapped = map_workbook(OpcPackage.open(path))
    sheets = {sheet["name"]: sheet for sheet in mapped.get("sheets", [])}
    rename_map = {
        edit["sheet"]: edit.get("value", "")
        for edit in edits
        if edit["type"] == "sheet_rename" and edit.get("value")
    }
    failures: list[str] = []
    matched = 0
    for edit in edits:
        edit_type = edit["type"]
        if edit_type == "sheet_rename":
            if edit.get("value") not in sheets:
                failures.append(f"sheet_rename:{edit['sheet']}")
            else:
                matched += 1
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
        matched += 1
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited XLSX does not satisfy every requested mutation.",
            details={"missing_or_mismatched": failures},
        )
    return {"requested_edits": len(edits), "matched_edits": matched}


def _assert_created(
    path: Path,
    workbook: dict[str, Any],
    *,
    creation: dict[str, Any] | None,
) -> dict[str, Any]:
    package = OpcPackage.open(path)
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
    expected_tables = {t["name"] for t in workbook.get("tables", [])}
    actual_tables = {t["name"] for t in tables}
    if expected_tables and not expected_tables.issubset(actual_tables):
        failures.append("tables")

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

    package = OpcPackage.open(path)
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


def _assert_preservation(manifest: PreservationManifest) -> dict[str, Any]:
    if manifest.removed:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "An XLSX mutation removed package parts.",
            details={"removed_parts": list(manifest.removed)},
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
