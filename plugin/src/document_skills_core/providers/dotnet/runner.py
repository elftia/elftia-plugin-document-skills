"""DotnetOpenXmlRunner — ProcessRunner-backed contained helper invocation.

Every invocation routes through the existing allowlisted ProcessRunner with:
shell:false argv arrays for a private build followed by ``dotnet exec``,
contained private cwd inside the project root, sanitized minimal environment,
bounded per-operation timeout, output limit, cancellation, and process-tree
cleanup.

Module provenance: original Elftia-authored clean-room implementation.
"""

import json
import os
from pathlib import Path
import time
from typing import Any, Protocol

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from ...core.process import ProcessPolicy, ProcessRunner, ProcessResult
from .constants import (
    ACCEPTED_SUBCOMMANDS,
    HELPER_DIR_NAME,
    OUTPUT_LIMIT,
    STDIN_CEILING,
    TIMEOUT_PROBE,
)

# Per-operation timeout lookup (keyed by subcommand).
_TIMEOUTS: dict[str, float] = {
    "--probe-json": TIMEOUT_PROBE,
    "--revisions-read": 30.0,
    "--revisions-accept": 30.0,
    "--revisions-reject": 30.0,
    "--comments-read": 30.0,
    "--comments-add": 30.0,
    "--comments-resolve": 30.0,
    "--template-apply": 60.0,
    "--schema-validate": 30.0,
}


class _ContainedRunner(Protocol):
    """Minimal interface for the contained ProcessRunner (real or fake)."""

    def run(
        self,
        provider_id: str,
        executable: str | Path,
        args: list[str],
        *,
        cwd: Path | None = ...,
        timeout_seconds: float = ...,
        output_limit: int = ...,
        stdin_json: object | None = ...,
        fixed_environment: dict[str, str] | None = ...,
    ) -> ProcessResult: ...


class DotnetOpenXmlRunner:
    """Contained private build and execution through ProcessRunner."""

    def __init__(
        self,
        project_root: Path,
        helper_dir: Path | None = None,
        executable: str | Path | None = None,
        runner: _ContainedRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        if helper_dir is not None:
            self._helper_dir = helper_dir.resolve()
        else:
            self._helper_dir = (
                Path(__file__).resolve().parent / HELPER_DIR_NAME
            )
        self._executable: str | Path | None = None
        self._policy: ProcessPolicy | None = None
        if runner is not None:
            self._runner = runner
        else:
            self._policy = ProcessPolicy(self.project_root)
            self._runner = ProcessRunner(self._policy)
        if executable is not None:
            self.set_executable(executable)

    def set_executable(self, executable: str | Path) -> None:
        self._executable = (
            self._policy.allow_executable("dotnet-openxml", executable)
            if self._policy is not None
            else executable
        )

    def run(
        self,
        subcommand: str,
        *,
        stdin_payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        output_limit: int | None = None,
    ) -> ProcessResult:
        """Run the helper with the given subcommand via ProcessRunner."""
        if subcommand not in ACCEPTED_SUBCOMMANDS:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                f"Unknown dotnet helper subcommand: {subcommand}",
                details={"subcommand": subcommand},
            )
        if self._executable is None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "dotnet executable is not resolved.",
            )
        _check_stdin(stdin_payload)
        resolved_timeout = timeout_seconds or _TIMEOUTS.get(subcommand, 30.0)
        resolved_limit = output_limit or OUTPUT_LIMIT
        started = time.monotonic()
        with OperationTempRoot() as private_root:
            private_cwd = private_root / "process-cwd"
            private_cwd.mkdir(mode=0o700)
            fixed_environment = _dotnet_fixed_environment(private_root)
            build_result = self._runner.run(
                "dotnet-openxml",
                self._executable,
                _build_argv(
                    self._helper_dir,
                    private_root / "dotnet-build",
                ),
                cwd=private_cwd,
                timeout_seconds=resolved_timeout,
                output_limit=resolved_limit,
                fixed_environment=fixed_environment,
            )
            if build_result.returncode != 0:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "The contained dotnet helper build failed.",
                    details={"returncode": build_result.returncode},
                )
            return self._runner.run(
                "dotnet-openxml",
                self._executable,
                _exec_argv(private_root / "dotnet-build", subcommand),
                cwd=private_cwd,
                timeout_seconds=_remaining_timeout(started, resolved_timeout),
                output_limit=resolved_limit,
                stdin_json=stdin_payload,
                fixed_environment=fixed_environment,
            )


def _build_argv(
    helper_dir: Path,
    build_root: Path,
) -> list[str]:
    """Build the helper with all generated outputs in a private root."""
    helper = helper_dir.resolve()
    private_build = build_root.resolve()
    package_environment = os.environ.get("NUGET_PACKAGES")
    package_root = (
        Path(package_environment)
        if package_environment is not None
        else Path.home() / ".nuget" / "packages"
    )
    packages = package_root.expanduser().resolve()
    return [
        "build",
        str(helper / "OpenXmlHelper.csproj"),
        "--nologo",
        "--verbosity:quiet",
        "--output",
        str(private_build / "app"),
        f"--property:RestoreConfigFile={helper / 'NuGet.Config'}",
        f"--property:RestorePackagesPath={packages}",
        "--property:BaseIntermediateOutputPath="
        f"{private_build / 'obj'}{os.sep}",
        f"--property:BaseOutputPath={private_build / 'bin'}{os.sep}",
    ]


def _exec_argv(build_root: Path, subcommand: str) -> list[str]:
    """Execute the private helper assembly with an accepted subcommand."""
    assembly = build_root.resolve() / "app" / "OpenXmlHelper.dll"
    return ["exec", str(assembly), subcommand]


def _remaining_timeout(started: float, budget: float) -> float:
    remaining = budget - (time.monotonic() - started)
    if remaining <= 0:
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "The contained dotnet helper exhausted its time budget while building.",
            details={"timeout_seconds": budget},
        )
    return remaining


def _check_stdin(payload: dict[str, Any] | None) -> int:
    """Validate the stdin payload is under the ceiling. Returns byte size."""
    if payload is None:
        return 0
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(raw) > STDIN_CEILING:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Stdin payload exceeds the 1 MiB ceiling.",
            details={"payload_bytes": len(raw), "ceiling": STDIN_CEILING},
        )
    return len(raw)


def _dotnet_fixed_environment(private_root: Path) -> dict[str, str]:
    private_profile = private_root / "userprofile"
    paths = {
        "APPDATA": private_profile / "AppData" / "Roaming",
        "DOTNET_CLI_HOME": private_root / "cli-home",
        "LOCALAPPDATA": private_profile / "AppData" / "Local",
        "NUGET_HTTP_CACHE_PATH": private_root / "http-cache",
        "NUGET_PLUGINS_CACHE_PATH": private_root / "plugins-cache",
        "USERPROFILE": private_profile,
    }
    environment = {
        # The .NET CLI otherwise persists this per-operation CLI home under
        # HKCU\Environment\Path on Windows. USERPROFILE isolation does not
        # contain that registry write.
        "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
        "DOTNET_NOLOGO": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    }
    for key, path in paths.items():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        environment[key] = str(path)
    return environment
