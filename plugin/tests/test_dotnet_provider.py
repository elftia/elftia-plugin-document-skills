"""dotnet-openxml enhancement provider tests — mock-injected present/absent/crash/timeout.

Real .NET is NOT required. Tests inject fake detectors and runners
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
from document_skills_core.core.process import ProcessPolicy, ProcessResult
from document_skills_core.providers.dotnet import build_dotnet_provider
from document_skills_core.providers.dotnet.constants import (
    ACCEPTED_SUBCOMMANDS,
    OUTPUT_LIMIT,
    RUNTIME_PREFIX,
    STDIN_CEILING,
    TIMEOUT_PROBE,
    TIMEOUT_RUNTIME_PROBE,
    platform_known_paths,
)
from document_skills_core.providers.dotnet.detector import DotnetOpenXmlDetector
from document_skills_core.providers.dotnet.runner import DotnetOpenXmlRunner, _build_argv, _check_stdin


# ---------------------------------------------------------------------------
# Fake detectors
# ---------------------------------------------------------------------------

class FakeCallableDetector:
    """A detector that always reports dotnet-openxml as callable."""

    def __init__(self, version="3.0.0", path="/fake/dotnet"):
        self._version = version
        self._path = path

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            available=True, version=self._version, path=self._path
        )


class FakeAbsentDetector:
    """A detector that always reports dotnet-openxml as unavailable."""

    def __init__(self, reason="no dotnet candidate found"):
        self._reason = reason

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(available=False, reason=self._reason)


class FakeRuntimeOnlyDetector:
    """Runtime present but assembly not resolvable."""

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            available=False,
            reason="The DocumentFormat.OpenXml assembly is not resolvable from the user environment",
            path="/fake/dotnet",
        )


# ---------------------------------------------------------------------------
# Fake runners
# ---------------------------------------------------------------------------

class FakeRunner:
    """A fake DotnetOpenXmlRunner that returns canned ProcessResults per subcommand.

    For mutation operations, writes the staged output file so the operation
    module can read it back.
    """

    def __init__(self, responses: dict[str, ProcessResult] | None = None):
        self._responses = responses or {}
        self.calls: list[dict] = []

    def set_executable(self, exe):
        pass

    def run(self, subcommand, *, stdin_payload=None, timeout_seconds=None, output_limit=None):
        self.calls.append({
            "subcommand": subcommand,
            "stdin_payload": stdin_payload,
            "timeout": timeout_seconds,
            "output_limit": output_limit,
        })
        # For mutation ops, create the output file so the operation module can read it.
        if stdin_payload and "output_path" in stdin_payload:
            output_path = Path(stdin_payload["output_path"])
            if "input_path" in stdin_payload:
                input_path = Path(stdin_payload["input_path"])
                if input_path.is_file():
                    output_path.write_bytes(input_path.read_bytes())
                else:
                    output_path.write_bytes(b"PK\x03\x04fake-output")
        response = self._responses.get(subcommand)
        if response is not None:
            return response
        return ProcessResult(0, "{}", "", 10)


class FakeCrashingRunner:
    """A runner that raises PROVIDER_FAILED on every invocation."""

    def set_executable(self, exe):
        pass

    def run(self, subcommand, *, stdin_payload=None, **kwargs):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Fake crash during dotnet helper invocation.",
        )


class FakeHangingRunner:
    """A runner that raises PROCESS_TIMEOUT on every invocation."""

    def set_executable(self, exe):
        pass

    def run(self, subcommand, *, stdin_payload=None, **kwargs):
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "dotnet helper exceeded its time budget.",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_docx(tmp_path: Path) -> Path:
    """Create a minimal fake DOCX for testing."""
    docx = tmp_path / "test_input.docx"
    docx.write_bytes(b"PK\x03\x04fake-docx-content")
    return docx


def _canned_revisions_response():
    return ProcessResult(
        0,
        json.dumps({"revisions": [
            {"id": "r1", "type": "insertion", "author": "Alice", "date": "2026-01-01T00:00:00Z"},
            {"id": "r2", "type": "deletion", "author": "Bob", "date": "2026-01-02T00:00:00Z"},
        ]}),
        "",
        50,
    )


def _canned_comments_response():
    return ProcessResult(
        0,
        json.dumps({"comments": [
            {"id": "c1", "author": "Alice", "date": "2026-01-01", "text": "Looks good"},
        ]}),
        "",
        50,
    )


def _canned_schema_valid_response():
    return ProcessResult(0, json.dumps({"valid": True, "errors": []}), "", 50)


def _canned_schema_invalid_response():
    return ProcessResult(
        0,
        json.dumps({"valid": False, "errors": [{"part": "MainDocumentPart", "description": "Missing attribute"}]}),
        "",
        50,
    )


def _canned_revisions_accept_response():
    return ProcessResult(
        0,
        json.dumps({"matched_ids": ["r1"], "unmatched_ids": ["r3"]}),
        "",
        50,
    )


def _canned_comments_add_response():
    return ProcessResult(0, json.dumps({"comment_id": "c99"}), "", 50)


def _canned_template_apply_response():
    return ProcessResult(0, json.dumps({"applied_variables": ["title"]}), "", 50)


def _make_runner_with_responses(responses: dict[str, ProcessResult]) -> FakeRunner:
    """Create a FakeRunner with canned responses per subcommand."""
    return FakeRunner(responses=responses)


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_accepted_subcommands_contains_probe(self):
        assert "--probe-json" in ACCEPTED_SUBCOMMANDS

    def test_accepted_subcommands_contains_revisions(self):
        assert "--revisions-read" in ACCEPTED_SUBCOMMANDS
        assert "--revisions-accept" in ACCEPTED_SUBCOMMANDS
        assert "--revisions-reject" in ACCEPTED_SUBCOMMANDS

    def test_accepted_subcommands_contains_comments(self):
        assert "--comments-read" in ACCEPTED_SUBCOMMANDS
        assert "--comments-add" in ACCEPTED_SUBCOMMANDS

    def test_accepted_subcommands_contains_template_and_schema(self):
        assert "--template-apply" in ACCEPTED_SUBCOMMANDS
        assert "--schema-validate" in ACCEPTED_SUBCOMMANDS

    def test_output_limit_is_bounded(self):
        assert OUTPUT_LIMIT > 0
        assert OUTPUT_LIMIT <= 4_194_304

    def test_stdin_ceiling_is_bounded(self):
        assert STDIN_CEILING > 0
        assert STDIN_CEILING <= 1_048_576

    def test_runtime_prefix(self):
        assert RUNTIME_PREFIX == "Microsoft.NETCore.App 8."

    def test_platform_known_paths_returns_list(self):
        paths = platform_known_paths()
        assert isinstance(paths, list)
        assert len(paths) >= 1

    def test_timeouts_bounded(self):
        assert TIMEOUT_PROBE <= 10.0
        assert TIMEOUT_RUNTIME_PROBE <= 2.0


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------

class TestDetector:
    def test_callable_runtime_and_assembly_parses_version(self, project_root, monkeypatch):
        """Callable .NET 8 runtime + assembly → available with parsed version."""
        monkeypatch.setattr("shutil.which", lambda name: "/fake/dotnet")

        class FakeRunner:
            def run(self, provider_id, executable, args, **kwargs):
                if "--list-runtimes" in args:
                    return ProcessResult(
                        0,
                        "Microsoft.NETCore.App 8.0.5 [C:\\Program Files\\dotnet\\shared\\Microsoft.NETCore.App]\n",
                        "",
                        50,
                    )
                if "--probe-json" in args:
                    return ProcessResult(
                        0,
                        json.dumps({
                            "protocol_version": "1.0",
                            "runtime_major": 8,
                            "assembly_loaded": True,
                            "openxml_version": "3.0.1",
                        }),
                        "",
                        50,
                    )
                return ProcessResult(1, "", "", 10)

        detector = DotnetOpenXmlDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is True
        assert evidence.version == "3.0.1"
        assert evidence.path is not None

    def test_executable_absent_returns_unavailable(self, project_root, monkeypatch):
        import shutil as sh
        monkeypatch.setattr(sh, "which", lambda name: None)
        monkeypatch.setattr(Path, "is_file", lambda self: False)
        detector = DotnetOpenXmlDetector(project_root)
        evidence = detector.detect()
        assert evidence.available is False
        assert "candidate" in (evidence.reason or "").lower()

    def test_dotnet_without_net8_runtime_returns_unavailable(self, project_root, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/fake/dotnet")

        class FakeRunner:
            def run(self, *a, **kw):
                return ProcessResult(0, "Microsoft.NETCore.App 7.0.5\n", "", 50)

        detector = DotnetOpenXmlDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "Microsoft.NETCore.App 8" in (evidence.reason or "")

    def test_net8_runtime_but_assembly_not_loaded(self, project_root, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/fake/dotnet")

        class FakeRunner:
            def run(self, provider_id, executable, args, **kwargs):
                if "--list-runtimes" in args:
                    return ProcessResult(0, "Microsoft.NETCore.App 8.0.5\n", "", 50)
                return ProcessResult(
                    0,
                    json.dumps({
                        "protocol_version": "1.0",
                        "runtime_major": 8,
                        "assembly_loaded": False,
                        "openxml_version": None,
                    }),
                    "",
                    50,
                )

        detector = DotnetOpenXmlDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "assembly" in (evidence.reason or "").lower()

    def test_probe_timeout_returns_unavailable(self, project_root, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/fake/dotnet")

        class FakeRunner:
            def run(self, provider_id, executable, args, **kwargs):
                if "--list-runtimes" in args:
                    return ProcessResult(0, "Microsoft.NETCore.App 8.0.5\n", "", 50)
                raise DocumentSkillsError(ErrorCode.PROCESS_TIMEOUT, "probe timed out")

        detector = DotnetOpenXmlDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "timeout" in (evidence.reason or "").lower()

    def test_probe_nonzero_exit_returns_unavailable(self, project_root, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/fake/dotnet")

        class FakeRunner:
            def run(self, provider_id, executable, args, **kwargs):
                if "--list-runtimes" in args:
                    return ProcessResult(0, "Microsoft.NETCore.App 8.0.5\n", "", 50)
                return ProcessResult(1, "", "NuGet restore failed", 50)

        detector = DotnetOpenXmlDetector(project_root)
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False


# ---------------------------------------------------------------------------
# Runner containment tests
# ---------------------------------------------------------------------------

class TestRunnerContainment:
    def test_build_argv_contains_run_project_and_subcommand(self):
        argv = _build_argv(Path("/fake/helper"), "--probe-json")
        assert argv[0] == "run"
        assert "--project" in argv
        assert "--probe-json" in argv

    def test_unknown_subcommand_rejected_before_spawn(self, project_root):
        runner = DotnetOpenXmlRunner(
            project_root, executable="/fake/dotnet",
        )
        with pytest.raises(DocumentSkillsError) as exc:
            runner.run("--malicious-command")
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_oversized_stdin_rejected_before_spawn(self):
        big_payload = {"data": "x" * (STDIN_CEILING + 1)}
        with pytest.raises(DocumentSkillsError) as exc:
            _check_stdin(big_payload)
        assert exc.value.code == ErrorCode.PROVIDER_FAILED
        assert "ceiling" in str(exc.value).lower()

    def test_runner_passes_cwd_inside_project_root(self, project_root):
        captured = {}

        class FakePR:
            def run(self, provider_id, executable, args, **kwargs):
                captured["cwd"] = kwargs.get("cwd")
                captured["args"] = args
                captured["timeout"] = kwargs.get("timeout_seconds")
                captured["output_limit"] = kwargs.get("output_limit")
                captured["stdin_json"] = kwargs.get("stdin_json")
                return ProcessResult(0, "{}", "", 10)

        runner = DotnetOpenXmlRunner(
            project_root, executable="/fake/dotnet", runner=FakePR(),
        )
        runner.run("--probe-json", stdin_payload={"test": True})
        assert captured["cwd"] == project_root.resolve()
        assert isinstance(captured["args"], list)
        assert captured["timeout"] is not None
        assert captured["output_limit"] > 0
        assert captured["stdin_json"] == {"test": True}

    def test_env_sanitized_by_process_runner(self, project_root):
        """The existing ProcessRunner sanitizes env — verify via its allowlist."""
        from document_skills_core.core.process.runner import _ENV_ALLOWLIST
        assert "HOME" not in _ENV_ALLOWLIST
        assert "USERPROFILE" not in _ENV_ALLOWLIST
        assert "PATH" in _ENV_ALLOWLIST
        assert "SystemRoot" in _ENV_ALLOWLIST
        assert "DOTNET_ROOT" in _ENV_ALLOWLIST
        assert "DOTNET_CLI_TELEMETRY_OPTOUT" in _ENV_ALLOWLIST


# ---------------------------------------------------------------------------
# Provider factory tests
# ---------------------------------------------------------------------------

class TestProviderFactory:
    def test_factory_returns_definition_and_provider(self, project_root):
        definition, provider = build_dotnet_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeRunner(),
        )
        assert definition.id == ProviderId.DOTNET_OPENXML
        assert definition.execute is not None
        assert definition.required is False
        assert len(definition.capabilities) > 0

    def test_factory_with_absent_detector_detects_unavailable(self, project_root):
        definition, _ = build_dotnet_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeRunner(),
        )
        evidence = definition.detect()
        assert evidence.available is False

    def test_factory_with_callable_detector_detects_available(self, project_root):
        definition, _ = build_dotnet_provider(
            project_root,
            detector=FakeCallableDetector(version="3.0.1"),
            runner=FakeRunner(),
        )
        evidence = definition.detect()
        assert evidence.available is True
        assert evidence.version == "3.0.1"

    def test_diagnostics_returns_path_and_version(self, project_root):
        _, provider = build_dotnet_provider(
            project_root,
            detector=FakeCallableDetector(version="3.0.1", path="/usr/bin/dotnet"),
            runner=FakeRunner(),
        )
        diag = provider.diagnostics()
        assert diag["path"] == "/usr/bin/dotnet"
        assert diag["version"] == "3.0.1"

    def test_diagnostics_absent_returns_reason(self, project_root):
        _, provider = build_dotnet_provider(
            project_root,
            detector=FakeAbsentDetector(reason="not installed"),
            runner=FakeRunner(),
        )
        diag = provider.diagnostics()
        assert diag["path"] is None
        assert diag["version"] is None
        assert "not installed" in diag["reason"]


# ---------------------------------------------------------------------------
# Consultation matrix: present / absent / crash / timeout
# ---------------------------------------------------------------------------

class TestConsultationMatrix:
    # --- Revisions read ---

    def test_revisions_read_present(self, project_root, fake_docx):
        runner = _make_runner_with_responses({"--revisions-read": _canned_revisions_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        result = provider.try_read_revisions(fake_docx)
        assert result is not None
        assert len(result) == 2
        assert result[0]["id"] == "r1"

    def test_revisions_read_absent(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        assert provider.try_read_revisions(fake_docx) is None

    def test_revisions_read_crash(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeCrashingRunner(),
        )
        assert provider.try_read_revisions(fake_docx) is None

    def test_revisions_read_timeout(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeHangingRunner(),
        )
        assert provider.try_read_revisions(fake_docx) is None

    # --- Revisions accept/reject ---

    def test_revisions_accept_present(self, project_root, fake_docx, tmp_path):
        runner = _make_runner_with_responses({"--revisions-accept": _canned_revisions_accept_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        output = tmp_path / "output.docx"
        result = provider.try_accept_reject_revisions(fake_docx, output, ["r1"], "accept")
        assert result is not None
        assert "r1" in result["matched_ids"]
        assert "r3" in result["unmatched_ids"]

    def test_revisions_accept_absent(self, project_root, fake_docx, tmp_path):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        output = tmp_path / "output.docx"
        assert provider.try_accept_reject_revisions(fake_docx, output, ["r1"], "accept") is None

    def test_revisions_accept_crash(self, project_root, fake_docx, tmp_path):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeCrashingRunner(),
        )
        output = tmp_path / "output.docx"
        assert provider.try_accept_reject_revisions(fake_docx, output, ["r1"], "accept") is None

    # --- Comments read ---

    def test_comments_read_present(self, project_root, fake_docx):
        runner = _make_runner_with_responses({"--comments-read": _canned_comments_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        result = provider.try_read_comments(fake_docx)
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "c1"

    def test_comments_read_absent(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        assert provider.try_read_comments(fake_docx) is None

    def test_comments_read_crash(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeCrashingRunner(),
        )
        assert provider.try_read_comments(fake_docx) is None

    # --- Comments add ---

    def test_comments_add_present(self, project_root, fake_docx, tmp_path):
        runner = _make_runner_with_responses({"--comments-add": _canned_comments_add_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        output = tmp_path / "output.docx"
        result = provider.try_add_comment(fake_docx, output, {"text": "Hello", "author": "Test"})
        assert result == "c99"

    def test_comments_add_absent(self, project_root, fake_docx, tmp_path):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        output = tmp_path / "output.docx"
        assert provider.try_add_comment(fake_docx, output, {"text": "Hello"}) is None

    def test_comments_add_rejects_hyperlink(self, project_root, fake_docx, tmp_path):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeRunner(),
        )
        output = tmp_path / "output.docx"
        # try_add_comment catches the validation error and returns None
        result = provider.try_add_comment(
            fake_docx, output, {"text": "Visit https://evil.com"},
        )
        assert result is None

    # --- Schema validate ---

    def test_schema_validate_present_valid(self, project_root, fake_docx):
        runner = _make_runner_with_responses({"--schema-validate": _canned_schema_valid_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        result = provider.try_validate_schema(fake_docx)
        assert result is not None
        assert result["valid"] is True

    def test_schema_validate_present_invalid(self, project_root, fake_docx):
        runner = _make_runner_with_responses({"--schema-validate": _canned_schema_invalid_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        result = provider.try_validate_schema(fake_docx)
        assert result is not None
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_schema_validate_absent(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        assert provider.try_validate_schema(fake_docx) is None

    def test_schema_validate_crash(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeCrashingRunner(),
        )
        assert provider.try_validate_schema(fake_docx) is None

    # --- Template apply ---

    def test_template_apply_present(self, project_root, fake_docx, tmp_path):
        runner = _make_runner_with_responses({"--template-apply": _canned_template_apply_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        output = tmp_path / "output.docx"
        result = provider.try_apply_template(fake_docx, output, {"title": "Hello"})
        assert result is not None
        assert result["backend"] == "dotnet-openxml"

    def test_template_apply_absent(self, project_root, fake_docx, tmp_path):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        output = tmp_path / "output.docx"
        assert provider.try_apply_template(fake_docx, output, {"title": "Hello"}) is None

    def test_template_apply_crash(self, project_root, fake_docx, tmp_path):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeCrashingRunner(),
        )
        output = tmp_path / "output.docx"
        assert provider.try_apply_template(fake_docx, output, {"title": "Hello"}) is None


# ---------------------------------------------------------------------------
# Provider execute dispatcher tests
# ---------------------------------------------------------------------------

class TestProviderExecuteDispatcher:
    def test_execute_revisions_read_returns_canonical_result(self, project_root, fake_docx):
        runner = _make_runner_with_responses({"--revisions-read": _canned_revisions_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        result = provider.execute("dotnet.docx.revisions-read", {
            "schema_version": "1.0",
            "operation": "dotnet.docx.revisions-read",
            "input": str(fake_docx),
        })
        assert result["schema_version"] == "1.0"
        assert result["status"] == "success"
        assert result["operation"] == "dotnet.docx.revisions-read"
        assert set(result) == {
            "schema_version", "status", "operation", "provider_chain",
            "requested_fidelity", "achieved_fidelity", "degraded",
            "degradations", "artifacts", "validation", "warnings",
            "errors", "diagnostics",
        }

    def test_execute_absent_returns_failed(self, project_root, fake_docx):
        _, provider = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        result = provider.execute("dotnet.docx.revisions-read", {
            "schema_version": "1.0",
            "operation": "dotnet.docx.revisions-read",
            "input": str(fake_docx),
        })
        assert result["status"] == "failed"

    @pytest.mark.parametrize(
        ("response", "status", "gate_outcome"),
        [
            (_canned_schema_valid_response(), "success", "pass"),
            (_canned_schema_invalid_response(), "failed", "fail"),
        ],
    )
    def test_execute_pptx_schema_validation_returns_canonical_gate(
        self,
        project_root,
        tmp_path,
        response,
        status,
        gate_outcome,
    ):
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK bounded schema fixture")
        runner = _make_runner_with_responses({"--schema-validate": response})
        definition, provider = build_dotnet_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )

        result = provider.execute("pptx.validate.schema", {
            "schema_version": "1.0",
            "operation": "pptx.validate.schema",
            "input": str(source),
            "arguments": {},
            "options": {"fidelity": "enhanced"},
        })

        assert result["status"] == status
        assert result["operation"] == "pptx.validate.schema"
        assert result["artifacts"][0]["role"] == "input"
        assert result["validation"]["status"] == gate_outcome
        assert result["validation"]["gates"][0]["id"] == "schema.full"
        assert result["validation"]["gates"][0]["outcome"] == gate_outcome
        assert runner.calls[0]["stdin_payload"]["input_path"].endswith("input.pptx")
        assert any(
            capability.operation == "pptx.validate.schema"
            for capability in definition.capabilities
        )
        assert callable(definition.validators["schema"])


# ---------------------------------------------------------------------------
# find_callable catalog tests
# ---------------------------------------------------------------------------

class TestFindCallable:
    def test_find_callable_true_with_callable_provider(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=FakeRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.DOTNET_OPENXML) is True

    def test_find_callable_false_with_absent_provider(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_dotnet_provider(
            project_root, detector=FakeAbsentDetector(), runner=FakeRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.DOTNET_OPENXML) is False

    def test_find_callable_false_for_unregistered(self, project_root):
        registry = ProviderCatalog()
        assert registry.find_callable(ProviderId.DOTNET_OPENXML) is False

    def test_find_callable_false_with_runtime_only(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_dotnet_provider(
            project_root, detector=FakeRuntimeOnlyDetector(), runner=FakeRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.DOTNET_OPENXML) is False


# ---------------------------------------------------------------------------
# Source preservation tests
# ---------------------------------------------------------------------------

class TestSourcePreservation:
    def test_revisions_read_preserves_source(self, project_root, fake_docx):
        import hashlib
        original_hash = hashlib.sha256(fake_docx.read_bytes()).hexdigest()
        runner = _make_runner_with_responses({"--revisions-read": _canned_revisions_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        provider.try_read_revisions(fake_docx)
        assert hashlib.sha256(fake_docx.read_bytes()).hexdigest() == original_hash

    def test_schema_validate_preserves_source(self, project_root, fake_docx):
        import hashlib
        original_hash = hashlib.sha256(fake_docx.read_bytes()).hexdigest()
        runner = _make_runner_with_responses({"--schema-validate": _canned_schema_valid_response()})
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        provider.try_validate_schema(fake_docx)
        assert hashlib.sha256(fake_docx.read_bytes()).hexdigest() == original_hash


# ---------------------------------------------------------------------------
# No-subprocess-outside-runner test
# ---------------------------------------------------------------------------

class TestNoDirectSubprocess:
    def test_no_subprocess_run_in_dotnet_package(self):
        """Ensure no direct subprocess/os.system/sh invocations in providers/dotnet/."""
        import ast
        import inspect
        from document_skills_core.providers import dotnet as dotnet_pkg

        forbidden = {"subprocess", "os.system", "os.popen"}
        # Check all modules in the dotnet package
        pkg_dir = Path(inspect.getfile(dotnet_pkg)).parent
        for py_file in pkg_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    full = f"{node.value.id}.{node.attr}"
                    if full in forbidden or node.value.id == "subprocess":
                        pytest.fail(f"Forbidden {full} in {py_file.name}")
