"""Platform-known dotnet paths, runtime prefix, timeouts, and subcommand allowlist.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
import sys

# Runtime line prefix validated in ``dotnet --list-runtimes`` output.
RUNTIME_PREFIX = "Microsoft.NETCore.App 8."

# Probe JSON schema fields validated in the helper's --probe-json response.
PROBE_PROTOCOL_VERSION = "1.0"
PROBE_RUNTIME_MAJOR = 8

# Accepted helper subcommands (the token after ``--`` in the argv).
ACCEPTED_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "--probe-json",
        "--revisions-read",
        "--revisions-accept",
        "--revisions-reject",
        "--comments-read",
        "--comments-add",
        "--comments-resolve",
        "--template-apply",
        "--schema-validate",
        "--xlsx-schema-validate",
    }
)

# Default per-operation timeouts (seconds).
TIMEOUT_PROBE: float = 10.0
TIMEOUT_REVISIONS_READ: float = 30.0
TIMEOUT_REVISIONS_MUTATE: float = 30.0
TIMEOUT_COMMENTS_READ: float = 30.0
TIMEOUT_COMMENTS_ADD: float = 30.0
TIMEOUT_TEMPLATE_APPLY: float = 60.0
TIMEOUT_SCHEMA_VALIDATE: float = 30.0
TIMEOUT_RUNTIME_PROBE: float = 2.0
TIMEOUT_LOCKED_RESTORE: float = 120.0
TIMEOUT_NO_RESTORE_BUILD: float = 60.0
TIMEOUT_COLD_DETECTION: float = (
    TIMEOUT_RUNTIME_PROBE
    + TIMEOUT_LOCKED_RESTORE
    + TIMEOUT_NO_RESTORE_BUILD
    + TIMEOUT_PROBE
)

# Output limit (4 MiB — schema validation can produce large error lists).
OUTPUT_LIMIT: int = 4_194_304

# Runtime/version probe output limit.
RUNTIME_PROBE_OUTPUT_LIMIT: int = 32_768
PROBE_OUTPUT_LIMIT: int = 65_536

# Stdin payload ceiling (1 MiB).
STDIN_CEILING: int = 1_048_576

# Helper subdirectory name (relative to this package).
HELPER_DIR_NAME = "helper"
HELPER_PROJECT_NAME = "OpenXmlHelper.csproj"

# The detector may materialize the checked-in graph, but only under NuGet's
# fail-closed lock semantics. Provider operations never restore packages.
LOCKED_RESTORE_FLAGS: tuple[str, ...] = ("--locked-mode", "--use-lock-file")
RUN_NO_RESTORE_FLAG = "--no-restore"
RUN_NO_BUILD_FLAG = "--no-build"

# These values are synthesized by ProcessRunner as directories beneath a unique,
# managed project-private operation root. No user HOME, USERPROFILE, NuGet cache,
# or per-user NuGet configuration is inherited. NuGet on Windows also requires
# private replacements for its application-data and machine-wide settings roots.
DOTNET_PRIVATE_ENVIRONMENT: tuple[str, ...] = (
    "DOTNET_CLI_HOME",
    "NUGET_PACKAGES",
    *(
        ("APPDATA", "LOCALAPPDATA", "PROGRAMFILES(X86)")
        if sys.platform == "win32"
        else ()
    ),
)


def helper_build_properties(private_home: Path) -> tuple[str, ...]:
    """Return concrete MSBuild paths beneath one runner-owned private home."""

    build_root = (private_home / "openxml-helper-build").resolve(strict=False)
    normalized = build_root.as_posix().rstrip("/")
    return (
        f"/p:BaseOutputPath={normalized}/bin/",
        f"/p:BaseIntermediateOutputPath={normalized}/obj/",
        f"/p:MSBuildProjectExtensionsPath={normalized}/obj/",
    )


def helper_assembly_path(private_home: Path) -> Path:
    """Return the helper DLL emitted by the private Debug/net8.0 build."""

    return (
        private_home
        / "openxml-helper-build"
        / "bin"
        / "Debug"
        / "net8.0"
        / "OpenXmlHelper.dll"
    ).resolve(strict=False)


def platform_known_paths() -> list[str]:
    """Return platform-known dotnet install locations."""
    if sys.platform == "win32":
        return [
            r"C:\Program Files\dotnet\dotnet.exe",
            r"C:\Program Files (x86)\dotnet\dotnet.exe",
        ]
    if sys.platform == "darwin":
        return [
            "/usr/local/share/dotnet/dotnet",
            "/opt/homebrew/bin/dotnet",
        ]
    return [
        "/usr/bin/dotnet",
        "/usr/share/dotnet/dotnet",
    ]
