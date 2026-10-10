"""Production Windows x64 WinFsp 2.1 hard-quota memory filesystem.

Every allocation and namespace growth is enforced by the broker. No backing
disk tree exists. Activation proves byte/entry denials before LibreOffice
launches. Module provenance: original Elftia-authored implementation.
"""

from __future__ import annotations

import ctypes as c
import errno
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ._quota_winfsp_abi import FileSystemHeader, PTR, U32, VolumeParameters, utf16
from ._quota_winfsp_library import LoadedWinFsp, library_path
from ._quota_winfsp_operations import WinFspCallbacks
from ._quota_windows_security import user_security_descriptor
from ._quota_windows_store import WindowsQuotaStore
from .quota import (
    DEFAULT_HARD_QUOTA_ENTRY_LIMIT, ActivatableQuotaBackend, HardQuotaCapability,
    ProcessStorageSession, capture_directory_identity, validate_final_quota_tree,
)

BACKEND_ID = "windows-winfsp-memory"


class WindowsWinFspHardQuotaBackend(ActivatableQuotaBackend):
    def capability(self) -> HardQuotaCapability:
        available = library_path() is not None
        return HardQuotaCapability(
            backend_id=BACKEND_ID if available else "none", platform="windows",
            reason_category="available" if available else "hard_quota_backend_unavailable",
            reason=(
                "Windows x64 WinFsp broker bounds total allocations and entries; activation must still prove enforcement."
                if available else
                "Windows x64 with official WinFsp 2.1.25156 is required; install WinFsp as a runtime prerequisite."
            ),
            aggregate_byte_limit=available, entry_count_limit=available,
            private_namespace=available, fail_closed_activation=available,
        )

    def validate_activation(self) -> None:
        with self.open(byte_limit=16 * 1024, entry_limit=16):
            pass

    @contextmanager
    def open(self, *, byte_limit: int, entry_limit: int = DEFAULT_HARD_QUOTA_ENTRY_LIMIT):
        path = library_path()
        if path is None:
            capability = self.capability()
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE, capability.reason, details=capability.evidence(),
            )
        session = WindowsWinFspQuotaSession(byte_limit, entry_limit)
        try:
            try:
                session.activate(path)
            except (OSError, ValueError) as error:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_UNAVAILABLE, "Windows hard-quota activation failed closed.",
                    details={"backend": BACKEND_ID, "reason_category": "hard_quota_activation_failed",
                             "error_type": type(error).__name__},
                ) from error
            yield session
        finally:
            session.close()


class WindowsWinFspQuotaSession(ProcessStorageSession):
    def __init__(self, byte_limit: int, entry_limit: int) -> None:
        self.store = WindowsQuotaStore(byte_limit, entry_limit)
        if entry_limit < 8:
            raise ValueError("A Windows enforced session needs at least eight entries.")
        self.byte_limit, self.entry_limit = byte_limit, entry_limit
        self.loaded = self.callbacks = None
        self.file_system = PTR()
        self.mounted = False
        self.started = False
        self.root = None
        self.closed = False
        self.serial = secrets.randbelow(0xFFFFFFFE) + 1

    def activate(self, path: Path) -> None:
        self.loaded = LoadedWinFsp(path)
        library = self.loaded.library
        self.callbacks = WinFspCallbacks(self.store, library, user_security_descriptor())
        parameters = VolumeParameters()
        parameters.Version = c.sizeof(parameters)
        parameters.SectorSize, parameters.SectorsPerAllocationUnit = 512, 1
        parameters.MaxComponentLength = 255
        parameters.VolumeCreationTime = 116444736000000000 + time.time_ns() // 100
        parameters.VolumeSerialNumber = self.serial
        parameters.IrpTimeout, parameters.IrpCapacity = 60000, 100
        parameters.FileInfoTimeout = 0
        # Case preserving, Unicode, private persistent ACL; purge caches at
        # cleanup. POSIX unlink retains charges until the final close.
        parameters.Flags = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 14) | (1 << 29)
        utf16(parameters.FileSystemName, "ElftiaQuota")
        self._check(library.FspFileSystemCreate(
            "WinFsp.Disk", c.byref(parameters), c.byref(self.callbacks.interface),
            c.byref(self.file_system),
        ))
        self.callbacks.expected_file_system = self.file_system.value
        header = c.cast(self.file_system, c.POINTER(FileSystemHeader)).contents
        if header.Version != 792:
            raise OSError("WinFsp filesystem instance ABI differs.")
        volume_bytes = bytes(header.VolumeName)
        self.volume_name = volume_bytes.decode("utf-16-le", errors="strict").split("\0", 1)[0]
        if not self.volume_name.startswith("\\Device\\"):
            raise OSError("Invalid native WinFsp volume identity.")
        library.FspFileSystemSetOperationGuardStrategyF(self.file_system, 1)
        # WinFsp selects/owns its next free drive letter; no physical mount
        # directory is created and no caller-selected path is removed.
        self._check(library.FspFileSystemSetMountPoint(self.file_system, None))
        self.mounted = True
        mount = library.FspFileSystemMountPointF(self.file_system)
        if not mount or len(mount) != 2 or mount[1] != ":" or not "D" <= mount[0] <= "Z":
            raise OSError("WinFsp did not provide one private drive mount.")
        self.root = Path(mount + "\\")
        self._check(library.FspFileSystemStartDispatcher(self.file_system, 2))
        self.started = True
        self._check_mount()
        self.root_identity = capture_directory_identity(self.root)
        self.output_dir, self.profile_dir = self.root / "output", self.root / "profile"
        self.temporary_dir, self.home_dir = self.root / "temporary", self.root / "home"
        for directory in (self.output_dir, self.profile_dir, self.temporary_dir, self.home_dir):
            directory.mkdir()
        self.appdata_dir = self.home_dir / "appdata"
        self.roaming_dir, self.local_dir = self.appdata_dir / "roaming", self.appdata_dir / "local"
        for directory in (self.appdata_dir, self.roaming_dir, self.local_dir):
            directory.mkdir()
        self.output_identity = capture_directory_identity(self.output_dir)
        self.process_storage = (self.root, (self.root_identity.device, self.root_identity.inode))
        self._prove_limits()

    @staticmethod
    def _check(status: int) -> None:
        if status < 0:
            raise OSError(f"WinFsp rejected operation (NTSTATUS {status & 0xFFFFFFFF:08x}).")

    def _check_mount(self) -> None:
        query = c.windll.kernel32.QueryDosDeviceW
        query.argtypes, query.restype = [c.c_wchar_p, c.c_wchar_p, U32], U32
        buffer = c.create_unicode_buffer(32768)
        if not query(self.root.drive, buffer, len(buffer)) or buffer.value.casefold() != self.volume_name.casefold():
            raise OSError("Windows quota drive no longer names its native volume.")

    def _prove_limits(self) -> None:
        probe = self.temporary_dir / "activation-probe"
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_BINARY, 0o600)
        try:
            before = self.store.denials
            try:
                os.ftruncate(descriptor, self.byte_limit + 512)
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
            else:
                raise OSError("Windows byte quota was not enforced.")
            if self.store.denials <= before or os.fstat(descriptor).st_size != 0:
                raise OSError("Windows quota denial changed the file.")
            os.write(descriptor, b"x")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.read(descriptor, 1) != b"x":
                raise OSError("Windows quota filesystem is not callable.")
        finally:
            os.close(descriptor)
            probe.unlink()
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
                raise OSError("Windows entry quota was not enforced.")
            if self.store.denials <= before:
                raise OSError("Windows entry quota bypassed the broker.")
        finally:
            with self.store.lock:
                self.store.entry_limit = original
                self.store.denials = 0
        self.assert_live()

    def assert_live(self) -> None:
        if self.closed or self.store.failed or self.store.denials or self.callbacks.stopped.is_set():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED, "Windows LibreOffice quota lost enforcement or rejected growth.",
                details={"backend": BACKEND_ID, "quota_denials": self.store.denials},
            )
        try:
            self._check_mount()
            if capture_directory_identity(self.root) != self.root_identity:
                raise OSError("Quota root identity changed.")
        except OSError as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED, "Windows LibreOffice quota mount identity changed.",
                details={"backend": BACKEND_ID},
            ) from error

    def validate_final_tree(self, *, expected_name: str):
        self.assert_live()
        return validate_final_quota_tree(
            root=self.root, root_identity=self.root_identity,
            output_dir=self.output_dir, output_identity=self.output_identity,
            expected_name=expected_name, byte_limit=self.byte_limit, entry_limit=self.entry_limit,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.loaded is not None:
            library = self.loaded.library
            if self.file_system:
                if self.mounted:
                    library.FspFileSystemRemoveMountPoint(self.file_system)
                    self.mounted = False
                if self.started:
                    library.FspFileSystemStopDispatcher(self.file_system)
                    self.started = False
                library.FspFileSystemDelete(self.file_system)
                self.file_system = PTR()
            self.loaded.close()
            self.loaded = None
        # Native dispatch has stopped; drop callback cycles and all broker
        # allocations before another operation can create a new session.
        if self.callbacks is not None:
            self.callbacks.references.clear()
        with self.store.lock:
            for node in self.store.nodes.values():
                node.data.clear()
            for mapping in (self.store.paths, self.store.nodes, self.store.names,
                            self.store.sizes, self.store.attributes, self.store.times):
                mapping.clear()
            self.store.total_bytes = self.store.entry_count = 0
