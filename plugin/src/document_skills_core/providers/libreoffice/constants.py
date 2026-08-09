"""Platform-known soffice paths, version regex, timeouts, and headless flags.

Module provenance: original Elftia-authored clean-room implementation.
"""

import sys

# Headless argument prefix — always present for every LibreOffice invocation.
HEADLESS_PREFIX: list[str] = [
    "--headless",
    "--norestore",
    "--nofirststartwizard",
    "--nolockcheck",
]

# Accepted subcommand prefixes (the first non-flag token in the argv).
# Anything else (e.g. --cmd, .bas/.xba paths, DDE args) is rejected.
ACCEPTED_SUBCOMMANDS: frozenset[str] = frozenset({"--convert-to", "--cat", "--print-to-file"})

# Tokens that MUST NEVER appear in argv (macro/DDE/external-data execution).
FORBIDDEN_TOKENS: frozenset[str] = frozenset({
    "--cmd", ".bas", ".xba", "--unaccept", "macro:", "DDE", "DDELINK",
})

# Default per-operation timeouts (seconds).
TIMEOUT_RECALC: float = 60.0
TIMEOUT_CONVERT: float = 30.0
TIMEOUT_RENDER: float = 30.0
TIMEOUT_LEGACY: float = 30.0
TIMEOUT_VERSION_PROBE: float = 2.0

# Output limit (1 MiB).
OUTPUT_LIMIT: int = 1_048_576

# Version probe output limit.
VERSION_PROBE_OUTPUT_LIMIT: int = 16_384

# Version regex — permissive; parses the dotted version after "LibreOffice".
import re

VERSION_REGEX = re.compile(r"LibreOffice\s+([0-9]+(?:\.[0-9]+)+)")

# Executable names to probe on PATH.
EXECUTABLE_NAMES: list[str] = ["soffice", "libreoffice"]


def platform_known_paths() -> list[str]:
    """Return platform-known soffice install locations."""
    if sys.platform == "win32":
        return [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    if sys.platform == "darwin":
        return ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    return [
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/opt/libreoffice/program/soffice",
    ]
