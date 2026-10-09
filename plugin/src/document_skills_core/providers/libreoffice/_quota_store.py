"""Serialized, logical-byte quota filesystem state (no backing disk tree).

Every growth and namespace mutation is checked before committing. Unlinked
open files continue to consume both quotas until their last handle closes.
Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

import errno
import os
import stat
import threading
import time
from dataclasses import dataclass, field


def refuse(code: int) -> None:
    raise OSError(code, os.strerror(code))


@dataclass
class Node:
    inode: int
    mode: int
    data: bytearray = field(default_factory=bytearray)
    opened: int = 0
    linked: bool = True
    modified_ns: int = field(default_factory=time.time_ns)

    @property
    def directory(self) -> bool:
        return stat.S_ISDIR(self.mode)


class QuotaStore:
    """One private filesystem; callers serialize callbacks with ``lock``."""

    def __init__(self, byte_limit: int, entry_limit: int) -> None:
        if type(byte_limit) is not int or not 0 < byte_limit <= 512 * 1024 * 1024:
            raise ValueError("Quota bytes must be between 1 and 512 MiB.")
        if type(entry_limit) is not int or not 1 <= entry_limit <= 4096:
            raise ValueError("Quota entries must be between 1 and 4096.")
        self.byte_limit = byte_limit
        self.entry_limit = entry_limit
        self.total_bytes = 0
        self.entry_count = 0
        self.next_inode = 2
        self.next_handle = 1
        self.paths = {"/": Node(1, stat.S_IFDIR | 0o700)}
        self.handles: dict[int, tuple[Node, int]] = {}
        self.lock = threading.RLock()
        self.denials = 0
        self.failed = False

    def deny_quota(self) -> None:
        self.denials += 1
        refuse(errno.ENOSPC)

    def lookup(self, path: str | None, handle: int = 0) -> Node:
        if handle:
            try:
                return self.handles[handle][0]
            except KeyError:
                refuse(errno.EBADF)
        try:
            return self.paths[path]
        except KeyError:
            refuse(errno.ENOENT)

    def children(self, path: str) -> list[str]:
        if not self.lookup(path).directory:
            refuse(errno.ENOTDIR)
        prefix = path.rstrip("/") + "/"
        return sorted(
            key[len(prefix):] for key in self.paths
            if key.startswith(prefix) and "/" not in key[len(prefix):]
            and key != "/"
        )

    def create(self, path: str, mode: int) -> Node:
        if path in self.paths:
            refuse(errno.EEXIST)
        if not path.startswith("/") or path.endswith("/") or len(path) > 4096:
            refuse(errno.EINVAL)
        parent, _, name = path.rpartition("/")
        if name in {"", ".", ".."} or len(os.fsencode(name)) > 255:
            refuse(errno.EINVAL)
        if not self.lookup(parent or "/").directory:
            refuse(errno.ENOTDIR)
        if self.entry_count >= self.entry_limit:
            self.deny_quota()
        node = Node(self.next_inode, mode)
        self.next_inode += 1
        self.paths[path] = node
        self.entry_count += 1
        return node

    def open(self, path: str, flags: int, *, directory: bool = False) -> int:
        node = self.lookup(path)
        if node.directory != directory:
            refuse(errno.EISDIR if node.directory else errno.ENOTDIR)
        if len(self.handles) >= self.entry_limit * 8:
            refuse(errno.EMFILE)
        if flags & os.O_TRUNC and not directory:
            self.resize(node, 0)
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = (node, flags)
        node.opened += 1
        return handle

    def resize(self, node: Node, size: int) -> None:
        if node.directory:
            refuse(errno.EISDIR)
        if size < 0:
            refuse(errno.EINVAL)
        growth = size - len(node.data)
        if self.total_bytes + growth > self.byte_limit:
            self.deny_quota()
        if growth > 0:
            node.data.extend(b"\0" * growth)
        elif growth < 0:
            del node.data[size:]
        self.total_bytes += growth
        node.modified_ns = time.time_ns()

    def write(self, handle: int, offset: int, payload: bytes) -> int:
        node, flags = self.handles[handle]
        if flags & (os.O_WRONLY | os.O_RDWR) == os.O_RDONLY:
            refuse(errno.EBADF)
        if flags & os.O_APPEND:
            offset = len(node.data)
        if offset < 0:
            refuse(errno.EINVAL)
        if not payload:
            return 0
        end = offset + len(payload)
        if end > len(node.data):
            self.resize(node, end)
        node.data[offset:end] = payload
        node.modified_ns = time.time_ns()
        return len(payload)

    def remove(self, path: str, *, directory: bool = False) -> None:
        if path in {"/", "/output", "/profile", "/temporary", "/home"}:
            refuse(errno.EPERM)
        node = self.lookup(path)
        if node.directory != directory:
            refuse(errno.ENOTDIR if directory else errno.EISDIR)
        if directory and self.children(path):
            refuse(errno.ENOTEMPTY)
        del self.paths[path]
        node.linked = False
        self._discard(node)

    def release(self, handle: int) -> None:
        node, _flags = self.handles.pop(handle)
        node.opened -= 1
        self._discard(node)

    def _discard(self, node: Node) -> None:
        if not node.linked and not node.opened:
            self.total_bytes -= len(node.data)
            self.entry_count -= 1
            node.data.clear()

    def rename(self, source: str, target: str, flags: int) -> None:
        protected = {"/", "/output", "/profile", "/temporary", "/home"}
        if source in protected or target in protected:
            refuse(errno.EPERM)
        if flags & ~1:  # RENAME_NOREPLACE only; exchange is deliberately denied.
            refuse(errno.EINVAL)
        node = self.lookup(source)
        if source == target:
            return
        if target.startswith(source + "/"):
            refuse(errno.EINVAL)
        parent = target.rpartition("/")[0] or "/"
        if not self.lookup(parent).directory:
            refuse(errno.ENOTDIR)
        previous = self.paths.get(target)
        moving = [key for key in self.paths if key == source or key.startswith(source + "/")]
        if any(len(target + key[len(source):]) > 4096 for key in moving):
            refuse(errno.ENAMETOOLONG)
        if previous is not None:
            if flags & 1:
                refuse(errno.EEXIST)
            if previous.directory != node.directory:
                refuse(errno.ENOTDIR if node.directory else errno.EISDIR)
            if previous.directory and self.children(target):
                refuse(errno.ENOTEMPTY)
            self.remove(target, directory=previous.directory)
        replacements = {target + key[len(source):]: self.paths[key] for key in moving}
        for key in moving:
            del self.paths[key]
        self.paths.update(replacements)
