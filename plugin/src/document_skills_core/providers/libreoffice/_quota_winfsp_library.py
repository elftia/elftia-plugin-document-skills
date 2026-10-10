"""Identity-held loading of the WinFsp 2.1.25156 x64 library.

The SHA-256 is bound to the DLL in the official v2.1 MSI (MSI SHA-256
073a70e00f77423e34bed98b86e600def93393ba5822204fac57a29324db9f7a).
Only the DLL and Windows System32 dependency search are permitted.
Module provenance: original Elftia-authored implementation.
"""

from __future__ import annotations

import ctypes as c
import sys
import sysconfig
from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError
from ...core.process import windows_handles as handles
from ._quota_winfsp_abi import U32, check_abi, configure_library

DLL_SHA256 = "08d7389b8d030770a4de108a60a86047d5cdd00b9ecafc6dd66e957bc51c2437"


def library_path() -> Path | None:
    if sys.platform != "win32" or sysconfig.get_platform() != "win-amd64":
        return None
    import winreg

    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WinFsp", 0, winreg.KEY_READ | view) as key:
                directory, kind = winreg.QueryValueEx(key, "InstallDir")
            if kind != winreg.REG_SZ or not isinstance(directory, str):
                continue
            root = Path(directory)
            if not root.is_absolute():
                continue
            candidate = root / "bin" / "winfsp-x64.dll"
            with PinnedLibraryFile(candidate):
                return candidate
        except (OSError, ValueError, DocumentSkillsError):
            continue
    return None


class PinnedLibraryFile:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self.held = []

    def __enter__(self):
        try:
            handles.require_local_fixed_path(self.path)
            for parent in handles.parent_components(self.path):
                handle = handles.create_handle(
                    parent, access=handles.FILE_READ_ATTRIBUTES,
                    flags=handles.FILE_FLAG_BACKUP_SEMANTICS | handles.FILE_FLAG_OPEN_REPARSE_POINT,
                )
                self.held.append(handle)
                attributes = handles.handle_attributes(handle)
                if not attributes & handles.FILE_ATTRIBUTE_DIRECTORY or attributes & handles.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise OSError("WinFsp DLL parent is redirected.")
            handle = handles.create_handle(
                self.path, access=handles.GENERIC_READ, flags=handles.FILE_FLAG_OPEN_REPARSE_POINT,
            )
            self.held.append(handle)
            if handles.handle_attributes(handle) & (handles.FILE_ATTRIBUTE_DIRECTORY | handles.FILE_ATTRIBUTE_REPARSE_POINT):
                raise OSError("WinFsp DLL is not a regular, unredirected file.")
            before = handles.file_snapshot(handle)
            digest, _ = handles.hash_handle(handle)
            if (digest != DLL_SHA256 or before != handles.file_snapshot(handle)
                    or handles.final_path(handle) != self.path):
                raise OSError("WinFsp DLL identity or pinned digest differs.")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args) -> None:
        for handle in reversed(self.held):
            handles.close_handle(handle)
        self.held.clear()


class LoadedWinFsp:
    def __init__(self, path: Path) -> None:
        self.pin = PinnedLibraryFile(path)
        self.pin.__enter__()
        self.library = None
        try:
            check_abi()
            self.library = c.WinDLL(str(path.absolute()), winmode=0x800)
            get_name = c.windll.kernel32.GetModuleFileNameW
            get_name.argtypes, get_name.restype = [c.c_void_p, c.c_wchar_p, U32], U32
            buffer = c.create_unicode_buffer(32768)
            length = get_name(self.library._handle, buffer, len(buffer))
            if not length or length >= len(buffer) or Path(buffer.value) != self.pin.path:
                raise OSError("Loaded WinFsp module differs from its held file.")
            configure_library(self.library)
            version = U32()
            if self.library.FspVersion(c.byref(version)) != 0 or version.value != 0x00020001:
                raise OSError("WinFsp 2.1 ABI is required.")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.library is not None:
            free = c.windll.kernel32.FreeLibrary
            free.argtypes, free.restype = [c.c_void_p], c.c_int32
            free(self.library._handle)
            self.library = None
        self.pin.__exit__(None, None, None)
