"""Platform-known dotnet paths, runtime prefix, timeouts, and subcommand allowlist.

Module provenance: original Elftia-authored clean-room implementation.
"""

import sys

# Runtime line prefix validated in ``dotnet --list-runtimes`` output.
RUNTIME_PREFIX = "Microsoft.NETCore.App 8."

# Probe JSON schema fields validated in the helper's --probe-json response.
PROBE_PROTOCOL_VERSION = "1.0"
PROBE_RUNTIME_MAJOR = 8

# Accepted helper subcommands (the token after ``--`` in the argv).
ACCEPTED_SUBCOMMANDS: frozenset[str] = frozenset({
    "--probe-json",
    "--revisions-read",
    "--revisions-accept",
    "--revisions-reject",
    "--comments-read",
    "--comments-add",
    "--template-apply",
    "--schema-validate",
    "--xlsx-schema-validate",
})

# Default per-operation timeouts (seconds).
TIMEOUT_PROBE: float = 10.0
TIMEOUT_REVISIONS_READ: float = 30.0
TIMEOUT_REVISIONS_MUTATE: float = 30.0
TIMEOUT_COMMENTS_READ: float = 30.0
TIMEOUT_COMMENTS_ADD: float = 30.0
TIMEOUT_TEMPLATE_APPLY: float = 60.0
TIMEOUT_SCHEMA_VALIDATE: float = 30.0
TIMEOUT_RUNTIME_PROBE: float = 2.0

# Output limit (4 MiB — schema validation can produce large error lists).
OUTPUT_LIMIT: int = 4_194_304

# Runtime/version probe output limit.
RUNTIME_PROBE_OUTPUT_LIMIT: int = 32_768
PROBE_OUTPUT_LIMIT: int = 65_536

# Stdin payload ceiling (1 MiB).
STDIN_CEILING: int = 1_048_576

# Helper subdirectory name (relative to this package).
HELPER_DIR_NAME = "helper"


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
