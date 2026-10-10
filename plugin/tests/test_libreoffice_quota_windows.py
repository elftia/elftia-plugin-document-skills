"""Native WinFsp ABI and serialized allocation quota regressions."""

import ctypes as c
import errno
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from document_skills_core.providers.libreoffice._quota_windows_store import WindowsQuotaStore, canonical_path
from document_skills_core.providers.libreoffice._quota_winfsp_abi import (
    CALLBACK_ARGUMENTS, INTERFACE_NAMES, FileInfo, Interface, PTR, STATUS, check_abi,
)
from document_skills_core.providers.libreoffice._quota_winfsp_operations import DISK_FULL, IO_ERROR, WinFspCallbacks


def _call(callbacks, name, *arguments):
    function = c.CFUNCTYPE(STATUS, *CALLBACK_ARGUMENTS[name])(
        callbacks.interface.Callbacks[INTERFACE_NAMES.index(name)]
    )
    return function(None, *arguments) & 0xFFFFFFFF


def _callbacks(byte_limit=4096, entries=16):
    store = WindowsQuotaStore(byte_limit, entries)
    return WinFspCallbacks(store, SimpleNamespace(), b"private-security")


def _create(callbacks, name="\\Result", allocation=0):
    context, info = PTR(), FileInfo()
    assert _call(callbacks, "Create", name, 0, 0, 0x80, None, allocation,
                 c.pointer(context), c.pointer(info)) == 0
    return context.value, info


def _enospc(action):
    with pytest.raises(OSError) as error:
        action()
    assert error.value.errno == errno.ENOSPC


def test_winfsp_abi_and_native_pointer_outputs():
    check_abi()
    assert c.sizeof(Interface) == 512
    callbacks = _callbacks()
    context, info = _create(callbacks, allocation=512)
    assert context == 2 and info.AllocationSize == 512 and info.FileSize == 0
    assert info.IndexNumber == context
    info.FileSize = 123
    assert _call(callbacks, "GetFileInfo", context, c.pointer(info)) == 0
    assert info.FileSize == 0
    assert _call(callbacks, "SetFileSize", context, 42, False, c.pointer(info)) == 0
    assert (info.FileSize, info.AllocationSize) == (42, 512)


def test_failed_native_growth_is_atomic_and_rejects_before_buffer_copy():
    callbacks = _callbacks(byte_limit=1024)
    context, info = _create(callbacks, allocation=512)
    _create(callbacks, "\\second", 512)
    assert _call(callbacks, "SetFileSize", context, 513, False, c.pointer(info)) == DISK_FULL
    transferred = c.c_uint32(99)
    # Deliberately invalid pointer: rejection must happen before string_at.
    assert _call(callbacks, "Write", context, 1, 512, 1, False, False,
                 c.pointer(transferred), c.pointer(info)) == DISK_FULL
    assert transferred.value == 0 and callbacks.store.total_bytes == 1024
    assert callbacks.store.sizes[context] == 0 and not callbacks.store.failed


def test_allocation_and_eof_are_distinct_and_regrowth_zeroes_truncated_data():
    store = WindowsQuotaStore(4096, 16)
    node = store.create_windows("\\file", False, 0x80, 2048)
    store.write_windows(node, 0, b"secret", False)
    assert store.total_bytes == 2048 and store.sizes[node.inode] == 6
    store.set_size(node, 2, False)
    assert store.total_bytes == 2048
    store.set_size(node, 6, False)
    assert node.data[:6] == b"se\0\0\0\0"
    store.set_size(node, 512, True)
    assert store.total_bytes == 512
    _enospc(lambda: store.set_size(node, 4097, False))
    assert store.sizes[node.inode] == 6
    with pytest.raises(OSError):
        store.reserve(node, -1)


def test_paging_write_can_only_modify_charged_eof():
    callbacks = _callbacks()
    context, info = _create(callbacks)
    assert _call(callbacks, "SetFileSize", context, 4, False, c.pointer(info)) == 0
    payload, transferred = c.create_string_buffer(b"abcdef"), c.c_uint32()
    assert _call(callbacks, "Write", context, payload, 2, 6, False, True,
                 c.pointer(transferred), c.pointer(info)) == 0
    assert transferred.value == 2 and info.FileSize == 4 and info.AllocationSize == 512
    assert callbacks.store.nodes[context].data[:4] == b"\0\0ab"
    assert _call(callbacks, "Write", context, payload, 9999, 6, False, True,
                 c.pointer(transferred), c.pointer(info)) == 0
    assert transferred.value == 0


@pytest.mark.parametrize("name", ["\\file:stream", "\\..\\escape", "\\CON.txt", "\\a.", "\\a/b", "relative"])
def test_invalid_names_and_alternate_streams_are_rejected(name):
    with pytest.raises(OSError):
        canonical_path(name)


def test_names_are_case_preserving_and_case_insensitive():
    callbacks = _callbacks()
    context, _ = _create(callbacks, "\\MixedName")
    store = callbacks.store
    assert store.lookup(canonical_path("\\MIXEDNAME")).inode == context
    store.rename_windows(store.nodes[context], "\\mixedname", "\\MIXEDname", False)
    assert store.names[context] == "MIXEDname"
    with pytest.raises(OSError):
        store.create_windows("\\mixedNAME", False, 0, 0)


def test_open_unlinked_and_replaced_files_remain_charged_until_last_close():
    callbacks = _callbacks(1024, 2)
    first, _ = _create(callbacks, "\\first", 512)
    second, _ = _create(callbacks, "\\second", 512)
    store = callbacks.store
    store.rename_windows(store.nodes[first], "\\first", "\\second", True)
    assert store.total_bytes == 1024 and store.entry_count == 2
    assert store.node(second).linked is False
    _enospc(lambda: store.create_windows("\\third", False, 0, 0))
    store.close_node(store.node(second))
    assert store.total_bytes == 512 and store.entry_count == 1
    store.open_node(store.node(first))
    store.unlink_node(store.node(first))
    store.close_node(store.node(first))
    assert store.total_bytes == 512
    store.close_node(store.node(first))
    assert store.total_bytes == 0 and store.entry_count == 0


def test_callbacks_serialize_concurrent_reservations():
    callbacks = _callbacks(4096, 32)
    contexts = [_create(callbacks, f"\\file-{i}")[0] for i in range(16)]
    def grow(context):
        return _call(callbacks, "SetFileSize", context, 1024, False, c.pointer(FileInfo()))
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(grow, contexts))
    assert results.count(0) == 4 and results.count(DISK_FULL) == 12
    assert callbacks.store.total_bytes == 4096


def test_unknown_callback_failure_invalidates_session(monkeypatch):
    callbacks = _callbacks()
    context, info = _create(callbacks)
    def fail(_context):
        raise RuntimeError("injected")
    monkeypatch.setattr(callbacks.store, "node", fail)
    assert _call(callbacks, "GetFileInfo", context, c.pointer(info)) == IO_ERROR
    assert callbacks.store.failed


def test_security_queries_report_required_capacity_without_overwrite():
    callbacks = _callbacks()
    capacity = c.c_size_t(0)
    assert _call(callbacks, "GetSecurityByName", "\\", None, None,
                 c.pointer(capacity)) == 0x80000005
    assert capacity.value == len(callbacks.security)
    buffer = c.create_string_buffer(capacity.value)
    assert _call(callbacks, "GetSecurityByName", "\\", None, buffer,
                 c.pointer(capacity)) == 0
    assert buffer.raw == callbacks.security


def test_forbidden_native_attributes_are_refused_before_create():
    callbacks = _callbacks()
    context, info = PTR(), FileInfo()
    for attributes in (0x400, 0x800, 0x4000):
        assert _call(callbacks, "Create", "\\file", 0, 0, attributes, None, 0,
                     c.pointer(context), c.pointer(info)) == 0xC0000022
    assert callbacks.store.entry_count == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows DLL pins and ACL")
def test_security_descriptor_and_untrusted_dll_rejection(tmp_path):
    from document_skills_core.providers.libreoffice._quota_windows_security import user_security_descriptor
    from document_skills_core.providers.libreoffice._quota_winfsp_library import PinnedLibraryFile
    assert len(user_security_descriptor()) > 32
    fake = tmp_path / "winfsp-x64.dll"
    fake.write_bytes(b"untrusted library")
    with pytest.raises(OSError):
        with PinnedLibraryFile(fake):
            pytest.fail("An untrusted DLL was accepted")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows runtime registry")
def test_runtime_discovery_pins_sxs_payload_instead_of_compatibility_junction(tmp_path, monkeypatch):
    import winreg
    from document_skills_core.providers.libreoffice import _quota_winfsp_library as module
    selected = []
    class Key:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def query(_key, name):
        assert name == "SxsDir"
        return str(tmp_path), winreg.REG_SZ
    class Pin(Key):
        def __init__(self, path):
            selected.append(path)
    monkeypatch.setattr(winreg, "OpenKey", lambda *args: Key())
    monkeypatch.setattr(winreg, "QueryValueEx", query)
    monkeypatch.setattr(module, "PinnedLibraryFile", Pin)
    assert module.library_path(strict=True) == tmp_path / "bin/winfsp-x64.dll"
    assert selected == [tmp_path / "bin/winfsp-x64.dll"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows held DLL identity")
def test_trusted_dll_copy_cannot_be_written_or_replaced_while_pinned(tmp_path):
    import os
    import shutil
    from document_skills_core.providers.libreoffice._quota_winfsp_library import PinnedLibraryFile, library_path
    source = library_path()
    if source is None:
        if os.environ.get("ELFTIA_REQUIRE_LIBREOFFICE_PROFILE") == "1":
            pytest.fail("Mandatory pinned runtime is absent")
        pytest.skip("Pinned WinFsp runtime is not installed")
    directory = tmp_path / "runtime"
    directory.mkdir()
    target = directory / "winfsp-x64.dll"
    shutil.copyfile(source, target)
    with PinnedLibraryFile(target):
        for action in (lambda: target.write_bytes(b"changed"),
                       lambda: target.rename(directory / "replacement.dll"),
                       lambda: directory.rename(tmp_path / "renamed")):
            with pytest.raises(OSError):
                action()
    target.rename(directory / "released.dll")
