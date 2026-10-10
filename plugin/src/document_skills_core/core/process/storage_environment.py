"""Narrow environment binding for an already-enforced LibreOffice tree.

Module provenance: original Elftia-authored clean-room implementation.
"""

import os
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
        names = ["temporary", "home"]
        if os.name == "nt":
            names += ["home/appdata", "home/appdata/roaming", "home/appdata/local"]
        for name in names:
            path = root / name
            item = path.lstat()
            if not stat.S_ISDIR(item.st_mode) or item.st_dev != metadata.st_dev or path.is_symlink():
                raise OSError("Quota environment directory changed.")
    except OSError as error:
        raise DocumentSkillsError(ErrorCode.PATH_UNSAFE, "Quota process environment lost its bound storage.") from error
    temporary, home = str(root / "temporary"), str(root / "home")
    environment = {
        "TMPDIR": temporary, "TEMP": temporary, "TMP": temporary, "HOME": home,
        "XDG_CACHE_HOME": home, "XDG_CONFIG_HOME": home,
        # Headless conversion must not use the desktop dconf service or its
        # writable shared-memory cache. Settings remain process-local.
        "GSETTINGS_BACKEND": "memory",
    }
    if os.name == "nt":
        profile = root / "home"
        environment.update({
            "USERPROFILE": str(profile), "HOMEDRIVE": profile.drive,
            "HOMEPATH": str(profile)[len(profile.drive):],
            "APPDATA": str(profile / "appdata" / "roaming"),
            "LOCALAPPDATA": str(profile / "appdata" / "local"),
            "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
        })
    return environment
