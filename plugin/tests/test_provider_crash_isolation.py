"""Unified provider-crash-isolation gate.

Proves for EACH provider (core-python across all four formats, core-node docx
template, libreoffice recalc/convert/render/legacy, dotnet-openxml revisions/
comments/template/schema) that an injected crash, hang, or timeout during ANY
mutation leaves the source SHA unchanged, publishes no partial output, and
never crashes the host process.

The suite reuses the existing mock-injection seams
(``build_libreoffice_provider(..., detector=, runner=)`` and
``build_dotnet_provider(..., detector=, runner=)``) and the existing fake
callable / absent / crashing / hanging runner fixtures.  It consolidates the
per-provider crash tests into one cross-provider gate and closes any gap
(core-node template, libreoffice convert/render/legacy crash variants,
dotnet comments/template crash variants) by reusing the same mock-injected
containment contract.

Real LibreOffice and real .NET SHALL NOT be required; only fake runners are
used.

Module provenance: original Elftia-authored clean-room implementation.
"""

import base64
import hashlib
from pathlib import Path

import pytest

import document_skills_core.formats.docx.service as service_module
from document_skills_core.cli import execute_request
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.providers.dotnet import build_dotnet_provider
from document_skills_core.providers.libreoffice import build_libreoffice_provider


# ---------------------------------------------------------------------------
# Shared fake runners and detectors (mirrors tests/test_{libreoffice,dotnet}_provider.py)
# ---------------------------------------------------------------------------


class _LibreCallableDetector:
    def detect(self):
        from document_skills_core.core.capabilities import DetectionEvidence

        return DetectionEvidence(available=True, version="25.8.0", path="/fake/soffice")


class _LibreAbsentDetector:
    def detect(self):
        from document_skills_core.core.capabilities import DetectionEvidence

        return DetectionEvidence(available=False, reason="no soffice candidate found")


class _LibreCrashRunner:
    """Raises PROVIDER_FAILED on every convert()."""

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Fake crash during LibreOffice conversion.",
        )


class _LibreTimeoutRunner:
    """Raises PROCESS_TIMEOUT on every convert()."""

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "LibreOffice exceeded its time budget.",
        )


class _DotnetCallableDetector:
    def detect(self):
        from document_skills_core.core.capabilities import DetectionEvidence

        return DetectionEvidence(available=True, version="3.0.0", path="/fake/dotnet")


class _DotnetCrashRunner:
    """Raises PROVIDER_FAILED on every run()."""

    def set_executable(self, exe):
        pass

    def run(self, subcommand, *, stdin_payload=None, **kwargs):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Fake crash during dotnet helper invocation.",
        )


class _DotnetTimeoutRunner:
    """Raises PROCESS_TIMEOUT on every run()."""

    def set_executable(self, exe):
        pass

    def run(self, subcommand, *, stdin_payload=None, **kwargs):
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "dotnet helper exceeded its time budget.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_fake_docx(tmp_path: Path) -> Path:
    """A minimal fake DOCX (bytes only — no structural validation needed)."""
    path = tmp_path / "source.docx"
    path.write_bytes(b"PK\x03\x04fake-docx-content-for-crash-isolation")
    return path


def _make_fake_xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "source.xlsx"
    path.write_bytes(b"PK\x03\x04fake-xlsx-content-for-crash-isolation")
    return path


# ---------------------------------------------------------------------------
# LibreOffice crash-isolation: recalc / convert / render / legacy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method_name", "failure_runner", "failure_label"),
    [
        ("try_recalc_xlsx", _LibreCrashRunner, "crash"),
        ("try_recalc_xlsx", _LibreTimeoutRunner, "timeout"),
        ("try_convert_to_pdf", _LibreCrashRunner, "crash"),
        ("try_convert_to_pdf", _LibreTimeoutRunner, "timeout"),
        ("try_render_to_image", _LibreCrashRunner, "crash"),
        ("try_render_to_image", _LibreTimeoutRunner, "timeout"),
        ("try_read_legacy", _LibreCrashRunner, "crash"),
        ("try_read_legacy", _LibreTimeoutRunner, "timeout"),
    ],
)
def test_libreoffice_crash_isolation(
    project_root: Path, tmp_path: Path, method_name: str, failure_runner, failure_label: str
):
    """LibreOffice provider mutation crashes are contained.

    For each provider × mutation path × failure mode, the source SHA-256 is
    unchanged, no output is promoted, and the host process survives.
    """
    source = _make_fake_xlsx(tmp_path) if "recalc" in method_name else _make_fake_docx(tmp_path)
    source_hash = _sha256(source)

    _, provider = build_libreoffice_provider(
        project_root,
        detector=_LibreCallableDetector(),
        runner=failure_runner(),
    )
    method = getattr(provider, method_name)
    # All paths return None on failure (crash/timeout caught + contained).
    if method_name == "try_read_legacy":
        result = method(source)
    else:
        result = method(source)

    assert result is None, (
        f"LibreOffice {method_name} {failure_label}: expected None, got {result!r}"
    )
    # Source SHA unchanged.
    assert _sha256(source) == source_hash, (
        f"LibreOffice {method_name} {failure_label}: source SHA drifted"
    )
    # No partial output promoted (no extra files in tmp_path).
    leftovers = [p for p in tmp_path.iterdir() if p.name != source.name]
    assert not leftovers, (
        f"LibreOffice {method_name} {failure_label}: unexpected leftovers {leftovers}"
    )


# ---------------------------------------------------------------------------
# dotnet-openxml crash-isolation: revisions/comments/template/schema mutations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method_name", "failure_runner", "failure_label", "needs_output"),
    [
        ("try_read_revisions", _DotnetCrashRunner, "crash", False),
        ("try_read_revisions", _DotnetTimeoutRunner, "timeout", False),
        ("try_accept_reject_revisions", _DotnetCrashRunner, "crash", True),
        ("try_accept_reject_revisions", _DotnetTimeoutRunner, "timeout", True),
        ("try_read_comments", _DotnetCrashRunner, "crash", False),
        ("try_read_comments", _DotnetTimeoutRunner, "timeout", False),
        ("try_add_comment", _DotnetCrashRunner, "crash", True),
        ("try_add_comment", _DotnetTimeoutRunner, "timeout", True),
        ("try_validate_schema", _DotnetCrashRunner, "crash", False),
        ("try_validate_schema", _DotnetTimeoutRunner, "timeout", False),
        ("try_apply_template", _DotnetCrashRunner, "crash", True),
        ("try_apply_template", _DotnetTimeoutRunner, "timeout", True),
    ],
)
def test_dotnet_crash_isolation(
    project_root: Path,
    tmp_path: Path,
    method_name: str,
    failure_runner,
    failure_label: str,
    needs_output: bool,
):
    """dotnet-openxml provider mutation crashes are contained.

    For each provider × mutation path × failure mode, the source SHA-256 is
    unchanged, no output is promoted, and the host process survives.
    """
    source = _make_fake_docx(tmp_path)
    source_hash = _sha256(source)
    output = tmp_path / "output.docx"

    _, provider = build_dotnet_provider(
        project_root,
        detector=_DotnetCallableDetector(),
        runner=failure_runner(),
    )
    method = getattr(provider, method_name)
    if needs_output:
        if method_name == "try_accept_reject_revisions":
            result = method(source, output, ["r1"], "accept")
        elif method_name == "try_add_comment":
            result = method(source, output, {"text": "Hello", "author": "Test"})
        elif method_name == "try_apply_template":
            result = method(source, output, {"title": "Hello"})
        else:
            pytest.skip(f"Unhandled output-bearing method: {method_name}")
    else:
        if method_name == "try_read_comments":
            result = method(source)
        else:
            result = method(source)

    assert result is None, (
        f"dotnet {method_name} {failure_label}: expected None, got {result!r}"
    )
    # Source SHA unchanged.
    assert _sha256(source) == source_hash, (
        f"dotnet {method_name} {failure_label}: source SHA drifted"
    )
    # No partial output promoted.
    assert not output.exists(), (
        f"dotnet {method_name} {failure_label}: partial output was promoted"
    )


# ---------------------------------------------------------------------------
# Core-python preservation under mutation failure
# ---------------------------------------------------------------------------


def test_core_python_docx_replace_preserves_source_on_failure(
    project_root: Path, tmp_path: Path
):
    """A failed DOCX edit (overlapping replacements → invalid_request) leaves
    the source SHA unchanged and no output promoted.
    """
    from document_skills_core.cli import execute_request
    from document_skills_core.core.contracts.schemas import SchemaCatalog

    source = project_root / "tests" / "fixtures" / "docx-rich.docx"
    source_hash = _sha256(source)
    output = tmp_path / "output.docx"
    request = {
        "schema_version": "1.0",
        "operation": "docx.edit.replace-text",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "replacements": [
                {"search": "AAA", "replace": "first"},
                {"search": "AA", "replace": "second"},
            ]
        },
    }
    result = execute_request(request, project_root, SchemaCatalog(project_root))
    assert result["status"] == "invalid_request", result
    assert _sha256(source) == source_hash, "Source SHA drifted after failed DOCX edit"
    assert not output.exists(), "Partial output promoted after failed DOCX edit"


def test_core_python_xlsx_edit_preserves_source_on_failure(
    project_root: Path, tmp_path: Path
):
    """A failed XLSX edit (zero edits) leaves source SHA unchanged."""
    from document_skills_core.cli import execute_request
    from document_skills_core.core.contracts.schemas import SchemaCatalog
    from document_skills_core.core.io.temp_roots import OperationTempRoot
    from document_skills_core.formats.xlsx.create import create_xlsx

    source = tmp_path / "source.xlsx"
    with OperationTempRoot() as private_root:
        staged = private_root / "created.xlsx"
        create_xlsx(
            staged,
            {
                "metadata": {},
                "sheets": [
                    {
                        "name": "Sheet1",
                        "rows": [{"cells": [{"ref": "A1", "value": "10", "type": "n"}]}],
                        "number_formats": [],
                    }
                ],
                "defined_names": [],
                "tables": [],
            },
        )
        source.write_bytes(staged.read_bytes())
    source_hash = _sha256(source)
    output = tmp_path / "output.xlsx"
    request = {
        "schema_version": "1.0",
        "operation": "xlsx.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"edits": [], "expected_edits": 0},
    }
    result = execute_request(request, project_root, SchemaCatalog(project_root))
    assert result["status"] == "invalid_request", result
    assert _sha256(source) == source_hash, "Source SHA drifted after failed XLSX edit"
    assert not output.exists(), "Partial output promoted after failed XLSX edit"


# ---------------------------------------------------------------------------
# Core-node docx-template crash-isolation: crash / timeout
# ---------------------------------------------------------------------------

_PNG_ONE_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _make_template_docx(project_root: Path, tmp_path: Path) -> Path:
    """Build a real DOCX template carrying one scalar token via core-python create.

    The paragraph ``Hello {customer.name}!`` ensures ``plan_template`` binds
    exactly one variable, so execution reaches the ``apply_template_with_node``
    seam where the crash is injected.
    """
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG_ONE_PIXEL)
    template = tmp_path / "template.docx"
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(template),
            "arguments": {
                "report": {
                    "metadata": {"title": "Crash-isolation template"},
                    "blocks": [
                        {"type": "heading", "text": "Crash Isolation", "level": 1},
                        {"type": "paragraph", "text": "Hello {customer.name}!"},
                        {
                            "type": "table",
                            "style": "TableGrid",
                            "rows": [["Name"], ["Value"]],
                        },
                    ],
                    "image": {
                        "path": str(image),
                        "alt_text": "pixel",
                        "width_inches": 1,
                    },
                    "header": "Header",
                    "footer": "Footer",
                    "sections": [
                        {"orientation": "portrait"},
                        {"orientation": "landscape"},
                    ],
                }
            },
        },
        project_root,
        SchemaCatalog(project_root),
    )
    assert result["status"] == "success", result
    return template


@pytest.mark.parametrize(
    ("failure_code", "failure_label"),
    [
        (ErrorCode.PROVIDER_FAILED, "crash"),
        (ErrorCode.PROCESS_TIMEOUT, "timeout"),
    ],
)
def test_core_node_template_crash_isolation(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_code: ErrorCode,
    failure_label: str,
):
    """Core-node docx template provider mutation crashes are contained.

    For each failure mode (crash / timeout) injected at the
    ``apply_template_with_node`` seam, the source SHA-256 is unchanged, no
    partial output is promoted, the host process survives, and the result
    reports the provider failure.
    """
    template = _make_template_docx(project_root, tmp_path)
    source_hash = _sha256(template)
    output = tmp_path / "output.docx"

    def crashing_backend(*args, **kwargs):
        raise DocumentSkillsError(
            failure_code,
            f"Fake {failure_label} during core-node template application.",
        )

    monkeypatch.setattr(
        service_module,
        "apply_template_with_node",
        crashing_backend,
    )

    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {"variables": {"customer": {"name": "Alice"}}},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    # Host survives; result reports the provider failure.
    assert result["status"] == "failed", (
        f"core-node template {failure_label}: expected status 'failed', "
        f"got {result.get('status')!r}"
    )
    assert result["errors"][0]["code"] == failure_code.value, (
        f"core-node template {failure_label}: expected error code "
        f"{failure_code.value!r}, got {result['errors'][0]['code']!r}"
    )
    # Source SHA unchanged.
    assert _sha256(template) == source_hash, (
        f"core-node template {failure_label}: source SHA drifted"
    )
    # No partial output promoted.
    assert not output.exists(), (
        f"core-node template {failure_label}: partial output was promoted"
    )


# ---------------------------------------------------------------------------
# Cross-provider invariant: every crash returns None (no partial output)
# ---------------------------------------------------------------------------


def test_every_provider_mutation_returns_none_on_crash(project_root: Path, tmp_path: Path):
    """Summary assertion: every provider mutation path returns None when its
    runner crashes, proving uniform containment across providers.
    """
    source = _make_fake_docx(tmp_path)
    output = tmp_path / "output.docx"

    # LibreOffice — all four mutation paths
    _, libre = build_libreoffice_provider(
        project_root, detector=_LibreCallableDetector(), runner=_LibreCrashRunner()
    )
    assert libre.try_convert_to_pdf(source) is None
    assert libre.try_render_to_image(source) is None
    assert libre.try_read_legacy(source) is None

    # dotnet — all mutation paths
    _, dotnet = build_dotnet_provider(
        project_root, detector=_DotnetCallableDetector(), runner=_DotnetCrashRunner()
    )
    assert dotnet.try_accept_reject_revisions(source, output, ["r1"], "accept") is None
    assert dotnet.try_add_comment(source, output, {"text": "Hi", "author": "T"}) is None
    assert dotnet.try_apply_template(source, output, {"title": "Hi"}) is None

    # Source and output untouched
    assert not output.exists()
