"""Identity-bound, empty-only private working directory lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import time

from document_skills_core.core.io.parent_anchor import DestinationParentAnchor
from document_skills_core.core.io.parent_anchor_types import FileIdentity, is_reparse


INVOCATION_ROOT = ".document-skills-tmp"
OPERATION_ROOT = "document-skills-operations"
_OPERATION_PREFIX = "operation-"
_CLEANUP_RETRY_DELAYS_SECONDS = (0.05, 0.1, 0.2)
_OPERATION_CLEANUP_SECONDS = 15.0
_OPERATION_CLEANUP_ENTRY_LIMIT = 250_000
_OPERATION_CLEANUP_DEPTH_LIMIT = 64
_WORKSPACE_FD_FLAG = "--workspace-fd"
_WORKSPACE_DEVICE_FLAG = "--workspace-device"
_WORKSPACE_INODE_FLAG = "--workspace-inode"


@dataclass
class PrivateWorkspace:
    """One held invocation directory with a narrow worker-launch capability."""

    _base: DestinationParentAnchor
    _root: DestinationParentAnchor
    _closed: bool = False

    @classmethod
    def create(cls, project_root: Path, invocation_id: str) -> PrivateWorkspace:
        root_anchor: DestinationParentAnchor | None = None
        base_anchor: DestinationParentAnchor | None = None
        project_anchor, _unused = DestinationParentAnchor.capture(
            project_root / ".private-workspace-anchor"
        )
        try:
            base_anchor = project_anchor.create_bound_directory(
                INVOCATION_ROOT,
                exist_ok=True,
            )
            root_anchor = base_anchor.create_bound_directory(
                f"invocation-{invocation_id}",
                exist_ok=False,
            )
            return cls(base_anchor, root_anchor)
        except BaseException:
            if root_anchor is not None and base_anchor is not None:
                try:
                    base_anchor.remove_empty_child(root_anchor)
                except BaseException:
                    try:
                        root_anchor.close()
                    except BaseException:
                        pass
            if base_anchor is not None:
                try:
                    base_anchor.close()
                except BaseException:
                    pass
            raise
        finally:
            try:
                project_anchor.close()
            except BaseException:
                pass

    @property
    def path(self) -> Path:
        if self._closed:
            raise OSError("private workspace is closed")
        return self._root.assert_bound("workspace_use")

    def launch_parameters(
        self,
    ) -> tuple[Path, int | None, FileIdentity | None, list[str]]:
        """Return a checked path plus the narrow POSIX worker capability."""
        path = self.path
        descriptor = self._root.posix_descriptor()
        if descriptor is None:
            return path, None, None, []
        identity = self._root.identity
        args = [
            _WORKSPACE_FD_FLAG,
            str(descriptor),
            _WORKSPACE_DEVICE_FLAG,
            str(identity[0]),
            _WORKSPACE_INODE_FLAG,
            str(identity[1]),
        ]
        return path, descriptor, identity, args

    def close(self) -> bool:
        if self._closed:
            return False
        self._closed = True
        removed = False
        try:
            removed = self._base.remove_empty_child(
                self._root,
                _CLEANUP_RETRY_DELAYS_SECONDS,
            )
        except OSError:
            pass
        for anchor in (self._root, self._base):
            try:
                anchor.close()
            except OSError:
                pass
        return removed


@dataclass
class PrivateOperationRoot:
    """One supervisor-owned operation root held across worker termination."""

    _base: DestinationParentAnchor
    _root: DestinationParentAnchor
    _closed: bool = False

    @classmethod
    def create(cls, project_root: Path, invocation_id: str) -> PrivateOperationRoot:
        operation_base: DestinationParentAnchor | None = None
        temporary_base: DestinationParentAnchor | None = None
        project_anchor, _unused = DestinationParentAnchor.capture(
            project_root / ".private-operation-root-anchor"
        )
        try:
            temporary_base = project_anchor.create_bound_directory(
                INVOCATION_ROOT,
                exist_ok=True,
            )
            operation_base = temporary_base.create_bound_directory(
                OPERATION_ROOT,
                exist_ok=True,
            )
            operation_root = operation_base.create_bound_directory(
                f"{_OPERATION_PREFIX}{invocation_id}",
                exist_ok=False,
            )
            return cls(operation_base, operation_root)
        except BaseException:
            if operation_base is not None:
                try:
                    operation_base.close()
                except BaseException:
                    pass
            raise
        finally:
            if temporary_base is not None:
                try:
                    temporary_base.close()
                except BaseException:
                    pass
            try:
                project_anchor.close()
            except BaseException:
                pass

    @property
    def path(self) -> Path:
        if self._closed:
            raise OSError("private operation root is closed")
        return self._root.assert_bound("operation_root_use")

    @property
    def identity(self) -> FileIdentity:
        if self._closed:
            raise OSError("private operation root is closed")
        return self._root.identity

    def close(self) -> bool:
        """Boundedly clear only this identity and remove it when safe."""

        if self._closed:
            return False
        self._closed = True
        cleaned = False
        try:
            _clear_bound_operation_root(self._root)
            removed = self._base.remove_empty_child(
                self._root,
                _CLEANUP_RETRY_DELAYS_SECONDS,
            )
            cleaned = removed if os.name == "nt" else True
        except OSError:
            cleaned = False
        finally:
            for anchor in (self._root, self._base):
                try:
                    anchor.close()
                except OSError:
                    pass
        return cleaned


class _CleanupBudget:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + _OPERATION_CLEANUP_SECONDS
        self.remaining = _OPERATION_CLEANUP_ENTRY_LIMIT

    def consume(self, depth: int) -> None:
        self.remaining -= 1
        if (
            self.remaining < 0
            or depth > _OPERATION_CLEANUP_DEPTH_LIMIT
            or time.monotonic() >= self.deadline
        ):
            raise TimeoutError("private operation-root cleanup exceeded its bound")


def _clear_bound_operation_root(root: DestinationParentAnchor) -> None:
    root.assert_bound("operation_cleanup_before")
    budget = _CleanupBudget()
    descriptor = root.posix_descriptor()
    if descriptor is None:
        _clear_windows_directory(root.assert_bound("operation_cleanup"), budget, 0)
    else:
        _clear_posix_directory(descriptor, budget, 0)
    root.assert_bound("operation_cleanup_after")


def _clear_posix_directory(
    descriptor: int,
    budget: _CleanupBudget,
    depth: int,
) -> None:
    with os.scandir(descriptor) as entries:
        names = [entry.name for entry in entries]
    for name in names:
        budget.consume(depth)
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            child = os.open(name, flags, dir_fd=descriptor)
            try:
                held = os.fstat(child)
                if (held.st_dev, held.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise OSError("private cleanup child identity changed")
                _clear_posix_directory(child, budget, depth + 1)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=descriptor)
        else:
            os.unlink(name, dir_fd=descriptor)


def _clear_windows_directory(
    directory: Path,
    budget: _CleanupBudget,
    depth: int,
) -> None:
    with os.scandir(directory) as entries:
        children = list(entries)
    for entry in children:
        budget.consume(depth)
        metadata = entry.stat(follow_symlinks=False)
        child = directory / entry.name
        if stat.S_ISDIR(metadata.st_mode) and not is_reparse(metadata):
            _clear_windows_directory(child, budget, depth + 1)
            os.rmdir(child)
        elif stat.S_ISDIR(metadata.st_mode):
            os.rmdir(child)
        else:
            os.unlink(child)


def bind_inherited_workspace(
    argv: list[str],
    project_root: Path,
) -> FileIdentity | None:
    """Bind a POSIX worker to its sole inherited cwd descriptor and close it."""
    if os.name == "nt":
        if argv:
            raise ValueError(
                "Windows private worker received POSIX bootstrap arguments"
            )
        return None
    if len(argv) != 6 or argv[::2] != [
        _WORKSPACE_FD_FLAG,
        _WORKSPACE_DEVICE_FLAG,
        _WORKSPACE_INODE_FLAG,
    ]:
        raise ValueError("private worker bootstrap arguments are invalid")
    try:
        descriptor, device, inode = (int(value, 10) for value in argv[1::2])
    except ValueError as error:
        raise ValueError("private worker bootstrap values are invalid") from error
    if descriptor < 3 or device < 0 or inode < 0:
        raise ValueError("private worker bootstrap values are out of range")
    expected = (device, inode)
    try:
        trusted_project_root = project_root.resolve(strict=True)
        held = os.fstat(descriptor)
        if not stat.S_ISDIR(held.st_mode) or (held.st_dev, held.st_ino) != expected:
            raise ValueError("inherited private workspace identity is invalid")
        os.fchdir(descriptor)
        actual = os.stat(".", follow_symlinks=False)
        if (
            not stat.S_ISDIR(actual.st_mode)
            or (actual.st_dev, actual.st_ino) != expected
        ):
            raise ValueError("private worker cwd identity differs from its held anchor")
        current = Path.cwd().resolve(strict=True)
        if not current.is_relative_to(trusted_project_root):
            raise ValueError("private worker cwd moved outside the project root")
    finally:
        os.close(descriptor)
    return expected
