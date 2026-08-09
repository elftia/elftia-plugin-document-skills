"""Portable path identity shared by runtime and release-policy boundaries."""

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
import unicodedata

FORBIDDEN_PORTABLE_COMPONENTS = frozenset(
    {
        ".document-skills-tmp",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "bin",
        "build",
        "dist",
        "node_modules",
        "obj",
    }
)
_DRIVE = re.compile(r"^[a-zA-Z]:")


@dataclass(frozen=True)
class PortablePath:
    original: str
    components: tuple[str, ...]
    keys: tuple[str, ...]

    @property
    def has_forbidden_component(self) -> bool:
        return bool(FORBIDDEN_PORTABLE_COMPONENTS.intersection(self.keys))


class PortablePathPolicy:
    """Normalize path components without losing the original evidence string."""

    @staticmethod
    def component_key(component: str) -> str:
        if type(component) is not str:
            raise TypeError("path component must be a plain string")
        if "\0" in component or any(0xD800 <= ord(char) <= 0xDFFF for char in component):
            raise ValueError("path component contains an invalid Unicode scalar")
        normalized = unicodedata.normalize("NFKC", component)
        normalized = unicodedata.normalize("NFKC", normalized.casefold())
        return normalized.rstrip(" .")

    def parse_relative(self, value: str) -> PortablePath:
        if type(value) is not str or not value:
            raise ValueError("path must be a non-empty plain string")
        normalized_separators = value.replace("\\", "/")
        if (
            normalized_separators.startswith(("/", "//"))
            or _DRIVE.match(normalized_separators)
        ):
            raise ValueError("absolute and device paths are forbidden")
        raw = tuple(PurePosixPath(normalized_separators).parts)
        if not raw:
            raise ValueError("path has no components")
        keys = tuple(self.component_key(part) for part in raw)
        if any(not key or key in {".", ".."} for key in keys):
            raise ValueError("empty, dot, and traversal components are forbidden")
        return PortablePath(value, raw, keys)

    def require_release_safe(self, value: str) -> PortablePath:
        identity = self.parse_relative(value)
        if identity.has_forbidden_component:
            raise ValueError(f"forbidden portable path component: {value}")
        return identity


PORTABLE_PATH_POLICY = PortablePathPolicy()
