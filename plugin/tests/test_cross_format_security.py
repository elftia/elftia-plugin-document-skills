"""Consolidated cross-format security gate.

Discovers every registered malicious fixture across DOCX/XLSX/PPTX/PDF via
``tests.support.cross_format_fixture_registry.discover_malicious_fixtures`` and
runs each one through a single parametrized gate that asserts the uniform
invariant:

* Mutation path (reject-mode package open) fails closed with ``ARCHIVE_UNSAFE``
  for every dangerous fixture (no format-specific escape).  For OOXML this
  exercises the full ``OpcPackage.open()`` path (archive preflight + OPC
  content-type validation + dangerous-content reject); for PDF this exercises
  ``read_pdf`` which explicitly rejects dangerous actions.
* Inspection path (preserve-disabled) either also fails closed
  (``container_reject`` fixtures whose archive/package itself is unsafe to
  open) or inventories the dangerous content under ``mutation_authorized:
  false`` / ``dangerous_content_present: true`` and NEVER authorizes mutation
  (``inert_inventory`` fixtures).

The gate reuses the existing fixtures in place via the registry helper; it
does NOT fork or duplicate any per-format fixture.  Per-format suites remain
the per-format SSOT.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any, Callable

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.docx.package import OpcPackage as DocxPackage
from document_skills_core.formats.pdf.inspect import inspect_pdf
from document_skills_core.formats.pdf.read import read_pdf
from document_skills_core.formats.pptx.package import OpcPackage as PptxPackage
from document_skills_core.formats.xlsx.package import OpcPackage as XlsxPackage

from tests.support.cross_format_fixture_registry import (
    ExpectedBehavior,
    MaliciousFixture,
    discover_malicious_fixtures,
)


_OOXML_OPENERS: dict[str, Callable[..., Any]] = {
    "docx": DocxPackage.open,
    "xlsx": XlsxPackage.open,
    "pptx": PptxPackage.open,
}


def _assert_ooxml_mutation_fails_closed(path: Path, format_id: str, fixture_id: str) -> None:
    """OOXML reject-mode package open must raise ARCHIVE_UNSAFE."""
    opener = _OOXML_OPENERS[format_id]
    with pytest.raises(DocumentSkillsError) as captured:
        opener(path)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE, (
        f"{fixture_id}: {format_id} mutation path must raise ARCHIVE_UNSAFE, "
        f"got {captured.value.code}"
    )


def _assert_ooxml_inspection_preserves_disabled(
    path: Path, format_id: str, fixture_id: str, behavior: ExpectedBehavior
) -> None:
    """OOXML preserve-disabled package open: fail closed or inventory."""
    opener = _OOXML_OPENERS[format_id]
    if behavior == "container_reject":
        with pytest.raises(DocumentSkillsError) as captured:
            opener(path, allow_dangerous_inventory=True)
        assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE, (
            f"{fixture_id}: {format_id} inspection of a container_reject fixture "
            f"must raise ARCHIVE_UNSAFE, got {captured.value.code}"
        )
        return

    package = opener(path, allow_dangerous_inventory=True)
    security = package.security
    assert security["dangerous"] is True, (
        f"{fixture_id}: inert_inventory must report dangerous=True"
    )
    assert security["mutation_authorized"] is False, (
        f"{fixture_id}: inspection must never authorize mutation"
    )
    positive = [cat for cat, count in security["counts"].items() if count > 0]
    assert positive, f"{fixture_id}: inert_inventory must have at least one positive category"


def _assert_pdf_mutation_fails_closed(path: Path, fixture_id: str) -> None:
    """PDF read (reject-mode) must raise ARCHIVE_UNSAFE for dangerous content."""
    with pytest.raises(DocumentSkillsError) as captured:
        read_pdf(path, {})
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE, (
        f"{fixture_id}: PDF mutation path must raise ARCHIVE_UNSAFE, "
        f"got {captured.value.code}"
    )


def _assert_pdf_inspection_preserves_disabled(
    path: Path, fixture_id: str, behavior: ExpectedBehavior
) -> None:
    """PDF inspect must inventory dangerous content without authorizing mutation.

    The dangerous content may be surfaced via ``dangerous_content_present``
    (for JavaScript/Launch/URI/GoToR actions) OR via the ``embedded_files``
    inventory (for embedded executables).  The invariant is that the dangerous
    content is inventoried and mutation is never authorized.
    """
    operation_result, _warnings = inspect_pdf(path, {})
    actions = operation_result.get("actions", [])
    embedded = operation_result.get("embedded_files", [])
    action_dangerous = operation_result.get("dangerous_content_present") is True
    embedded_dangerous = any(
        isinstance(entry.get("mime_type"), str)
        and "dosexec" in entry["mime_type"].lower()
        for entry in embedded
    )
    assert action_dangerous or embedded_dangerous, (
        f"{fixture_id}: PDF inspect must inventory the dangerous content "
        f"(actions={len(actions)}, embedded={len(embedded)}, "
        f"dangerous_content_present={operation_result.get('dangerous_content_present')})"
    )
    for action in actions:
        assert action["mutation_authorized"] is False, (
            f"{fixture_id}: PDF action {action.get('kind')} must not authorize mutation"
        )


@pytest.fixture
def all_fixtures(project_root: Path) -> list[MaliciousFixture]:
    return discover_malicious_fixtures(project_root)


def test_registry_discovers_fixtures_across_all_four_formats(all_fixtures):
    """The registry must cover every format with at least one fixture."""
    formats = {f.format for f in all_fixtures}
    assert formats == {"docx", "xlsx", "pptx", "pdf"}, formats
    assert len(all_fixtures) >= 15, (
        f"Expected at least 15 registered fixtures; got {len(all_fixtures)}"
    )


def test_registry_references_existing_on_disk_docx_fixtures_in_place(
    project_root: Path, all_fixtures: list[MaliciousFixture]
):
    """On-disk DOCX fixtures are referenced by path, not duplicated."""
    on_disk = [f for f in all_fixtures if f.kind == "on-disk"]
    assert on_disk, "Registry must discover the on-disk DOCX fixtures"
    for fixture in on_disk:
        assert fixture.on_disk_path is not None
        assert fixture.on_disk_path.startswith("tests/fixtures/docx-malicious-")
        resolved = project_root / fixture.on_disk_path
        assert resolved.is_file(), f"On-disk fixture missing: {resolved}"


def test_registry_does_not_fork_built_fixtures(all_fixtures: list[MaliciousFixture]):
    """Built fixtures carry a source_ref citing the per-format canonical pattern."""
    built = [f for f in all_fixtures if f.kind == "built"]
    assert built, "Registry must cover inline (built) patterns"
    for fixture in built:
        assert fixture.builder is not None
        assert fixture.source_ref, (
            f"Built fixture {fixture.pattern_id} must cite a per-format source_ref"
        )


_FIXTURES_FOR_PARAM = discover_malicious_fixtures(Path(__file__).resolve().parents[1])


@pytest.mark.parametrize(
    "fixture",
    [pytest.param(f, id=f.pattern_id) for f in _FIXTURES_FOR_PARAM],
)
def test_mutation_path_fails_closed_uniformly(
    project_root: Path, tmp_path: Path, fixture: MaliciousFixture
):
    """Every malicious fixture's mutation (reject-mode) path fails closed.

    No format-specific escape: DOCX/XLSX/PPTX/PDF all raise ARCHIVE_UNSAFE
    when a dangerous package is opened through the default reject-mode path.
    """
    source = fixture.materialize(project_root, tmp_path)
    if fixture.format == "pdf":
        _assert_pdf_mutation_fails_closed(source, fixture.pattern_id)
    else:
        _assert_ooxml_mutation_fails_closed(source, fixture.format, fixture.pattern_id)


@pytest.mark.parametrize(
    "fixture",
    [pytest.param(f, id=f.pattern_id) for f in _FIXTURES_FOR_PARAM],
)
def test_inspection_path_preserves_but_disables_uniformly(
    project_root: Path, tmp_path: Path, fixture: MaliciousFixture
):
    """Every malicious fixture is handled uniformly by the inspection path.

    ``container_reject`` fixtures fail closed at the inspection path too (the
    archive/package itself is unsafe).  ``inert_inventory`` fixtures are opened
    with ``allow_dangerous_inventory=True`` and the dangerous content is
    inventoried under ``mutation_authorized: false`` — never authorized.
    """
    source = fixture.materialize(project_root, tmp_path)
    behavior: ExpectedBehavior = fixture.expected_behavior

    if fixture.format == "pdf":
        _assert_pdf_inspection_preserves_disabled(source, fixture.pattern_id, behavior)
    else:
        _assert_ooxml_inspection_preserves_disabled(
            source, fixture.format, fixture.pattern_id, behavior
        )


def test_no_format_specific_escape_across_equivalent_patterns(
    project_root: Path, tmp_path: Path, all_fixtures: list[MaliciousFixture]
):
    """Equivalent malicious patterns across formats classify identically.

    The same structural category must produce the same ``expected_behavior``
    across every format that carries it.  This is the cross-format consistency
    assertion: no format gets a carve-out.
    """
    by_pattern_root: dict[str, list[MaliciousFixture]] = {}
    for fixture in all_fixtures:
        root = fixture.pattern_id.split(":")[-1]
        by_pattern_root.setdefault(root, []).append(fixture)

    for root, group in by_pattern_root.items():
        if len({f.format for f in group}) < 2:
            continue
        behaviors = {f.expected_behavior for f in group}
        assert len(behaviors) == 1, (
            f"Equivalent pattern '{root}' classified inconsistently across formats: {behaviors}"
        )


def test_on_disk_inert_inventory_fixture_also_passes_high_level_inspect_structure(
    project_root: Path,
):
    """The on-disk inert_inventory DOCX fixture is also accepted by the
    high-level ``docx.inspect.structure`` operation (via execute_request).

    This confirms the package-level inspect.structure path — not just the
    package open — honors the preserve-disabled contract for a valid
    dangerous package.
    """
    from document_skills_core.cli import execute_request
    from document_skills_core.core.contracts.schemas import SchemaCatalog

    source = project_root / "tests" / "fixtures" / "docx-malicious-active.docx"
    request = {
        "schema_version": "1.0",
        "operation": "docx.inspect.structure",
        "input": str(source),
        "arguments": {},
    }
    result = execute_request(request, project_root, SchemaCatalog(project_root))
    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["mutation_authorized"] is False
    assert operation_result["dangerous_content"]["dangerous"] is True
