import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import document_skills_core.cli as facade
from document_skills_core.cli import execute_request
from document_skills_core.core.capabilities import (
    Capability,
    Provider,
    ProviderId,
    ProviderRegistry,
)
from document_skills_core.core.capabilities.detectors import RuntimeDetectors
from document_skills_core.core.capabilities.reports import build_capabilities
from document_skills_core.core.contracts import (
    DocumentSkillsError,
    ErrorCode,
    SchemaCatalog,
    make_error_result,
)
from document_skills_core.core.process import (
    ProcessPolicy,
    ProcessResult,
    ProcessRunner,
)
from document_skills_core.providers import build_default_registry
from document_skills_core.providers.libreoffice.constants import platform_known_paths
from document_skills_core.providers.libreoffice.quota import hard_quota_capability


# Covers the bounded 132-second dotnet chain plus the other sequential detectors
# and Windows process-startup overhead without inheriting their private constants.
_CORE_REPORT_TIMEOUT_SECONDS = 210


def _detector_state(provider_id: str = "fixture-provider") -> dict:
    return {
        "id": provider_id,
        "available": True,
        "version": "1",
        "reason": None,
        "required": False,
        "path": None,
    }


def test_core_only_optional_absence_is_honest(project_root, monkeypatch):
    real_which = shutil.which

    def hidden_optional(name):
        if name in {"soffice", "libreoffice", "dotnet"}:
            return None
        return real_which(name)

    monkeypatch.setattr(shutil, "which", hidden_optional)
    detectors = RuntimeDetectors(project_root)
    assert detectors.detect_libreoffice_provider().available is False
    assert detectors.detect_openxml_provider().available is False
    assert detectors.detect_node_provider().available is True


def test_docx_core_only_profile_disables_optional_provider_probes(
    project_root,
    monkeypatch,
):
    monkeypatch.setenv("DOCUMENT_SKILLS_PROVIDER_PROFILE", "core-only")
    registry = build_default_registry(project_root)

    for provider_id in ("libreoffice", "dotnet-openxml"):
        state = registry.detect(registry.providers[provider_id])
        assert state["available"] is False
        assert state["path"] is None
        assert state["reason"] == (
            f"{provider_id} is disabled by "
            "DOCUMENT_SKILLS_PROVIDER_PROFILE=core-only"
        )
        assert registry.find_callable(provider_id) is False

    capabilities = build_capabilities(project_root, "docx", registry)
    provider_states = {item["id"]: item for item in capabilities["providers"]}
    assert provider_states["libreoffice"]["available"] is False
    assert provider_states["dotnet-openxml"]["available"] is False
    assert capabilities["validation"] == {
        "package": "available",
        "schema": "unavailable",
        "visual": "unavailable",
    }


def test_optional_descriptors_never_create_callable_operations(project_root):
    registry = build_default_registry(project_root)
    assert {
        "core-python",
        "core-node",
        "libreoffice",
        "dotnet-openxml",
        "html-browser",
    } == set(registry.providers)
    # Existing public format-prefix operations remain unbound to optional providers.
    public_operations = {
        "docx.create",
        "docx.edit.replace-text",
        "docx.inspect.structure",
        "docx.read",
        "docx.template.apply",
        "pdf.create",
        "pdf.edit",
        "pdf.inspect.structure",
        "pdf.read",
        "pdf.rewrite.apply",
        "pptx.create",
        "pptx.create.from-markdown",
        "pptx.create.from-template",
        "pptx.template.inspect",
        "pptx.template.sanitize",
        "pptx.edit",
        "pptx.inspect.structure",
        "pptx.outline.create",
        "pptx.read",
        "xlsx.create",
        "xlsx.edit",
        "xlsx.convert",
        "xlsx.inspect.structure",
        "xlsx.read",
        "xlsx.template.instantiate",
        "xlsx.summary.aggregate",
        "xlsx.pivot.create",
    }
    for operation in public_operations:
        bindings = registry.operations.get(operation, [])
        assert all(
            str(binding.provider_id)
            not in {"libreoffice", "dotnet-openxml", "html-browser"}
            for binding in bindings
        ), f"public operation {operation} is bound to an optional provider"
    html_bindings = registry.operations["pptx.create.from-html"]
    assert [str(binding.provider_id) for binding in html_bindings] == ["html-browser"]
    # The libreoffice provider's internal operations use the libreoffice.* prefix
    # and are consulted enhancement identifiers, NOT public operation routes.
    libreoffice_ops = {
        op for op in registry.operations if op.startswith("libreoffice.")
    }
    assert all(
        registry.providers[str(b.provider_id)].id == ProviderId.LIBREOFFICE
        for op in libreoffice_ops
        for b in registry.operations[op]
    )


def test_node_health_protocol_runs_only_through_python_policy(project_root):
    state = RuntimeDetectors(project_root).detect_node_protocol()
    assert state["available"] is True
    assert state["version"]
    package = json.loads((project_root / "package.json").read_text())
    assert "bin" not in package and "scripts" not in package


def test_node_health_allows_bounded_startup_and_retains_timeout(
    project_root,
    monkeypatch,
):
    detectors = RuntimeDetectors(project_root)
    observed = {}

    def bounded(*_args, **kwargs):
        observed["timeout_seconds"] = kwargs["timeout_seconds"]
        return ProcessResult(
            0,
            json.dumps(
                {
                    "protocol_version": "1.0",
                    "ok": True,
                    "provider": "core-node",
                    "node_version": "v-test",
                }
            ),
            "",
            5_500,
        )

    monkeypatch.setattr(detectors.runner, "run", bounded)
    assert detectors.detect_node_protocol()["available"] is True
    assert observed["timeout_seconds"] == 6.0

    def timeout(*_args, **kwargs):
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "detector timed out",
            details={"timeout_seconds": kwargs["timeout_seconds"]},
        )

    monkeypatch.setattr(detectors.runner, "run", timeout)
    unavailable = detectors.detect_node_protocol()
    assert unavailable["available"] is False
    assert "timed out" in unavailable["reason"]


@pytest.fixture(scope="module")
def core_report_environment():
    project_root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    node = shutil.which("node")
    assert uv is not None
    assert node is not None
    managed_path = os.pathsep.join(
        [str(Path(uv).parent), str(Path(node).parent)]
    )
    core_only_env = os.environ.copy()
    core_only_env["PATH"] = managed_path
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("PATH", managed_path)
        registry = build_default_registry(project_root)
        provider = registry.providers[str(ProviderId.DOTNET_OPENXML)]
        expected_dotnet = registry.detect(provider)
    return uv, core_only_env, expected_dotnet


@pytest.mark.parametrize("skill", ["document-docx", "document-xlsx", "document-pptx", "document-pdf"])
@pytest.mark.parametrize("command", [["doctor", "--json"], ["capabilities", "--json"]])
def test_all_entrypoints_run_core_reports_through_frozen_uv(
    project_root,
    skill,
    command,
    core_report_environment,
):
    uv, core_only_env, expected_dotnet = core_report_environment
    entrypoint = project_root / "skills" / skill / "scripts" / "run.py"
    completed = subprocess.run(
        [
            uv,
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(entrypoint),
            *command,
        ],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        timeout=_CORE_REPORT_TIMEOUT_SECONDS,
        env=core_only_env,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    schema = "doctor-report" if command[0] == "doctor" else "capability-report"
    SchemaCatalog(project_root).validate(schema, report)
    optional = {
        item["id"]: item
        for item in report["providers"]
    }
    libreoffice = optional["libreoffice"]
    known_launchers = [
        Path(path).resolve()
        for path in platform_known_paths()
        if Path(path).is_file()
    ]
    assert libreoffice["required"] is False
    quota_supported = hard_quota_capability().supported
    provider_core_only = (
        core_only_env.get("DOCUMENT_SKILLS_PROVIDER_PROFILE") == "core-only"
    )
    if provider_core_only:
        assert libreoffice["available"] is False
        assert libreoffice["path"] is None
        assert libreoffice["reason"] == (
            "libreoffice is disabled by "
            "DOCUMENT_SKILLS_PROVIDER_PROFILE=core-only"
        )
    elif known_launchers and quota_supported:
        assert libreoffice["available"] is True, libreoffice
        assert libreoffice["reason"] is None
        assert libreoffice["version"]
        assert Path(libreoffice["path"]).resolve() in known_launchers
    else:
        assert libreoffice["available"] is False
        assert libreoffice["reason"]
        assert libreoffice["path"] is None
        if known_launchers:
            assert "hard quota" in libreoffice["reason"].lower()
    dotnet = optional[str(ProviderId.DOTNET_OPENXML)]
    assert dotnet["required"] is False
    for field in ("available", "version", "path", "reason"):
        assert dotnet[field] == expected_dotnet[field]
    if command[0] == "doctor":
        assert report["status"] == "healthy"
    elif skill == "document-xlsx":
        render = next(
            operation
            for operation in report["operations"]
            if operation["operation"] == "xlsx.render"
        )
        assert (
            str(ProviderId.LIBREOFFICE) in render["providers"]
        ) is libreoffice["available"]
        assert render["available"] is libreoffice["available"]


def test_detector_timeout_is_reported_as_unavailable(project_root, monkeypatch):
    detectors = RuntimeDetectors(project_root)

    def timeout(*_args, **_kwargs):
        raise DocumentSkillsError(ErrorCode.PROCESS_TIMEOUT, "detector timed out")

    monkeypatch.setattr(detectors.runner, "run", timeout)
    state = detectors.detect_uv()
    assert state["available"] is False
    assert "timed out" in state["reason"]


def test_process_policy_rejects_executable_and_script_escape(project_root, tmp_path):
    policy = ProcessPolicy(project_root)
    runner = ProcessRunner(policy)
    with pytest.raises(DocumentSkillsError) as executable_error:
        runner.run("fixture", Path(sys.executable), [])
    assert executable_error.value.code == ErrorCode.PROVIDER_FAILED
    outside = tmp_path / "outside.py"
    outside.write_text("print('x')")
    with pytest.raises(DocumentSkillsError) as script_error:
        policy.allow_script("fixture", outside)
    assert script_error.value.code == ErrorCode.PATH_UNSAFE
    allowed = policy.allow_script(
        "fixture", project_root / "tests" / "support" / "provider_fixture.py"
    )
    executable = policy.allow_executable("fixture", sys.executable)
    with pytest.raises(DocumentSkillsError) as argv_error:
        runner.run(
            "fixture",
            executable,
            [str(outside), "ok"],
            script=allowed,
        )
    assert argv_error.value.code == ErrorCode.PATH_UNSAFE


@pytest.mark.skipif(os.name == "nt", reason="POSIX virtualenv executables are symlinks")
def test_process_runner_preserves_allowlisted_executable_symlink(project_root, tmp_path):
    executable_link = tmp_path / "python3"
    executable_link.symlink_to(Path(sys.executable))
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", executable_link)

    result = ProcessRunner(policy).run(
        "fixture",
        executable,
        ["-c", "import json, sys; print(json.dumps({'executable': sys.executable}))"],
    )

    assert result.returncode == 0
    assert Path(result.json()["executable"]) == executable_link


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable identity uses symlinks")
def test_process_runner_rejects_retargeted_executable_symlink(project_root, tmp_path):
    executable_link = tmp_path / "python3"
    executable_link.symlink_to(Path(sys.executable))
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", executable_link)
    replacement = shutil.which("true")
    assert replacement is not None
    executable_link.unlink()
    executable_link.symlink_to(replacement)

    with pytest.raises(DocumentSkillsError) as failure:
        ProcessRunner(policy).run("fixture", executable, [])

    assert failure.value.code == ErrorCode.PROVIDER_FAILED


def test_timeout_crash_and_invalid_json_are_contained(project_root):
    script = project_root / "tests" / "support" / "provider_fixture.py"
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    allowed_script = policy.allow_script("fixture", script)
    runner = ProcessRunner(policy)
    with pytest.raises(DocumentSkillsError) as timeout:
        runner.run(
            "fixture",
            executable,
            [str(allowed_script), "hang"],
            script=allowed_script,
            timeout_seconds=0.05,
        )
    assert timeout.value.code == ErrorCode.PROCESS_TIMEOUT
    crash = runner.run(
        "fixture", executable, [str(allowed_script), "crash"], script=allowed_script
    )
    assert crash.returncode == 7
    invalid = runner.run(
        "fixture", executable, [str(allowed_script), "invalid"], script=allowed_script
    )
    with pytest.raises(DocumentSkillsError) as invalid_error:
        invalid.json()
    assert invalid_error.value.code == ErrorCode.PROVIDER_FAILED
    secret = runner.run(
        "fixture", executable, [str(allowed_script), "secret"], script=allowed_script
    )
    assert "topsecret" not in secret.stderr
    assert "<redacted>" in secret.stderr


def test_runtime_check_cannot_extend_process_deadline(project_root):
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    started = time.monotonic()

    with pytest.raises(DocumentSkillsError) as failure:
        ProcessRunner(policy).run(
            "fixture",
            executable,
            ["-c", "import time; time.sleep(10)"],
            timeout_seconds=0.1,
            runtime_check=lambda: time.sleep(1.0),
        )

    assert failure.value.code == ErrorCode.PROCESS_TIMEOUT
    assert time.monotonic() - started < 0.75


def test_runtime_check_exception_is_typed_and_terminates_descendant(
    project_root,
    tmp_path,
):
    child_pid_path = tmp_path / "runtime-check-child.pid"
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    parent_script = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii')\n"
        "time.sleep(30)\n"
    )

    def reject_after_child_starts() -> None:
        if child_pid_path.is_file():
            raise RuntimeError("private runtime-check failure")

    with pytest.raises(DocumentSkillsError) as failure:
        ProcessRunner(policy).run(
            "fixture",
            executable,
            ["-c", parent_script, str(child_pid_path)],
            timeout_seconds=5.0,
            runtime_check=reject_after_child_starts,
        )

    assert failure.value.code == ErrorCode.PROVIDER_FAILED
    assert failure.value.details["reason_category"] == "runtime_check_failed"
    assert "private runtime-check failure" not in str(failure.value)
    child_pid = int(child_pid_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 2.0
    while _process_is_alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _process_is_alive(child_pid) is False


def test_runtime_check_runs_once_more_after_process_exit(project_root):
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    calls = 0

    def fail_post_exit_check() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            time.sleep(0.1)
            return
        raise RuntimeError("post-exit runtime check failed")

    with pytest.raises(DocumentSkillsError) as failure:
        ProcessRunner(policy).run(
            "fixture",
            executable,
            ["-c", "pass"],
            timeout_seconds=2.0,
            runtime_check=fail_post_exit_check,
        )

    assert failure.value.code == ErrorCode.PROVIDER_FAILED
    assert failure.value.details["reason_category"] == "runtime_check_failed"
    assert calls == 2


def _process_is_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(
            process,
            ctypes.byref(exit_code),
        ):
            return False
        return exit_code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def test_facade_contains_detector_provider_and_invalid_result_failures(
    project_root, monkeypatch, tmp_path, capsys
):
    operation = "fixture.read"
    catalog = SchemaCatalog(project_root)

    def registry_with(*, detect, execute):
        registry = ProviderRegistry()
        registry.register_provider(
            Provider(
                id="fixture-provider",
                version="1",
                detect=detect,
                execute=execute,
                capabilities=[Capability(operation, "core")],
            )
        )
        return registry

    cases = [
        registry_with(
            detect=lambda: (_ for _ in ()).throw(RuntimeError("private detector path")),
            execute=lambda _operation, _request: {},
        ),
        registry_with(
            detect=_detector_state,
            execute=lambda _operation, _request: (_ for _ in ()).throw(
                RuntimeError("private document body")
            ),
        ),
        registry_with(
            detect=_detector_state,
            execute=lambda _operation, _request: {"status": "pretend-success"},
        ),
    ]
    request = {"schema_version": "1.0", "operation": operation}
    for registry in cases:
        monkeypatch.setattr(facade, "build_default_registry", lambda _root, item=registry: item)
        result = execute_request(request, project_root, catalog)
        catalog.validate("operation-result", result)
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED
        rendered = json.dumps(result)
        assert "private detector path" not in rendered
        assert "private document body" not in rendered

    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(facade, "build_default_registry", lambda _root: cases[1])
    assert facade.main("docx", project_root, ["run", "--request", str(request_path)]) == 2
    captured = capsys.readouterr()
    assert len([line for line in captured.out.splitlines() if line.strip()]) == 1
    catalog.validate("operation-result", json.loads(captured.out))
    assert "Traceback" not in captured.err


def test_provider_owned_result_data_is_contained_at_registry_boundary(
    project_root, monkeypatch, tmp_path, capsys
):
    operation = "fixture.read"
    catalog = SchemaCatalog(project_root)
    request = {"schema_version": "1.0", "operation": operation}

    class HostileList(list):
        def __iter__(self):
            raise RuntimeError("private hostile iterator")

    class HostileDict(dict):
        def items(self):
            raise RuntimeError("private hostile mapping")

    def canonical_result():
        return make_error_result(
            operation,
            DocumentSkillsError(ErrorCode.PROVIDER_FAILED, "fixture failure"),
        )

    malformed = []
    wrong_chain = canonical_result()
    wrong_chain["provider_chain"] = 42
    malformed.append(wrong_chain)
    hostile_chain = canonical_result()
    hostile_chain["provider_chain"] = HostileList(["nested-provider"])
    malformed.append(hostile_chain)
    hostile_nested = canonical_result()
    hostile_nested["diagnostics"] = {"payload": object()}
    malformed.append(hostile_nested)
    non_finite = canonical_result()
    non_finite["diagnostics"] = {"value": float("nan")}
    malformed.append(non_finite)
    deep_nested = canonical_result()
    cursor = deep_nested["diagnostics"]
    for index in range(40):
        cursor["nested"] = {"index": index}
        cursor = cursor["nested"]
    malformed.extend([deep_nested, HostileDict(canonical_result())])

    for provider_result in malformed:
        registry = ProviderRegistry()
        registry.register_provider(
            Provider(
                id="hostile-provider",
                version="1",
                detect=lambda: _detector_state("hostile-provider"),
                execute=lambda _operation, _request, item=provider_result: item,
                capabilities=[Capability(operation, "core")],
            )
        )
        monkeypatch.setattr(facade, "build_default_registry", lambda _root, item=registry: item)
        result = execute_request(request, project_root, catalog)
        catalog.validate("operation-result", result)
        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED
        rendered = json.dumps(result)
        assert "private hostile" not in rendered

    request_path = tmp_path / "hostile-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    registry = ProviderRegistry()
    registry.register_provider(
        Provider(
            id="hostile-provider",
            version="1",
            detect=lambda: _detector_state("hostile-provider"),
            execute=lambda _operation, _request: wrong_chain,
            capabilities=[Capability(operation, "core")],
        )
    )
    monkeypatch.setattr(facade, "build_default_registry", lambda _root: registry)
    assert facade.main("docx", project_root, ["run", "--request", str(request_path)]) == 2
    captured = capsys.readouterr()
    assert len([line for line in captured.out.splitlines() if line.strip()]) == 1
    public_result = json.loads(captured.out)
    catalog.validate("operation-result", public_result)
    assert public_result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "provider_value",
    [
        10**5000,
        "x" * 1_048_577,
        "\ud800",
        (item for item in range(1)),
        {"nested": (1, 2)},
    ],
    ids=["huge-integer", "huge-string", "surrogate", "generator", "tuple"],
)
def test_provider_json_limits_fail_at_provider_boundary(
    project_root, monkeypatch, provider_value
):
    operation = "fixture.read"
    catalog = SchemaCatalog(project_root)
    provider_result = make_error_result(
        operation,
        DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "fixture failure"),
    )
    provider_result["diagnostics"] = {"provider_value": provider_value}
    registry = ProviderRegistry()
    registry.register_provider(
        Provider(
            id="bounded-provider",
            version="1",
            detect=lambda: _detector_state("bounded-provider"),
            execute=lambda _operation, _request: provider_result,
            capabilities=[Capability(operation, "core")],
        )
    )
    monkeypatch.setattr(facade, "build_default_registry", lambda _root: registry)
    result = execute_request(
        {"schema_version": "1.0", "operation": operation},
        project_root,
        catalog,
    )
    catalog.validate("operation-result", result)
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED


@pytest.mark.parametrize(
    ("expression", "expected_code", "expected_value"),
    [
        ("'portable \\U0001f642'", "DS_VALIDATION_FAILED", "portable \U0001f642"),
        ("10 ** 5000", "DS_PROVIDER_FAILED", None),
    ],
)
def test_public_json_is_one_complete_line_under_non_utf_console_encoding(
    project_root, tmp_path, expression, expected_code, expected_value
):
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"schema_version": "1.0", "operation": "fixture.read"}),
        encoding="utf-8",
    )
    script = tmp_path / "provider_console_case.py"
    script.write_text(
        f"""
from pathlib import Path
import document_skills_core.cli as facade
from document_skills_core.core.capabilities import Capability, Provider, ProviderRegistry
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode, make_error_result

root = Path({str(project_root)!r})
request_path = Path({str(request)!r})
result = make_error_result(
    "fixture.read",
    DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "fixture failure"),
)
result["diagnostics"] = {{"provider_value": {expression}}}
registry = ProviderRegistry()
registry.register_provider(Provider(
    id="console-provider",
    version="1",
    detect=lambda: {{
        "id": "console-provider",
        "available": True,
        "version": "1",
        "reason": None,
        "required": False,
        "path": None,
    }},
    execute=lambda _operation, _request: result,
    capabilities=[Capability("fixture.read", "core")],
))
facade.build_default_registry = lambda _root: registry
raise SystemExit(facade.main("docx", root, ["run", "--request", str(request_path)]))
""".lstrip(),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252:strict"
    environment["PYTHONPATH"] = str(project_root / "src")
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=15,
    )
    assert completed.returncode == 2
    assert completed.stderr == b""
    assert completed.stdout.count(b"\n") == 1
    payload = json.loads(completed.stdout)
    assert payload["errors"][0]["code"] == expected_code
    if expected_value is not None:
        assert payload["diagnostics"]["provider_value"] == expected_value


@pytest.mark.parametrize("command", ["doctor", "capabilities", "run"])
@pytest.mark.parametrize(
    "mode",
    ["object", "huge-int", "exception", "hostile-mapping", "surrogate", "unicode"],
)
def test_public_commands_contain_hostile_detector_records(
    project_root, tmp_path, command, mode
):
    request = tmp_path / f"{command}-{mode}.json"
    request.write_text(
        json.dumps({"schema_version": "1.0", "operation": "fixture.read"}),
        encoding="utf-8",
    )
    script = tmp_path / f"hostile_detector_{command}_{mode}.py"
    script.write_text(
        f"""
from pathlib import Path
import document_skills_core.cli as facade
import document_skills_core.core.capabilities.reports as reports
from document_skills_core.core.capabilities import Capability, Provider, ProviderRegistry
from document_skills_core.core.capabilities.detectors import RuntimeDetectors
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode, make_error_result

root = Path({str(project_root)!r})
mode = {mode!r}

class HostileMapping(dict):
    def get(self, *_args, **_kwargs):
        raise RuntimeError("untrusted get")
    def items(self):
        raise RuntimeError("untrusted items")

def detector():
    if mode == "exception":
        raise RuntimeError("untrusted exception")
    value = {{
        "id": "hostile-provider",
        "available": True,
        "version": "portable \U0001f642",
        "reason": None,
        "required": False,
        "path": None,
    }}
    if mode == "object":
        value["version"] = object()
    elif mode == "huge-int":
        value["version"] = 10 ** 5000
    elif mode == "hostile-mapping":
        value = HostileMapping(value)
    elif mode == "surrogate":
        value["version"] = "\\ud800"
    return value

registry = ProviderRegistry()
registry.register_provider(Provider(
    id="hostile-provider",
    version="1",
    detect=detector,
    execute=lambda operation, _request: make_error_result(
        operation,
        DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "fixture failure"),
    ),
    capabilities=[Capability("fixture.read", "core")],
))
facade.build_default_registry = lambda _root: registry

if {command!r} == "doctor":
    class HostileDetectors:
        def __init__(self, detector_root):
            self.real = RuntimeDetectors(detector_root)
        def all(self):
            return [self.real._safe_detector("hostile-provider", False, detector)]
    reports.RuntimeDetectors = HostileDetectors
    argv = ["doctor", "--json"]
elif {command!r} == "capabilities":
    argv = ["capabilities", "--json"]
else:
    argv = ["run", "--request", {str(request)!r}]
raise SystemExit(facade.main("docx", root, argv))
""".lstrip(),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252:strict"
    environment["PYTHONPATH"] = str(project_root / "src")
    uv = shutil.which("uv")
    assert uv is not None
    completed = subprocess.run(
        [
            uv,
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(script),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=30,
    )
    assert completed.stdout.count(b"\n") == 1, completed
    assert completed.stderr == b""
    payload = json.loads(completed.stdout)
    schema = {
        "doctor": "doctor-report",
        "capabilities": "capability-report",
        "run": "operation-result",
    }[command]
    SchemaCatalog(project_root).validate(schema, payload)
    if command == "run":
        expected = "DS_VALIDATION_FAILED" if mode == "unicode" else "DS_PROVIDER_FAILED"
        assert payload["errors"][0]["code"] == expected
    else:
        records = (
            payload["runtime"]
            if command == "doctor"
            else payload["providers"]
        )
        assert records
        if command == "doctor":
            assert all(type(item["available"]) is bool for item in records)
        else:
            provider = records[0]
            assert provider["available"] is (mode == "unicode")
            if mode != "unicode":
                assert len(provider["reason"].encode("utf-8")) <= 512


def test_detected_executables_do_not_claim_unimplemented_validators(project_root):
    registry = ProviderRegistry()
    registry.register_provider(
        Provider(
            id="present-only",
            version="1",
            detect=lambda: {
                "id": "present-only",
                "available": True,
                "version": "1",
                "reason": None,
                "required": False,
                "path": "present",
            },
            validators={"schema": None},
        )
    )
    report = build_capabilities(project_root, "docx", registry)
    assert report["validation"] == {
        "package": "available",
        "schema": "unavailable",
        "visual": "unavailable",
    }


def test_dotnet_openxml_requires_net8_and_verified_local_assembly(
    tmp_path, monkeypatch
):
    provider_root = tmp_path / "runtime" / "dotnet" / "openxml"
    provider_root.mkdir(parents=True)
    (provider_root / "OpenXmlProbe.dll").write_bytes(b"probe")
    (provider_root / "DocumentFormat.OpenXml.dll").write_bytes(b"assembly")
    detectors = RuntimeDetectors(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: sys.executable if name == "dotnet" else None)
    monkeypatch.setattr(
        detectors,
        "detect_dotnet_runtime",
        lambda: {
            "id": "dotnet-runtime",
            "available": True,
            "version": "Microsoft.NETCore.App 8.0.0",
            "reason": None,
            "required": False,
            "path": "dotnet",
        },
    )
    monkeypatch.setattr(
        detectors.runner,
        "run",
        lambda *_args, **_kwargs: ProcessResult(
            0,
            json.dumps(
                {
                    "protocol_version": "1.0",
                    "runtime_major": 8,
                    "openxml_version": "3.3.0",
                    "assembly_loaded": True,
                }
            ),
            "",
            1,
        ),
    )
    assert detectors.detect_dotnet_openxml()["available"] is True
    monkeypatch.setattr(
        detectors.runner,
        "run",
        lambda *_args, **_kwargs: ProcessResult(
            0,
            json.dumps(
                {
                    "protocol_version": "1.0",
                    "runtime_major": 10,
                    "openxml_version": "3.3.0",
                    "assembly_loaded": True,
                }
            ),
            "",
            1,
        ),
    )
    assert detectors.detect_dotnet_openxml()["available"] is False


def test_dotnet_capability_probes_use_private_cli_home(tmp_path, monkeypatch):
    provider_root = tmp_path / "runtime" / "dotnet" / "openxml"
    provider_root.mkdir(parents=True)
    (provider_root / "OpenXmlProbe.dll").write_bytes(b"probe")
    (provider_root / "DocumentFormat.OpenXml.dll").write_bytes(b"assembly")
    detectors = RuntimeDetectors(tmp_path)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: sys.executable if name == "dotnet" else None,
    )
    calls = []

    def capture_run(*args, **kwargs):
        calls.append((args, kwargs))
        if "--list-runtimes" in args[2]:
            return ProcessResult(0, "Microsoft.NETCore.App 8.0.0\n", "", 1)
        return ProcessResult(
            0,
            json.dumps(
                {
                    "protocol_version": "1.0",
                    "runtime_major": 8,
                    "openxml_version": "3.0.0",
                    "assembly_loaded": True,
                }
            ),
            "",
            1,
        )

    monkeypatch.setattr(detectors.runner, "run", capture_run)

    assert detectors.detect_dotnet_runtime()["available"] is True
    assert detectors.detect_dotnet_openxml()["available"] is True
    assert len(calls) == 3
    assert all(
        call[1]["private_environment"] == ("DOTNET_CLI_HOME",)
        for call in calls
    )


@pytest.mark.parametrize("mode", ["overflow_stdout", "overflow_stderr"])
def test_process_output_is_bounded_while_streaming(project_root, mode):
    script = project_root / "tests" / "support" / "provider_fixture.py"
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    allowed_script = policy.allow_script("fixture", script)
    runner = ProcessRunner(policy)
    started = time.monotonic()
    with pytest.raises(DocumentSkillsError) as failure:
        runner.run(
            "fixture",
            executable,
            [str(allowed_script), mode],
            script=allowed_script,
            timeout_seconds=5,
            output_limit=4096,
        )
    assert failure.value.code == ErrorCode.PROVIDER_FAILED
    assert time.monotonic() - started < 3


def test_process_tree_closes_descendant_inherited_handles(project_root):
    script = project_root / "tests" / "support" / "provider_fixture.py"
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    allowed_script = policy.allow_script("fixture", script)
    started = time.monotonic()
    result = ProcessRunner(policy).run(
        "fixture",
        executable,
        [str(allowed_script), "descendant_handles"],
        script=allowed_script,
        timeout_seconds=5,
    )
    assert result.returncode == 0
    assert result.json()["ok"] is True
    assert time.monotonic() - started < 3
