"""LibreOfficeRunner — ProcessRunner-backed headless execution with containment.

Every invocation routes through the existing allowlisted ProcessRunner with:
shell:false argv array, contained private cwd inside the project root,
sanitized minimal environment, headless prefix flags, macro DISABLED,
bounded timeout, output limit, cancellation, and process-tree cleanup.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Protocol

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.process import ProcessPolicy, ProcessRunner, ProcessResult
from .constants import (
    ACCEPTED_SUBCOMMANDS,
    FORBIDDEN_TOKENS,
    HEADLESS_PREFIX,
    OUTPUT_LIMIT,
    TIMEOUT_CONVERT,
    TIMEOUT_LEGACY,
    TIMEOUT_RECALC,
    TIMEOUT_RENDER,
)


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
    ) -> ProcessResult: ...


class LibreOfficeRunner:
    """Headless LibreOffice execution through the existing ProcessRunner."""

    def __init__(
        self,
        project_root: Path,
        executable: str | Path | None = None,
        runner: _ContainedRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self._executable = executable
        if runner is not None:
            self._runner = runner
        else:
            policy = ProcessPolicy(self.project_root)
            self._runner = ProcessRunner(policy)

    def set_executable(self, executable: str | Path) -> None:
        self._executable = executable

    def convert(
        self,
        input_path: Path,
        target_format: str,
        output_dir: Path,
        *,
        timeout_seconds: float | None = None,
    ) -> Path:
        """Convert ``input_path`` to ``target_format`` via headless soffice.

        Returns the path to the converted file.
        Raises DocumentSkillsError on any failure.
        """
        if self._executable is None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice executable is not resolved.",
            )
        if timeout_seconds is None:
            timeout_seconds = _timeout_for_format(target_format)
        resolved_output = output_dir.resolve()
        profile_dir = resolved_output / ".libreoffice-profile"
        profile_dir.mkdir(mode=0o700, exist_ok=True)
        argv = _build_argv(
            f"-env:UserInstallation={profile_dir.as_uri()}",
            "--convert-to",
            target_format,
            "--outdir",
            str(resolved_output),
            str(input_path.resolve()),
        )
        result = self._runner.run(
            "libreoffice",
            self._executable,
            argv,
            cwd=self.project_root,
            timeout_seconds=timeout_seconds,
            output_limit=OUTPUT_LIMIT,
        )
        if result.returncode != 0:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice conversion exited non-zero.",
                details={"returncode": result.returncode},
            )
        expected = resolved_output / (input_path.stem + "." + target_format)
        if not expected.is_file():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice conversion produced no output file.",
                details={"expected": expected.name},
            )
        return expected


def _build_argv(*operation_args: str) -> list[str]:
    """Build the full argv: headless prefix + operation args, validated."""
    argv = [*HEADLESS_PREFIX, *operation_args]
    _validate_argv(argv)
    return argv


def _validate_argv(argv: list[str]) -> None:
    """Reject forbidden tokens and require an accepted subcommand prefix."""
    joined = " ".join(argv)
    for forbidden in FORBIDDEN_TOKENS:
        if forbidden.lower() in joined.lower():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice argv contains a forbidden macro/DDE token.",
                details={"token": forbidden},
            )
    non_flag = next((tok for tok in argv if not tok.startswith("-")), None)
    if non_flag is None:
        first_sub = next(
            (tok for tok in argv if tok in ACCEPTED_SUBCOMMANDS), None
        )
    else:
        first_sub = None
    has_accepted = any(tok in ACCEPTED_SUBCOMMANDS for tok in argv)
    if not has_accepted:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice argv does not begin with an accepted subcommand.",
            details={"argv": [tok for tok in argv if tok in ACCEPTED_SUBCOMMANDS]},
        )


def _timeout_for_format(target_format: str) -> float:
    if target_format == "xlsx":
        return TIMEOUT_RECALC
    if target_format == "pdf":
        return TIMEOUT_CONVERT
    if target_format == "png":
        return TIMEOUT_RENDER
    return TIMEOUT_LEGACY
