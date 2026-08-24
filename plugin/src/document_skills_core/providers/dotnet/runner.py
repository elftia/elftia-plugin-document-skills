"""DotnetOpenXmlRunner — ProcessRunner-backed contained helper invocation.

Every invocation routes through the existing allowlisted ProcessRunner with:
shell:false argv array, ``run --project <helper> -- <subcommand>`` prefix,
contained private cwd inside the project root, sanitized minimal environment,
bounded per-operation timeout, output limit, cancellation, and process-tree
cleanup.

Module provenance: original Elftia-authored clean-room implementation.
"""

import json
from pathlib import Path
from typing import Any, Protocol

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.process import ProcessPolicy, ProcessRunner, ProcessResult
from .constants import (
    ACCEPTED_SUBCOMMANDS,
    HELPER_DIR_NAME,
    OUTPUT_LIMIT,
    STDIN_CEILING,
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
    ) -> ProcessResult: ...


class DotnetOpenXmlRunner:
    """Contained ``dotnet run --project`` execution through ProcessRunner."""

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
        self._executable = executable
        if runner is not None:
            self._runner = runner
        else:
            policy = ProcessPolicy(self.project_root)
            self._runner = ProcessRunner(policy)

    def set_executable(self, executable: str | Path) -> None:
        self._executable = executable

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
        argv = _build_argv(self._helper_dir, subcommand)
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
        )


def _build_argv(helper_dir: Path, subcommand: str) -> list[str]:
    """Build the full argv: run --project <helper> -- <subcommand>."""
    return ["run", "--project", str(helper_dir), "--", subcommand]


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
