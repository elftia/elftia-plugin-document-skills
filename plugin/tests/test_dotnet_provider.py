"""dotnet-openxml enhancement provider tests — mock-injected present/absent/crash/timeout.

Real .NET is NOT required. Tests inject fake detectors and runners
to exercise the wiring, honesty, and containment.

Module provenance: original Elftia-authored clean-room implementation.
"""

import json
from pathlib import Path
import sys

import pytest

from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.temp_roots import managed_temp_root
from document_skills_core.core.process import ProcessPolicy, ProcessResult, ProcessRunner
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
from document_skills_core.providers.dotnet.runner import (
    DotnetOpenXmlRunner,
    _build_argv,
    _check_stdin,
    _exec_argv,
)


def _msbuild_property_path(argv: list[str], property_name: str) -> Path:
    prefix = f"--property:{property_name}="
    value = next(item.removeprefix(prefix) for item in argv if item.startswith(prefix))
    return Path(value.rstrip("/\\")).resolve()


def _assert_private_build_paths(argv: list[str]) -> None:
    build_paths = {
        _msbuild_property_path(argv, "BaseIntermediateOutputPath"),
        _msbuild_property_path(argv, "BaseOutputPath"),
    }
    assert all(path.is_relative_to(managed_temp_root()) for path in build_paths)
    helper_root = Path(__file__).resolve().parents[1] / (
        "src/document_skills_core/providers/dotnet/helper"
    )
    assert all(not path.is_relative_to(helper_root) for path in build_paths)


def _assert_private_exec_path(argv: list[str]) -> None:
    assert argv[0] == "exec"
    assembly = Path(argv[1]).resolve()
    assert assembly.name == "OpenXmlHelper.dll"
    assert assembly.is_relative_to(managed_temp_root())
    helper_root = Path(__file__).resolve().parents[1] / (
        "src/document_skills_core/providers/dotnet/helper"
    )
    assert not assembly.is_relative_to(helper_root)


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
            {
                "id": "r1", "type": "insertion", "author": "Alice",
                "date": "2026-01-01T00:00:00Z",
                "location": {"story": "body", "paragraph_index": 0, "table_index": None},
            },
            {
                "id": "r2", "type": "deletion", "author": "Bob",
                "date": "2026-01-02T00:00:00Z",
                "location": {"story": "body", "paragraph_index": 1, "table_index": 0},
            },
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
        assert "--comments-resolve" in ACCEPTED_SUBCOMMANDS

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
        assert 10.0 < TIMEOUT_PROBE <= 30.0
        assert TIMEOUT_RUNTIME_PROBE <= 2.0


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------

class TestDetector:
    def test_assembly_probe_supplies_an_empty_json_request(self, project_root, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/fake/dotnet")
        captured = {}

        class FakeRunner:
            def run(self, provider_id, executable, args, **kwargs):
                if "--list-runtimes" in args:
                    return ProcessResult(
                        0,
                        "Microsoft.NETCore.App 8.0.5 [/fake/dotnet/shared]\n",
                        "",
                        10,
                    )
                captured.setdefault("calls", []).append(args)
                if args[0] == "build":
                    return ProcessResult(0, "", "", 10)
                captured["stdin_json"] = kwargs.get("stdin_json")
                return ProcessResult(
                    0,
                    json.dumps(
                        {
                            "protocol_version": "1.0",
                            "runtime_major": 8,
                            "assembly_loaded": True,
                            "openxml_version": "3.0.0",
                        }
                    ),
                    "",
                    10,
                )

        detector = DotnetOpenXmlDetector(project_root)
        detector._runner = FakeRunner()

        assert detector.detect().available is True
        assert captured["stdin_json"] == {}
        _assert_private_build_paths(captured["calls"][0])
        _assert_private_exec_path(captured["calls"][1])

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
                if args[0] == "build":
                    return ProcessResult(0, "", "", 10)
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
    def test_helper_argv_binds_restore_to_inert_config_and_global_cache(
        self, tmp_path, monkeypatch
    ):
        packages = tmp_path / "nuget-packages"
        monkeypatch.setenv("NUGET_PACKAGES", str(packages))

        def unavailable_home():
            raise RuntimeError("worker home is intentionally unavailable")

        monkeypatch.setattr(Path, "home", unavailable_home)
        helper = tmp_path / "helper"
        build_root = tmp_path / "operation" / "dotnet-build"

        argv = _build_argv(helper, build_root)

        assert (
            f"--property:RestoreConfigFile={helper.resolve() / 'NuGet.Config'}"
            in argv
        )
        assert f"--property:RestorePackagesPath={packages.resolve()}" in argv
        assert _msbuild_property_path(
            argv, "BaseIntermediateOutputPath"
        ) == (build_root.resolve() / "obj")
        assert _msbuild_property_path(
            argv, "BaseOutputPath"
        ) == (build_root.resolve() / "bin")

    def test_build_and_exec_argv_use_private_assembly(self):
        argv = _build_argv(
            Path("/fake/helper"),
            Path("/private/operation/dotnet-build"),
        )
        assert argv[0] == "build"
        assert argv[1].endswith("OpenXmlHelper.csproj")
        exec_argv = _exec_argv(
            Path("/private/operation/dotnet-build"),
            "--probe-json",
        )
        assert exec_argv[0] == "exec"
        assert exec_argv[1].endswith("OpenXmlHelper.dll")
        assert exec_argv[2] == "--probe-json"

    def test_unknown_subcommand_rejected_before_spawn(self, project_root):
        runner = DotnetOpenXmlRunner(
            project_root, executable=sys.executable,
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

    def test_runner_uses_private_managed_cwd(self, project_root):
        captured = {"calls": []}

        class FakePR:
            def run(self, provider_id, executable, args, **kwargs):
                captured["calls"].append((args, kwargs))
                if args[0] == "build":
                    return ProcessResult(0, "", "", 10)
                captured["fixed_environment"] = kwargs.get("fixed_environment")
                return ProcessResult(0, "{}", "", 10)

        runner = DotnetOpenXmlRunner(
            project_root, executable="/fake/dotnet", runner=FakePR(),
        )
        runner.run("--probe-json", stdin_payload={"test": True})
        assert len(captured["calls"]) == 2
        build_args, build_kwargs = captured["calls"][0]
        exec_args, exec_kwargs = captured["calls"][1]
        build_cwd = build_kwargs["cwd"].resolve()
        exec_cwd = exec_kwargs["cwd"].resolve()
        assert build_cwd == exec_cwd
        assert build_cwd.is_relative_to(managed_temp_root())
        assert not build_cwd.is_relative_to(project_root.resolve())
        assert build_kwargs["timeout_seconds"] is not None
        assert exec_kwargs["timeout_seconds"] > 0
        assert exec_kwargs["output_limit"] > 0
        assert exec_kwargs["stdin_json"] == {"test": True}
        _assert_private_build_paths(build_args)
        _assert_private_exec_path(exec_args)
        fixed_environment = captured["fixed_environment"]
        assert set(fixed_environment) == {
            "APPDATA",
            "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH",
            "DOTNET_CLI_HOME",
            "DOTNET_CLI_TELEMETRY_OPTOUT",
            "DOTNET_GENERATE_ASPNET_CERTIFICATE",
            "DOTNET_NOLOGO",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE",
            "LOCALAPPDATA",
            "NUGET_HTTP_CACHE_PATH",
            "NUGET_PLUGINS_CACHE_PATH",
            "USERPROFILE",
        }
        assert fixed_environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] == "0"
        assert fixed_environment["DOTNET_CLI_TELEMETRY_OPTOUT"] == "1"
        assert fixed_environment["DOTNET_GENERATE_ASPNET_CERTIFICATE"] == "false"
        assert fixed_environment["DOTNET_NOLOGO"] == "1"
        assert fixed_environment["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] == "1"
        private_profile = Path(fixed_environment["USERPROFILE"])
        assert Path(fixed_environment["APPDATA"]) == (
            private_profile / "AppData" / "Roaming"
        )
        assert Path(fixed_environment["LOCALAPPDATA"]) == (
            private_profile / "AppData" / "Local"
        )
        assert all(
            Path(value).resolve().is_relative_to(managed_temp_root())
            for key, value in fixed_environment.items()
            if key
            in {
                "APPDATA",
                "DOTNET_CLI_HOME",
                "LOCALAPPDATA",
                "NUGET_HTTP_CACHE_PATH",
                "NUGET_PLUGINS_CACHE_PATH",
                "USERPROFILE",
            }
        )

    def test_env_sanitized_by_process_runner(self, project_root):
        """The existing ProcessRunner sanitizes env — verify via its allowlist."""
        from document_skills_core.core.process.runner import _ENV_ALLOWLIST
        assert "HOME" not in _ENV_ALLOWLIST
        assert "USERPROFILE" not in _ENV_ALLOWLIST
        assert "PATH" in _ENV_ALLOWLIST
        assert "SystemRoot" in _ENV_ALLOWLIST
        assert "DOTNET_ROOT" in _ENV_ALLOWLIST
        assert "DOTNET_CLI_TELEMETRY_OPTOUT" in _ENV_ALLOWLIST
        assert "ProgramFiles" in _ENV_ALLOWLIST
        assert "ProgramData" in _ENV_ALLOWLIST

    def test_minimal_environment_derives_only_the_nuget_package_cache(
        self, tmp_path, monkeypatch
    ):
        packages = tmp_path / ".nuget" / "packages"
        packages.mkdir(parents=True)
        monkeypatch.delenv("NUGET_PACKAGES", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        environment = ProcessRunner._minimal_environment()

        assert environment["NUGET_PACKAGES"] == str(packages.resolve())
        assert "HOME" not in environment
        assert "USERPROFILE" not in environment

    def test_process_runner_accepts_only_the_path_pollution_opt_out(self):
        environment = ProcessRunner._minimal_environment(
            {"DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0"}
        )
        assert environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] == "0"

        with pytest.raises(DocumentSkillsError) as captured:
            ProcessRunner._minimal_environment(
                {"DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "1"}
            )
        assert captured.value.code == ErrorCode.PROVIDER_FAILED
        assert captured.value.details == {
            "environment_key": "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"
        }


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

    def test_revisions_read_passes_bounded_filters_scope_and_ids(
        self, project_root, fake_docx,
    ):
        runner = _make_runner_with_responses(
            {"--revisions-read": _canned_revisions_response()}
        )
        _, provider = build_dotnet_provider(
            project_root, detector=FakeCallableDetector(), runner=runner,
        )
        filters = {"authors": ["Alice"], "types": ["insertion"]}
        scope = {"story": "body", "range": "paragraph", "paragraph_index": 0}
        result = provider.read_revisions(
            fake_docx,
            5,
            filters=filters,
            scope=scope,
            revision_ids=["r1"],
        )

        assert len(result) == 2
        payload = runner.calls[0]["stdin_payload"]
        assert payload["max_revisions"] == 5
        assert payload["filters"] == filters
        assert payload["scope"] == scope
        assert payload["revision_ids"] == ["r1"]

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
