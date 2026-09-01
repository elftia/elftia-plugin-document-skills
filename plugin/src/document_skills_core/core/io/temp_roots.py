"""Private operation roots and conservative stale cleanup."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterator
import uuid

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .parent_anchor_types import (
    FileIdentity,
    assert_plain_directory,
    is_reparse,
    reject_redirected_components,
    same_path,
)

_ROOT_NAME = "document-skills-operations"
_OP_PREFIX = "operation-"
_SUPERVISED_OPERATION_ROOT: ContextVar[
    tuple[Path, FileIdentity, str] | None
] = ContextVar("document-skills-supervised-operation-root", default=None)


def managed_temp_root() -> Path:
    return (Path(tempfile.gettempdir()).resolve() / _ROOT_NAME).resolve()


class OperationTempRoot:
    def __init__(self, base: Path | None = None) -> None:
        self.base = (base or managed_temp_root()).resolve()
        self.path = self.base / f"{_OP_PREFIX}{uuid.uuid4().hex}"

    def __enter__(self) -> Path:
        self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.mkdir(mode=0o700)
        return self.path

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        _safe_remove_operation_root(self.path, self.base)


@contextmanager
def bind_supervised_operation_root(
    project_root: Path,
    invocation_id: str,
    root_path: str | Path,
    identity: FileIdentity,
) -> Iterator[Path]:
    """Bind one supervisor-owned private root to the current worker command."""

    root = _validate_supervised_operation_root(
        project_root,
        invocation_id,
        root_path,
        identity,
    )
    token = _SUPERVISED_OPERATION_ROOT.set((root, identity, invocation_id))
    try:
        yield root
    finally:
        _SUPERVISED_OPERATION_ROOT.reset(token)


def current_supervised_operation_root(project_root: Path) -> Path | None:
    """Return the still identity-matched root bound to this command, if any."""

    binding = _SUPERVISED_OPERATION_ROOT.get()
    if binding is None:
        return None
    root, identity, invocation_id = binding
    return _validate_supervised_operation_root(
        project_root,
        invocation_id,
        root,
        identity,
    )


def cleanup_stale_roots(
    *, base: Path | None = None, older_than: timedelta = timedelta(hours=24), limit: int = 32
) -> list[str]:
    root = (base or managed_temp_root()).resolve()
    if root.name != _ROOT_NAME or not root.is_dir():
        return []
    cutoff = datetime.now(timezone.utc) - older_than
    removed: list[str] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if len(removed) >= limit or not candidate.name.startswith(_OP_PREFIX):
            continue
        resolved = candidate.resolve(strict=False)
        if resolved.parent != root or not resolved.is_dir():
            continue
        modified = datetime.fromtimestamp(resolved.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            _safe_remove_operation_root(resolved, root)
            removed.append(resolved.name)
    return removed


def _safe_remove_operation_root(path: Path, base: Path) -> None:
    resolved = path.resolve(strict=False)
    safe_base = base.resolve()
    if (
        resolved.parent != safe_base
        or not resolved.name.startswith(_OP_PREFIX)
        or safe_base.name != _ROOT_NAME
    ):
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Refusing to clean an unresolved or unmanaged temporary path.",
        )
    if resolved.exists():
        shutil.rmtree(resolved)


def _validate_supervised_operation_root(
    project_root: Path,
    invocation_id: str,
    root_path: str | Path,
    identity: FileIdentity,
) -> Path:
    project = project_root.resolve(strict=True)
    raw_base = project / ".document-skills-tmp" / _ROOT_NAME
    try:
        reject_redirected_components(raw_base)
        assert_plain_directory(raw_base, phase="operation_root_bind")
        base = raw_base.resolve(strict=True)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "The supervised operation root base is unsafe.",
        ) from error
    root = Path(root_path)
    if not root.is_absolute() or len(identity) != 2:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "The supervised operation root binding is invalid.",
        )
    expected = base / f"{_OP_PREFIX}{invocation_id}"
    try:
        metadata = os.stat(root, follow_symlinks=False)
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "The supervised operation root is unavailable.",
        ) from error
    actual_identity = (metadata.st_dev, metadata.st_ino)
    if (
        not base.is_relative_to(project)
        or base.name != _ROOT_NAME
        or not same_path(root, expected)
        or not same_path(resolved, expected)
        or resolved.parent != base
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or is_reparse(metadata)
        or actual_identity != identity
    ):
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "The supervised operation root identity does not match.",
        )
    return resolved
