"""Windows file allocation accounting on the bounded shared memory store.

Allocation reservations are charged before acceptance, including mapped-file
growth. Logical EOF never exceeds the charged allocation. Names are case
insensitive and case preserving; alternate streams and reparse points are
not offered. Module provenance: original Elftia-authored implementation.
"""

from __future__ import annotations

import errno
import stat
import time

from ._quota_store import Node, QuotaStore, refuse

PROTECTED = {"/", "/output", "/profile", "/temporary", "/home"}
SECTOR = 512


def canonical_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("\\"):
        refuse(errno.EINVAL)
    parts = value[1:].split("\\") if value != "\\" else []
    for part in parts:
        stem = part.split(".", 1)[0].casefold()
        if (
            not part or part in {".", ".."} or part.endswith((" ", "."))
            or any(ord(char) < 32 or char in '/:<>"|?*' for char in part)
            or stem in {"con", "prn", "aux", "nul"}
            or (len(stem) == 4 and stem[:3] in {"com", "lpt"} and stem[3] in "123456789")
        ):
            refuse(errno.EINVAL)
    return "/" + "/".join(part.casefold() for part in parts)


class WindowsQuotaStore(QuotaStore):
    def __init__(self, byte_limit: int, entry_limit: int) -> None:
        super().__init__(byte_limit, entry_limit)
        self.nodes = {1: self.paths["/"]}
        self.names = {1: ""}
        self.sizes = {1: 0}
        self.attributes = {1: 0x10}
        self.times = {}

    def create_windows(self, name: str, directory: bool, attributes: int, allocation: int) -> Node:
        path = canonical_path(name)
        if allocation > self.byte_limit:
            self.deny_quota()
        node = self.create(path, (stat.S_IFDIR | 0o700) if directory else (stat.S_IFREG | 0o600))
        try:
            if not directory:
                self.reserve(node, allocation)
        except BaseException:
            self.remove(path, directory=directory)
            raise
        self.nodes[node.inode] = node
        self.names[node.inode] = name.rsplit("\\", 1)[-1]
        self.sizes[node.inode] = 0
        self.attributes[node.inode] = (attributes & 0x2127) | (0x10 if directory else 0x20)
        return node

    def reserve(self, node: Node, size: int) -> None:
        if size < 0:
            refuse(errno.EINVAL)
        allocation = ((size + SECTOR - 1) // SECTOR) * SECTOR
        self.resize(node, allocation)

    def set_size(self, node: Node, size: int, allocation: bool) -> None:
        if node.directory:
            refuse(errno.EISDIR)
        old = self.sizes[node.inode]
        if allocation:
            self.reserve(node, size)
            self.sizes[node.inode] = min(old, size)
        else:
            if size < 0:
                refuse(errno.EINVAL)
            if size > len(node.data):
                self.reserve(node, size)
            if size > old:
                node.data[old:size] = b"\0" * (size - old)
            self.sizes[node.inode] = size
        node.modified_ns = time.time_ns()

    def open_node(self, node: Node) -> None:
        if sum(item.opened for item in self.nodes.values()) >= self.entry_limit * 8:
            refuse(errno.EMFILE)
        node.opened += 1

    def close_node(self, node: Node) -> None:
        if node.opened < 1:
            refuse(errno.EBADF)
        node.opened -= 1
        self._discard(node)
        if not node.linked and not node.opened:
            for mapping in (self.nodes, self.names, self.sizes, self.attributes, self.times):
                mapping.pop(node.inode, None)

    def node(self, context: int) -> Node:
        try:
            return self.nodes[int(context)]
        except (KeyError, TypeError, ValueError):
            refuse(errno.EBADF)

    def path_for(self, node: Node) -> str:
        for name, candidate in self.paths.items():
            if candidate is node:
                return name
        refuse(errno.ENOENT)

    def can_delete(self, node: Node) -> None:
        path = self.path_for(node)
        if path in PROTECTED:
            refuse(errno.EPERM)
        if node.directory and self.children(path):
            refuse(errno.ENOTEMPTY)

    def unlink_node(self, node: Node) -> None:
        if not node.linked:
            return
        self.can_delete(node)
        self.remove(self.path_for(node), directory=node.directory)

    def rename_windows(self, node: Node, source: str, target: str, replace: bool) -> None:
        before, after = canonical_path(source), canonical_path(target)
        if self.lookup(before) is not node:
            refuse(errno.ENOENT)
        if before == after and before in PROTECTED:
            refuse(errno.EPERM)
        previous = self.paths.get(after)
        self.rename(before, after, 0 if replace else 1)
        self.names[node.inode] = target.rsplit("\\", 1)[-1]
        if previous is not None and previous is not node and not previous.opened:
            for mapping in (self.nodes, self.names, self.sizes, self.attributes, self.times):
                mapping.pop(previous.inode, None)

    def write_windows(self, node: Node, offset: int, payload: bytes, constrained: bool) -> int:
        if node.directory:
            refuse(errno.EISDIR)
        if offset < 0:
            refuse(errno.EINVAL)
        if not payload:
            return 0
        size = self.sizes[node.inode]
        if constrained:
            payload = payload[:max(0, size - offset)]
        elif offset + len(payload) > size:
            self.set_size(node, offset + len(payload), False)
        if payload:
            node.data[offset:offset + len(payload)] = payload
            node.modified_ns = time.time_ns()
        return len(payload)
