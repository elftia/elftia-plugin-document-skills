"""WinFsp 2.1 x64 public ABI, checked against the versioned upstream headers.

Elftia-authored binding; WinFsp implementation code is not included.
"""

from __future__ import annotations

import ctypes as c

U16, U32, U64 = c.c_uint16, c.c_uint32, c.c_uint64
PTR, STATUS, BOOL = c.c_void_p, c.c_int32, c.c_ubyte
PPTR, PU32, PSIZE = c.POINTER(PTR), c.POINTER(U32), c.POINTER(c.c_size_t)


class VolumeParameters(c.Structure):
    _fields_ = [
        ("Version", U16), ("SectorSize", U16),
        ("SectorsPerAllocationUnit", U16), ("MaxComponentLength", U16),
        ("VolumeCreationTime", U64), ("VolumeSerialNumber", U32),
        ("TransactTimeout", U32), ("IrpTimeout", U32), ("IrpCapacity", U32),
        ("FileInfoTimeout", U32), ("Flags", U32),
        ("Prefix", U16 * 192), ("FileSystemName", U16 * 16),
        ("AdditionalFlags", U32), ("VolumeInfoTimeout", U32),
        ("DirInfoTimeout", U32), ("SecurityTimeout", U32),
        ("StreamInfoTimeout", U32), ("EaTimeout", U32),
        ("FsextControlCode", U32), ("Reserved32", U32),
        ("Reserved64", U64 * 2),
    ]


class VolumeInfo(c.Structure):
    _fields_ = [
        ("TotalSize", U64), ("FreeSize", U64),
        ("VolumeLabelLength", U16), ("VolumeLabel", U16 * 32),
    ]


class FileInfo(c.Structure):
    _fields_ = [
        ("FileAttributes", U32), ("ReparseTag", U32),
        ("AllocationSize", U64), ("FileSize", U64),
        ("CreationTime", U64), ("LastAccessTime", U64),
        ("LastWriteTime", U64), ("ChangeTime", U64),
        ("IndexNumber", U64), ("HardLinks", U32), ("EaSize", U32),
    ]


class DirectoryInfo(c.Structure):
    _fields_ = [("Size", U16), ("FileInfo", FileInfo), ("Padding", c.c_ubyte * 24)]


class Interface(c.Structure):
    _fields_ = [("Callbacks", PTR * 64)]


class FileSystemHeader(c.Structure):
    _fields_ = [
        ("Version", U16), ("UserContext", PTR),
        ("VolumeName", U16 * 256), ("VolumeHandle", PTR),
    ]


PFILE, PVOLUME = c.POINTER(FileInfo), c.POINTER(VolumeInfo)
INTERFACE_NAMES = (
    "GetVolumeInfo", "SetVolumeLabel", "GetSecurityByName", "Create", "Open",
    "Overwrite", "Cleanup", "Close", "Read", "Write", "Flush", "GetFileInfo",
    "SetBasicInfo", "SetFileSize", "CanDelete", "Rename", "GetSecurity",
    "SetSecurity", "ReadDirectory", "ResolveReparsePoints", "GetReparsePoint",
    "SetReparsePoint", "DeleteReparsePoint", "GetStreamInfo", "GetDirInfoByName",
    "Control", "SetDelete", "CreateEx", "OverwriteEx", "GetEa", "SetEa",
    "Obsolete0", "DispatcherStopped",
)
CALLBACK_ARGUMENTS = {
    "GetVolumeInfo": (PTR, PVOLUME),
    "GetSecurityByName": (PTR, c.c_wchar_p, PU32, PTR, PSIZE),
    "Create": (PTR, c.c_wchar_p, U32, U32, U32, PTR, U64, PPTR, PFILE),
    "Open": (PTR, c.c_wchar_p, U32, U32, PPTR, PFILE),
    "Overwrite": (PTR, PTR, U32, BOOL, U64, PFILE),
    "Cleanup": (PTR, PTR, c.c_wchar_p, U32),
    "Close": (PTR, PTR),
    "Read": (PTR, PTR, PTR, U64, U32, PU32),
    "Write": (PTR, PTR, PTR, U64, U32, BOOL, BOOL, PU32, PFILE),
    "Flush": (PTR, PTR, PFILE),
    "GetFileInfo": (PTR, PTR, PFILE),
    "SetBasicInfo": (PTR, PTR, U32, U64, U64, U64, U64, PFILE),
    "SetFileSize": (PTR, PTR, U64, BOOL, PFILE),
    "CanDelete": (PTR, PTR, c.c_wchar_p),
    "Rename": (PTR, PTR, c.c_wchar_p, c.c_wchar_p, BOOL),
    "GetSecurity": (PTR, PTR, PTR, PSIZE),
    "ReadDirectory": (PTR, PTR, c.c_wchar_p, c.c_wchar_p, PTR, U32, PU32),
    "SetDelete": (PTR, PTR, c.c_wchar_p, BOOL),
    "DispatcherStopped": (PTR, BOOL),
}
VOID_CALLBACKS = {"Cleanup", "Close", "DispatcherStopped"}


def utf16(target, value: str) -> int:
    data = value.encode("utf-16-le", errors="strict")
    if len(data) + 2 > c.sizeof(target):
        raise ValueError("WinFsp UTF-16 buffer is too small.")
    c.memset(c.addressof(target), 0, c.sizeof(target))
    c.memmove(c.addressof(target), data, len(data))
    return len(data)


def configure_library(library) -> None:
    signatures = [
        (library.FspVersion, STATUS, [PU32]),
        (library.FspFileSystemCreate, STATUS, [
            c.c_wchar_p, c.POINTER(VolumeParameters), c.POINTER(Interface), PPTR,
        ]),
        (library.FspFileSystemSetMountPoint, STATUS, [PTR, c.c_wchar_p]),
        (library.FspFileSystemMountPointF, c.c_wchar_p, [PTR]),
        (library.FspFileSystemRemoveMountPoint, None, [PTR]),
        (library.FspFileSystemStartDispatcher, STATUS, [PTR, U32]),
        (library.FspFileSystemStopDispatcher, None, [PTR]),
        (library.FspFileSystemDelete, None, [PTR]),
        (library.FspFileSystemSetOperationGuardStrategyF, None, [PTR, c.c_int32]),
        (library.FspFileSystemAddDirInfo, BOOL, [PTR, PTR, U32, PU32]),
    ]
    for function, result, arguments in signatures:
        function.restype, function.argtypes = result, arguments


def check_abi() -> None:
    expected = {VolumeParameters: 504, VolumeInfo: 88, FileInfo: 72, DirectoryInfo: 104}
    if c.sizeof(PTR) != 8 or any(c.sizeof(kind) != size for kind, size in expected.items()):
        raise OSError("WinFsp x64 ABI size mismatch.")
    if c.sizeof(Interface) != 512 or DirectoryInfo.FileInfo.offset != 8:
        raise OSError("WinFsp interface ABI offset mismatch.")
    if FileSystemHeader.VolumeName.offset != 16 or FileSystemHeader.VolumeHandle.offset != 528:
        raise OSError("WinFsp filesystem header ABI offset mismatch.")
