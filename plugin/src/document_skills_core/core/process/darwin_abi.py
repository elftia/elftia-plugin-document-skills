"""Fixed Darwin spawn/libproc ABI; no user-selected library or symbol."""

import ctypes


PROC_PIDREGIONPATHINFO = 8
MAX_PATH_BYTES = 1024
SPAWN_FLAGS = (
    0x0080  # POSIX_SPAWN_START_SUSPENDED
    | 0x0400  # POSIX_SPAWN_SETSID
    | 0x4000  # POSIX_SPAWN_CLOEXEC_DEFAULT
    | 0x0004  # POSIX_SPAWN_SETSIGDEF
    | 0x0008  # POSIX_SPAWN_SETSIGMASK
)


class RegionInfo(ctypes.Structure):
    _fields_ = [
        ("protection", ctypes.c_uint32),
        ("max_protection", ctypes.c_uint32),
        ("inheritance", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("offset", ctypes.c_uint64),
        ("behavior", ctypes.c_uint32),
        ("user_wired_count", ctypes.c_uint32),
        ("user_tag", ctypes.c_uint32),
        ("pages_resident", ctypes.c_uint32),
        ("pages_shared_now_private", ctypes.c_uint32),
        ("pages_swapped_out", ctypes.c_uint32),
        ("pages_dirtied", ctypes.c_uint32),
        ("ref_count", ctypes.c_uint32),
        ("shadow_depth", ctypes.c_uint32),
        ("share_mode", ctypes.c_uint32),
        ("private_pages_resident", ctypes.c_uint32),
        ("shared_pages_resident", ctypes.c_uint32),
        ("object_id", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
        ("address", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
    ]


class VnodeStat(ctypes.Structure):
    _fields_ = [
        ("device", ctypes.c_uint32),
        ("mode", ctypes.c_uint16),
        ("links", ctypes.c_uint16),
        ("inode", ctypes.c_uint64),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("atime", ctypes.c_int64),
        ("atime_nsec", ctypes.c_int64),
        ("mtime", ctypes.c_int64),
        ("mtime_nsec", ctypes.c_int64),
        ("ctime", ctypes.c_int64),
        ("ctime_nsec", ctypes.c_int64),
        ("birthtime", ctypes.c_int64),
        ("birthtime_nsec", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("blocks", ctypes.c_int64),
        ("blocksize", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("generation", ctypes.c_uint32),
        ("rdevice", ctypes.c_uint32),
        ("spare", ctypes.c_int64 * 2),
    ]


class VnodeInfo(ctypes.Structure):
    _fields_ = [
        ("stat", VnodeStat),
        ("type", ctypes.c_int32),
        ("padding", ctypes.c_int32),
        ("filesystem_id", ctypes.c_int32 * 2),
    ]


class VnodePath(ctypes.Structure):
    _fields_ = [("vnode", VnodeInfo), ("path", ctypes.c_char * MAX_PATH_BYTES)]


class RegionPathInfo(ctypes.Structure):
    _fields_ = [("region", RegionInfo), ("file", VnodePath)]


class DarwinAPI:
    def __init__(self) -> None:
        self.libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        self.libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        pointer = ctypes.POINTER(ctypes.c_void_p)
        strings = ctypes.POINTER(ctypes.c_char_p)
        signal_set = ctypes.POINTER(ctypes.c_uint32)
        signatures = [
            (
                self.libc.posix_spawn,
                [ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, pointer, pointer, strings, strings],
            ),
            (self.libc.posix_spawn_file_actions_init, [pointer]),
            (self.libc.posix_spawn_file_actions_destroy, [pointer]),
            (self.libc.posix_spawn_file_actions_adddup2, [pointer, ctypes.c_int, ctypes.c_int]),
            (self.libc.posix_spawn_file_actions_addclose, [pointer, ctypes.c_int]),
            (self.libc.posix_spawn_file_actions_addinherit_np, [pointer, ctypes.c_int]),
            (self.libc.posix_spawn_file_actions_addchdir_np, [pointer, ctypes.c_char_p]),
            (self.libc.posix_spawnattr_init, [pointer]),
            (self.libc.posix_spawnattr_destroy, [pointer]),
            (self.libc.posix_spawnattr_setflags, [pointer, ctypes.c_short]),
            (self.libc.posix_spawnattr_setsigdefault, [pointer, signal_set]),
            (self.libc.posix_spawnattr_setsigmask, [pointer, signal_set]),
            (self.libc.sigemptyset, [signal_set]),
            (self.libc.sigaddset, [signal_set, ctypes.c_int]),
            # Only the two fixed arguments belong in a variadic signature.
            (self.libc.fcntl, [ctypes.c_int, ctypes.c_int]),
            (self.libproc.proc_pidpath, [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]),
            (
                self.libproc.proc_pidinfo,
                [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int],
            ),
        ]
        for function, arguments in signatures:
            function.argtypes = arguments
            function.restype = ctypes.c_int
