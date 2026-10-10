"""Quota-enforcing WinFsp callbacks; all mutations share one broker lock.

Windows cached and mapped growth uses the same allocation/EOF gate as
ordinary writes. Unexpected callback failures invalidate the session.
Module provenance: original Elftia-authored implementation.
"""

from __future__ import annotations

import ctypes as c
import errno
import threading

from ._quota_winfsp_abi import (
    CALLBACK_ARGUMENTS, INTERFACE_NAMES, VOID_CALLBACKS, DirectoryInfo,
    FileInfo, Interface, STATUS, utf16,
)
from ._quota_windows_store import PROTECTED, canonical_path

SUCCESS = 0
DISK_FULL = 0xC000007F
IO_ERROR = 0xC0000185
ACCESS_DENIED = 0xC0000022
ERRORS = {
    errno.ENOSPC: DISK_FULL, errno.ENOENT: 0xC0000034,
    errno.EEXIST: 0xC0000035, errno.EPERM: ACCESS_DENIED,
    errno.EACCES: ACCESS_DENIED, errno.ENOTDIR: 0xC0000103,
    errno.EISDIR: 0xC00000BA, errno.ENOTEMPTY: 0xC0000101,
    errno.EINVAL: 0xC000000D, errno.EBADF: 0xC0000008,
    errno.EMFILE: 0xC000009A, errno.ENAMETOOLONG: 0xC0000106,
}
WINDOWS_EPOCH = 116444736000000000
ALLOWED_ATTRIBUTES = 0x21B7


class WinFspCallbacks:
    def __init__(self, store, library, security: bytes) -> None:
        self.store, self.library, self.security = store, library, security
        self.interface = Interface()
        self.references = []
        self.stopped = threading.Event()
        self.expected_file_system = None
        methods = {
            "GetVolumeInfo": self._GetVolumeInfo, "GetSecurityByName": self._GetSecurityByName,
            "Create": self._Create, "Open": self._Open, "Overwrite": self._Overwrite,
            "Cleanup": self._Cleanup, "Close": self._Close, "Read": self._Read,
            "Write": self._Write, "Flush": self._Flush, "GetFileInfo": self._GetFileInfo,
            "SetBasicInfo": self._SetBasicInfo, "SetFileSize": self._SetFileSize,
            "CanDelete": self._CanDelete, "Rename": self._Rename, "GetSecurity": self._GetSecurity,
            "ReadDirectory": self._ReadDirectory, "SetDelete": self._SetDelete,
            "DispatcherStopped": self._DispatcherStopped,
        }
        for name, arguments in CALLBACK_ARGUMENTS.items():
            result = None if name in VOID_CALLBACKS else STATUS
            function = c.CFUNCTYPE(result, *arguments)(self._guard(name, methods[name]))
            self.references.append(function)
            self.interface.Callbacks[INTERFACE_NAMES.index(name)] = c.cast(function, c.c_void_p).value

    def _guard(self, name, method):
        void = name in VOID_CALLBACKS

        def invoke(file_system, *arguments):
            with self.store.lock:
                try:
                    if self.expected_file_system is not None and file_system != self.expected_file_system:
                        raise RuntimeError("WinFsp callback used an unexpected filesystem.")
                    if self.store.failed and name not in VOID_CALLBACKS:
                        return c.c_int32(IO_ERROR).value
                    value = method(*arguments)
                    return None if void else c.c_int32(value or SUCCESS).value
                except OSError as error:
                    if void:
                        self.store.failed = True
                        return None
                    code = ERRORS.get(error.errno)
                    if code is None:
                        self.store.failed = True
                    return c.c_int32(code or IO_ERROR).value
                except BaseException:
                    self.store.failed = True
                    return None if void else c.c_int32(IO_ERROR).value
        return invoke

    def _info(self, node) -> FileInfo:
        result = FileInfo()
        result.FileAttributes = self.store.attributes[node.inode]
        result.AllocationSize = len(node.data)
        result.FileSize = self.store.sizes[node.inode]
        stamp = WINDOWS_EPOCH + node.modified_ns // 100
        values = self.store.times.get(node.inode, (stamp,) * 4)
        result.CreationTime, result.LastAccessTime, result.LastWriteTime, result.ChangeTime = values
        result.IndexNumber = node.inode
        return result

    def _GetVolumeInfo(self, result):
        result.contents.TotalSize = self.store.byte_limit
        result.contents.FreeSize = self.store.byte_limit - self.store.total_bytes
        result.contents.VolumeLabelLength = utf16(result.contents.VolumeLabel, "ElftiaQuota")

    def _security(self, buffer, size):
        if not size:
            return SUCCESS
        capacity = size[0]
        size[0] = len(self.security)
        if capacity < len(self.security):
            return 0x80000005
        if buffer:
            c.memmove(buffer, self.security, len(self.security))
        return SUCCESS

    def _GetSecurityByName(self, name, attributes, buffer, size):
        node = self.store.lookup(canonical_path(name))
        if attributes:
            attributes[0] = self.store.attributes[node.inode]
        return self._security(buffer, size)

    def _GetSecurity(self, context, buffer, size):
        self.store.node(context)
        return self._security(buffer, size)

    def _Create(self, name, options, access, attributes, security, allocation, context, info):
        if attributes & ~ALLOWED_ATTRIBUTES:
            return ACCESS_DENIED
        if options & 0x1000 and canonical_path(name) in PROTECTED:
            return ACCESS_DENIED
        if sum(node.opened for node in self.store.nodes.values()) >= self.store.entry_limit * 8:
            return 0xC000009A
        node = self.store.create_windows(name, bool(options & 1), attributes, allocation)
        self.store.open_node(node)
        context[0] = node.inode
        info[0] = self._info(node)

    def _Open(self, name, options, access, context, info):
        path = canonical_path(name)
        if options & 0x1000 and path in PROTECTED:
            return ACCESS_DENIED
        node = self.store.lookup(path)
        if options & 1 and not node.directory:
            return 0xC0000103
        if options & 0x40 and node.directory:
            return 0xC00000BA
        self.store.open_node(node)
        context[0] = node.inode
        info[0] = self._info(node)

    def _Overwrite(self, context, attributes, replace, allocation, info):
        node = self.store.node(context)
        if attributes & ~ALLOWED_ATTRIBUTES or self.store.path_for(node) in PROTECTED:
            return ACCESS_DENIED
        # Reserve the new size before changing EOF, preserving old contents
        # and accounting if the reservation is rejected.
        self.store.reserve(node, allocation)
        self.store.sizes[node.inode] = 0
        self.store.attributes[node.inode] = (attributes & 0x2127) | 0x20 if replace else (self.store.attributes[node.inode] | (attributes & 0x2127))
        info[0] = self._info(node)

    def _Cleanup(self, context, name, flags):
        node = self.store.node(context)
        if flags & 2 and not node.directory:
            self.store.reserve(node, self.store.sizes[node.inode])
        if flags & 1:
            self.store.unlink_node(node)

    def _Close(self, context):
        self.store.close_node(self.store.node(context))

    def _Read(self, context, buffer, offset, length, transferred):
        transferred[0] = 0
        node = self.store.node(context)
        size = self.store.sizes[node.inode]
        if offset >= size and length:
            return 0xC0000011
        payload = bytes(node.data[offset:min(size, offset + length)])
        if payload:
            c.memmove(buffer, payload, len(payload))
        transferred[0] = len(payload)

    def _Write(self, context, buffer, offset, length, append, constrained, transferred, info):
        transferred[0] = 0
        node = self.store.node(context)
        if append:
            offset = self.store.sizes[node.inode]
        if constrained:
            length = min(length, max(0, self.store.sizes[node.inode] - offset))
        # Refuse impossible growth before copying a potentially large native
        # buffer; paging writes only modify bytes already charged.
        elif length and offset + length > self.store.byte_limit:
            self.store.deny_quota()
        if not constrained and length:
            allocation = ((offset + length + 511) // 512) * 512
            growth = max(0, allocation - len(node.data))
            if self.store.total_bytes + growth > self.store.byte_limit:
                self.store.deny_quota()
        payload = c.string_at(buffer, length) if length else b""
        transferred[0] = self.store.write_windows(node, offset, payload, bool(constrained))
        info[0] = self._info(node)

    def _Flush(self, context, info):
        if context:
            info[0] = self._info(self.store.node(context))

    def _GetFileInfo(self, context, info):
        info[0] = self._info(self.store.node(context))

    def _SetBasicInfo(self, context, attributes, creation, access, write, change, info):
        node = self.store.node(context)
        if attributes != 0xFFFFFFFF:
            if attributes & ~ALLOWED_ATTRIBUTES:
                return ACCESS_DENIED
            self.store.attributes[node.inode] = (attributes & 0x2127) | (0x10 if node.directory else 0x20)
        current = self._info(node)
        old = (current.CreationTime, current.LastAccessTime, current.LastWriteTime, current.ChangeTime)
        self.store.times[node.inode] = tuple(new or previous for new, previous in zip((creation, access, write, change), old))
        info[0] = self._info(node)

    def _SetFileSize(self, context, size, allocation, info):
        self.store.set_size(self.store.node(context), size, bool(allocation))
        info[0] = self._info(self.store.node(context))

    def _CanDelete(self, context, name):
        self.store.can_delete(self.store.node(context))

    def _SetDelete(self, context, name, delete):
        if delete:
            self.store.can_delete(self.store.node(context))

    def _Rename(self, context, before, after, replace):
        self.store.rename_windows(self.store.node(context), before, after, bool(replace))

    def _ReadDirectory(self, context, pattern, marker, buffer, length, transferred):
        transferred[0] = 0
        node = self.store.node(context)
        path = self.store.path_for(node)
        entries = [(self.store.names[self.store.lookup(path.rstrip("/") + "/" + key).inode],
                    self.store.lookup(path.rstrip("/") + "/" + key))
                   for key in self.store.children(path)]
        if path != "/":
            entries += [(".", node), ("..", self.store.lookup(path.rpartition("/")[0] or "/"))]
        for name, child in sorted(entries, key=lambda item: item[0].casefold()):
            if marker is not None and name.casefold() <= marker.casefold():
                continue
            encoded = name.encode("utf-16-le")
            record = c.create_string_buffer(c.sizeof(DirectoryInfo) + len(encoded))
            header = DirectoryInfo.from_buffer(record)
            header.Size = len(record)
            header.FileInfo = self._info(child)
            c.memmove(c.addressof(record) + c.sizeof(DirectoryInfo), encoded, len(encoded))
            if not self.library.FspFileSystemAddDirInfo(record, buffer, length, transferred):
                return SUCCESS
        self.library.FspFileSystemAddDirInfo(None, buffer, length, transferred)

    def _DispatcherStopped(self, normally):
        self.stopped.set()
        if not normally:
            self.store.failed = True
