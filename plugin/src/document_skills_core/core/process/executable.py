"""Identity-bound external executable authorization and launch leases."""

import hashlib
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .windows_handles import (
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_FLAG_BACKUP_SEMANTICS,
    FILE_FLAG_OPEN_REPARSE_POINT,
    FILE_READ_ATTRIBUTES,
    GENERIC_READ,
    MAX_EXECUTABLE_BYTES,
    WindowsFileSnapshot,
    close_handle,
    create_handle,
    file_snapshot,
    final_path,
    handle_attributes,
    hash_handle,
    parent_components,
    require_local_fixed_path,
)

_HASH_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class ExecutableIdentity:
    """The exact filesystem object and bytes approved for one launch path."""

    launch_path: Path
    resolved_path: Path
    alias_identity: tuple[int, int, int, int, int]
    object_identity: tuple[int, int] | tuple[int, bytes]
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


@dataclass
class ExecutableLaunchLease:
    """A stable launch object kept alive until process creation completes."""

    launch_path: Path
    popen_executable: str
    pass_fds: tuple[int, ...]
    identity: ExecutableIdentity
    _fd: int | None = None
    _windows_file_handle: int | None = None
    _windows_directory_handles: list[int] = field(default_factory=list)
    _closed: bool = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            if self._windows_file_handle is not None:
                close_handle(self._windows_file_handle)
                self._windows_file_handle = None
        finally:
            for handle in reversed(self._windows_directory_handles):
                close_handle(handle)
            self._windows_directory_handles.clear()


def capture_executable_identity(path: Path) -> ExecutableIdentity:
    """Capture one authorization record without claiming path-only identity."""

    launch_path = _absolute_path(path)
    if os.name == "nt":
        lease = _open_windows_resolved_lease(launch_path, require_native=False)
        try:
            return lease.identity
        finally:
            lease.close()
    return _capture_posix_identity(launch_path)


def acquire_executable_lease(
    expected: ExecutableIdentity,
    *,
    require_native: bool,
) -> ExecutableLaunchLease:
    """Open the authorized object and keep it stable across process creation."""

    if os.name == "nt":
        lease = _open_windows_resolved_lease(
            expected.launch_path,
            require_native=require_native,
        )
    else:
        lease = _open_posix_authorized_lease(
            expected,
            require_native=require_native,
        )
    if lease.identity != expected:
        lease.close()
        _identity_changed(expected.launch_path)
    return lease


def _capture_posix_identity(launch_path: Path) -> ExecutableIdentity:
    try:
        alias_before = os.lstat(launch_path)
        resolved_path = launch_path.resolve(strict=True)
        fd, snapshot, digest, _prefix = _open_and_hash_posix(resolved_path)
        os.close(fd)
        alias_after = os.lstat(launch_path)
        resolved_after = launch_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _identity_error(launch_path, "capture_failed") from error
    alias_identity = _stat_identity(alias_before)
    if alias_identity != _stat_identity(alias_after) or resolved_after != resolved_path:
        _identity_changed(launch_path)
    return ExecutableIdentity(
        launch_path=launch_path,
        resolved_path=resolved_path,
        alias_identity=alias_identity,
        object_identity=(snapshot.st_dev, snapshot.st_ino),
        size=snapshot.st_size,
        mtime_ns=snapshot.st_mtime_ns,
        ctime_ns=snapshot.st_ctime_ns,
        sha256=digest,
    )


def _open_posix_authorized_lease(
    expected: ExecutableIdentity,
    *,
    require_native: bool,
) -> ExecutableLaunchLease:
    if require_native:
        _require_linux_proc_fd()
    try:
        alias = os.lstat(expected.launch_path)
        resolved = expected.launch_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _identity_error(expected.launch_path, "path_unavailable") from error
    if _stat_identity(alias) != expected.alias_identity or resolved != expected.resolved_path:
        _identity_changed(expected.launch_path)
    try:
        fd, snapshot, digest, prefix = _open_and_hash_posix(expected.resolved_path)
    except OSError as error:
        raise _identity_error(expected.launch_path, "open_failed") from error
    identity = ExecutableIdentity(
        launch_path=expected.launch_path,
        resolved_path=expected.resolved_path,
        alias_identity=expected.alias_identity,
        object_identity=(snapshot.st_dev, snapshot.st_ino),
        size=snapshot.st_size,
        mtime_ns=snapshot.st_mtime_ns,
        ctime_ns=snapshot.st_ctime_ns,
        sha256=digest,
    )
    if require_native and not prefix.startswith(b"\x7fELF"):
        os.close(fd)
        _native_unavailable(expected.launch_path)
    return ExecutableLaunchLease(
        launch_path=expected.launch_path,
        popen_executable=f"/proc/self/fd/{fd}",
        pass_fds=(fd,),
        identity=identity,
        _fd=fd,
    )


def _open_and_hash_posix(path: Path) -> tuple[int, os.stat_result, str, bytes]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        _require_regular_bounded_file(before, path)
        digest, prefix = _hash_fd(fd)
        after = os.fstat(fd)
        if _stat_identity(before) != _stat_identity(after):
            _identity_changed(path)
        return fd, after, digest, prefix
    except BaseException:
        os.close(fd)
        raise


def _open_windows_resolved_lease(
    launch_path: Path,
    *,
    require_native: bool,
) -> ExecutableLaunchLease:
    followed_handle: int | None = None
    canonical_lease: ExecutableLaunchLease | None = None
    try:
        (
            followed_handle,
            resolved_path,
            followed_snapshot,
            followed_object_identity,
            followed_digest,
            followed_prefix,
        ) = _open_windows_following_reparse(launch_path)
        canonical_lease = _open_windows_canonical_lease(
            launch_path,
            resolved_path,
            followed_snapshot,
            followed_digest,
            followed_prefix,
            require_native=require_native,
        )
        followed_identity = ExecutableIdentity(
            launch_path=launch_path,
            resolved_path=resolved_path,
            alias_identity=followed_snapshot.alias_identity(),
            object_identity=followed_object_identity,
            size=followed_snapshot.size,
            mtime_ns=followed_snapshot.mtime_ns,
            ctime_ns=followed_snapshot.ctime_ns,
            sha256=followed_digest,
        )
        if canonical_lease.identity != followed_identity:
            _identity_changed(launch_path)
        if require_native and not followed_prefix.startswith(b"MZ"):
            _native_unavailable(launch_path)
        return canonical_lease
    except BaseException:
        if canonical_lease is not None:
            canonical_lease.close()
        raise
    finally:
        if followed_handle is not None:
            close_handle(followed_handle)


def _open_windows_following_reparse(
    launch_path: Path,
) -> tuple[int, Path, WindowsFileSnapshot, tuple[int, bytes], str, bytes]:
    require_local_fixed_path(launch_path)
    handle: int | None = None
    try:
        handle = create_handle(
            launch_path,
            access=GENERIC_READ,
            flags=0,
        )
        attributes = handle_attributes(handle)
        if attributes & FILE_ATTRIBUTE_DIRECTORY:
            raise OSError("executable path resolved to a directory")
        resolved_path = final_path(handle)
        require_local_fixed_path(resolved_path)
        before = file_snapshot(handle)
        _require_bounded_size(before.size, launch_path)
        digest, prefix = hash_handle(handle)
        after = file_snapshot(handle)
        if before != after:
            _identity_changed(launch_path)
        opened_handle = handle
        handle = None
        return (
            opened_handle,
            resolved_path,
            after,
            after.object_identity,
            digest,
            prefix,
        )
    except DocumentSkillsError:
        raise
    except OSError as error:
        raise _identity_error(launch_path, "windows_path_not_stable") from error
    finally:
        if handle is not None:
            close_handle(handle)


def _open_windows_canonical_lease(
    launch_path: Path,
    resolved_path: Path,
    alias_snapshot: WindowsFileSnapshot,
    known_digest: str,
    known_prefix: bytes,
    *,
    require_native: bool,
) -> ExecutableLaunchLease:
    require_local_fixed_path(resolved_path)
    directory_handles: list[int] = []
    file_handle: int | None = None
    transferred = False
    try:
        for directory in parent_components(resolved_path):
            handle = create_handle(
                directory,
                access=FILE_READ_ATTRIBUTES,
                flags=FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            )
            directory_handles.append(handle)
            attributes = handle_attributes(handle)
            if not attributes & FILE_ATTRIBUTE_DIRECTORY:
                raise OSError("path component is not a directory")
            if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("reparse directory component is not launch-stable")
        file_handle = create_handle(
            resolved_path,
            access=GENERIC_READ,
            flags=FILE_FLAG_OPEN_REPARSE_POINT,
        )
        attributes = handle_attributes(file_handle)
        if attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError("executable is a directory or reparse point")
        before = file_snapshot(file_handle)
        _require_bounded_size(before.size, resolved_path)
        after = file_snapshot(file_handle)
        if before != after:
            _identity_changed(resolved_path)
        if require_native and not known_prefix.startswith(b"MZ"):
            _native_unavailable(launch_path)
        identity = ExecutableIdentity(
            launch_path=launch_path,
            resolved_path=resolved_path,
            alias_identity=alias_snapshot.alias_identity(),
            object_identity=after.object_identity,
            size=after.size,
            mtime_ns=after.mtime_ns,
            ctime_ns=after.ctime_ns,
            sha256=known_digest,
        )
        lease = ExecutableLaunchLease(
            launch_path=launch_path,
            popen_executable=str(resolved_path),
            pass_fds=(),
            identity=identity,
            _windows_file_handle=file_handle,
            _windows_directory_handles=directory_handles,
        )
        file_handle = None
        transferred = True
        return lease
    except DocumentSkillsError:
        raise
    except OSError as error:
        raise _identity_error(launch_path, "windows_path_not_stable") from error
    finally:
        if file_handle is not None:
            close_handle(file_handle)
        if not transferred:
            for handle in reversed(directory_handles):
                close_handle(handle)


def _hash_fd(fd: int) -> tuple[str, bytes]:
    digest = hashlib.sha256()
    prefix = bytearray()
    total = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, _HASH_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_EXECUTABLE_BYTES:
            raise OSError("executable exceeds the authorization byte ceiling")
        if len(prefix) < 64:
            prefix.extend(chunk[: 64 - len(prefix)])
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest(), bytes(prefix)


def _require_regular_bounded_file(metadata: os.stat_result, path: Path) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"{path.name} is not a regular file")
    _require_bounded_size(metadata.st_size, path)


def _require_bounded_size(size: int, path: Path) -> None:
    if size <= 0 or size > MAX_EXECUTABLE_BYTES:
        raise OSError(f"{path.name} has an invalid executable size")


def _require_linux_proc_fd() -> None:
    if not sys.platform.startswith("linux") or not Path("/proc/self/fd").is_dir():
        raise DocumentSkillsError(
            ErrorCode.RUNTIME_UNAVAILABLE,
            "Atomic native executable launch is unavailable on this platform.",
            details={"reason_category": "atomic_launch_unavailable"},
        )


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _identity_error(path: Path, reason: str) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.PROVIDER_FAILED,
        "Executable identity could not be captured safely.",
        details={
            "executable": path.name,
            "reason_category": reason,
        },
    )


def _identity_changed(path: Path) -> None:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_FAILED,
        "Executable identity changed after authorization.",
        details={
            "executable": path.name,
            "reason_category": "executable_identity_changed",
        },
    )


def _native_unavailable(path: Path) -> None:
    raise DocumentSkillsError(
        ErrorCode.RUNTIME_UNAVAILABLE,
        "Atomic launch requires a native executable; script launchers are unavailable.",
        details={
            "executable": path.name,
            "reason_category": "atomic_native_launch_unavailable",
        },
    )
