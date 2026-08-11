"""XLSX reopen, semantic, and preservation validation gates."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation import validate_artifact

from .formula_state import assert_invariant
from .mapping import map_workbook
from .package import OpcPackage, PreservationManifest
from .projection import project_tables


def validate_created(
    path: Path,
    workbook: dict[str, Any],
) -> dict[str, Any]:
    assertions = [
        ("consumer-package-conformance", _assert_consumer_package),
        ("create-semantics", lambda candidate: _assert_created(candidate, workbook)),
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


def _assert_created(path: Path, workbook: dict[str, Any]) -> dict[str, Any]:
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
        "requested_structure": True,
    }


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
