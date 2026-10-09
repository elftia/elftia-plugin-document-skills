"""Narrow environment binding for an already-enforced LibreOffice tree.

Module provenance: original Elftia-authored clean-room implementation.
"""

import stat
from pathlib import Path

from ..contracts.errors import DocumentSkillsError, ErrorCode


def quota_storage_environment(
    provider_id: str, storage: tuple[Path, tuple[int, int]],
) -> dict[str, str]:
    root, identity = storage
    if provider_id != "libreoffice":
        raise DocumentSkillsError(ErrorCode.PATH_UNSAFE, "Quota storage is restricted to LibreOffice.")
    try:
        metadata = root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != identity:
            raise OSError("Quota root identity changed.")
        for name in ("temporary", "home"):
            path = root / name
            item = path.lstat()
            if not stat.S_ISDIR(item.st_mode) or item.st_dev != metadata.st_dev or path.is_symlink():
                raise OSError("Quota environment directory changed.")
    except OSError as error:
        raise DocumentSkillsError(ErrorCode.PATH_UNSAFE, "Quota process environment lost its bound storage.") from error
    temporary, home = str(root / "temporary"), str(root / "home")
    return {
        "TMPDIR": temporary, "TEMP": temporary, "TMP": temporary, "HOME": home,
        "XDG_CACHE_HOME": home, "XDG_CONFIG_HOME": home,
        # Headless conversion must not use the desktop dconf service or its
        # writable shared-memory cache. Settings remain process-local.
        "GSETTINGS_BACKEND": "memory",
    }
