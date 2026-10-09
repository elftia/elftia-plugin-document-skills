"""FUSE callbacks enforcing quotas before each filesystem mutation.

All callbacks run under one session lock. No links, devices, xattrs,
ioctls, writable mmap/writeback caching, or native copy/allocation shortcuts are
exposed. Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

import ctypes as c
import errno
import os
import stat
import threading

from ._quota_fuse_abi import (
    Filler, FuseConfig, InfoPointer, LinuxStat, LinuxStatVfs, OPERATION_NAMES, Operations,
    Timespec,
)
from ._quota_store import QuotaStore, refuse


class FuseCallbacks:
    def __init__(self, store: QuotaStore) -> None:
        self.store = store
        self.ready = threading.Event()
        self.references = []
        self.operations = Operations()
        p = c.c_char_p
        v = c.c_void_p
        i = c.c_int
        u = c.c_uint
        f = InfoPointer
        signatures = {
            "getattr": (p, c.POINTER(LinuxStat), f),
            "mknod": (p, u, c.c_ulong), "mkdir": (p, u),
            "unlink": (p,), "rmdir": (p,), "symlink": (p, p), "link": (p, p),
            "rename": (p, p, u), "chmod": (p, u, f), "chown": (p, u, u, f),
            "truncate": (p, c.c_long, f), "open": (p, f),
            "read": (p, v, c.c_size_t, c.c_long, f),
            "write": (p, v, c.c_size_t, c.c_long, f),
            "statfs": (p, c.POINTER(LinuxStatVfs)),
            "flush": (p, f), "release": (p, f), "fsync": (p, i, f),
            "opendir": (p, f), "readdir": (p, v, Filler, c.c_long, f, i),
            "releasedir": (p, f), "fsyncdir": (p, i, f),
            "access": (p, i), "create": (p, u, f),
            "utimens": (p, c.POINTER(Timespec), f),
        }
        methods = {
            "getattr": self.getattr, "mknod": self.mknod, "mkdir": self.mkdir,
            "unlink": self.unlink, "rmdir": self.rmdir, "symlink": self.symlink,
            "link": self.link, "rename": self.rename, "chmod": self.chmod,
            "chown": self.chown, "truncate": self.truncate, "open": self.open,
            "read": self.read, "write": self.write, "statfs": self.statfs,
            "flush": self.flush, "release": self.release, "fsync": self.fsync,
            "opendir": self.opendir, "readdir": self.readdir, "releasedir": self.releasedir,
            "fsyncdir": self.fsyncdir, "access": self.access, "create": self.create,
            "utimens": self.utimens,
        }
        for name, arguments in signatures.items():
            callback = c.CFUNCTYPE(i, *arguments)(self._guard(methods[name]))
            self.references.append(callback)
            self.operations[OPERATION_NAMES.index(name)] = c.cast(callback, v)
        init = c.CFUNCTYPE(v, v, c.POINTER(FuseConfig))(self._init)
        self.references.append(init)
        self.operations[OPERATION_NAMES.index("init")] = c.cast(init, v)

    def _guard(self, function):
        def callback(*args):
            with self.store.lock:
                if self.store.failed:
                    return -errno.EIO
                try:
                    return function(*args)
                except OSError as error:
                    return -(error.errno or errno.EIO)
                except BaseException:
                    self.store.failed = True
                    return -errno.EIO
        return callback

    def _init(self, _connection, config):
        settings = config.contents
        # libfuse retains an unlinked open file under its private hidden name
        # until release. Its bytes and entry stay charged during that period.
        # hard_remove breaks fstat on Linux requests without a supplied fh.
        settings.hard_remove = 0
        settings.direct_io = 0  # Per-handle direct I/O below; read-only mmap is safe.
        settings.nullpath_ok = 1
        settings.use_ino = 1
        settings.kernel_cache = settings.auto_cache = 0
        self.ready.set()
        return None

    @staticmethod
    def _path(path):
        return os.fsdecode(path) if path is not None else None

    def _node(self, path, info=None):
        handle = info.contents.handle if info else 0
        return self.store.lookup(self._path(path), handle)

    def getattr(self, path, result, info):
        node = self._node(path, info)
        metadata = result.contents
        metadata.inode = node.inode
        metadata.mode = node.mode
        metadata.links = 2 if node.directory else int(node.linked)
        metadata.uid, metadata.gid = os.getuid(), os.getgid()
        metadata.size = 0 if node.directory else len(node.data)
        metadata.blocksize = 4096
        metadata.blocks = (metadata.size + 511) // 512
        for field in (metadata.accessed, metadata.modified, metadata.changed):
            field.seconds, field.nanoseconds = divmod(node.modified_ns, 1_000_000_000)
        return 0

    def mkdir(self, path, mode):
        self.store.create(self._path(path), stat.S_IFDIR | (mode & 0o700))
        return 0

    def mknod(self, *_args):
        refuse(errno.EPERM)

    symlink = mknod
    link = mknod

    def create(self, path, mode, info):
        name = self._path(path)
        self.store.create(name, stat.S_IFREG | (mode & 0o600))
        try:
            return self.open(path, info)
        except BaseException:
            self.store.remove(name)
            raise

    def open(self, path, info):
        info.contents.handle = self.store.open(self._path(path), info.contents.flags)
        if info.contents.flags & (os.O_WRONLY | os.O_RDWR):
            info.contents.bits |= 2  # Every writable handle uses synchronous direct I/O.
        else:
            info.contents.bits &= ~2  # Read-only mappings cannot grow persistent storage.
        return 0

    def read(self, path, buffer, size, offset, info):
        node = self._node(path, info)
        if offset < 0:
            refuse(errno.EINVAL)
        payload = bytes(node.data[offset:offset + size])
        c.memmove(buffer, payload, len(payload))
        return len(payload)

    def write(self, _path, buffer, size, offset, info):
        handle = info.contents.handle
        node, flags = self.store.handles[handle]
        end = (len(node.data) if flags & os.O_APPEND else offset) + size
        if offset < 0:
            refuse(errno.EINVAL)
        if self.store.total_bytes + max(0, end - len(node.data)) > self.store.byte_limit:
            self.store.deny_quota()
        return self.store.write(handle, offset, c.string_at(buffer, size))

    def truncate(self, path, size, info):
        self.store.resize(self._node(path, info), size)
        return 0

    def unlink(self, path):
        self.store.remove(self._path(path))
        return 0

    def rmdir(self, path):
        self.store.remove(self._path(path), directory=True)
        return 0

    def rename(self, source, target, flags):
        self.store.rename(self._path(source), self._path(target), flags)
        return 0

    def release(self, _path, info):
        self.store.release(info.contents.handle)
        return 0

    def chmod(self, path, mode, info):
        node = self._node(path, info)
        node.mode = stat.S_IFMT(node.mode) | (mode & 0o700)
        return 0

    def chown(self, path, uid, gid, info):
        self._node(path, info)
        if uid not in {os.getuid(), 0xFFFFFFFF} or gid not in {os.getgid(), 0xFFFFFFFF}:
            refuse(errno.EPERM)
        return 0

    def utimens(self, path, times, info):
        node = self._node(path, info)
        if times and times[1].nanoseconds < 1_000_000_000:
            node.modified_ns = times[1].seconds * 1_000_000_000 + times[1].nanoseconds
        return 0

    def statfs(self, _path, result):
        values = result.contents
        values.blocksize, values.fragmentsize = 4096, 1
        values.blocks = self.store.byte_limit
        values.free = values.available = self.store.byte_limit - self.store.total_bytes
        values.files = self.store.entry_limit
        values.files_free = values.files_available = self.store.entry_limit - self.store.entry_count
        values.namemax = 255
        return 0

    def readdir(self, path, buffer, filler, offset, info, _flags):
        node = self._node(path, info)
        names = [".", ".."]
        for key, value in self.store.paths.items():
            if value is node:
                names.extend(self.store.children(key))
                break
        for index in range(offset, len(names)):
            if filler(buffer, os.fsencode(names[index]), None, index + 1, 0):
                break
        return 0

    def opendir(self, path, info):
        info.contents.handle = self.store.open(self._path(path), os.O_RDONLY, directory=True)
        return 0

    def access(self, path, _mode):
        self._node(path)
        return 0  # Kernel default_permissions performs the actual permission check.

    @staticmethod
    def flush(*_args):
        return 0

    fsync = flush
    fsyncdir = flush
    releasedir = release
