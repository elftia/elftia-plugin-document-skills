"""Verify the kernel-loaded main image before a suspended child may run."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
from typing import TYPE_CHECKING

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .darwin_abi import DarwinAPI, PROC_PIDREGIONPATHINFO, RegionPathInfo
from .windows_handles import MAX_EXECUTABLE_BYTES

if TYPE_CHECKING:
    from .executable import ExecutableIdentity


def _reject(reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_FAILED,
        "The suspended executable identity could not be verified.",
        details={"reason_category": reason},
    )


def verify_suspended_image(
    api: DarwinAPI, pid: int, expected: ExecutableIdentity, descriptor: int
) -> None:
    # START_SUSPENDED stops before dyld or executable instructions run. Inspect
    # the mapped vnode, not a stat of its pathname, which may have been replaced.
    path_buffer = ctypes.create_string_buffer(4096)
    if api.libproc.proc_pidpath(pid, path_buffer, len(path_buffer)) <= 0:
        _reject("suspended_image_path_unavailable")
    image_path = path_buffer.value
    address = 0
    for _index in range(256):
        region = RegionPathInfo()
        size = ctypes.sizeof(region)
        received = api.libproc.proc_pidinfo(
            pid, PROC_PIDREGIONPATHINFO, address, ctypes.byref(region), size
        )
        if received != size:
            _reject("suspended_image_mapping_unavailable")
        mapped = region.file.vnode.stat
        # A universal Mach-O's executable slice can begin at a nonzero offset.
        if region.file.path == image_path and region.region.protection & 0x4:
            if (
                not stat.S_ISREG(mapped.mode)
                or (mapped.device, mapped.inode) != expected.object_identity
                or mapped.size != expected.size
                or mapped.mtime * 1_000_000_000 + mapped.mtime_nsec != expected.mtime_ns
                or mapped.ctime * 1_000_000_000 + mapped.ctime_nsec != expected.ctime_ns
            ):
                _reject("suspended_image_identity_changed")
            _verify_held_bytes(expected, descriptor)
            return
        next_address = region.region.address + region.region.size
        if next_address <= address or next_address >= 1 << 64:
            _reject("suspended_image_mapping_invalid")
        address = next_address
    _reject("suspended_image_mapping_limit")


def _verify_held_bytes(expected: ExecutableIdentity, descriptor: int) -> None:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or (before.st_dev, before.st_ino) != expected.object_identity
        or before.st_size != expected.size
        or before.st_mtime_ns != expected.mtime_ns
        or before.st_ctime_ns != expected.ctime_ns
    ):
        _reject("suspended_image_identity_changed")
    digest = hashlib.sha256()
    total = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 65_536):
        total += len(chunk)
        if total > MAX_EXECUTABLE_BYTES:
            _reject("suspended_image_size_limit")
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    after = os.fstat(descriptor)
    if (
        digest.hexdigest() != expected.sha256
        or total != expected.size
        or (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        ) != (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
    ):
        _reject("suspended_image_bytes_changed")
