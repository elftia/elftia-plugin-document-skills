"""Identity-bound destination-parent operations for atomic promotion."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys
from typing import BinaryIO, Callable

from .parent_anchor_types import FileIdentity, ParentSafetyError
from .parent_anchor_posix import (
    darwin_descriptor_path as _darwin_descriptor_path,
    darwin_rename_no_replace as _darwin_rename_no_replace,
    linux_rename_no_replace as _linux_rename_no_replace,
)
from .parent_anchor_windows import (
    close_windows_handle as _close_windows_handle,
    open_windows_directory as _open_windows_directory,
    open_windows_relative_file as _open_windows_relative_file,
    windows_final_path as _windows_final_path,
    windows_rename_relative as _windows_rename_relative,
)


@dataclass
class DestinationParentAnchor:
    """An open identity for one physical destination directory."""

    original_path: Path
    identity: FileIdentity
    _descriptor: int | None = None
    _windows_handle: int | None = None
    _closed: bool = False

    @classmethod
    def capture(cls, destination: str | Path) -> tuple[DestinationParentAnchor, Path]:
        raw_destination = _absolute_without_resolution(destination)
        _reject_redirected_components(raw_destination.parent)
        raw_destination.parent.mkdir(parents=True, exist_ok=True)
        physical_parent = raw_destination.parent.resolve(strict=True)
        if not _same_path(raw_destination.parent, physical_parent):
            raise ParentSafetyError(
                "destination_parent_redirected",
                phase="capture",
                original_path=raw_destination.parent,
                current_path=physical_parent,
            )
        _assert_plain_directory(physical_parent, phase="capture")
        anchor = cls._open(physical_parent)
        try:
            anchor.assert_bound("capture")
        except Exception:
            anchor.close()
            raise
        return anchor, physical_parent / raw_destination.name

    @classmethod
    def _open(cls, parent: Path) -> DestinationParentAnchor:
        if os.name == "nt":
            handle = _open_windows_directory(parent)
            try:
                current = _windows_final_path(handle)
                metadata = os.stat(current, follow_symlinks=False)
            except Exception:
                _close_windows_handle(handle)
                raise
            return cls(
                original_path=parent,
                identity=(metadata.st_dev, metadata.st_ino),
                _windows_handle=handle,
            )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(parent, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            raise ParentSafetyError(
                "destination_parent_not_directory",
                phase="capture",
                original_path=parent,
            )
        if not _path_recovery_supported():
            os.close(descriptor)
            raise ParentSafetyError(
                "destination_parent_recovery_unavailable",
                phase="capture",
                original_path=parent,
            )
        return cls(
            original_path=parent,
            identity=(metadata.st_dev, metadata.st_ino),
            _descriptor=descriptor,
        )

    @property
    def device(self) -> int:
        return self.identity[0]

    def __enter__(self) -> DestinationParentAnchor:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
        if self._windows_handle is not None:
            _close_windows_handle(self._windows_handle)
            self._windows_handle = None

    def current_path(self) -> Path:
        self._assert_open()
        if self._windows_handle is not None:
            return _windows_final_path(self._windows_handle)
        assert self._descriptor is not None
        if sys.platform.startswith("linux"):
            value = os.readlink(f"/proc/self/fd/{self._descriptor}")
            if value.endswith(" (deleted)"):
                raise ParentSafetyError(
                    "destination_parent_path_unavailable",
                    phase="recover",
                    original_path=self.original_path,
                )
            return Path(value).resolve(strict=False)
        if sys.platform == "darwin":
            return _darwin_descriptor_path(self._descriptor)
        raise ParentSafetyError(
            "destination_parent_recovery_unavailable",
            phase="recover",
            original_path=self.original_path,
        )

    def assert_bound(self, phase: str) -> Path:
        current = self.current_path()
        try:
            metadata = os.stat(self.original_path, follow_symlinks=False)
        except OSError as error:
            raise ParentSafetyError(
                "destination_parent_identity_changed",
                phase=phase,
                original_path=self.original_path,
                current_path=current,
            ) from error
        actual = (metadata.st_dev, metadata.st_ino)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or _is_reparse(metadata)
            or actual != self.identity
            or not _same_path(current, self.original_path)
        ):
            raise ParentSafetyError(
                "destination_parent_identity_changed",
                phase=phase,
                original_path=self.original_path,
                current_path=current,
            )
        return current

    def entry_path(self, name: str, *, require_bound: bool, phase: str) -> Path:
        leaf = _safe_leaf(name)
        parent = self.assert_bound(phase) if require_bound else self.current_path()
        return parent / leaf

    def create_exclusive(
        self,
        name: str,
        *,
        on_created: Callable[[FileIdentity], None],
    ) -> BinaryIO:
        leaf = _safe_leaf(name)
        self.assert_bound("stage_create")
        if self._descriptor is not None:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= os.O_CLOEXEC | os.O_NOFOLLOW
            descriptor = os.open(leaf, flags, 0o600, dir_fd=self._descriptor)
            handle = os.fdopen(descriptor, "wb")
        else:
            assert self._windows_handle is not None
            handle = _open_windows_relative_file(
                self._windows_handle,
                leaf,
                create=True,
                writable=True,
            )
        try:
            metadata = os.fstat(handle.fileno())
            on_created((metadata.st_dev, metadata.st_ino))
            if metadata.st_dev != self.device or not stat.S_ISREG(metadata.st_mode):
                raise ParentSafetyError(
                    "cross_volume_or_non_regular_stage",
                    phase="stage_create",
                    original_path=self.original_path,
                    current_path=self.current_path(),
                )
            self.assert_bound("stage_created")
        except Exception:
            handle.close()
            raise
        return handle

    def open_entry(self, name: str) -> BinaryIO:
        leaf = _safe_leaf(name)
        if self._descriptor is not None:
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
            descriptor = os.open(leaf, flags, dir_fd=self._descriptor)
            return os.fdopen(descriptor, "rb")
        assert self._windows_handle is not None
        return _open_windows_relative_file(
            self._windows_handle,
            leaf,
            create=False,
            writable=False,
        )

    def entry_stat(self, name: str) -> os.stat_result:
        leaf = _safe_leaf(name)
        if self._descriptor is not None:
            return os.stat(leaf, dir_fd=self._descriptor, follow_symlinks=False)
        with self.open_entry(leaf) as handle:
            return os.fstat(handle.fileno())

    def rename_no_replace(self, source_name: str, destination_name: str) -> None:
        source_leaf = _safe_leaf(source_name)
        destination_leaf = _safe_leaf(destination_name)
        self.assert_bound("rename_before")
        if self._windows_handle is not None:
            _windows_rename_relative(
                self._windows_handle,
                source_leaf,
                destination_leaf,
            )
        elif sys.platform.startswith("linux"):
            assert self._descriptor is not None
            _linux_rename_no_replace(
                self._descriptor,
                source_leaf,
                destination_leaf,
            )
        elif sys.platform == "darwin":
            assert self._descriptor is not None
            _darwin_rename_no_replace(
                self._descriptor,
                source_leaf,
                destination_leaf,
            )
        else:  # pragma: no cover - rejected during capture
            raise OSError("atomic no-replace rename is unavailable")
        self.assert_bound("rename_after")

    def _assert_open(self) -> None:
        if self._closed:
            raise ParentSafetyError(
                "destination_parent_anchor_closed",
                phase="anchor",
                original_path=self.original_path,
            )


def _absolute_without_resolution(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _reject_redirected_components(parent: Path) -> None:
    absolute = _absolute_without_resolution(parent)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise ParentSafetyError(
                "destination_parent_redirected",
                phase="preflight",
                original_path=absolute,
                current_path=current,
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise ParentSafetyError(
                "destination_parent_not_directory",
                phase="preflight",
                original_path=absolute,
                current_path=current,
            )


def _assert_plain_directory(path: Path, *, phase: str) -> None:
    metadata = os.lstat(path)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise ParentSafetyError(
            "destination_parent_not_plain_directory",
            phase=phase,
            original_path=path,
        )


def _is_reparse(metadata: os.stat_result) -> bool:
    if os.name != "nt":
        return False
    return bool(metadata.st_file_attributes & 0x400)


def _safe_leaf(name: str) -> str:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ParentSafetyError(
            "destination_path_escape",
            phase="leaf",
            original_path=Path(name),
        )
    return name


def _same_path(first: Path, second: Path) -> bool:
    if os.name == "nt":
        return os.path.normcase(str(first)) == os.path.normcase(str(second))
    return first == second


def _path_recovery_supported() -> bool:
    return sys.platform.startswith("linux") or sys.platform == "darwin"
