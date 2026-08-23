"""Conservative static XLSX formula classification and reference checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record

from .constants import NS
from .mapping import map_workbook
from .package import OpcPackage
from .projection import project_tables

_MAIN_NS = NS["main"]
_MAX_ROW = 1_048_576
_MAX_COLUMN = 16_384
_SHEET = r"(?:'(?:[^']|'')+'|[A-Za-z_\\][A-Za-z0-9_.\\]*)"
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_COLUMN_RANGE = r"\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}"
_ROW_RANGE = r"\$?\d+:\$?\d+"
_REFERENCE_RE = re.compile(
    rf"(?<![A-Za-z0-9_.])(?:(?P<sheet>{_SHEET})!)?"
    rf"(?P<ref>(?:{_CELL})(?::{_CELL})?|{_COLUMN_RANGE}|{_ROW_RANGE})"
    r"(?![A-Za-z0-9_])"
)
_EXTERNAL_RE = re.compile(
    rf"(?:'\[[^\]]+\](?:[^']|'')+'|\[[^\]]+\][^!\"']*)!"
    rf"(?:(?:{_CELL})(?::{_CELL})?|{_COLUMN_RANGE}|{_ROW_RANGE})?",
    re.IGNORECASE,
)
_NAMED_STRUCTURED_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<table>[A-Za-z_\\][A-Za-z0-9_.\\]*)"
    r"\[(?P<body>[^\[\]]+)\]"
)
_ANY_STRUCTURED_RE = re.compile(r"\[[#@A-Za-z_\\][^\]]*\]")
_TABLE_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<table>[A-Za-z_\\][A-Za-z0-9_.\\]*)(?=\[)"
)
_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_.\\])(?P<name>[A-Za-z_\\][A-Za-z0-9_.\\]*)"
    r"(?![A-Za-z0-9_.\\])"
)
_FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!")
_KNOWN_CONSTANTS = {"FALSE", "TRUE"}
_CATEGORY_NAMES = (
    "normal",
    "shared",
    "array",
    "data_table",
    "dynamic_array",
    "structured_reference",
    "external_reference",
)


def analyze_formulas(
    path: str | Path,
    *,
    allow_dangerous_inventory: bool = False,
) -> dict[str, Any]:
    """Return a bounded, non-evaluating formula analysis report."""

    package = OpcPackage.open(
        path,
        allow_dangerous_inventory=allow_dangerous_inventory,
    )
    workbook = map_workbook(package)
    sheet_names = {sheet["name"].casefold() for sheet in workbook["sheets"]}
    defined_names = {
        item["name"].casefold()
        for item in workbook.get("defined_names", [])
        if item.get("name")
    }
    tables = {
        name.casefold(): {column.casefold() for column in item.get("columns", [])}
        for item in project_tables(package)
        for name in {item.get("name", ""), item.get("display_name", "")}
        if name
    }
    category_counts = {name: 0 for name in _CATEGORY_NAMES}
    reference_counts = {
        "cell_or_range": 0,
        "defined_name": 0,
        "structured": 0,
        "external": 0,
    }
    cells: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for sheet in workbook["sheets"]:
        part = sheet.get("part")
        if not part:
            continue
        root = package.xml(part)
        for cell in root.findall(f".//{{{_MAIN_NS}}}c"):
            formula = cell.find(f"{{{_MAIN_NS}}}f")
            if formula is None:
                continue
            ref = f"{sheet['name']}!{cell.attrib.get('r', '')}"
            text = formula.text or ""
            formula_type = formula.attrib.get("t", "normal") or "normal"
            categories = _categories(text, formula_type)
            for category in categories:
                category_counts[category] = category_counts.get(category, 0) + 1
            cell_issues, counts = _analyze_text(
                text,
                ref=ref,
                current_sheet=sheet["name"],
                formula_type=formula_type,
                sheet_names=sheet_names,
                defined_names=defined_names,
                tables=tables,
            )
            issues.extend(cell_issues)
            for name, count in counts.items():
                reference_counts[name] += count
            cells.append(
                {
                    "ref": ref,
                    "formula_type": formula_type,
                    "categories": categories,
                    "valid": not cell_issues,
                }
            )
    issues.sort(key=lambda item: (item["ref"], item["code"], item.get("token", "")))
    cells.sort(key=lambda item: item["ref"])
    return {
        "valid": not issues,
        "formula_cells": len(cells),
        "categories": category_counts,
        "references": reference_counts,
        "issues": issues,
        "cells": cells,
        "scope": "static-token-reference-checks-only",
        "calculation_engine": False,
        "limitations": [
            "does-not-evaluate-formulas",
            "does-not-prove-calculated-values",
            "let-and-lambda-local-names-are-not-resolved",
        ],
    }


def validate_formula_analysis(
    path: str | Path,
    validation: dict[str, Any],
    *,
    required: bool,
    allow_dangerous_inventory: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Analyze formulas, append a gate, and reject invalid mutation candidates."""

    analysis = analyze_formulas(
        path,
        allow_dangerous_inventory=allow_dangerous_inventory,
    )
    outcome = "pass" if analysis["valid"] else "fail"
    gates = list(validation.get("gates", []))
    gates.append(
        gate_record(
            "operation.formula-static-analysis",
            outcome,
            required=required,
            evidence={
                "formula_cells": analysis["formula_cells"],
                "categories": analysis["categories"],
                "issue_count": len(analysis["issues"]),
                "scope": analysis["scope"],
                "calculation_engine": False,
            },
            warnings=(
                []
                if analysis["valid"]
                else ["Static formula analysis found invalid references or syntax."]
            ),
        )
    )
    gated = {
        "schema_version": validation.get("schema_version", "1.0"),
        "status": (
            "pass"
            if all(not gate["required"] or gate["outcome"] == "pass" for gate in gates)
            else "fail"
        ),
        "gates": gates,
    }
    if required and not analysis["valid"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Static formula analysis rejected the staged XLSX.",
            details={"formula_issues": analysis["issues"]},
            validation=gated,
        )
    return analysis, gated


def _categories(formula: str, formula_type: str) -> list[str]:
    categories: set[str] = set()
    if formula_type == "shared":
        categories.add("shared")
    elif formula_type == "array":
        categories.add("array")
    elif formula_type == "dataTable":
        categories.add("data_table")
    if re.search(r"(?:_xlfn\.|_xlws\.|(?<=[A-Za-z0-9_)])#)", formula, re.IGNORECASE):
        categories.add("dynamic_array")
    if _EXTERNAL_RE.search(formula):
        categories.add("external_reference")
    if _ANY_STRUCTURED_RE.search(formula) and "external_reference" not in categories:
        categories.add("structured_reference")
    if not categories:
        categories.add("normal")
    return sorted(categories)


def _analyze_text(
    formula: str,
    *,
    ref: str,
    current_sheet: str,
    formula_type: str,
    sheet_names: set[str],
    defined_names: set[str],
    tables: dict[str, set[str]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    issues = _syntax_issues(formula, ref=ref, allow_empty=formula_type == "shared")
    counts = {"cell_or_range": 0, "defined_name": 0, "structured": 0, "external": 0}
    masked = _mask_strings(formula)
    occupied = [False] * len(masked)
    for match in _EXTERNAL_RE.finditer(masked):
        counts["external"] += 1
        _occupy(occupied, match.span())
        issues.append(
            _issue(ref, "formula-external-reference-unsupported", match.group(0))
        )
    checked_tables: set[str] = set()
    for match in _TABLE_PREFIX_RE.finditer(masked):
        if _overlaps(occupied, match.span()):
            continue
        table_name = match.group("table")
        checked_tables.add(table_name.casefold())
        if table_name.casefold() not in tables:
            issues.append(_issue(ref, "formula-table-missing", table_name))
    for match in _NAMED_STRUCTURED_RE.finditer(masked):
        if _overlaps(occupied, match.span()):
            continue
        counts["structured"] += 1
        _occupy(occupied, match.span())
        table_name = match.group("table")
        columns = tables.get(table_name.casefold())
        if columns is None:
            if table_name.casefold() not in checked_tables:
                issues.append(_issue(ref, "formula-table-missing", table_name))
            continue
        body = match.group("body").lstrip("@").strip()
        if body and not body.startswith("#") and body.casefold() not in columns:
            issues.append(_issue(ref, "formula-table-column-missing", body))
    for match in _ANY_STRUCTURED_RE.finditer(masked):
        if _overlaps(occupied, match.span()):
            continue
        counts["structured"] += 1
        _occupy(occupied, match.span())
    for match in _REFERENCE_RE.finditer(masked):
        if _overlaps(occupied, match.span()):
            continue
        counts["cell_or_range"] += 1
        _occupy(occupied, match.span())
        sheet = _decode_sheet(match.group("sheet")) if match.group("sheet") else current_sheet
        if sheet.casefold() not in sheet_names:
            issues.append(_issue(ref, "formula-sheet-missing", sheet))
        if not _reference_in_bounds(match.group("ref")):
            issues.append(_issue(ref, "formula-reference-out-of-bounds", match.group("ref")))
    if re.search(r"\b(?:LET|LAMBDA)\s*\(", masked, re.IGNORECASE):
        return issues, counts
    for match in _NAME_RE.finditer(masked):
        if _overlaps(occupied, match.span()):
            continue
        name = match.group("name")
        suffix = masked[match.end():].lstrip()
        if suffix.startswith(("(", "!", "[")) or name.upper() in _KNOWN_CONSTANTS:
            continue
        counts["defined_name"] += 1
        if name.casefold() not in defined_names:
            issues.append(_issue(ref, "formula-defined-name-missing", name))
    if formula_type not in {"normal", "shared", "array", "dataTable"}:
        issues.append(_issue(ref, "formula-type-unknown", formula_type))
    return issues, counts


def _syntax_issues(formula: str, *, ref: str, allow_empty: bool) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not formula and not allow_empty:
        issues.append(_issue(ref, "formula-empty", ""))
        return issues
    if formula.lstrip().startswith("="):
        issues.append(_issue(ref, "formula-leading-equals", "="))
    if any(ord(character) < 32 for character in formula):
        issues.append(_issue(ref, "formula-control-character", ""))
    masked = _mask_literals(formula)
    for opening, closing, code in (
        ("(", ")", "formula-unbalanced-parentheses"),
        ("{", "}", "formula-unbalanced-array-constant"),
    ):
        depth = 0
        for character in masked:
            if character == opening:
                depth += 1
            elif character == closing:
                depth -= 1
                if depth < 0:
                    break
        if depth != 0:
            issues.append(_issue(ref, code, ""))
    if _has_unterminated_string(formula):
        issues.append(_issue(ref, "formula-unterminated-string", ""))
    upper = masked.upper()
    for token in _FORMULA_ERRORS:
        if token in upper:
            issues.append(_issue(ref, "formula-error-token", token))
    return issues


def _mask_literals(value: str) -> str:
    masked = _mask_strings(value)
    for match in re.finditer(r"'(?:[^']|'')+'(?=!)", masked):
        masked = masked[:match.start()] + " " * (match.end() - match.start()) + masked[match.end():]
    return masked


def _mask_strings(value: str) -> str:
    result = list(value)
    in_string = False
    index = 0
    while index < len(result):
        if result[index] == '"':
            if in_string and index + 1 < len(result) and result[index + 1] == '"':
                result[index] = result[index + 1] = " "
                index += 2
                continue
            in_string = not in_string
            result[index] = " "
        elif in_string:
            result[index] = " "
        index += 1
    return "".join(result)


def _has_unterminated_string(value: str) -> bool:
    in_string = False
    index = 0
    while index < len(value):
        if value[index] != '"':
            index += 1
            continue
        if in_string and index + 1 < len(value) and value[index + 1] == '"':
            index += 2
            continue
        in_string = not in_string
        index += 1
    return in_string


def _reference_in_bounds(reference: str) -> bool:
    for token in reference.replace("$", "").split(":"):
        cell = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", token)
        if cell is not None:
            if _column_number(cell.group(1)) > _MAX_COLUMN or not 1 <= int(cell.group(2)) <= _MAX_ROW:
                return False
            continue
        if token.isdigit():
            if not 1 <= int(token) <= _MAX_ROW:
                return False
            continue
        if _column_number(token) > _MAX_COLUMN:
            return False
    return True


def _column_number(value: str) -> int:
    result = 0
    for character in value.upper():
        if not "A" <= character <= "Z":
            return _MAX_COLUMN + 1
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _decode_sheet(value: str) -> str:
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _issue(ref: str, code: str, token: str) -> dict[str, str]:
    return {"ref": ref, "code": code, "token": token[:256]}


def _occupy(occupied: list[bool], span: tuple[int, int]) -> None:
    for index in range(span[0], min(span[1], len(occupied))):
        occupied[index] = True


def _overlaps(occupied: list[bool], span: tuple[int, int]) -> bool:
    return any(occupied[span[0]:span[1]])
