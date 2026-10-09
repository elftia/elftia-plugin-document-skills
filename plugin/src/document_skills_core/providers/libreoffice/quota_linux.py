"""Production Linux FUSE hard-quota backend with activation-time proof.

Requires Linux x86-64/glibc, libfuse 3.14-3.16 and an accessible /dev/fuse.
All file data stays in bounded broker memory; there is no writable backing
directory that can bypass accounting. Module provenance: original
Elftia-authored clean-room implementation.
"""

from __future__ import annotations

import ctypes as c
import errno
import os
import stat
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ._quota_fuse_abi import FuseArgs, load_fuse
from ._quota_fuse_operations import FuseCallbacks
from ._quota_store import QuotaStore
from .quota import (
    DEFAULT_HARD_QUOTA_ENTRY_LIMIT, ActivatableQuotaBackend, HardQuotaCapability, ProcessStorageSession,
    capture_directory_identity, validate_final_quota_tree,
)

_LIBRARIES = (
    Path("/usr/lib/x86_64-linux-gnu/libfuse3.so.3"),
    Path("/lib/x86_64-linux-gnu/libfuse3.so.3"),
)


def _library_path() -> Path | None:
    if not sys.platform.startswith("linux") or os.uname().machine != "x86_64":
        return None
    # A fixed glibc loader is required; the ctypes structures do not claim a
    # compatible ABI on musl or another architecture.
    if not Path("/lib64/ld-linux-x86-64.so.2").is_file():
        return None
    for candidate in _LIBRARIES:
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
            if stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and not metadata.st_mode & 0o022:
                return resolved
        except OSError:
            continue
    return None


class LinuxFuseHardQuotaBackend(ActivatableQuotaBackend):
    def validate_activation(self) -> None:
        with self.open(byte_limit=16 * 1024, entry_limit=16):
            pass

    def capability(self) -> HardQuotaCapability:
        available = _library_path() is not None
        try:
            device = Path("/dev/fuse").lstat()
            available = available and stat.S_ISCHR(device.st_mode) and os.access("/dev/fuse", os.R_OK | os.W_OK)
        except OSError:
            available = False
        return HardQuotaCapability(
            backend_id="linux-fuse3-memory" if available else "none",
            platform="linux",
            reason_category="available" if available else "hard_quota_backend_unavailable",
            reason=(
                "Linux FUSE broker enforces aggregate logical bytes and entries before mutations; mount activation must still pass."
                if available else
                "Linux x86-64/glibc, libfuse 3.14-3.16 and accessible /dev/fuse are required."
            ),
            aggregate_byte_limit=available, entry_count_limit=available,
            private_namespace=available, fail_closed_activation=available,
        )

    @contextmanager
    def open(self, *, byte_limit: int, entry_limit: int = DEFAULT_HARD_QUOTA_ENTRY_LIMIT):
        capability = self.capability()
        library_path = _library_path()
        if not capability.supported or library_path is None:
            raise DocumentSkillsError(ErrorCode.PROVIDER_UNAVAILABLE, capability.reason,
                                      details=capability.evidence())
        session = LinuxFuseQuotaSession(byte_limit, entry_limit)
        try:
            try:
                session.activate(library_path)
            except OSError as error:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    "LibreOffice hard-quota activation failed closed.",
                    details={"backend": capability.backend_id, "reason_category": "hard_quota_activation_failed",
                             "errno": error.errno},
                ) from error
            yield session
        finally:
            session.close()


class LinuxFuseQuotaSession(ProcessStorageSession):
    def __init__(self, byte_limit: int, entry_limit: int) -> None:
        self.store = QuotaStore(byte_limit, entry_limit)
        if entry_limit < 5:
            raise ValueError("An enforced session needs at least five entries.")
        self.byte_limit, self.entry_limit = byte_limit, entry_limit
        self.callbacks = FuseCallbacks(self.store)
        self.library = None
        self.fuse = None
        self.thread = None
        self.mounted = False
        self.base = None
        self.mount_fd = None
        self.loop_result = None
        self.underlying_identity = None

    def activate(self, library_path: Path) -> None:
        self.library = load_fuse(str(library_path))
        self.base = Path(tempfile.mkdtemp(prefix="elftia-lo-quota-", dir="/tmp"))
        self.base_identity = capture_directory_identity(self.base)
        self.root = self.base / "storage"
        self.root.mkdir(mode=0o700)
        self.mount_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.underlying_identity = capture_directory_identity(self.root)
        options = (
            b"default_permissions,nodev,nosuid,noexec,"
            b"attr_timeout=0,entry_timeout=0,negative_timeout=0,fsname=elftia-lo-quota"
        )
        values = (c.c_char_p * 3)(b"elftia-lo-quota", b"-o", options)
        arguments = FuseArgs(3, values, 0)
        try:
            self.fuse = self.library.fuse_new(c.byref(arguments), self.callbacks.operations,
                                              c.sizeof(self.callbacks.operations), None)
        finally:
            self.library.fuse_opt_free_args(c.byref(arguments))
        if not self.fuse:
            raise OSError(errno.EIO, "FUSE construction failed.")
        if self.library.fuse_mount(self.fuse, os.fsencode(self.root)) != 0:
            raise OSError(errno.EACCES, "FUSE mount failed.")
        self.mounted = True
        # If the connection disappears, the hidden directory supplies no
        # writable fallback. It is empty and never holds provider bytes.
        os.fchmod(self.mount_fd, 0)
        self.thread = threading.Thread(target=self._loop, name="elftia-quota-fuse", daemon=True)
        self.thread.start()
        if not self.callbacks.ready.wait(5.0):
            raise OSError(errno.ETIMEDOUT, "FUSE initialization failed.")
        self.root_identity = capture_directory_identity(self.root)
        if self.root_identity.device == self.underlying_identity.device:
            raise OSError(errno.EIO, "Quota namespace was not mounted.")
        self.output_dir, self.profile_dir = self.root / "output", self.root / "profile"
        self.temporary_dir, self.home_dir = self.root / "temporary", self.root / "home"
        for directory in (self.output_dir, self.profile_dir, self.temporary_dir, self.home_dir):
            directory.mkdir(mode=0o700)
        self.output_identity = capture_directory_identity(self.output_dir)
        self.process_storage = (self.root, (self.root_identity.device, self.root_identity.inode))
        self._prove_limits()

    def _loop(self) -> None:
        self.loop_result = self.library.fuse_loop(self.fuse)

    def _prove_limits(self) -> None:
        probe = self.temporary_dir / "activation-probe"
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        try:
            before = self.store.denials
            try:
                os.ftruncate(descriptor, self.byte_limit + 1)
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
            else:
                raise OSError(errno.EIO, "Aggregate quota was not activated.")
            if self.store.denials != before + 1 or os.fstat(descriptor).st_size != 0:
                raise OSError(errno.EIO, "Quota denial did not preserve the file.")
            os.write(descriptor, b"x")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.read(descriptor, 1) != b"x":
                raise OSError(errno.EIO, "Quota filesystem is not callable.")
        finally:
            os.close(descriptor)
            probe.unlink()
        # Lower the entry ceiling to the occupied count for one activation
        # probe. This only tightens the configured quota, before any provider
        # starts, and proves the kernel request reaches the enforcing callback.
        with self.store.lock:
            original = self.store.entry_limit
            self.store.entry_limit = self.store.entry_count
            before = self.store.denials
        try:
            try:
                probe.touch(exist_ok=False)
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
            else:
                raise OSError(errno.EIO, "Entry quota was not activated.")
            if self.store.denials != before + 1:
                raise OSError(errno.EIO, "Entry quota request bypassed the broker.")
        finally:
            with self.store.lock:
                self.store.entry_limit = original
                self.store.denials = 0

    def assert_live(self) -> None:
        if self.store.failed or self.store.denials or not self.thread.is_alive():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED, "LibreOffice storage exceeded its quota or lost enforcement.",
                details={"backend": "linux-fuse3-memory", "quota_denials": self.store.denials},
            )
        if capture_directory_identity(self.root) != self.root_identity:
            raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, "Quota mount identity changed.")

    def validate_final_tree(self, *, expected_name: str):
        self.assert_live()
        return validate_final_quota_tree(
            root=self.root, root_identity=self.root_identity,
            output_dir=self.output_dir, output_identity=self.output_identity,
            expected_name=expected_name, byte_limit=self.byte_limit, entry_limit=self.entry_limit,
        )

    def close(self) -> None:
        if self.fuse:
            if self.mounted:
                self.library.fuse_exit(self.fuse)
                self.library.fuse_unmount(self.fuse)
                self.mounted = False
            if self.thread:
                self.thread.join(5.0)
                if self.thread.is_alive():
                    # Keep callbacks/state alive if libfuse has not stopped;
                    # never destroy an active native callback allocation.
                    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, "Quota filesystem cleanup did not stop.")
            self.library.fuse_destroy(self.fuse)
            self.fuse = None
        if self.mount_fd is not None:
            os.close(self.mount_fd)
            self.mount_fd = None
        if self.base is not None:
            # Exact empty directories only. No recursive deletion, even when
            # activation failed or another actor changed the paths.
            if (self.underlying_identity is not None
                    and capture_directory_identity(self.base) == self.base_identity
                    and capture_directory_identity(self.root) == self.underlying_identity):
                self.root.rmdir()
                self.base.rmdir()
            self.base = None
