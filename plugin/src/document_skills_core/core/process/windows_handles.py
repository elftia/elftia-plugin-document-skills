"""Low-level Windows path pins and stable executable-handle evidence."""

import ctypes
import hashlib
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from ..contracts.errors import DocumentSkillsError, ErrorCode

HASH_CHUNK_BYTES = 64 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_READ_ATTRIBUTES = 0x00000080
GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_DRIVE_FIXED = 3
_FILE_ID_INFO_CLASS = 18


@dataclass(frozen=True)
class WindowsFileSnapshot:
    object_identity: tuple[int, bytes]
    size: int
    mtime_ns: int
    ctime_ns: int

    def alias_identity(self) -> tuple[int, int, int, int, int]:
        volume, file_id = self.object_identity
        return (
            volume,
            int.from_bytes(file_id, byteorder="little", signed=False),
            self.size,
            self.mtime_ns,
            self.ctime_ns,
        )


def require_local_fixed_path(path: Path) -> None:
    anchor = path.anchor
    if not anchor or anchor.startswith("\\\\"):
        _atomic_launch_unavailable()
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    get_drive_type.argtypes = [wintypes.LPCWSTR]
    get_drive_type.restype = wintypes.UINT
    if get_drive_type(anchor) != _DRIVE_FIXED:
        _atomic_launch_unavailable()


def parent_components(path: Path) -> tuple[Path, ...]:
    current = Path(path.anchor)
    components = [current]
    for part in path.parts[1:-1]:
        current /= part
        components.append(current)
    return tuple(components)


def create_handle(path: Path, *, access: int, flags: int) -> int:
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        access,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in {None, invalid}:
        raise ctypes.WinError()
    return int(handle)


def handle_attributes(handle: int) -> int:
    information = _ByHandleFileInformation()
    get_information = ctypes.windll.kernel32.GetFileInformationByHandle
    get_information.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    get_information.restype = wintypes.BOOL
    if not get_information(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise ctypes.WinError()
    return int(information.file_attributes)


def file_snapshot(handle: int) -> WindowsFileSnapshot:
    standard = _ByHandleFileInformation()
    get_standard = ctypes.windll.kernel32.GetFileInformationByHandle
    get_standard.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    get_standard.restype = wintypes.BOOL
    if not get_standard(wintypes.HANDLE(handle), ctypes.byref(standard)):
        raise ctypes.WinError()
    basic = _FileBasicInfo()
    get_extended = ctypes.windll.kernel32.GetFileInformationByHandleEx
    get_extended.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    get_extended.restype = wintypes.BOOL
    if not get_extended(
        wintypes.HANDLE(handle),
        0,
        ctypes.byref(basic),
        ctypes.sizeof(basic),
    ):
        raise ctypes.WinError()
    return WindowsFileSnapshot(
        object_identity=_file_id(handle),
        size=(int(standard.file_size_high) << 32) | int(standard.file_size_low),
        mtime_ns=int(basic.last_write_time) * 100,
        ctime_ns=int(basic.change_time) * 100,
    )


def hash_handle(handle: int) -> tuple[str, bytes]:
    set_pointer = ctypes.windll.kernel32.SetFilePointerEx
    set_pointer.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    set_pointer.restype = wintypes.BOOL
    if not set_pointer(wintypes.HANDLE(handle), 0, None, 0):
        raise ctypes.WinError()
    read_file = ctypes.windll.kernel32.ReadFile
    read_file.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    read_file.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(HASH_CHUNK_BYTES)
    received = wintypes.DWORD()
    digest = hashlib.sha256()
    prefix = bytearray()
    total = 0
    while True:
        if not read_file(
            wintypes.HANDLE(handle),
            buffer,
            len(buffer),
            ctypes.byref(received),
            None,
        ):
            raise ctypes.WinError()
        if received.value == 0:
            break
        chunk = buffer.raw[: received.value]
        total += len(chunk)
        if total > MAX_EXECUTABLE_BYTES:
            raise OSError("executable exceeds the authorization byte ceiling")
        if len(prefix) < 64:
            prefix.extend(chunk[: 64 - len(prefix)])
        digest.update(chunk)
    if not set_pointer(wintypes.HANDLE(handle), 0, None, 0):
        raise ctypes.WinError()
    return digest.hexdigest(), bytes(prefix)


def final_path(handle: int) -> Path:
    get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_final_path.restype = wintypes.DWORD
    required = get_final_path(wintypes.HANDLE(handle), None, 0, 0)
    if required == 0:
        raise ctypes.WinError()
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = get_final_path(wintypes.HANDLE(handle), buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        raise ctypes.WinError()
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def close_handle(handle: int) -> None:
    if os.name != "nt":
        return
    close = ctypes.windll.kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    close(wintypes.HANDLE(handle))


def _file_id(handle: int) -> tuple[int, bytes]:
    information = _FileIdInfo()
    get_information = ctypes.windll.kernel32.GetFileInformationByHandleEx
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    get_information.restype = wintypes.BOOL
    if not get_information(
        wintypes.HANDLE(handle),
        _FILE_ID_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ctypes.WinError()
    return int(information.volume_serial_number), bytes(information.file_id)


def _atomic_launch_unavailable() -> None:
    raise DocumentSkillsError(
        ErrorCode.RUNTIME_UNAVAILABLE,
        "Atomic executable launch requires a local fixed Windows volume.",
        details={"reason_category": "atomic_launch_unavailable"},
    )


class _FileIdInfo(ctypes.Structure):
    _fields_ = [
        ("volume_serial_number", ctypes.c_ulonglong),
        ("file_id", ctypes.c_ubyte * 16),
    ]


class _FileBasicInfo(ctypes.Structure):
    _fields_ = [
        ("creation_time", ctypes.c_longlong),
        ("last_access_time", ctypes.c_longlong),
        ("last_write_time", ctypes.c_longlong),
        ("change_time", ctypes.c_longlong),
        ("file_attributes", wintypes.DWORD),
    ]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("creation_time", wintypes.FILETIME),
        ("last_access_time", wintypes.FILETIME),
        ("last_write_time", wintypes.FILETIME),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    ]
