"""Narrow libfuse 3 ABI for Linux x86-64/glibc; other ABIs fail closed.

Layout follows the public libfuse 3.14 headers and glibc x86-64 stat ABI.
No FUSE library code is copied or bundled. Module provenance: original
Elftia-authored clean-room implementation.
"""

import ctypes as c


class Timespec(c.Structure):
    _fields_ = [("seconds", c.c_long), ("nanoseconds", c.c_long)]


class LinuxStat(c.Structure):
    _fields_ = [
        ("device", c.c_ulong), ("inode", c.c_ulong), ("links", c.c_ulong),
        ("mode", c.c_uint), ("uid", c.c_uint), ("gid", c.c_uint),
        ("padding", c.c_int), ("rdev", c.c_ulong), ("size", c.c_long),
        ("blocksize", c.c_long), ("blocks", c.c_long),
        ("accessed", Timespec), ("modified", Timespec), ("changed", Timespec),
        ("reserved", c.c_long * 3),
    ]


class LinuxStatVfs(c.Structure):
    _fields_ = [(name, c.c_ulong) for name in (
        "blocksize", "fragmentsize", "blocks", "free", "available",
        "files", "files_free", "files_available", "fsid", "flags", "namemax",
    )] + [("reserved", c.c_int * 6)]


class FileInfo(c.Structure):
    _fields_ = [
        ("flags", c.c_int), ("bits", c.c_uint), ("padding2", c.c_uint),
        ("handle", c.c_uint64), ("lock_owner", c.c_uint64),
        ("poll_events", c.c_uint32),
    ]


class FuseArgs(c.Structure):
    _fields_ = [("count", c.c_int), ("values", c.POINTER(c.c_char_p)), ("allocated", c.c_int)]


class FuseConfig(c.Structure):
    _fields_ = [
        ("set_gid", c.c_int), ("gid", c.c_uint),
        ("set_uid", c.c_int), ("uid", c.c_uint),
        ("set_mode", c.c_int), ("umask", c.c_uint),
        ("entry_timeout", c.c_double), ("negative_timeout", c.c_double),
        ("attr_timeout", c.c_double), ("intr", c.c_int),
        ("intr_signal", c.c_int), ("remember", c.c_int),
        ("hard_remove", c.c_int), ("use_ino", c.c_int),
        ("readdir_ino", c.c_int), ("direct_io", c.c_int),
        ("kernel_cache", c.c_int), ("auto_cache", c.c_int),
        ("no_rofd_flush", c.c_int), ("ac_attr_timeout_set", c.c_int),
        ("ac_attr_timeout", c.c_double), ("nullpath_ok", c.c_int),
    ]


# The prefix ends at utimens. libfuse zero-fills all subsequent operations.
OPERATION_NAMES = (
    "getattr", "readlink", "mknod", "mkdir", "unlink", "rmdir", "symlink",
    "rename", "link", "chmod", "chown", "truncate", "open", "read", "write",
    "statfs", "flush", "release", "fsync", "setxattr", "getxattr", "listxattr",
    "removexattr", "opendir", "readdir", "releasedir", "fsyncdir", "init",
    "destroy", "access", "create", "lock", "utimens",
)
Operations = c.c_void_p * len(OPERATION_NAMES)
InfoPointer = c.POINTER(FileInfo)
Filler = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_char_p, c.c_void_p, c.c_long, c.c_int)


def load_fuse(library_path: str):
    if (c.sizeof(LinuxStat), c.sizeof(LinuxStatVfs), c.sizeof(FileInfo)) != (144, 112, 40):
        raise OSError("Unsupported Linux FUSE ABI.")
    library = c.CDLL(library_path, use_errno=True)
    declarations = [
        (library.fuse_version, [], c.c_int),
        (library.fuse_new, [c.POINTER(FuseArgs), c.c_void_p, c.c_size_t, c.c_void_p], c.c_void_p),
        (library.fuse_mount, [c.c_void_p, c.c_char_p], c.c_int),
        (library.fuse_loop, [c.c_void_p], c.c_int),
        (library.fuse_exit, [c.c_void_p], None),
        (library.fuse_unmount, [c.c_void_p], None),
        (library.fuse_destroy, [c.c_void_p], None),
        (library.fuse_opt_free_args, [c.POINTER(FuseArgs)], None),
    ]
    for function, arguments, result in declarations:
        function.argtypes = arguments
        function.restype = result
    if not 314 <= library.fuse_version() < 400:
        raise OSError("libfuse 3.14 or newer is required.")
    return library
