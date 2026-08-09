"""Private operation roots and conservative stale cleanup."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from ..contracts.errors import DocumentSkillsError, ErrorCode

_ROOT_NAME = "document-skills-operations"
_OP_PREFIX = "operation-"


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

