"""Actual FUSE enforcement and pure accounting regressions (no fake quota)."""

from __future__ import annotations

import errno
import os
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process.storage_environment import quota_storage_environment
from document_skills_core.providers.libreoffice._quota_store import QuotaStore
from document_skills_core.providers.libreoffice.quota import hard_quota_capability, require_hard_quota_backend


def _file(store, name):
    store.create(name, stat.S_IFREG | 0o600)
    return store.open(name, os.O_RDWR)


def _assert_enospc(action):
    with pytest.raises(OSError) as error:
        action()
    assert error.value.errno == errno.ENOSPC


def test_accounting_aggregate_growth_is_atomic():
    store = QuotaStore(16, 8)
    first, second = _file(store, "/a"), _file(store, "/b")
    store.write(first, 0, b"a" * 9)
    _assert_enospc(lambda: store.write(second, 0, b"b" * 8))
    assert store.total_bytes == 9
    assert store.lookup("/b").data == b""
    store.write(second, 0, b"b" * 7)
    assert store.total_bytes == 16
    store.resize(store.lookup("/a"), 1)
    store.write(second, 7, b"b" * 8)
    assert store.total_bytes == 16


def test_accounting_sparse_truncate_and_sparse_offset_are_bounded():
    store = QuotaStore(16, 4)
    handle = _file(store, "/a")
    _assert_enospc(lambda: store.resize(store.lookup("/a"), 2**40))
    _assert_enospc(lambda: store.write(handle, 2**40, b"x"))
    assert store.total_bytes == 0
    store.write(handle, 15, b"x")
    assert store.total_bytes == 16
    assert store.lookup("/a").data == b"\0" * 15 + b"x"


def test_accounting_unlinked_open_files_retain_both_quotas():
    store = QuotaStore(16, 2)
    handle = _file(store, "/a")
    store.write(handle, 0, b"a" * 16)
    store.remove("/a")
    assert store.total_bytes == 16 and store.entry_count == 1
    next_handle = _file(store, "/b")
    _assert_enospc(lambda: store.write(next_handle, 0, b"b"))
    _assert_enospc(lambda: _file(store, "/c"))
    store.release(handle)
    assert store.total_bytes == 0 and store.entry_count == 1
    store.write(next_handle, 0, b"b" * 16)
    assert store.total_bytes == 16


def test_accounting_rename_replacement_retains_open_destination():
    store = QuotaStore(16, 4)
    first, second = _file(store, "/a"), _file(store, "/b")
    store.write(first, 0, b"a" * 8)
    store.write(second, 0, b"b" * 8)
    store.rename("/a", "/b", 0)
    assert store.lookup("/b").data == b"a" * 8
    assert store.lookup(None, second).data == b"b" * 8
    assert store.total_bytes == 16 and store.entry_count == 2
    store.release(second)
    assert store.total_bytes == 8 and store.entry_count == 1


@pytest.mark.parametrize("byte_limit,entry_limit", [(0,8), (-1,8), (True,8), (16,0), (16,4097), (2**40,8)])
def test_accounting_rejects_unbounded_or_invalid_limits(byte_limit, entry_limit):
    with pytest.raises(ValueError):
        QuotaStore(byte_limit, entry_limit)


def _real_backend():
    if not hard_quota_capability().supported:
        if os.environ.get("ELFTIA_REQUIRE_LIBREOFFICE_PROFILE") == "1":
            pytest.fail("Mandatory real LibreOffice quota backend is unavailable.")
        pytest.skip("Linux x86-64/glibc with libfuse3 and accessible /dev/fuse required.")
    return require_hard_quota_backend()


def test_real_fuse_aggregate_sparse_and_one_shot_denial():
    with _real_backend().open(byte_limit=16 * 1024, entry_limit=16) as session:
        first, second = session.output_dir / "first", session.profile_dir / "second"
        first.write_bytes(b"a" * 9000)
        _assert_enospc(lambda: second.write_bytes(b"b" * 9000))
        assert sum(path.stat().st_size for path in session.root.rglob("*") if path.is_file()) <= 16 * 1024
        _assert_enospc(lambda: os.truncate(first, 2**40))
        assert first.stat().st_size == 9000
        large = session.output_dir / "large"
        _assert_enospc(lambda: large.write_bytes(b"x" * (32 * 1024 * 1024)))
        assert large.stat().st_size <= 16 * 1024 - 9000
        with pytest.raises(DocumentSkillsError) as error:
            session.validate_final_tree(expected_name="first")
        assert error.value.code == ErrorCode.PROVIDER_FAILED
    assert not session.root.exists()
    assert not session.base


def test_real_fuse_entry_limit_and_namespace_identity():
    with _real_backend().open(byte_limit=16384, entry_limit=8) as session:
        root_identity = session.root_identity
        for index in range(4):
            (session.profile_dir / f"entry-{index}").touch()
        _assert_enospc(lambda: (session.profile_dir / "excess").touch())
        _assert_enospc(lambda: (session.profile_dir / "excess-dir").mkdir())
        assert len(list(session.root.rglob("*"))) == 8
        assert session.root_identity == root_identity
        with pytest.raises(OSError):
            session.output_dir.rename(session.root / "replaced")


def test_real_fuse_unlinked_open_files_and_release_reclaim():
    with _real_backend().open(byte_limit=16384, entry_limit=16) as session:
        first = session.profile_dir / "unlinked"
        with first.open("w+b", buffering=0) as stream:
            stream.write(b"a" * 16384)
            first.unlink()
            assert not first.exists()
            assert os.fstat(stream.fileno()).st_size == 16384
            _assert_enospc(lambda: (session.output_dir / "result.pdf").write_bytes(b"b"))
            stream.seek(0)
            assert stream.read(1) == b"a"
        (session.output_dir / "result.pdf").write_bytes(b"b" * 16384)
        assert session.store.total_bytes == 16384


def test_real_fuse_concurrent_writers_cannot_overcommit():
    with _real_backend().open(byte_limit=16384, entry_limit=32) as session:
        def write(index):
            try:
                (session.profile_dir / f"writer-{index}").write_bytes(b"x" * 4096)
            except OSError as error:
                assert error.errno == errno.ENOSPC
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write, range(16)))
        assert session.store.total_bytes <= 16384
        assert sum(path.stat().st_size for path in session.profile_dir.iterdir()) <= 16384


def test_real_fuse_forbids_links_special_files_and_writable_mmap(tmp_path):
    import mmap

    with _real_backend().open(byte_limit=16384, entry_limit=16) as session:
        source = session.output_dir / "result.pdf"
        source.write_bytes(b"x" * 4096)
        for action in (
            lambda: os.link(source, session.profile_dir / "link"),
            lambda: os.symlink(source, session.profile_dir / "symlink"),
            lambda: os.mkfifo(session.profile_dir / "fifo"),
        ):
            with pytest.raises(OSError):
                action()
        with source.open("r+b") as stream:
            with pytest.raises(OSError):
                mmap.mmap(stream.fileno(), 4096, access=mmap.ACCESS_WRITE)
        # A page fault while Python holds the broker's GIL would deadlock its
        # own FUSE callbacks. Real providers map from a separate process.
        from document_skills_core.core.process import ProcessPolicy, ProcessRunner

        policy = ProcessPolicy(tmp_path)
        executable = policy.allow_executable("libreoffice", sys.executable)
        code = "import mmap,sys; f=open(sys.argv[1],'rb'); m=mmap.mmap(f.fileno(),4096,access=mmap.ACCESS_READ); assert m[:4]==b'xxxx'; m.close(); f.close()"
        result = ProcessRunner(policy).run("libreoffice", executable, ["-c",code,str(source)],
                                           cwd=tmp_path, timeout_seconds=10)
        assert result.returncode == 0
        assert session.validate_final_tree(expected_name="result.pdf").output_bytes == 4096


def test_real_fuse_session_isolation_and_storage_environment():
    backend = _real_backend()
    with backend.open(byte_limit=16384, entry_limit=16) as first:
        with backend.open(byte_limit=16384, entry_limit=16) as second:
            assert first.root != second.root
            assert first.root_identity.device != second.root_identity.device
            (first.output_dir / "result.pdf").write_bytes(b"first")
            assert not (second.output_dir / "result.pdf").exists()
            environment = quota_storage_environment("libreoffice", first.process_storage)
            path_names = {"HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"}
            assert set(environment) == path_names | {"GSETTINGS_BACKEND"}
            assert environment["GSETTINGS_BACKEND"] == "memory"
            assert all(Path(environment[name]).is_relative_to(first.root) for name in path_names)
            with pytest.raises(DocumentSkillsError):
                quota_storage_environment("other", first.process_storage)
            with pytest.raises(DocumentSkillsError):
                quota_storage_environment("libreoffice", (first.root, (0,0)))
            assert first.validate_final_tree(expected_name="result.pdf").total_bytes == 5


def test_real_native_process_receives_quota_bound_temporary_and_home(tmp_path):
    from document_skills_core.core.process import ProcessPolicy, ProcessRunner

    with _real_backend().open(byte_limit=16384, entry_limit=16) as session:
        policy = ProcessPolicy(tmp_path)
        executable = policy.allow_executable("libreoffice", sys.executable)
        runner = ProcessRunner(policy)
        code = (
            "import os,pathlib,errno; "
            "t=pathlib.Path(os.environ['TMPDIR']); h=pathlib.Path(os.environ['HOME']); "
            "assert t.parent==h.parent; "
            "assert os.environ['GSETTINGS_BACKEND']=='memory'; "
            "(t/'temp').write_bytes(b't'*8192); "
            "(h/'cache').write_bytes(b'c'*8192); "
            "print((t/'temp').stat().st_size+(h/'cache').stat().st_size)"
        )
        result = runner.run("libreoffice", executable, ["-c", code], cwd=tmp_path,
                            timeout_seconds=10, quota_storage=session.process_storage,
                            runtime_check=session.assert_live)
        assert result.returncode == 0
        assert result.stdout.strip() == "16384"
        assert session.store.total_bytes == 16384


def test_zero_exit_after_real_quota_denial_never_publishes(tmp_path, monkeypatch):
    from document_skills_core.core.process import ProcessPolicy, ProcessRunner
    from document_skills_core.providers.libreoffice import output
    from document_skills_core.providers.libreoffice.runner import LibreOfficeRunner

    backend = _real_backend()
    monkeypatch.setitem(output.OUTPUT_LIMITS, "pdf", 16384)
    source = tmp_path / "input.docx"
    source.write_bytes(b"input")
    destination = tmp_path / "destination"
    destination.mkdir()
    policy = ProcessPolicy(tmp_path)
    executable = policy.allow_executable("libreoffice", sys.executable)
    process_runner = ProcessRunner(policy)
    calls = []

    class NativeQuotaWriter:
        def run(self, provider, executable, args, **kwargs):
            calls.append(True)
            target = str(Path(args[args.index("--outdir") + 1]) / "input.pdf")
            code = (
                "import os,pathlib,errno,sys\n"
                "temporary=pathlib.Path(os.environ['TMPDIR'])\n"
                "(temporary/'first').write_bytes(b'a'*8192)\n"
                "try: (temporary/'excess').write_bytes(b'b'*16384)\n"
                "except OSError as error: assert error.errno==errno.ENOSPC\n"
                "else: raise AssertionError('quota did not reject growth')\n"
                "pathlib.Path(sys.argv[1]).write_bytes(b'%PDF-1.7')\n"
            )
            return process_runner.run(provider, executable, ["-c", code, target], **kwargs)

    runner = LibreOfficeRunner(tmp_path, executable=executable,
                              runner=NativeQuotaWriter(), quota_backend=backend)
    with pytest.raises(DocumentSkillsError) as error:
        runner.convert(source, "pdf", destination, timeout_seconds=10)
    assert error.value.code == ErrorCode.PROVIDER_FAILED
    assert calls == [True]
    assert list(destination.iterdir()) == []


def test_detector_does_not_probe_executable_when_activation_fails(tmp_path, monkeypatch):
    from document_skills_core.providers.libreoffice.detector import LibreOfficeDetector
    from document_skills_core.providers.libreoffice.quota import ActivatableQuotaBackend, HardQuotaCapability

    class RejectedMount(ActivatableQuotaBackend):
        def capability(self):
            return HardQuotaCapability("test-rejected-mount", "test", "available", "Probe test",
                                       True, True, True, True)
        def validate_activation(self):
            raise DocumentSkillsError(ErrorCode.PROVIDER_UNAVAILABLE, "Mount denied")

    class MustNotProbe:
        def run(self, *_args, **_kwargs):
            pytest.fail("Version probe ran after rejected activation")

    executable = tmp_path / "native"
    executable.write_bytes(Path(sys.executable).read_bytes())
    detector = LibreOfficeDetector(tmp_path, runner=MustNotProbe(), quota_backend=RejectedMount())
    monkeypatch.setattr(detector, "_find_candidate", lambda: str(executable))
    evidence = detector.detect()
    assert evidence.available is False
    assert "hard_quota_activation_failed" in evidence.reason


def test_optional_evidence_cannot_record_partial_or_unavailable_profile(tmp_path):
    from tools.ci_docx_optional_evidence import _write_final_evidence

    for results, available in (({},False), ({},True)):
        with pytest.raises(AssertionError):
            _write_final_evidence(tmp_path, results, libreoffice_available=available)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.slow
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Real Linux LibreOffice quota profile")
def test_real_libreoffice_runs_in_quota_filesystem_with_bounded_diagnostics(project_root, tmp_path):
    from document_skills_core.core.process import ProcessPolicy, ProcessRunner
    from document_skills_core.providers.libreoffice.detector import LibreOfficeDetector
    from document_skills_core.providers.libreoffice.runner import _build_argv, _prepare_private_profile

    backend = _real_backend()
    policy = ProcessPolicy(project_root)
    detected = LibreOfficeDetector(project_root, policy=policy).detect()
    if not detected.available:
        if os.environ.get("ELFTIA_REQUIRE_LIBREOFFICE_PROFILE") == "1":
            pytest.fail(f"Mandatory real LibreOffice unavailable: {detected.reason}")
        pytest.skip("Real LibreOffice is not installed/callable.")
    source = tmp_path / "quota-native.docx"
    _write_native_probe_fixture(project_root, source)
    runner = ProcessRunner(policy)
    with backend.open(byte_limit=16 * 1024 * 1024, entry_limit=4096) as session:
        _prepare_private_profile(session.profile_dir)
        arguments = _build_argv(session.profile_dir, "--convert-to", "pdf", "--outdir",
                                str(session.output_dir), str(source))
        result = runner.run("libreoffice", detected.path, arguments, cwd=project_root,
                            timeout_seconds=30, quota_storage=session.process_storage,
                            runtime_check=session.assert_live)
        # Diagnostic text comes only from this fixed, generated fixture; no
        # user document, credential or inherited user profile is involved.
        assert result.returncode == 0, {"returncode":result.returncode, "stderr":result.stderr[-6000:]}
        snapshot = session.validate_final_tree(expected_name="quota-native.pdf")
        assert snapshot.output_bytes > 0
        assert (session.output_dir / "quota-native.pdf").read_bytes().startswith(b"%PDF-")


def _write_native_probe_fixture(project_root, source):
    from document_skills_core.cli import execute_request
    from document_skills_core.core.contracts.schemas import SchemaCatalog

    result = execute_request({
        "schema_version": "1.0", "operation": "docx.create", "output": str(source),
        "arguments": {"report": {"metadata": {"title": "Quota native probe"},
                                 "blocks": [{"type": "paragraph", "text": "Quota native probe"}]}},
    }, project_root, SchemaCatalog(project_root))
    assert result["status"] == "success", result


def test_native_probe_fixture_uses_valid_public_request(project_root, tmp_path):
    source = tmp_path / "probe.docx"
    _write_native_probe_fixture(project_root, source)
    assert source.read_bytes().startswith(b"PK")


def test_profile_disables_all_macro_runtimes_and_active_content(tmp_path):
    from xml.etree.ElementTree import fromstring
    from document_skills_core.providers.libreoffice.runner import _prepare_private_profile

    profile = tmp_path / "profile"
    profile.mkdir()
    _prepare_private_profile(profile)
    root = fromstring((profile / "user/registrymodifications.xcu").read_bytes())
    names = {prop.get("{http://openoffice.org/2001/registry}name"):prop.findtext("value")
             for prop in root.iter("prop")}
    assert names == {"DisableMacrosExecution":"true", "DisableActiveContent":"true", "MacroSecurityLevel":"3"}
    with pytest.raises(DocumentSkillsError):
        _prepare_private_profile(profile)  # Never merge with an existing user profile.


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux mount activation")
def test_activation_failure_cleans_empty_directories_and_never_yields(monkeypatch):
    from document_skills_core.providers.libreoffice import quota_linux

    _real_backend()
    created = []
    actual_activate = quota_linux.LinuxFuseQuotaSession.activate
    def fail_probe(self, library_path):
        actual_activate(self, library_path)
        created.append(self.root)
        raise OSError(errno.EIO, "Injected activation failure")
    monkeypatch.setattr(quota_linux.LinuxFuseQuotaSession, "activate", fail_probe)
    with pytest.raises(DocumentSkillsError) as error:
        with quota_linux.LinuxFuseHardQuotaBackend().open(byte_limit=16384, entry_limit=16):
            pytest.fail("Failed activation yielded a session")
    assert error.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert all(not path.exists() and not path.parent.exists() for path in created)
