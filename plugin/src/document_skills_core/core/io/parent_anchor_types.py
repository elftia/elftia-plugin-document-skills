"""Shared types and small helpers for identity-bound directory anchors."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


FileIdentity = tuple[int, int]


class ParentSafetyError(OSError):
    """The destination parent cannot support a safe anchored transaction."""

    def __init__(
        self,
        reason: str,
        *,
        phase: str,
        original_path: Path,
        current_path: Path | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.phase = phase
        self.original_path = original_path
        self.current_path = current_path


def absolute_without_resolution(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def reject_redirected_components(parent: Path) -> None:
    absolute = absolute_without_resolution(parent)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode) or is_reparse(metadata):
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


def assert_plain_directory(path: Path, *, phase: str) -> None:
    metadata = os.lstat(path)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or is_reparse(metadata)
    ):
        raise ParentSafetyError(
            "destination_parent_not_plain_directory",
            phase=phase,
            original_path=path,
        )


def is_reparse(metadata: os.stat_result) -> bool:
    return os.name == "nt" and bool(metadata.st_file_attributes & 0x400)


def safe_leaf(name: str) -> str:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ParentSafetyError(
            "destination_path_escape",
            phase="leaf",
            original_path=Path(name),
        )
    return name


def same_path(first: Path, second: Path) -> bool:
    if os.name == "nt":
        return os.path.normcase(str(first)) == os.path.normcase(str(second))
    return first == second


def path_recovery_supported() -> bool:
    return sys.platform.startswith("linux") or sys.platform == "darwin"
