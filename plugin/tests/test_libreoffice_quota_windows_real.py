"""Mandatory kernel-backed WinFsp and real Windows LibreOffice acceptance."""

import ctypes as c
import errno
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner
from document_skills_core.core.process.storage_environment import quota_storage_environment
from document_skills_core.providers.libreoffice.quota import hard_quota_capability, require_hard_quota_backend

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Real Windows WinFsp profile")


def _backend():
    if not hard_quota_capability().supported:
        if os.environ.get("ELFTIA_REQUIRE_LIBREOFFICE_PROFILE") == "1":
            from document_skills_core.providers.libreoffice._quota_winfsp_library import library_path
            library_path(strict=True)
            pytest.fail("Mandatory Windows WinFsp backend is unavailable")
        pytest.skip("Official WinFsp 2.1.25156 x64 runtime is required")
    return require_hard_quota_backend()


def _denied(action):
    with pytest.raises(OSError) as caught:
        action()
    assert caught.value.errno == errno.ENOSPC


def _native_truncate(path, size):
    from document_skills_core.providers.libreoffice.quota_windows import _set_windows_eof
    with path.open("r+b", buffering=0) as stream:
        _set_windows_eof(stream.fileno(), size)


def _child(tmp_path, code, arguments, **options):
    policy = ProcessPolicy(tmp_path)
    executable = policy.allow_executable("libreoffice", sys.executable)
    return ProcessRunner(policy).run("libreoffice", executable, ["-c", code, *arguments],
                                     cwd=tmp_path, timeout_seconds=15, **options)


def _released(session, expected=0):
    deadline = time.monotonic() + 5
    while session.store.total_bytes != expected and time.monotonic() < deadline:
        time.sleep(0.01)
    assert session.store.total_bytes == expected


def test_real_winfsp_aggregate_sparse_and_one_shot_denial():
    with _backend().open(byte_limit=16384, entry_limit=32) as session:
        first, second = session.output_dir / "first", session.profile_dir / "second"
        first.write_bytes(b"a" * 9000)
        _denied(lambda: second.write_bytes(b"b" * 9000))
        assert session.store.total_bytes <= 16384
        _denied(lambda: _native_truncate(first, 2**40))
        assert first.stat().st_size == 9000
        _denied(lambda: (session.output_dir / "large").write_bytes(b"x" * (32 * 1024 * 1024)))
        assert session.store.total_bytes <= 16384
        with pytest.raises(DocumentSkillsError):
            session.validate_final_tree(expected_name="first")
    assert not session.root.exists() and not session.file_system


def test_real_winfsp_entries_and_protected_namespace():
    with _backend().open(byte_limit=16384, entry_limit=8) as session:
        (session.profile_dir / "one").touch()
        _denied(lambda: (session.profile_dir / "extra").touch())
        _denied(lambda: (session.profile_dir / "extra-dir").mkdir())
        assert len(list(session.root.rglob("*"))) == 8
        with pytest.raises(OSError):
            session.output_dir.rename(session.root / "replacement")


def test_real_winfsp_concurrent_writes_are_bounded():
    with _backend().open(byte_limit=16384, entry_limit=32) as session:
        def write(index):
            try:
                (session.profile_dir / f"writer-{index}").write_bytes(b"x" * 4096)
            except OSError as error:
                assert error.errno == errno.ENOSPC
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write, range(16)))
        assert session.store.total_bytes <= 16384
        assert sum(path.stat().st_size for path in session.profile_dir.iterdir()) <= 16384


def test_real_winfsp_delete_shared_open_handle_keeps_allocation(tmp_path):
    with _backend().open(byte_limit=4096, entry_limit=16) as session:
        source = session.profile_dir / "open-file"
        source.write_bytes(b"x" * 4096)
        # CRT descriptors do not permit FILE_SHARE_DELETE. Keep a real native
        # handle while deleting and prove storage cannot be reused early.
        create = c.windll.kernel32.CreateFileW
        create.argtypes = [c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_void_p,
                           c.c_uint32, c.c_uint32, c.c_void_p]
        create.restype = c.c_void_p
        handle = create(str(source), 0x80000000, 7, None, 3, 0, None)
        assert handle not in {None, c.c_void_p(-1).value}
        try:
            source.unlink()
            # Windows may keep a delete-pending name until all handles close;
            # either namespace behavior must retain the underlying charge.
            assert session.store.total_bytes == 4096
            _denied(lambda: (session.output_dir / "replacement").write_bytes(b"y"))
        finally:
            close = c.windll.kernel32.CloseHandle
            close.argtypes, close.restype = [c.c_void_p], c.c_int32
            assert close(handle)
        _released(session)
        (session.output_dir / "replacement").write_bytes(b"y" * 4096)
        assert session.store.total_bytes == 4096


def test_real_winfsp_mapped_writes_and_growth_rejection(tmp_path):
    with _backend().open(byte_limit=4096, entry_limit=16) as session:
        source = session.output_dir / "result.pdf"
        source.write_bytes(b"x" * 4096)
        code = (
            "import mmap,os,sys,errno\n"
            "with open(sys.argv[1],'r+b',buffering=0) as f:\n"
            " with mmap.mmap(f.fileno(),4096,access=mmap.ACCESS_WRITE) as m:\n"
            "  m[:4]=b'yyyy'; m.flush()\n"
            " os.fsync(f.fileno())\n"
            " for action in (lambda: mmap.mmap(f.fileno(),8192,access=mmap.ACCESS_WRITE),\n"
            "                lambda: os.ftruncate(f.fileno(),8192)):\n"
            "  try: action()\n"
            "  except OSError as e: assert e.errno==errno.ENOSPC or e.winerror==112\n"
            "  else: raise AssertionError('mapped growth bypassed quota')\n"
            "  assert os.fstat(f.fileno()).st_size==4096\n"
        )
        result = _child(tmp_path, code, [str(source)])
        assert result.returncode == 0, result.stderr
        assert source.read_bytes()[:4] == b"yyyy" and session.store.total_bytes == 4096
        assert session.store.denials >= 2


def test_real_winfsp_refuses_streams_links_and_preserves_case():
    with _backend().open(byte_limit=16384, entry_limit=32) as session:
        source = session.output_dir / "MixedName"
        source.write_bytes(b"first")
        assert (session.output_dir / "MIXEDNAME").read_bytes() == b"first"
        assert [path.name for path in session.output_dir.iterdir()] == ["MixedName"]
        for action in (
            lambda: Path(str(source) + ":stream").write_bytes(b"bypass"),
            lambda: os.link(source, session.profile_dir / "link"),
            lambda: os.symlink(source, session.profile_dir / "symlink"),
        ):
            with pytest.raises(OSError):
                action()
        assert session.store.total_bytes == 512


def test_real_winfsp_session_isolation_and_private_environment(tmp_path):
    with _backend().open(byte_limit=16384, entry_limit=16) as first:
        with _backend().open(byte_limit=16384, entry_limit=16) as second:
            assert first.root != second.root and first.volume_name != second.volume_name
            (first.output_dir / "result.pdf").write_bytes(b"first")
            assert not (second.output_dir / "result.pdf").exists()
            environment = quota_storage_environment("libreoffice", first.process_storage)
            for name in ("HOME", "TMP", "TEMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
                assert Path(environment[name]).is_relative_to(first.root)
            assert environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] == "0"
            code = (
                "import os,pathlib\n"
                "assert os.environ['DOTNET_ADD_GLOBAL_TOOLS_TO_PATH']=='0'\n"
                "for key in ('TEMP','HOME','APPDATA','LOCALAPPDATA'):\n"
                " (pathlib.Path(os.environ[key])/key).write_bytes(b'x'*1024)\n"
            )
            result = _child(tmp_path, code, [], quota_storage=first.process_storage,
                            runtime_check=first.assert_live)
            assert result.returncode == 0, result.stderr
            assert first.store.total_bytes == 4608
            assert first.validate_final_tree(expected_name="result.pdf").output_bytes == 5
        assert not second.root.exists()
        first.assert_live()
    assert not first.root.exists()


def test_real_winfsp_mount_identity_drift_is_rejected(monkeypatch):
    with _backend().open(byte_limit=16384, entry_limit=16) as session:
        monkeypatch.setattr(session, "volume_name", "\\Device\\wrong-volume")
        with pytest.raises(DocumentSkillsError) as error:
            session.assert_live()
        assert error.value.code == ErrorCode.PROVIDER_FAILED


def test_real_winfsp_activation_failure_unmounts_before_return(monkeypatch):
    from document_skills_core.providers.libreoffice import quota_windows
    _backend()
    roots = []
    def fail_probe(session):
        roots.append(session.root)
        raise OSError(errno.EIO, "Injected probe failure")
    monkeypatch.setattr(quota_windows.WindowsWinFspQuotaSession, "_prove_limits", fail_probe)
    with pytest.raises(DocumentSkillsError):
        with quota_windows.WindowsWinFspHardQuotaBackend().open(byte_limit=16384, entry_limit=16):
            pytest.fail("Failed activation yielded a filesystem")
    assert len(roots) == 1 and not roots[0].exists()


def test_real_winfsp_zero_exit_after_denial_never_publishes(tmp_path, monkeypatch):
    from tests.test_libreoffice_quota_linux import test_zero_exit_after_real_quota_denial_never_publishes
    import tests.test_libreoffice_quota_linux as linux_tests
    monkeypatch.setattr(linux_tests, "_real_backend", _backend)
    test_zero_exit_after_real_quota_denial_never_publishes(tmp_path, monkeypatch)


@pytest.mark.slow
@pytest.mark.parametrize("cancel", [False, True])
def test_real_winfsp_timeout_and_cancellation_terminate_owned_descendants(tmp_path, cancel):
    from tests.test_runtime import _process_is_alive
    with _backend().open(byte_limit=16384, entry_limit=32) as session:
        ready = session.temporary_dir / "child.pid"
        policy = ProcessPolicy(tmp_path)
        executable = policy.allow_executable("libreoffice", sys.executable)
        code = (
            "import pathlib,subprocess,sys,time\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii')\n"
            "time.sleep(30)\n"
        )
        def check():
            session.assert_live()
            if cancel and ready.is_file():
                raise KeyboardInterrupt()
        with pytest.raises(DocumentSkillsError) as error:
            ProcessRunner(policy).run("libreoffice", executable, ["-c", code, str(ready)],
                                     cwd=tmp_path, timeout_seconds=5,
                                     quota_storage=session.process_storage, runtime_check=check)
        assert error.value.code == (ErrorCode.PROVIDER_FAILED if cancel else ErrorCode.PROCESS_TIMEOUT)
        if cancel:
            assert error.value.details["reason_category"] == "cancelled"
        pid = int(ready.read_text(encoding="ascii"))
        assert not _process_is_alive(pid)
        session.assert_live()
    assert not session.root.exists()


@pytest.mark.slow
def test_real_libreoffice_runs_in_quota_filesystem_windows(project_root, tmp_path):
    from document_skills_core.providers.libreoffice.detector import LibreOfficeDetector
    from document_skills_core.providers.libreoffice.runner import LibreOfficeRunner
    from tests.test_libreoffice_quota_linux import _write_native_probe_fixture
    _backend().validate_activation()
    detected = LibreOfficeDetector(project_root).detect()
    assert detected.available, detected.reason
    source = tmp_path / "native-probe.docx"
    _write_native_probe_fixture(project_root, source)
    output = tmp_path / "output"
    output.mkdir()
    result = LibreOfficeRunner(project_root, executable=detected.path).convert(source, "pdf", output)
    assert result.read_bytes().startswith(b"%PDF-")


@pytest.mark.slow
def test_real_windows_xlsx_recalculation_and_render_use_production_quota(project_root, tmp_path):
    from document_skills_core.core.capabilities import ProviderCatalog
    from document_skills_core.formats.xlsx.create import create_xlsx
    from document_skills_core.formats.pdf.validation import reopen_pdf
    from document_skills_core.providers.libreoffice import build_libreoffice_provider
    from document_skills_core.providers.libreoffice.detector import LibreOfficeDetector
    from document_skills_core.providers.libreoffice.recalc import recalculate_xlsx_artifact
    from document_skills_core.providers.libreoffice.runner import LibreOfficeRunner
    _backend().validate_activation()
    detected = LibreOfficeDetector(project_root).detect()
    assert detected.available, detected.reason
    source = tmp_path / "stale-cache.xlsx"
    create_xlsx(source, {"metadata": {}, "sheets": [{"name": "Inputs", "rows": [{"cells": [
        {"ref": "A1", "value": "2", "type": "n"},
        {"ref": "A2", "value": "3", "type": "n"},
        {"ref": "A3", "formula": "SUM(A1:A2)", "cached_value": "999", "type": "n"},
    ]}], "number_formats": []}], "defined_names": [], "tables": []})
    before = source.read_bytes()
    recalculated = recalculate_xlsx_artifact(source, LibreOfficeRunner(project_root, executable=detected.path))
    assert recalculated.cached_values == {"Inputs!A3": "5"}
    registry = ProviderCatalog()
    definition, _ = build_libreoffice_provider(project_root)
    registry.register_provider(definition)
    output = tmp_path / "rendered.pdf"
    result = registry.execute({"schema_version": "1.0", "operation": "xlsx.render",
                               "input": str(source), "output": str(output),
                               "arguments": {"max_sheets": 5, "max_cells_per_sheet": 50}})
    assert result["status"] == "success" and result["provider_chain"] == ["libreoffice"], result
    assert reopen_pdf(output)["pages"] >= 1 and source.read_bytes() == before
