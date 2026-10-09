"""Executable authorization stays bound to the object that was approved."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import replace

import document_skills_core.core.process.executable as executable_module
import document_skills_core.core.process.runner as runner_module
from document_skills_core.core.process.darwin_spawn import _launch_environment
import pytest
from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner
from document_skills_core.core.process.windows_handles import WindowsFileSnapshot
from document_skills_core.providers.dotnet import build_dotnet_provider
from document_skills_core.providers.dotnet.detector import DotnetOpenXmlDetector
from document_skills_core.providers.dotnet.runner import DotnetOpenXmlRunner
from tools.audit_python import audit_python_source

_AUTHORIZED_OUTPUT = "AUTHORIZED-LAUNCH-OBJECT"


def test_darwin_python_environment_preserves_only_the_authorized_alias(tmp_path):
    identity = executable_module.capture_executable_identity(Path(sys.executable))
    alias = tmp_path / "authorized-python"
    lease = executable_module.ExecutableLaunchLease(
        launch_path=alias, popen_executable=str(identity.resolved_path),
        pass_fds=(), identity=identity,
    )
    source = {"PATH": "fixture-path"}
    assert _launch_environment(lease, source) == {
        "PATH": "fixture-path", "PYTHONEXECUTABLE": str(alias),
    }
    assert source == {"PATH": "fixture-path"}

    lease.identity = replace(identity, resolved_path=tmp_path / "other-native-image")
    assert _launch_environment(lease, source) == source


def test_same_path_replacement_cannot_be_reauthorized(
    project_root: Path,
    tmp_path: Path,
) -> None:
    target, replacement, _args = _native_launch_fixture(tmp_path)
    policy = ProcessPolicy(project_root)
    policy.allow_executable("identity-fixture", target)
    _replace_path(target, replacement)

    with pytest.raises(DocumentSkillsError, match="identity"):
        policy.allow_executable("identity-fixture", target)


def test_same_path_replacement_after_authorization_is_rejected(
    project_root: Path,
    tmp_path: Path,
) -> None:
    target, replacement, args = _native_launch_fixture(tmp_path)
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("identity-fixture", target)
    _replace_path(target, replacement)

    with pytest.raises(DocumentSkillsError, match="identity"):
        ProcessRunner(policy).run("identity-fixture", executable, args)


def test_final_launch_window_executes_the_authorized_object(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, replacement, args = _native_launch_fixture(tmp_path)
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("identity-fixture", target)
    spawn_module, spawn_name, real_popen = _spawn_target()
    race = {"attempted": False, "replacement_succeeded": False}

    def replacing_popen(*popen_args, **popen_kwargs):
        race["attempted"] = True
        try:
            _replace_path(target, replacement)
        except OSError:
            pass
        else:
            race["replacement_succeeded"] = True
        return real_popen(*popen_args, **popen_kwargs)

    monkeypatch.setattr(spawn_module, spawn_name, replacing_popen)
    result = ProcessRunner(policy).run("identity-fixture", executable, args)

    assert race["attempted"] is True
    assert result.returncode == 0
    assert _AUTHORIZED_OUTPUT in result.stdout
    if os.name == "nt":
        assert race["replacement_succeeded"] is False
    else:
        assert race["replacement_succeeded"] is True


def test_atomic_spawn_failure_is_typed_and_releases_the_launch_lease(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, replacement, args = _native_launch_fixture(tmp_path)
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("identity-fixture", target)

    def failed_spawn(*_args, **_kwargs):
        raise OSError("private spawn failure details")

    spawn_module, spawn_name, _real_spawn = _spawn_target()
    monkeypatch.setattr(spawn_module, spawn_name, failed_spawn)
    with pytest.raises(DocumentSkillsError) as failure:
        ProcessRunner(policy).run("identity-fixture", executable, args)

    assert failure.value.code == ErrorCode.RUNTIME_UNAVAILABLE
    assert failure.value.details == {
        "provider": "identity-fixture",
        "reason_category": "atomic_launch_failed",
        "exception_class": "OSError",
    }
    assert "private spawn failure details" not in str(failure.value)
    _replace_path(target, replacement)


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse canonicalization")
def test_windows_directory_reparse_alias_launches_the_canonical_object(
    project_root: Path,
    tmp_path: Path,
) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    target, _replacement, args = _native_launch_fixture(real_directory)
    alias_directory = tmp_path / "alias"
    try:
        alias_directory.symlink_to(real_directory, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {type(error).__name__}")
    alias_target = alias_directory / target.name
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("identity-fixture", alias_target)

    result = ProcessRunner(policy).run("identity-fixture", executable, args)

    assert result.returncode == 0
    assert _AUTHORIZED_OUTPUT in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows share-mode enforcement")
def test_windows_launch_lease_blocks_hardlink_alias_writes(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, _replacement, args = _native_launch_fixture(tmp_path)
    hardlink = tmp_path / "authorized-hardlink.exe"
    os.link(target, hardlink)
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("identity-fixture", target)
    real_popen = subprocess.Popen
    write_was_blocked = False

    def writing_popen(*popen_args, **popen_kwargs):
        nonlocal write_was_blocked
        try:
            with hardlink.open("r+b") as stream:
                stream.write(b"MALICIOUS")
        except OSError:
            write_was_blocked = True
        return real_popen(*popen_args, **popen_kwargs)

    monkeypatch.setattr(subprocess, "Popen", writing_popen)
    result = ProcessRunner(policy).run("identity-fixture", executable, args)

    assert write_was_blocked is True
    assert result.returncode == 0
    assert _AUTHORIZED_OUTPUT in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows handle ownership")
@pytest.mark.parametrize(
    "failure_stage",
    ["directory_create", "directory_attributes", "file_create"],
)
def test_windows_partial_launch_pins_are_closed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    created: list[int] = []
    closed: list[int] = []
    attribute_calls = 0
    snapshot = WindowsFileSnapshot(
        object_identity=(7, b"identity".ljust(16, b"\0")),
        size=128,
        mtime_ns=11,
        ctime_ns=12,
    )

    def create_handle(*_args, **_kwargs) -> int:
        call = len(created) + 1
        if failure_stage == "directory_create" and call == 3:
            raise OSError("directory create failed")
        if failure_stage == "file_create" and call == 4:
            raise OSError("file create failed")
        handle = 100 + call
        created.append(handle)
        return handle

    def handle_attributes(_handle: int) -> int:
        nonlocal attribute_calls
        attribute_calls += 1
        if failure_stage == "directory_attributes" and attribute_calls == 2:
            raise OSError("directory attributes failed")
        if attribute_calls == 1:
            return 0
        return executable_module.FILE_ATTRIBUTE_DIRECTORY

    monkeypatch.setattr(executable_module, "require_local_fixed_path", lambda _path: None)
    monkeypatch.setattr(executable_module, "create_handle", create_handle)
    monkeypatch.setattr(executable_module, "handle_attributes", handle_attributes)
    monkeypatch.setattr(
        executable_module,
        "parent_components",
        lambda _path: (Path("C:/one"), Path("C:/one/two")),
    )
    monkeypatch.setattr(
        executable_module,
        "final_path",
        lambda _handle: Path("C:/one/two/tool.exe"),
    )
    monkeypatch.setattr(executable_module, "file_snapshot", lambda _handle: snapshot)
    monkeypatch.setattr(
        executable_module,
        "hash_handle",
        lambda _handle: ("a" * 64, b"MZ"),
    )
    monkeypatch.setattr(executable_module, "close_handle", closed.append)

    with pytest.raises(DocumentSkillsError):
        executable_module.capture_executable_identity(tmp_path / "tool.exe")

    assert sorted(closed) == sorted(created)
    assert len(closed) == len(set(closed))


def test_dotnet_factory_shares_the_probe_authorization_policy(
    project_root: Path,
) -> None:
    _definition, provider = build_dotnet_provider(project_root)

    assert provider.detector._policy is provider.runner._policy
    assert provider.detector._runner is provider.runner._runner


def test_dotnet_operation_binding_rejects_post_probe_replacement(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, replacement, _args = _native_launch_fixture(tmp_path)
    policy = ProcessPolicy(project_root)
    process_runner = ProcessRunner(policy)
    detector = DotnetOpenXmlDetector(
        project_root,
        runner=process_runner,
        policy=policy,
    )
    runner = DotnetOpenXmlRunner(
        project_root,
        runner=process_runner,
        policy=policy,
    )

    def probed() -> DetectionEvidence:
        policy.allow_executable("dotnet-openxml", target)
        return DetectionEvidence(True, version="3.3.0", path=str(target))

    def replace_then_bind(path: str | Path) -> None:
        _replace_path(target, replacement)
        runner.bind_authorized_executable(path)

    monkeypatch.setattr(detector, "detect", probed)
    evidence = detector.detect_and_authorize(replace_then_bind)

    assert evidence.available is False
    assert "identity" in (evidence.reason or "").lower()


@pytest.mark.parametrize(
    "relative",
    [
        "src/document_skills_core/core/process/executable.py",
        "src/document_skills_core/core/process/runner.py",
        "src/document_skills_core/core/process/windows_handles.py",
        "src/document_skills_core/providers/dotnet/detector.py",
        "src/document_skills_core/providers/dotnet/runner.py",
        "src/document_skills_core/providers/dotnet/service.py",
        "src/document_skills_core/providers/libreoffice/detector.py",
    ],
)
def test_executable_launch_policy_passes_runtime_source_audit(
    project_root: Path,
    relative: str,
) -> None:
    audit_python_source(
        relative,
        (project_root / relative).read_text(encoding="utf-8"),
    )


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux proc-fd launch is the supported POSIX capability",
)
def test_posix_script_launcher_is_truthfully_unavailable(
    project_root: Path,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "script-ran"
    script = tmp_path / "launcher"
    script.write_text(
        f"#!/bin/sh\nprintf ran > '{marker.as_posix()}'\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("script-fixture", script)

    with pytest.raises(DocumentSkillsError, match="native executable"):
        ProcessRunner(policy).run("script-fixture", executable, [])

    assert marker.exists() is False


def _spawn_target():
    if sys.platform == "darwin":
        return runner_module, "spawn_authorized_process", runner_module.spawn_authorized_process
    return subprocess, "Popen", subprocess.Popen


def _native_launch_fixture(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    target = tmp_path / ("authorized.exe" if os.name == "nt" else "authorized")
    replacement = tmp_path / (
        "replacement.exe" if os.name == "nt" else "replacement"
    )
    if os.name == "nt":
        cmd = shutil.which("cmd.exe")
        where = shutil.which("where.exe")
        assert cmd is not None
        assert where is not None
        shutil.copy2(cmd, target)
        shutil.copy2(where, replacement)
        return target, replacement, ["/d", "/s", "/c", f"echo {_AUTHORIZED_OUTPUT}"]
    target.symlink_to(Path(sys.executable))
    replacement_executable = shutil.which("true")
    assert replacement_executable is not None
    replacement.symlink_to(replacement_executable)
    return target, replacement, ["-c", f"print('{_AUTHORIZED_OUTPUT}')"]


def _replace_path(target: Path, replacement: Path) -> None:
    os.replace(replacement, target)
