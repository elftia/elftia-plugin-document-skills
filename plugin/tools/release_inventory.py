"""Shared release inventory, hashing, and fail-closed artifact classification."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from document_skills_core.core.io.portable_paths import (
    FORBIDDEN_PORTABLE_COMPONENTS,
    PORTABLE_PATH_POLICY,
)

FORBIDDEN_RELEASE_NAMES = FORBIDDEN_PORTABLE_COMPONENTS | {".mcp.json"}
_LOCAL_GENERATED_ROOTS = {
    ".document-skills-tmp",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}
_LOCAL_GENERATED_PREFIXES = {
    (
        "src",
        "document_skills_core",
        "providers",
        "dotnet",
        "helper",
        "bin",
    ),
    (
        "src",
        "document_skills_core",
        "providers",
        "dotnet",
        "helper",
        "obj",
    ),
}
_LOCAL_GENERATED_NAMES = {"__pycache__"}
_NON_RUNTIME_DIRECTORY_NAMES = {
    ".computer-use",
    ".github",
    ".idea",
    ".vscode",
}
_EXECUTABLE_SUFFIXES = {
    ".appimage", ".bash", ".bat", ".bin", ".cjs", ".cmd", ".com", ".command",
    ".dll", ".dylib", ".exe", ".fish", ".jar", ".js", ".jsx", ".mjs", ".msi",
    ".mts", ".node", ".ps1", ".psd1", ".psm1", ".py", ".pyz", ".sh", ".so",
    ".ts", ".tsx", ".vbe", ".vbs", ".wasm", ".wsf", ".xla", ".xlam", ".xll",
    ".zsh",
}
_EXECUTION_LOCATIONS = {
    "bin", "provider", "providers", "runtime", "script", "scripts", "tools",
}
_EXECUTABLE_MAGICS = (
    b"\x00asm",  # WebAssembly
    b"\x7fELF",
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O fat
    b"\xbe\xba\xfe\xca",  # Mach-O fat, reversed
    b"\xca\xfe\xba\xbf",  # Mach-O FAT64
    b"\xbf\xba\xfe\xca",  # Mach-O FAT64, reversed
    b"\xce\xfa\xed\xfe",  # Mach-O 32, little endian
    b"\xcf\xfa\xed\xfe",  # Mach-O 64, little endian
    b"\xfe\xed\xfa\xce",  # Mach-O 32, big endian
    b"\xfe\xed\xfa\xcf",  # Mach-O 64, big endian
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE/CFB, including MSI
    b"MZ",  # PE/DOS
)


@dataclass(frozen=True)
class ReleaseArtifact:
    path: str
    sha256: str
    bytes: int
    classification: str
    reason: str

    @property
    def risky(self) -> bool:
        return self.classification == "executable-or-risky"


def release_inventory(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not _is_worktree_only(path.relative_to(root))
    )


def release_artifacts(
    root: Path, inventory: list[str] | None = None
) -> list[ReleaseArtifact]:
    paths = inventory if inventory is not None else release_inventory(root)
    fixture_data = _fixture_data_allowlist(root)
    return [
        _classify(root / relative, relative, fixture_data)
        for relative in sorted(paths)
    ]


def executable_artifacts(root: Path, inventory: list[str] | None = None) -> list[str]:
    return [
        artifact.path
        for artifact in release_artifacts(root, inventory)
        if artifact.risky
    ]


def is_executable_artifact(path: Path, relative: str) -> bool:
    root = path
    for _part in Path(relative).parts:
        root = root.parent
    return _classify(path, relative, _fixture_data_allowlist(root)).risky


def _classify(
    path: Path,
    relative: str,
    fixture_data: set[str],
) -> ReleaseArtifact:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    suffix = path.suffix.lower()
    identity = PORTABLE_PATH_POLICY.parse_relative(relative)
    parts = identity.keys[:-1]
    header = payload[:16]
    reason = ""
    if suffix in _EXECUTABLE_SUFFIXES:
        reason = f"executable suffix {suffix}"
    elif set(parts).intersection(_EXECUTION_LOCATIONS):
        reason = "execution-bearing release location"
    elif header.startswith(b"#!"):
        reason = "shebang launcher"
    elif header.startswith(_EXECUTABLE_MAGICS):
        reason = "executable/installer binary magic"
    elif _has_executable_mode(path):
        reason = "executable filesystem mode"
    elif not suffix:
        reason = "extensionless release artifact"
    elif _is_opaque(payload) and relative not in fixture_data:
        reason = "opaque or low-text bytes without fixture data allowlist"
    if reason:
        classification = "executable-or-risky"
    elif relative in fixture_data:
        classification = "fixture-data"
        reason = "exact hash is backed by tests/fixtures/manifest.json"
    else:
        classification = "reviewed-data"
        reason = "high-text non-execution release data"
    return ReleaseArtifact(relative, digest, len(payload), classification, reason)


def _fixture_data_allowlist(root: Path) -> set[str]:
    manifest_path = root / "tests" / "fixtures" / "manifest.json"
    if not manifest_path.is_file():
        return set()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    allowed: set[str] = set()
    for record in manifest.get("fixtures", []):
        if type(record) is not dict or record.get("redistribution_allowed") is not True:
            continue
        relative = record.get("path")
        expected = record.get("sha256")
        if type(relative) is not str or type(expected) is not str:
            continue
        project_relative = f"tests/fixtures/{relative}"
        candidate = root / project_relative
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == expected:
            allowed.add(project_relative)
    return allowed


def _is_opaque(payload: bytes) -> bool:
    if not payload:
        return False
    sample = payload[:65_536]
    if b"\0" in sample:
        return True
    try:
        text = sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return True
    controls = sum(
        ord(character) < 32 and character not in "\t\n\r"
        for character in text
    )
    return bool(text) and controls / len(text) > 0.02


def _has_executable_mode(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False


def _is_worktree_only(relative: Path) -> bool:
    if not relative.parts:
        return False
    normalized_directories = {part.casefold() for part in relative.parts[:-1]}
    # Only exact canonical generated-state spellings are locally disposable.
    # Portable aliases remain release candidates so the policy can reject them.
    return (
        relative.parts[0] in _LOCAL_GENERATED_ROOTS
        or any(
            relative.parts[: len(prefix)] == prefix
            for prefix in _LOCAL_GENERATED_PREFIXES
        )
        or bool(set(relative.parts).intersection(_LOCAL_GENERATED_NAMES))
        or bool(normalized_directories.intersection(_NON_RUNTIME_DIRECTORY_NAMES))
    )
