"""Regression coverage for identity-bound private workspace lifetimes."""

from __future__ import annotations

import json
import inspect
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
from typing import Callable

import pytest

import document_skills_core.core.io.bound_child_directory as bound_child_module
import document_skills_core.core.io.parent_anchor as parent_anchor_module
import document_skills_core.core.process.runner as runner_module
import document_skills_core.worker.main as worker_main_module
import document_skills_core.worker.private_workspace as workspace_module
from document_skills_core.core.io.bound_child_directory import BoundDirectoryMixin
from document_skills_core.core.io.parent_anchor import DestinationParentAnchor
from document_skills_core.core.io.temp_roots import bind_supervised_operation_root
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor
from document_skills_core.worker.private_workspace import (
    PrivateOperationRoot,
    PrivateWorkspace,
)


class _FaultingAnchor(BoundDirectoryMixin):
    fail_at = ""

    def __init__(
        self,
        original_path: Path,
        identity: tuple[int, int],
        _descriptor: int | None = None,
        _windows_handle: int | None = None,
    ) -> None:
        if type(self).fail_at == "constructor" and original_path.name == "child":
            raise RuntimeError("injected child construction failure")
        self.original_path = original_path
        self.identity = identity
        self._descriptor = _descriptor
        self._windows_handle = _windows_handle

    def assert_bound(self, _phase: str) -> Path:
        return self.original_path

    def entry_path(self, name: str, **_kwargs: object) -> Path:
        if type(self).fail_at == "entry":
            raise RuntimeError("injected entry-path failure")
        return self.original_path / name

    def close(self) -> None:
        self._descriptor = None


@pytest.mark.parametrize("fail_at", ["fstat", "entry", "constructor"])
def test_bound_child_post_open_failure_closes_raw_fd_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_at: str,
) -> None:
    acquired = 197
    closed: list[int] = []
    _FaultingAnchor.fail_at = fail_at
    parent = _FaultingAnchor(tmp_path / "parent", (1, 2), _descriptor=91)
    for flag in ("O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"):
        monkeypatch.setattr(bound_child_module.os, flag, 0, raising=False)
    monkeypatch.setattr(bound_child_module.os, "mkdir", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        bound_child_module.os,
        "open",
        lambda *_args, **_kwargs: acquired,
    )

    def injected_fstat(_descriptor: int) -> SimpleNamespace:
        if fail_at == "fstat":
            raise RuntimeError("injected fstat failure")
        return SimpleNamespace(st_dev=3, st_ino=4)

    monkeypatch.setattr(bound_child_module.os, "fstat", injected_fstat)
    monkeypatch.setattr(bound_child_module.os, "close", closed.append)

    with pytest.raises(RuntimeError):
        parent.create_bound_directory("child", exist_ok=False)

    assert closed == [acquired]


def test_parent_anchor_post_open_fstat_failure_closes_raw_fd_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquired = 211
    closed: list[int] = []
    for flag in ("O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"):
        monkeypatch.setattr(parent_anchor_module.os, flag, 0, raising=False)
    monkeypatch.setattr(
        parent_anchor_module.os,
        "open",
        lambda *_args, **_kwargs: acquired,
    )
    monkeypatch.setattr(
        parent_anchor_module.os,
        "fstat",
        lambda _descriptor: (_ for _ in ()).throw(RuntimeError("injected fstat")),
    )
    monkeypatch.setattr(parent_anchor_module.os, "close", closed.append)

    with pytest.raises(RuntimeError):
        DestinationParentAnchor._open_posix(tmp_path)

    assert closed == [acquired]


def test_inherited_worker_fd_closes_when_fchdir_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path.cwd()
    if os.name == "nt":
        monkeypatch.setattr(workspace_module.os, "name", "posix")
    descriptor = 223
    closed: list[int] = []
    directory_mode = stat.S_IFDIR | 0o700
    monkeypatch.setattr(
        workspace_module.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(
            st_mode=directory_mode,
            st_dev=5,
            st_ino=6,
        ),
    )
    monkeypatch.setattr(
        workspace_module.os,
        "fchdir",
        lambda _descriptor: (_ for _ in ()).throw(OSError("injected fchdir")),
        raising=False,
    )
    monkeypatch.setattr(workspace_module.os, "close", closed.append)

    with pytest.raises(OSError):
        workspace_module.bind_inherited_workspace(
            [
                "--workspace-fd",
                str(descriptor),
                "--workspace-device",
                "5",
                "--workspace-inode",
                "6",
            ],
            project_root,
        )

    assert closed == [descriptor]


def test_imported_worker_run_closes_fd_when_project_root_resolve_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    descriptor = 225
    closed: list[int] = []
    injected = OSError("injected project-root resolve failure")
    if os.name == "nt":
        monkeypatch.setattr(workspace_module.os, "name", "posix")

    def fail_project_root_resolve(
        path: Path,
        *,
        strict: bool = False,
    ) -> Path:
        assert path == project_root
        assert strict is True
        raise injected

    monkeypatch.setattr(workspace_module.Path, "resolve", fail_project_root_resolve)
    monkeypatch.setattr(workspace_module.os, "close", closed.append)
    monkeypatch.setattr(worker_main_module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        worker_main_module.sys,
        "argv",
        [
            "worker.py",
            "--workspace-fd",
            str(descriptor),
            "--workspace-device",
            "5",
            "--workspace-inode",
            "6",
        ],
    )

    assert worker_main_module.run() == 70
    assert closed == [descriptor]


def test_inherited_worker_fd_rejects_cwd_outside_project_and_closes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside" / "held-invocation"
    outside.mkdir(parents=True)
    descriptor = 227
    closed: list[int] = []
    directory_mode = stat.S_IFDIR | 0o700
    if os.name == "nt":
        monkeypatch.setattr(workspace_module.os, "name", "posix")
    monkeypatch.setattr(
        workspace_module.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(
            st_mode=directory_mode,
            st_dev=7,
            st_ino=8,
        ),
    )
    monkeypatch.setattr(
        workspace_module.os,
        "fchdir",
        lambda _descriptor: None,
        raising=False,
    )
    monkeypatch.setattr(
        workspace_module.os,
        "stat",
        lambda _path, **_kwargs: SimpleNamespace(
            st_mode=directory_mode,
            st_dev=7,
            st_ino=8,
        ),
    )
    monkeypatch.setattr(
        workspace_module.Path,
        "cwd",
        classmethod(lambda _class: outside),
    )
    monkeypatch.setattr(workspace_module.os, "close", closed.append)

    with pytest.raises(ValueError, match="outside the project root"):
        workspace_module.bind_inherited_workspace(
            [
                "--workspace-fd",
                str(descriptor),
                "--workspace-device",
                "7",
                "--workspace-inode",
                "8",
            ],
            project_root,
        )

    assert closed == [descriptor]


def test_worker_does_not_read_or_dispatch_after_workspace_binding_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached: list[str] = []
    monkeypatch.setattr(
        worker_main_module,
        "bind_inherited_workspace",
        lambda _argv, _project_root: (_ for _ in ()).throw(
            ValueError("injected moved-outside workspace")
        ),
    )
    monkeypatch.setattr(
        worker_main_module,
        "_read_command",
        lambda: reached.append("read"),
    )
    monkeypatch.setattr(
        worker_main_module,
        "_dispatch_command",
        lambda _envelope: reached.append("dispatch"),
    )

    assert worker_main_module.run() == 70
    assert reached == []


def test_workspace_success_closes_root_and_base_ownership_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = PrivateWorkspace.create(tmp_path / "project", "close-once")
    root_path = workspace._root.original_path
    base_path = workspace._base.original_path
    if os.name == "nt":
        tokens = (workspace._root._windows_handle, workspace._base._windows_handle)
        real_close = parent_anchor_module._close_windows_handle
        closed: list[int] = []

        def observed_close(handle: int) -> None:
            closed.append(handle)
            real_close(handle)

        monkeypatch.setattr(
            parent_anchor_module, "_close_windows_handle", observed_close
        )
    else:
        tokens = (workspace._root._descriptor, workspace._base._descriptor)
        real_close = parent_anchor_module.os.close
        closed = []

        def observed_close(descriptor: int) -> None:
            closed.append(descriptor)
            real_close(descriptor)

        monkeypatch.setattr(parent_anchor_module.os, "close", observed_close)
    assert all(token is not None for token in tokens)

    removed = workspace.close()
    assert workspace.close() is False
    assert removed is (os.name == "nt")
    assert [closed.count(token) for token in tokens] == [1, 1]

    if root_path.exists():
        root_path.rmdir()
    if base_path.exists():
        base_path.rmdir()


class _ControlChild:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.close_count = 0

    def assert_bound(self, _phase: str) -> Path:
        raise self.error

    def close(self) -> None:
        self.close_count += 1


class _ControlParent(BoundDirectoryMixin):
    def __init__(self, child: _ControlChild) -> None:
        self._descriptor = 1
        self.child = child

    def assert_bound(self, _phase: str) -> Path:
        return Path.cwd()

    def _create_bound_posix_directory(
        self,
        _leaf: str,
        *,
        exist_ok: bool,
    ) -> _ControlChild:
        assert exist_ok is False
        return self.child


def test_bound_child_keyboard_interrupt_closes_once_and_reraises_unchanged() -> None:
    injected = KeyboardInterrupt("injected after child construction")
    child = _ControlChild(injected)

    with pytest.raises(KeyboardInterrupt) as captured:
        _ControlParent(child).create_bound_directory("child", exist_ok=False)

    assert captured.value is injected
    assert child.close_count == 1


class _WorkspaceCreationAnchor:
    def __init__(
        self,
        *,
        child: _WorkspaceCreationAnchor | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.child = child
        self.error = error
        self.close_count = 0

    def create_bound_directory(
        self,
        _name: str,
        *,
        exist_ok: bool,
    ) -> _WorkspaceCreationAnchor:
        if self.error is not None:
            raise self.error
        assert self.child is not None
        return self.child

    def close(self) -> None:
        self.close_count += 1


def test_workspace_system_exit_after_base_assignment_closes_once_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    injected = SystemExit(73)
    base = _WorkspaceCreationAnchor(error=injected)
    project = _WorkspaceCreationAnchor(child=base)
    monkeypatch.setattr(
        workspace_module.DestinationParentAnchor,
        "capture",
        lambda _path: (project, tmp_path / "unused"),
    )

    with pytest.raises(SystemExit) as captured:
        PrivateWorkspace.create(tmp_path / "project", "control-exception")

    assert captured.value is injected
    assert base.close_count == 1
    assert project.close_count == 1


@pytest.mark.parametrize(
    "args_factory",
    [
        lambda worker: ["-c", "print('dynamic')", str(worker)],
        lambda worker: ["-m", "document_skills_core.worker.main", str(worker)],
        lambda worker: ["--workspace-fd", "3", str(worker)],
        lambda worker: [str(worker), "--workspace-fd", "3"],
    ],
    ids=[
        "dynamic-c",
        "dynamic-module",
        "misplaced-script",
        "malformed-bootstrap",
    ],
)
def test_public_worker_capability_rejects_nonstatic_argv(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    args_factory: Callable[[Path], list[str]],
) -> None:
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("public-command-worker", sys.executable)
    worker = policy.allow_script(
        "public-command-worker",
        project_root / "src" / "document_skills_core" / "worker" / "main.py",
    )
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("rejected argv reached Popen"),
    )

    with pytest.raises(DocumentSkillsError) as captured:
        ProcessRunner(policy).run_public_command_worker(
            "public-command-worker",
            executable,
            args_factory(worker),
            script=worker,
            stdin_json={},
            workspace_cwd=project_root,
            posix_workspace_fd=None,
            posix_workspace_identity=None,
            timeout_seconds=1,
            output_limit=1024,
        )

    assert captured.value.code == ErrorCode.PATH_UNSAFE


def test_public_worker_capability_rejects_other_script_and_provider(
    project_root: Path,
) -> None:
    other = project_root / "tests" / "support" / "provider_fixture.py"
    for provider_id, script in (
        ("public-command-worker", other),
        (
            "other-provider",
            project_root / "src" / "document_skills_core" / "worker" / "main.py",
        ),
    ):
        policy = ProcessPolicy(project_root)
        executable = policy.allow_executable(provider_id, sys.executable)
        allowed_script = policy.allow_script(provider_id, script)
        with pytest.raises(DocumentSkillsError) as captured:
            ProcessRunner(policy).run_public_command_worker(
                provider_id,
                executable,
                [str(allowed_script)],
                script=allowed_script,
                stdin_json={},
                workspace_cwd=project_root,
                posix_workspace_fd=None,
                posix_workspace_identity=None,
                timeout_seconds=1,
                output_limit=1024,
            )
        assert captured.value.code == ErrorCode.PATH_UNSAFE


@pytest.mark.skipif(os.name != "nt", reason="requires the Windows launch branch")
def test_public_worker_capability_rejects_windows_pass_fds(project_root: Path) -> None:
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("public-command-worker", sys.executable)
    worker = policy.allow_script(
        "public-command-worker",
        project_root / "src" / "document_skills_core" / "worker" / "main.py",
    )
    with pytest.raises(DocumentSkillsError) as captured:
        ProcessRunner(policy).run_public_command_worker(
            "public-command-worker",
            executable,
            [str(worker)],
            script=worker,
            stdin_json={},
            workspace_cwd=project_root,
            posix_workspace_fd=37,
            posix_workspace_identity=(5, 7),
            timeout_seconds=1,
            output_limit=1024,
        )
    assert captured.value.code == ErrorCode.PATH_UNSAFE


def test_generic_runner_has_no_fd_capability_branch(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "posix_cwd_fd" not in inspect.signature(ProcessRunner.run).parameters
    assert "posix_cwd_identity" not in inspect.signature(ProcessRunner.run).parameters
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("fixture", sys.executable)
    observed: dict[str, object] = {}
    real_popen = subprocess.Popen

    def observe_popen(command: list[str], **kwargs: object) -> subprocess.Popen:
        observed.update(kwargs)
        return real_popen(command, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "Popen", observe_popen)
    result = ProcessRunner(policy).run(
        "fixture",
        executable,
        ["-c", "print('generic')"],
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "generic"
    assert "pass_fds" not in observed
    assert observed["cwd"] == project_root.resolve()


@pytest.mark.skipif(os.name != "nt", reason="requires identity-held Windows cleanup")
@pytest.mark.slow
def test_timed_out_worker_removes_only_its_owned_operation_root(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "sandbox"
    shutil.copytree(project_root / "src", sandbox / "src")
    shutil.copytree(project_root / "schemas", sandbox / "schemas")
    worker = sandbox / "src" / "document_skills_core" / "worker" / "main.py"
    shutil.copy2(
        project_root / "tests" / "support" / "command_worker_fixture.py",
        worker,
    )
    invocation_base = tmp_path / "invocation-base"
    invocation_base.mkdir()
    (invocation_base / "fixture-request.json").write_text(
        json.dumps({"operation": "docx.fixture"}),
        encoding="utf-8",
    )
    operation_base = (
        sandbox / ".document-skills-tmp" / "document-skills-operations"
    )
    operation_base.mkdir(parents=True)
    concurrent_root = operation_base / "operation-concurrent"
    concurrent_root.mkdir()
    concurrent_sentinel = concurrent_root / "sentinel.bin"
    concurrent_sentinel.write_bytes(b"concurrent")
    monkeypatch.chdir(invocation_base)

    payload, success = PublicCommandSupervisor(
        sandbox,
        timeout_seconds=2.0,
        nonce_factory=lambda: "fixture-hang",
    ).run("docx", ["run", "--request", "fixture-request.json"])

    owned_root = Path(
        (invocation_base / "owned-operation-root.txt").read_text(encoding="utf-8")
    )
    assert success is False
    assert payload["errors"][0]["code"] == ErrorCode.PROCESS_TIMEOUT.value
    assert not owned_root.exists()
    assert concurrent_sentinel.read_bytes() == b"concurrent"


def test_process_runner_reuses_only_the_identity_bound_supervised_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    owned = PrivateOperationRoot.create(project, "bound-runner")
    owned_path = owned.path
    runner = ProcessRunner(ProcessPolicy(project))
    try:
        with bind_supervised_operation_root(
            project,
            "bound-runner",
            owned.path,
            owned.identity,
        ):
            private_home = runner.private_environment_directory("DOTNET_CLI_HOME")
            assert private_home.parent == owned.path
            runner.close()
            assert owned.path == owned_path
    finally:
        assert owned.close() is True


def test_supervised_operation_root_rejects_identity_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    owned = PrivateOperationRoot.create(project, "identity-mismatch")
    wrong_identity = (owned.identity[0], owned.identity[1] + 1)
    try:
        with pytest.raises(DocumentSkillsError) as captured:
            with bind_supervised_operation_root(
                project,
                "identity-mismatch",
                owned.path,
                wrong_identity,
            ):
                pytest.fail("mismatched operation-root identity was accepted")
        assert captured.value.code == ErrorCode.PATH_UNSAFE
    finally:
        assert owned.close() is True


def test_worker_rejects_envelope_operation_root_identity_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    invocation_id = "worker-envelope-mismatch"
    owned = PrivateOperationRoot.create(project, invocation_id)
    wrong_identity = (owned.identity[0], owned.identity[1] + 1)
    dispatched: list[dict[str, object]] = []
    frames: list[dict[str, object]] = []
    envelope = {
        "invocation_id": invocation_id,
        "command": "run",
        "operation_root": str(owned.path),
        "operation_root_identity": list(wrong_identity),
    }
    monkeypatch.setattr(worker_main_module, "PROJECT_ROOT", project)
    monkeypatch.setattr(worker_main_module.sys, "argv", ["worker.py"])
    monkeypatch.setattr(
        worker_main_module,
        "bind_inherited_workspace",
        lambda _argv, _project_root: None,
    )
    monkeypatch.setattr(worker_main_module, "_read_command", lambda: envelope)
    monkeypatch.setattr(
        worker_main_module,
        "_dispatch_command",
        lambda value: dispatched.append(value),
    )
    monkeypatch.setattr(
        worker_main_module,
        "encode_worker_terminal_frame",
        lambda value: frames.append(value) or b"",
    )
    try:
        assert worker_main_module.run() == 0
        assert dispatched == []
        assert len(frames) == 1
        assert frames[0]["outcome"] == "runtime_failure"
        assert frames[0]["failure"]["exception_class"] == "DocumentSkillsError"
    finally:
        assert owned.close() is True


@pytest.mark.skipif(os.name != "nt", reason="requires Windows reparse semantics")
def test_operation_root_cleanup_never_follows_directory_links(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"outside")
    owned = PrivateOperationRoot.create(project, "no-follow")
    redirect = owned.path / "redirect"
    try:
        redirect.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        owned.close()
        pytest.skip(f"directory symlink unavailable: {type(error).__name__}")

    assert owned.close() is True
    assert sentinel.read_bytes() == b"outside"


def test_supervisor_reports_operation_root_cleanup_failure(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "sandbox"
    shutil.copytree(project_root / "src", sandbox / "src")
    shutil.copytree(project_root / "schemas", sandbox / "schemas")
    worker = sandbox / "src" / "document_skills_core" / "worker" / "main.py"
    shutil.copy2(
        project_root / "tests" / "support" / "command_worker_fixture.py",
        worker,
    )
    invocation_base = tmp_path / "invocation-base"
    invocation_base.mkdir()
    (invocation_base / "fixture-request.json").write_text(
        json.dumps({"operation": "docx.fixture"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(invocation_base)
    real_close = PrivateOperationRoot.close

    def close_but_report_failure(root: PrivateOperationRoot) -> bool:
        assert real_close(root) is True
        return False

    monkeypatch.setattr(PrivateOperationRoot, "close", close_but_report_failure)

    payload, success = PublicCommandSupervisor(
        sandbox,
        timeout_seconds=4.0,
        nonce_factory=lambda: "fixture-text-noise",
    ).run("docx", ["run", "--request", "fixture-request.json"])

    assert success is False
    assert payload["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED.value
    assert (
        payload["errors"][0]["details"]["reason_category"]
        == "cleanup_failed"
    )


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") or sys.platform == "darwin"),
    reason="requires movable POSIX directory descriptors",
)
def test_posix_replacement_after_identity_observation_is_never_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _unused = DestinationParentAnchor.capture(tmp_path / "project" / "unused")
    base = project.create_bound_directory("private", exist_ok=True)
    child = base.create_bound_directory("invocation", exist_ok=False)
    original = child.original_path
    displaced = original.with_name("held-invocation")
    real_assert = child.assert_bound
    observed: list[tuple[int, int]] = []

    def observe_then_replace(phase: str) -> Path:
        current = real_assert(phase)
        observed.append(child.identity)
        original.rename(displaced)
        original.mkdir()
        return current

    monkeypatch.setattr(child, "assert_bound", observe_then_replace)
    try:
        assert base.remove_empty_child(child) is False
        assert observed == [child.identity]
        assert original.is_dir()
        assert displaced.is_dir()
    finally:
        original.rmdir()
        displaced.rmdir()
        base.close()
        project.close()


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") or sys.platform == "darwin"),
    reason="requires inherited POSIX directory descriptors",
)
def test_posix_spawn_replacement_uses_held_workspace_identity(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "sandbox"
    shutil.copytree(project_root / "src", sandbox / "src")
    shutil.copytree(project_root / "schemas", sandbox / "schemas")
    worker = sandbox / "src" / "document_skills_core" / "worker" / "main.py"
    shutil.copy2(
        project_root / "tests" / "support" / "command_worker_fixture.py",
        worker,
    )
    invocation_base = tmp_path / "invocation-base"
    invocation_base.mkdir()
    (invocation_base / "request.json").write_text(
        json.dumps({"operation": "docx.fixture"}),
        encoding="utf-8",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"outside")
    private_root = sandbox / ".document-skills-tmp" / "invocation-fixture-cwd-identity"
    displaced = private_root.with_name("held-after-spawn-check")
    observed: dict[str, object] = {}
    real_popen = subprocess.Popen

    def replace_at_spawn(command: list[str], **kwargs: object) -> subprocess.Popen:
        pass_fds = kwargs.get("pass_fds")
        assert type(pass_fds) is tuple and len(pass_fds) == 1
        descriptor = pass_fds[0]
        metadata = os.fstat(descriptor)
        observed["identity"] = [metadata.st_dev, metadata.st_ino]
        observed["launch_cwd"] = kwargs.get("cwd")
        observed["close_fds"] = kwargs.get("close_fds")
        private_root.rename(displaced)
        private_root.symlink_to(outside, target_is_directory=True)
        return real_popen(command, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "Popen", replace_at_spawn)
    monkeypatch.chdir(invocation_base)
    payload, success = PublicCommandSupervisor(
        sandbox,
        nonce_factory=lambda: "fixture-cwd-identity",
    ).run("docx", ["run", "--request", "request.json"])

    assert success is True
    diagnostics = payload["diagnostics"]
    assert diagnostics["actual_cwd_identity"] == observed["identity"]
    assert diagnostics["held_workspace_identity"] == observed["identity"]
    assert observed["launch_cwd"] == sandbox.resolve()
    assert observed["close_fds"] is True
    assert private_root.is_symlink()
    assert displaced.is_dir()
    assert sentinel.read_bytes() == b"outside"

    private_root.unlink()
    displaced.rmdir()
    displaced.parent.rmdir()


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") or sys.platform == "darwin"),
    reason="requires inherited movable POSIX directory descriptors",
)
def test_posix_worker_rejects_held_workspace_moved_outside_project_before_popen(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "sandbox"
    shutil.copytree(project_root / "src", sandbox / "src")
    shutil.copytree(project_root / "schemas", sandbox / "schemas")
    worker = sandbox / "src" / "document_skills_core" / "worker" / "main.py"
    shutil.copy2(
        project_root / "tests" / "support" / "command_worker_fixture.py",
        worker,
    )
    invocation_base = tmp_path / "invocation-base"
    invocation_base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "provider-dispatch.bin"
    sentinel.write_bytes(b"untouched")
    request = invocation_base / "request.json"
    request.write_text(
        json.dumps(
            {
                "operation": "docx.fixture",
                "provider_dispatch_sentinel": str(sentinel),
            }
        ),
        encoding="utf-8",
    )
    private_root = sandbox / ".document-skills-tmp" / "invocation-fixture-moved-outside"
    displaced = outside / "held-invocation"
    observed: dict[str, object] = {}
    real_popen = subprocess.Popen

    def move_outside_at_spawn(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.Popen:
        pass_fds = kwargs.get("pass_fds")
        assert type(pass_fds) is tuple and len(pass_fds) == 1
        observed["launch_cwd"] = kwargs.get("cwd")
        observed["worker_argv0"] = command[1]
        private_root.rename(displaced)
        private_root.symlink_to(outside, target_is_directory=True)
        return real_popen(command, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "Popen", move_outside_at_spawn)
    monkeypatch.chdir(invocation_base)
    try:
        payload, success = PublicCommandSupervisor(
            sandbox,
            nonce_factory=lambda: "fixture-moved-outside",
        ).run("docx", ["run", "--request", "request.json"])

        assert success is False
        assert payload["errors"][0]["details"]["reason_category"] == "worker_exit"
        assert sentinel.read_bytes() == b"untouched"
        assert observed["launch_cwd"] == sandbox.resolve()
        assert observed["worker_argv0"] == str(worker.resolve())
    finally:
        if private_root.is_symlink():
            private_root.unlink()
        if displaced.is_dir():
            displaced.rmdir()
        base = sandbox / ".document-skills-tmp"
        if base.is_dir():
            base.rmdir()
