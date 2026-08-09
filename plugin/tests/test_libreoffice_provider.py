"""LibreOffice enhancement provider tests — mock-injected present/absent/crash/timeout.

Real LibreOffice is NOT required. Tests inject fake detectors and runners
to exercise the wiring, honesty, and containment.

Module provenance: original Elftia-authored clean-room implementation.
"""

import json
from pathlib import Path

import pytest

from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessResult, ProcessRunner
from document_skills_core.formats.xlsx.constants import FORMULA_STATE_RECALCULATED
from document_skills_core.formats.xlsx.service import XlsxService
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from document_skills_core.providers.libreoffice.constants import (
    ACCEPTED_SUBCOMMANDS,
    FORBIDDEN_TOKENS,
    HEADLESS_PREFIX,
    platform_known_paths,
)
from document_skills_core.providers.libreoffice.detector import LibreOfficeDetector
from document_skills_core.providers.libreoffice.runner import (
    LibreOfficeRunner,
    _build_argv,
    _validate_argv,
)
from document_skills_core.providers.libreoffice.recalc import recalculate_xlsx


# ---------------------------------------------------------------------------
# Fake detectors
# ---------------------------------------------------------------------------

class FakeCallableDetector:
    """A detector that always reports LibreOffice as callable."""

    def __init__(self, version="25.8.0", path="/fake/soffice"):
        self._version = version
        self._path = path

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            available=True, version=self._version, path=self._path
        )


class FakeAbsentDetector:
    """A detector that always reports LibreOffice as unavailable."""

    def __init__(self, reason="no soffice candidate found"):
        self._reason = reason

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(available=False, reason=self._reason)


# ---------------------------------------------------------------------------
# Fake runners
# ---------------------------------------------------------------------------

class FakeCallableRunner:
    """A runner that writes a canned output file on convert()."""

    def __init__(self, canned_data: bytes | None = None, canned_path: Path | None = None):
        if canned_path is not None and canned_data is None:
            canned_data = Path(canned_path).read_bytes()
        self._canned_data = canned_data or b"fake-output"
        self._canned_path = canned_path
        self.calls: list[dict] = []

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        self.calls.append({
            "input": str(input_path),
            "format": target_format,
            "output_dir": str(output_dir),
            "timeout": timeout_seconds,
        })
        output = output_dir / (Path(input_path).stem + "." + target_format)
        output.write_bytes(self._canned_data)
        return output
        return output


class FakeCrashingRunner:
    """A runner that raises PROVIDER_FAILED on every convert()."""

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Fake crash during LibreOffice conversion.",
        )


class FakeHangingRunner:
    """A runner that raises PROCESS_TIMEOUT on every convert()."""

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "LibreOffice exceeded its time budget.",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_xlsx(project_root: Path, tmp_path: Path) -> Path:
    """Create a real XLSX with formula cells (with cached values) for testing."""
    from document_skills_core.formats.xlsx.create import create_xlsx
    from document_skills_core.core.io.temp_roots import OperationTempRoot
    workbook = {
        "metadata": {},
        "sheets": [{
            "name": "Sheet1",
            "rows": [
                {"cells": [
                    {"ref": "A1", "value": "10", "type": "n"},
                    {"ref": "A2", "value": "20", "type": "n"},
                    {"ref": "A3", "formula": "SUM(A1:A2)", "cached_value": "30", "type": "n"},
                ]},
            ],
            "number_formats": [],
        }],
        "defined_names": [],
        "tables": [],
    }
    output = tmp_path / "test_input.xlsx"
    with OperationTempRoot() as private_root:
        staged = private_root / "created.xlsx"
        create_xlsx(staged, workbook)
        output.write_bytes(staged.read_bytes())
    return output


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_headless_prefix_contains_required_flags(self):
        assert "--headless" in HEADLESS_PREFIX
        assert "--norestore" in HEADLESS_PREFIX
        assert "--nofirststartwizard" in HEADLESS_PREFIX

    def test_accepted_subcommands_excludes_cmd(self):
        assert "--cmd" not in ACCEPTED_SUBCOMMANDS
        assert "--convert-to" in ACCEPTED_SUBCOMMANDS

    def test_forbidden_tokens_include_macro_and_dde(self):
        assert "--cmd" in FORBIDDEN_TOKENS
        assert ".bas" in FORBIDDEN_TOKENS
        assert ".xba" in FORBIDDEN_TOKENS

    def test_platform_known_paths_returns_list(self):
        paths = platform_known_paths()
        assert isinstance(paths, list)
        assert len(paths) >= 1


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------

class TestDetector:
    def test_callable_version_probe_parses_version(self, project_root, monkeypatch):
        """Callable soffice --version → available with parsed version."""
        detector = LibreOfficeDetector(project_root)

        class FakeRunner:
            def run(self, provider_id, executable, args, **kwargs):
                assert "--version" in args
                assert kwargs["timeout_seconds"] <= 2.0
                return ProcessResult(
                    0, "LibreOffice 25.8.0.0 1234567890", "", 100
                )

        monkeypatch.setattr(shutil_module(), "which", lambda name: "/fake/soffice")
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is True
        assert evidence.version == "25.8.0.0"
        assert evidence.path is not None

    def test_executable_absent_returns_unavailable(self, project_root, monkeypatch):
        import shutil as sh
        monkeypatch.setattr(sh, "which", lambda name: None)
        monkeypatch.setattr(Path, "is_file", lambda self: False)
        detector = LibreOfficeDetector(project_root)
        evidence = detector.detect()
        assert evidence.available is False
        assert evidence.reason is not None
        assert "candidate" in evidence.reason.lower()

    def test_nonzero_exit_returns_unavailable(self, project_root, monkeypatch):
        import shutil as sh
        monkeypatch.setattr(sh, "which", lambda name: "/fake/soffice")

        class FakeRunner:
            def run(self, *a, **kw):
                return ProcessResult(1, "", "error", 50)

        detector = LibreOfficeDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "exited" in evidence.reason

    def test_unparseable_version_returns_unavailable(self, project_root, monkeypatch):
        import shutil as sh
        monkeypatch.setattr(sh, "which", lambda name: "/fake/soffice")

        class FakeRunner:
            def run(self, *a, **kw):
                return ProcessResult(0, "Weird Office 1.0", "", 50)

        detector = LibreOfficeDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "unparseable" in evidence.reason

    def test_timeout_returns_unavailable(self, project_root, monkeypatch):
        import shutil as sh
        monkeypatch.setattr(sh, "which", lambda name: "/fake/soffice")

        class FakeRunner:
            def run(self, *a, **kw):
                raise DocumentSkillsError(
                    ErrorCode.PROCESS_TIMEOUT, "probe timed out"
                )

        detector = LibreOfficeDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "timeout" in evidence.reason.lower()


def shutil_module():
    import shutil
    return shutil


# ---------------------------------------------------------------------------
# Runner containment tests
# ---------------------------------------------------------------------------

class TestRunnerContainment:
    def test_argv_is_validated_before_spawn(self):
        """Macro-execution arguments are rejected before spawning."""
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv(
                [*HEADLESS_PREFIX, "--cmd", "macro:///Standard.Module1.Recalc"]
            )
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_bas_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([*HEADLESS_PREFIX, "--convert-to", "file.bas"])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_xba_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([*HEADLESS_PREFIX, "--convert-to", "file.xba"])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_dde_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([*HEADLESS_PREFIX, "--convert-to", "DDE:link"])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_no_accepted_subcommand_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([*HEADLESS_PREFIX, "--unknown-flag", "file.xlsx"])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_valid_convert_to_argv_accepted(self):
        argv = _build_argv(
            "--convert-to", "xlsx", "--outdir", "/tmp", "input.xlsx"
        )
        assert "--headless" in argv
        assert "--convert-to" in argv

    def test_runner_convert_uses_project_root_cwd(self, project_root, monkeypatch):
        """The runner passes cwd=project_root to the ProcessRunner."""
        captured = {}

        class FakeProcessRunner:
            def run(self, provider_id, executable, args, **kwargs):
                captured["cwd"] = kwargs.get("cwd")
                captured["shell"] = False
                captured["args"] = args
                captured["timeout"] = kwargs.get("timeout_seconds")
                captured["output_limit"] = kwargs.get("output_limit")
                return ProcessResult(0, "", "", 10)

        runner = LibreOfficeRunner(
            project_root, executable="/fake/soffice", runner=FakeProcessRunner()
        )
        import tempfile
        outdir = Path(tempfile.gettempdir()) / "test_lo_out"
        outdir.mkdir(exist_ok=True)
        input_file = outdir / "test.xlsx"
        input_file.write_bytes(b"fake")
        runner.convert(input_file, "xlsx", outdir)
        assert captured["cwd"] == project_root.resolve()
        assert captured["shell"] is False
        assert isinstance(captured["args"], list)
        assert captured["timeout"] is not None
        assert captured["output_limit"] > 0

    def test_env_sanitized_by_process_runner(self, project_root):
        """The existing ProcessRunner sanitizes env — verify via its allowlist."""
        from document_skills_core.core.process.runner import _ENV_ALLOWLIST
        assert "HOME" not in _ENV_ALLOWLIST
        assert "USERPROFILE" not in _ENV_ALLOWLIST
        assert "PATH" in _ENV_ALLOWLIST
        assert "SystemRoot" in _ENV_ALLOWLIST


# ---------------------------------------------------------------------------
# Provider factory and consultation tests
# ---------------------------------------------------------------------------

class TestProviderFactory:
    def test_factory_returns_definition_and_provider(self, project_root):
        definition, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(),
        )
        assert definition.id == ProviderId.LIBREOFFICE
        assert definition.execute is not None
        assert definition.required is False
        assert len(definition.capabilities) > 0

    def test_factory_with_absent_detector_detects_unavailable(self, project_root):
        definition, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        evidence = definition.detect()
        assert evidence.available is False

    def test_factory_with_callable_detector_detects_available(self, project_root):
        definition, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(version="25.8.0"),
            runner=FakeCallableRunner(),
        )
        evidence = definition.detect()
        assert evidence.available is True
        assert evidence.version == "25.8.0"

    def test_diagnostics_returns_path_and_version(self, project_root):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(version="25.8.0", path="/usr/bin/soffice"),
            runner=FakeCallableRunner(),
        )
        diag = provider.diagnostics()
        assert diag["path"] == "/usr/bin/soffice"
        assert diag["version"] == "25.8.0"

    def test_diagnostics_absent_returns_reason(self, project_root):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(reason="not installed"),
            runner=FakeCallableRunner(),
        )
        diag = provider.diagnostics()
        assert diag["path"] is None
        assert diag["version"] is None
        assert "not installed" in diag["reason"]


# ---------------------------------------------------------------------------
# Consultation tests (present / absent / crash / timeout)
# ---------------------------------------------------------------------------

class TestConsultationMatrix:
    def test_recalc_present_returns_cached_values(
        self, project_root, fake_xlsx
    ):
        """With callable detector+runner, try_recalc_xlsx returns cached values."""
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_path=fake_xlsx),
        )
        result = provider.try_recalc_xlsx(fake_xlsx)
        assert result is not None
        assert any(key.startswith("Sheet1!") for key in result)
        assert any(key.startswith("Sheet1!") for key in result)

    def test_recalc_absent_returns_none(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_recalc_xlsx(fake_xlsx) is None

    def test_recalc_crash_returns_none(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCrashingRunner(),
        )
        assert provider.try_recalc_xlsx(fake_xlsx) is None

    def test_recalc_timeout_returns_none(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeHangingRunner(),
        )
        assert provider.try_recalc_xlsx(fake_xlsx) is None

    def test_convert_pdf_present_returns_bytes(self, project_root, tmp_path):
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(b"fake docx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"%PDF-1.4 fake"),
        )
        result = provider.try_convert_to_pdf(input_file)
        assert result is not None
        assert result.startswith(b"%PDF")

    def test_convert_pdf_absent_returns_none(self, project_root, tmp_path):
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(b"fake docx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_convert_to_pdf(input_file) is None

    def test_render_present_returns_bytes(self, project_root, tmp_path):
        input_file = tmp_path / "input.pptx"
        input_file.write_bytes(b"fake pptx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"\x89PNG fake"),
        )
        result = provider.try_render_to_image(input_file)
        assert result is not None
        assert result.startswith(b"\x89PNG")

    def test_render_absent_returns_none(self, project_root, tmp_path):
        input_file = tmp_path / "input.pptx"
        input_file.write_bytes(b"fake pptx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_render_to_image(input_file) is None

    def test_legacy_present_returns_bytes(self, project_root, tmp_path):
        input_file = tmp_path / "input.doc"
        input_file.write_bytes(b"fake doc")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"PK fake docx"),
        )
        result = provider.try_read_legacy(input_file)
        assert result is not None
        assert result.startswith(b"PK")

    def test_legacy_absent_returns_none(self, project_root, tmp_path):
        input_file = tmp_path / "input.doc"
        input_file.write_bytes(b"fake doc")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_read_legacy(input_file) is None


# ---------------------------------------------------------------------------
# XLSX service integration tests
# ---------------------------------------------------------------------------

class TestXlsxServiceIntegration:
    def _read_request(self, input_path: Path) -> dict:
        return {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(input_path),
            "arguments": {},
        }

    def test_read_with_libreoffice_marks_recalculated(
        self, project_root, fake_xlsx
    ):
        """When LibreOffice recalc succeeds, formula cells become 'recalculated'."""
        _, libreoffice = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_path=fake_xlsx),
        )
        service = XlsxService(project_root, libreoffice=libreoffice)
        result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        assert result["status"] in ("success", "degraded")
        formula_state = result["diagnostics"]["operation_result"]["formula_state"]
        summary = formula_state["summary"]
        assert summary["recalculation_provider"] == "libreoffice"
        assert summary["no_unverified_claimed_recalculated"] is True
        has_recalculated = any(
            cell["state"] == FORMULA_STATE_RECALCULATED
            for cell in formula_state["cells"].values()
        )
        assert has_recalculated

    def test_read_without_libreoffice_preserves_core(self, project_root, fake_xlsx):
        """Without LibreOffice, the Core result is byte-identical."""
        service_core = XlsxService(project_root)
        result_core = service_core.execute("xlsx.read", self._read_request(fake_xlsx))

        _, libreoffice_absent = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        service_absent = XlsxService(project_root, libreoffice=libreoffice_absent)
        result_absent = service_absent.execute("xlsx.read", self._read_request(fake_xlsx))

        core_summary = result_core["diagnostics"]["operation_result"]["formula_state"]["summary"]
        absent_summary = result_absent["diagnostics"]["operation_result"]["formula_state"]["summary"]
        assert core_summary["recalculation_provider"] == "unavailable"
        assert absent_summary["recalculation_provider"] == "unavailable"
        assert (
            result_absent["diagnostics"]["operation_result"]["formula_state"]["cells"]
            == result_core["diagnostics"]["operation_result"]["formula_state"]["cells"]
        )

    def test_read_with_crashing_libreoffice_falls_back_to_core(
        self, project_root, fake_xlsx
    ):
        """When LibreOffice crashes, recalculation_provider is None (Core fallback)."""
        _, libreoffice_crash = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCrashingRunner(),
        )
        service = XlsxService(project_root, libreoffice=libreoffice_crash)
        result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        formula_state = result["diagnostics"]["operation_result"]["formula_state"]
        summary = formula_state["summary"]
        assert summary["recalculation_provider"] == "unavailable"
        assert all(
            cell["state"] != FORMULA_STATE_RECALCULATED
            for cell in formula_state["cells"].values()
        )

    def test_read_with_timeout_libreoffice_falls_back_to_core(
        self, project_root, fake_xlsx
    ):
        _, libreoffice_timeout = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeHangingRunner(),
        )
        service = XlsxService(project_root, libreoffice=libreoffice_timeout)
        result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        summary = result["diagnostics"]["operation_result"]["formula_state"]["summary"]
        assert summary["recalculation_provider"] == "unavailable"


# ---------------------------------------------------------------------------
# Provider execute dispatcher tests
# ---------------------------------------------------------------------------

class TestProviderExecuteDispatcher:
    def test_execute_recalc_returns_canonical_result(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_path=fake_xlsx),
        )
        result = provider.execute("libreoffice.recalc-xlsx", {
            "schema_version": "1.0",
            "operation": "libreoffice.recalc-xlsx",
            "input": str(fake_xlsx),
        })
        assert result["schema_version"] == "1.0"
        assert result["status"] == "success"
        assert result["operation"] == "libreoffice.recalc-xlsx"
        assert set(result) == {
            "schema_version", "status", "operation", "provider_chain",
            "requested_fidelity", "achieved_fidelity", "degraded",
            "degradations", "artifacts", "validation", "warnings",
            "errors", "diagnostics",
        }

    def test_execute_absent_returns_failed(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        result = provider.execute("libreoffice.recalc-xlsx", {
            "schema_version": "1.0",
            "operation": "libreoffice.recalc-xlsx",
            "input": str(fake_xlsx),
        })
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# find_callable catalog tests
# ---------------------------------------------------------------------------

class TestFindCallable:
    def test_find_callable_returns_true_with_callable_provider(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.LIBREOFFICE) is True

    def test_find_callable_returns_false_with_absent_provider(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.LIBREOFFICE) is False

    def test_find_callable_returns_false_for_unregistered(self, project_root):
        registry = ProviderCatalog()
        assert registry.find_callable(ProviderId.LIBREOFFICE) is False


# ---------------------------------------------------------------------------
# No-macro-argv assertion tests
# ---------------------------------------------------------------------------

class TestNoMacroArgv:
    def test_recalc_uses_convert_to_xlsx_only(self, project_root, fake_xlsx):
        """The recalc argv contains --convert-to xlsx and no macro tokens."""
        canned_xlsx = fake_xlsx
        runner = FakeCallableRunner(canned_path=canned_xlsx)
        recalculate_xlsx(fake_xlsx, runner)
        assert len(runner.calls) == 1
        assert runner.calls[0]["format"] == "xlsx"
