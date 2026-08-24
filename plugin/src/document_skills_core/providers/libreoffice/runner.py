"""LibreOfficeRunner — ProcessRunner-backed headless execution with containment.

Every invocation routes through the existing allowlisted ProcessRunner with:
shell:false argv array, contained private cwd inside the project root,
sanitized minimal environment, headless prefix flags, macro DISABLED,
bounded timeout, output limit, cancellation, and process-tree cleanup.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from ...core.process import ProcessPolicy, ProcessResult, ProcessRunner
from .constants import (
    ACCEPTED_SUBCOMMANDS,
    FORBIDDEN_TOKENS,
    HEADLESS_PREFIX,
    OUTPUT_LIMIT,
    TIMEOUT_CONVERT,
    TIMEOUT_LEGACY,
    TIMEOUT_RECALC,
    TIMEOUT_RENDER,
    USER_INSTALLATION_PREFIX,
)
from .output import (
    assert_output_capacity,
    assert_output_within_limit,
    output_limit,
    output_runtime_check,
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
        runtime_check: Callable[[], None] | None = ...,
    ) -> ProcessResult: ...


class LibreOfficeRunner:
    """Headless LibreOffice execution through the existing ProcessRunner."""

    def __init__(
        self,
        project_root: Path,
        executable: str | Path | None = None,
        runner: _ContainedRunner | None = None,
        *,
        policy: ProcessPolicy | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self._executable: Path | None = None
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
        if executable is not None:
            self.set_executable(executable)

    def set_executable(self, executable: str | Path) -> None:
        self._executable = self._policy.allow_executable("libreoffice", executable)

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
        output_limit(target_format)
        assert_output_capacity(output_dir, target_format)
        expected = output_dir.resolve() / (input_path.stem + "." + target_format)
        runtime_check = output_runtime_check(
            output_dir,
            expected,
            target_format,
        )
        with OperationTempRoot() as private_root:
            profile_root = private_root / "libreoffice-profile"
            profile_root.mkdir(mode=0o700)
            argv = _build_argv(
                profile_root,
                "--convert-to",
                target_format,
                "--outdir",
                str(output_dir.resolve()),
                str(input_path.resolve()),
            )
            self._runner.run(
                "libreoffice",
                self._executable,
                argv,
                cwd=self.project_root,
                timeout_seconds=timeout_seconds,
                output_limit=OUTPUT_LIMIT,
                runtime_check=runtime_check,
            )
        if not expected.is_file():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice conversion produced no output file.",
                details={"expected": expected.name},
            )
        assert_output_within_limit(expected, target_format)
        return expected


def _build_argv(profile_root: Path, *operation_args: str) -> list[str]:
    """Build the full argv: headless prefix + operation args, validated."""
    profile_uri = profile_root.resolve().as_uri()
    argv = [
        *HEADLESS_PREFIX,
        f"{USER_INSTALLATION_PREFIX}{profile_uri}",
        *operation_args,
    ]
    _validate_argv(argv)
    return argv


def _validate_argv(argv: list[str]) -> None:
    """Require the fixed prefix, one private profile, and an accepted command."""
    prefix_length = len(HEADLESS_PREFIX)
    if argv[:prefix_length] != HEADLESS_PREFIX:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice argv does not begin with the required headless flags.",
        )
    profile_args = [
        token for token in argv if token.startswith(USER_INSTALLATION_PREFIX)
    ]
    profile_index = prefix_length
    expected_command_index = profile_index + 1
    if (
        len(profile_args) != 1
        or len(argv) <= profile_index
        or argv[profile_index] != profile_args[0]
        or not profile_args[0][len(USER_INSTALLATION_PREFIX):].startswith("file:///")
    ):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice argv requires one local file-URI user profile before the command.",
        )
    if (
        len(argv) <= expected_command_index
        or argv[expected_command_index] not in ACCEPTED_SUBCOMMANDS
    ):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice argv does not begin with an accepted subcommand.",
            details={
                "argv": [tok for tok in argv if tok in ACCEPTED_SUBCOMMANDS]
            },
        )
    operation_argv = argv[expected_command_index:]
    joined_operation = " ".join(operation_argv)
    for forbidden in FORBIDDEN_TOKENS:
        if forbidden.lower() in joined_operation.lower():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice argv contains a forbidden macro/DDE token.",
                details={"token": forbidden},
            )


def _timeout_for_format(target_format: str) -> float:
    if target_format == "xlsx":
        return TIMEOUT_RECALC
    if target_format == "pdf":
        return TIMEOUT_CONVERT
    if target_format == "png":
        return TIMEOUT_RENDER
    return TIMEOUT_LEGACY
