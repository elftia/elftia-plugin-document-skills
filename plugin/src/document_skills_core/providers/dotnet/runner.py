"""DotnetOpenXmlRunner — ProcessRunner-backed contained helper invocation.

Every invocation routes through the existing allowlisted ProcessRunner with:
shell:false argv array, a no-restore helper/subcommand prefix,
contained private cwd inside the project root, sanitized minimal environment,
bounded per-operation timeout, output limit, cancellation, and process-tree
cleanup.

Module provenance: original Elftia-authored clean-room implementation.
"""

import json
from pathlib import Path
from typing import Any, Protocol

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.process import ProcessPolicy, ProcessResult, ProcessRunner
from .constants import (
    ACCEPTED_SUBCOMMANDS,
    DOTNET_PRIVATE_ENVIRONMENT,
    HELPER_DIR_NAME,
    OUTPUT_LIMIT,
    RUN_NO_BUILD_FLAG,
    RUN_NO_RESTORE_FLAG,
    STDIN_CEILING,
    helper_assembly_path,
    helper_build_properties,
)

# Per-operation timeout lookup (keyed by subcommand).
_TIMEOUTS: dict[str, float] = {
    "--probe-json": 10.0,
    "--revisions-read": 30.0,
    "--revisions-accept": 30.0,
    "--revisions-reject": 30.0,
    "--comments-read": 30.0,
    "--comments-add": 30.0,
    "--template-apply": 60.0,
    "--schema-validate": 30.0,
    "--xlsx-schema-validate": 30.0,
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
        private_environment: tuple[str, ...] = ...,
    ) -> ProcessResult: ...


class DotnetOpenXmlRunner:
    """Contained helper execution through ProcessRunner without restore."""

    def __init__(
        self,
        project_root: Path,
        helper_dir: Path | None = None,
        executable: str | Path | None = None,
        runner: _ContainedRunner | None = None,
        policy: ProcessPolicy | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        if helper_dir is not None:
            self._helper_dir = helper_dir.resolve()
        else:
            self._helper_dir = Path(__file__).resolve().parent / HELPER_DIR_NAME
        self._executable: str | Path | None = None
        if runner is not None:
            self._runner = runner
            if isinstance(runner, ProcessRunner):
                if policy is not None and policy is not runner.policy:
                    raise ValueError(
                        "Injected ProcessRunner must use the injected ProcessPolicy."
                    )
                self._policy = runner.policy
            else:
                self._policy = policy or ProcessPolicy(self.project_root)
        else:
            self._policy = policy or ProcessPolicy(self.project_root)
            self._runner = ProcessRunner(self._policy)
        (
            self._helper_build_properties,
            self._helper_assembly,
        ) = _private_helper_build_layout(
            self._runner
        )
        if executable is not None:
            self.set_executable(executable)

    def set_executable(self, executable: str | Path) -> None:
        self._executable = self._policy.allow_executable(
            "dotnet-openxml", executable
        )

    def bind_authorized_executable(self, executable: str | Path) -> None:
        """Bind the exact executable record already proven by the detector."""

        self._executable = self._policy.require_executable(
            "dotnet-openxml",
            executable,
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
        if self._helper_assembly is None:
            argv = _build_argv(self._helper_dir, subcommand)
        else:
            argv = _build_argv(
                self._helper_dir,
                subcommand,
                self._helper_build_properties,
                self._helper_assembly,
            )
        _require_no_restore_argv(argv)
        resolved_timeout = timeout_seconds or _TIMEOUTS.get(subcommand, 30.0)
        resolved_limit = output_limit or OUTPUT_LIMIT
        return self._runner.run(
            "dotnet-openxml",
            self._executable,
            argv,
            cwd=self.project_root,
            timeout_seconds=resolved_timeout,
            output_limit=resolved_limit,
            stdin_json=stdin_payload,
            private_environment=DOTNET_PRIVATE_ENVIRONMENT,
        )


def _build_argv(
    helper_dir: Path,
    subcommand: str,
    build_properties: tuple[str, ...] = (),
    helper_assembly: Path | None = None,
) -> list[str]:
    """Build the full argv with implicit package restore disabled."""
    if helper_assembly is not None:
        return ["exec", str(helper_assembly), subcommand]
    return [
        "run",
        RUN_NO_RESTORE_FLAG,
        RUN_NO_BUILD_FLAG,
        "--project",
        str(helper_dir),
        *build_properties,
        "--",
        subcommand,
    ]


def _private_helper_build_layout(
    runner: _ContainedRunner,
) -> tuple[tuple[str, ...], Path | None]:
    if not isinstance(runner, ProcessRunner):
        return (), None
    private_home = runner.private_environment_directory("DOTNET_CLI_HOME")
    return (
        helper_build_properties(private_home),
        helper_assembly_path(private_home),
    )


def _require_no_restore_argv(argv: list[str]) -> None:
    """Fail closed if a provider operation could implicitly restore NuGet."""
    if argv and argv[0] == "exec" and len(argv) == 3:
        return
    if (
        not argv
        or argv[0] != "run"
        or RUN_NO_RESTORE_FLAG not in argv
        or RUN_NO_BUILD_FLAG not in argv
    ):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Dotnet helper execution must disable implicit package restore and build.",
        )


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
