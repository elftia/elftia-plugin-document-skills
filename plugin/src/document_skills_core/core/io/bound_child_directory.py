"""Identity-bound creation and empty-child lifecycle for directory anchors."""

from __future__ import annotations

import os
import stat
import time
from typing import Self

from .parent_anchor_types import ParentSafetyError, safe_leaf, same_path
from .parent_anchor_windows import (
    close_windows_handle,
    mark_windows_directory_for_delete,
    open_windows_relative_directory,
    open_windows_relative_directory_for_delete,
    windows_handle_metadata,
)


class BoundDirectoryMixin:
    """Empty-only child-directory behavior shared by parent anchors."""

    def create_bound_directory(self, name: str, *, exist_ok: bool) -> Self:
        leaf = safe_leaf(name)
        self.assert_bound("directory_create_before")
        if self._descriptor is not None:
            child = self._create_bound_posix_directory(leaf, exist_ok=exist_ok)
        else:
            child = self._create_bound_windows_directory(leaf, exist_ok=exist_ok)
        try:
            child.assert_bound("directory_created")
            self.assert_bound("directory_create_after")
        except BaseException:
            try:
                child.close()
            except BaseException:
                pass
            raise
        return child

    def _create_bound_posix_directory(self, leaf: str, *, exist_ok: bool) -> Self:
        try:
            os.mkdir(leaf, mode=0o700, dir_fd=self._descriptor)
        except FileExistsError:
            if not exist_ok:
                raise
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(leaf, flags, dir_fd=self._descriptor)
        try:
            metadata = os.fstat(descriptor)
            path = self.entry_path(
                leaf,
                require_bound=True,
                phase="directory_created",
            )
            return type(self)(
                original_path=path,
                identity=(metadata.st_dev, metadata.st_ino),
                _descriptor=descriptor,
            )
        except BaseException:
            os.close(descriptor)
            raise

    def _create_bound_windows_directory(self, leaf: str, *, exist_ok: bool) -> Self:
        assert self._windows_handle is not None
        handle = open_windows_relative_directory(
            self._windows_handle,
            leaf,
            exist_ok=exist_ok,
            share_delete=False,
        )
        try:
            path = self.entry_path(
                leaf,
                require_bound=True,
                phase="directory_created",
            )
            metadata = os.stat(path, follow_symlinks=False)
            identity, attributes = windows_handle_metadata(handle)
            if (
                identity != metadata.st_ino
                or not stat.S_ISDIR(metadata.st_mode)
                or attributes & 0x400
            ):
                raise ParentSafetyError(
                    "child_directory_not_plain",
                    phase="directory_created",
                    original_path=path,
                )
            return type(self)(
                original_path=path,
                identity=(metadata.st_dev, metadata.st_ino),
                _windows_handle=handle,
            )
        except BaseException:
            close_windows_handle(handle)
            raise

    def remove_empty_child(
        self,
        child: Self,
        retry_delays: tuple[float, ...] = (),
    ) -> bool:
        leaf = safe_leaf(child.original_path.name)
        try:
            parent = self.assert_bound("directory_remove_before")
            child.assert_bound("directory_remove_before")
            if not same_path(child.original_path.parent, parent):
                raise ParentSafetyError(
                    "child_directory_parent_changed",
                    phase="directory_remove_before",
                    original_path=child.original_path,
                )
            if self._descriptor is not None:
                # POSIX has no portable object-bound rmdir primitive. A separate
                # stat-at then rmdir-at can delete a substituted directory, so the
                # safe production boundary is an empty random-directory residue.
                return False
            return self._remove_empty_windows_child(child, leaf, retry_delays)
        except OSError:
            return False
        finally:
            child.close()

    def _remove_empty_windows_child(
        self,
        child: Self,
        leaf: str,
        retry_delays: tuple[float, ...],
    ) -> bool:
        assert self._windows_handle is not None
        expected_identity = child.identity[1]
        child.close()
        for attempt in range(len(retry_delays) + 1):
            handle: int | None = None
            try:
                self.assert_bound("directory_remove")
                handle = open_windows_relative_directory_for_delete(
                    self._windows_handle,
                    leaf,
                )
                identity, attributes = windows_handle_metadata(handle)
                if identity != expected_identity or attributes & 0x400:
                    raise ParentSafetyError(
                        "child_directory_identity_changed",
                        phase="directory_remove",
                        original_path=child.original_path,
                    )
                mark_windows_directory_for_delete(handle)
                return True
            except PermissionError as error:
                if error.winerror not in {5, 32} or attempt >= len(retry_delays):
                    return False
                time.sleep(retry_delays[attempt])
            except OSError:
                return False
            finally:
                if handle is not None:
                    close_windows_handle(handle)
        return False
