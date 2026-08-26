"""Windows native operations used by destination-parent anchors."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import BinaryIO


def open_windows_directory(path: Path, *, share_delete: bool = True) -> int:
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x1 | 0x2 | 0x4 | 0x20 | 0x80 | 0x00100000,
        0x1 | 0x2 | (0x4 if share_delete else 0),
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        raise ctypes.WinError()
    return int(handle)


def open_windows_relative_directory(
    parent_handle: int,
    name: str,
    *,
    exist_ok: bool,
    share_delete: bool,
) -> int:
    return _nt_create_relative(
        parent_handle,
        name,
        access=0x1 | 0x2 | 0x4 | 0x20 | 0x80 | 0x00100000,
        disposition=3 if exist_ok else 2,
        share_delete=share_delete,
        directory=True,
    )


def open_windows_relative_directory_for_delete(
    parent_handle: int,
    name: str,
) -> int:
    return _nt_create_relative(
        parent_handle,
        name,
        access=0x00010000 | 0x80 | 0x00100000,
        disposition=1,
        share_delete=False,
        directory=True,
    )


def windows_handle_metadata(handle: int) -> tuple[int, int]:
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("CreationTime", wintypes.FILETIME),
            ("LastAccessTime", wintypes.FILETIME),
            ("LastWriteTime", wintypes.FILETIME),
            ("VolumeSerialNumber", wintypes.DWORD),
            ("FileSizeHigh", wintypes.DWORD),
            ("FileSizeLow", wintypes.DWORD),
            ("NumberOfLinks", wintypes.DWORD),
            ("FileIndexHigh", wintypes.DWORD),
            ("FileIndexLow", wintypes.DWORD),
        ]

    information = ByHandleFileInformation()
    function = ctypes.windll.kernel32.GetFileInformationByHandle
    function.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    function.restype = wintypes.BOOL
    if not function(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise ctypes.WinError()
    identity = (information.FileIndexHigh << 32) | information.FileIndexLow
    return identity, information.FileAttributes


def mark_windows_directory_for_delete(handle: int) -> None:
    from ctypes import wintypes

    class FileDispositionInformation(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    information = FileDispositionInformation(True)
    function = ctypes.windll.kernel32.SetFileInformationByHandle
    function.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    function.restype = wintypes.BOOL
    if not function(
        wintypes.HANDLE(handle),
        4,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ctypes.WinError()


def windows_final_path(handle: int) -> Path:
    from ctypes import wintypes

    function = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    function.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    function.restype = wintypes.DWORD
    size = function(handle, None, 0, 0)
    if size == 0:
        raise ctypes.WinError()
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = function(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        raise ctypes.WinError()
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value).resolve(strict=False)


def open_windows_relative_file(
    parent_handle: int,
    name: str,
    *,
    create: bool,
    writable: bool,
) -> BinaryIO:
    access = (0x40000000 if writable else 0x80000000) | 0x00000080 | 0x00100000
    handle = _nt_create_relative(
        parent_handle,
        name,
        access=access,
        disposition=2 if create else 1,
    )
    flags = (os.O_WRONLY if writable else os.O_RDONLY) | os.O_BINARY
    runtime = ctypes.CDLL("ucrtbase.dll")
    open_descriptor = runtime._open_osfhandle
    open_descriptor.argtypes = [ctypes.c_void_p, ctypes.c_int]
    open_descriptor.restype = ctypes.c_int
    descriptor = -1
    try:
        descriptor = open_descriptor(handle, flags)
        if descriptor == -1:
            raise OSError("_open_osfhandle failed")
        return os.fdopen(descriptor, "wb" if writable else "rb")
    except Exception:
        if descriptor == -1:
            close_windows_handle(handle)
        else:
            os.close(descriptor)
        raise


def windows_rename_relative(
    parent_handle: int,
    source_name: str,
    destination_name: str,
) -> None:
    from ctypes import wintypes

    source_handle = _nt_create_relative(
        parent_handle,
        source_name,
        access=0x00010000 | 0x00000080 | 0x00100000,
        disposition=1,
    )

    class FileRenameInformation(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", wintypes.BYTE),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    class IoStatusUnion(ctypes.Union):
        _fields_ = [("Status", ctypes.c_long), ("Pointer", wintypes.LPVOID)]

    class IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("value", IoStatusUnion), ("Information", ctypes.c_size_t)]

    encoded = destination_name.encode("utf-16-le")
    offset = FileRenameInformation.FileName.offset
    information_size = offset + len(encoded)
    buffer = ctypes.create_string_buffer(
        max(ctypes.sizeof(FileRenameInformation), information_size)
    )
    header = FileRenameInformation.from_buffer(buffer)
    header.ReplaceIfExists = 0
    header.RootDirectory = parent_handle
    header.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    io_status = IoStatusBlock()
    set_information = ctypes.windll.ntdll.NtSetInformationFile
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.c_int,
    ]
    set_information.restype = ctypes.c_long
    try:
        status = set_information(
            source_handle,
            ctypes.byref(io_status),
            buffer,
            len(buffer),
            10,
        )
        if status < 0:
            _raise_ntstatus(status, destination_name)
    finally:
        close_windows_handle(source_handle)


def _nt_create_relative(
    parent_handle: int,
    name: str,
    *,
    access: int,
    disposition: int,
    share_delete: bool = True,
    directory: bool = False,
) -> int:
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class IoStatusUnion(ctypes.Union):
        _fields_ = [("Status", ctypes.c_long), ("Pointer", wintypes.LPVOID)]

    class IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("value", IoStatusUnion), ("Information", ctypes.c_size_t)]

    name_buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        parent_handle,
        ctypes.pointer(unicode_name),
        0x40,
        None,
        None,
    )
    io_status = IoStatusBlock()
    handle = wintypes.HANDLE()
    nt_create_file = ctypes.windll.ntdll.NtCreateFile
    nt_create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    nt_create_file.restype = ctypes.c_long
    status = nt_create_file(
        ctypes.byref(handle),
        access,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0x80,
        0x1 | 0x2 | (0x4 if share_delete else 0),
        disposition,
        0x20 | (0x1 if directory else 0x40) | 0x00200000,
        None,
        0,
    )
    if status < 0:
        _raise_ntstatus(status, name)
    return int(handle.value)


def _raise_ntstatus(status: int, name: str) -> None:
    converter = ctypes.windll.ntdll.RtlNtStatusToDosError
    converter.argtypes = [ctypes.c_long]
    converter.restype = ctypes.c_ulong
    _raise_windows_error(int(converter(status)), name)


def _raise_windows_error(number: int, name: str) -> None:
    error = ctypes.WinError(number)
    error.filename = name
    raise error


def close_windows_handle(handle: int) -> None:
    from ctypes import wintypes

    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    close_handle(handle)
