"""LibreOfficeRunner — ProcessRunner-backed headless execution with containment.

Every invocation routes through the existing allowlisted ProcessRunner with:
shell:false argv array, contained private cwd inside the project root,
sanitized minimal environment, headless prefix flags, macro DISABLED,
bounded timeout, output limit, cancellation, and process-tree cleanup.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
import os
from pathlib import Path
from typing import Protocol
import uuid

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.process import ProcessPolicy, ProcessResult, ProcessRunner
from .constants import (
    ACCEPTED_SUBCOMMANDS,
    FORBIDDEN_TOKENS,
    HEADLESS_PREFIX,
    OUTPUT_LIMIT,
    TIMEOUT_CONVERT,
    TIMEOUT_LEGACY,
    TIMEOUT_RECALC_REQUIRED,
    TIMEOUT_RENDER,
    USER_INSTALLATION_PREFIX,
)
from .output import (
    assert_output_within_limit,
    output_limit,
    output_runtime_observer,
    read_provider_output,
)
from .quota import (
    HardQuotaBackend,
    ProcessStorageSession,
    capture_directory_identity,
    require_hard_quota_backend,
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
        quota_storage: tuple[Path, tuple[int, int]] | None = ...,
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
        quota_backend: HardQuotaBackend | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self._executable: Path | None = None
        self._quota_backend = quota_backend
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
        artifact_limit = output_limit(target_format)
        backend = require_hard_quota_backend(self._quota_backend)
        output_root = output_dir.resolve(strict=True)
        output_identity = capture_directory_identity(output_root)
        expected_name = input_path.stem + "." + target_format
        expected = output_root / expected_name
        with backend.open(byte_limit=artifact_limit) as session:
            provider_expected = session.output_dir / expected_name
            runtime_check = output_runtime_observer(
                session.output_dir,
                provider_expected,
                target_format,
            )
            storage_options = {}
            if isinstance(session, ProcessStorageSession):
                storage_options["quota_storage"] = session.process_storage
                observe_output = runtime_check

                def runtime_check():
                    session.assert_live()
                    observe_output()
            argv = _build_argv(
                session.profile_dir,
                "--convert-to",
                target_format,
                "--outdir",
                str(session.output_dir),
                str(input_path.resolve(strict=True)),
            )
            result = self._runner.run(
                "libreoffice",
                self._executable,
                argv,
                cwd=self.project_root,
                timeout_seconds=timeout_seconds,
                output_limit=OUTPUT_LIMIT,
                runtime_check=runtime_check,
                **storage_options,
            )
            if result.returncode != 0:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice conversion exited non-zero.",
                    details={"returncode": result.returncode},
                )
            session.validate_final_tree(expected_name=expected_name)
            payload = read_provider_output(provider_expected, target_format)
        if capture_directory_identity(output_root) != output_identity:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice destination directory identity changed.",
            )
        _atomic_publish(payload, expected)
        assert_output_within_limit(expected, target_format)
        return expected


def _atomic_publish(payload: bytes, destination: Path) -> None:
    """Publish one already-bounded provider artifact from trusted Python."""

    temporary = destination.parent / (
        f".{destination.name}.{uuid.uuid4().hex}.provider-output.tmp"
    )
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice output could not be published safely.",
            details={"reason": type(error).__name__},
        ) from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


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
    for token in operation_argv:
        forbidden = _forbidden_operation_token(token)
        if forbidden is not None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice argv contains a forbidden macro/DDE token.",
                details={"token": forbidden},
            )


def _forbidden_operation_token(token: str) -> str | None:
    """Return the forbidden token represented by one operation argument.

    Operation values can contain arbitrary user-controlled paths.  Match the
    dangerous forms at their argument boundaries instead of scanning a joined
    command line, so a path or UUID containing ``dde`` cannot be mistaken for
    a DDE argument.
    """

    normalized = token.casefold()
    for forbidden in FORBIDDEN_TOKENS:
        candidate = forbidden.casefold()
        if candidate.startswith("--"):
            if normalized == candidate or normalized.startswith(f"{candidate}="):
                return forbidden
        elif candidate in {".bas", ".xba"}:
            if normalized.endswith(candidate):
                return forbidden
        elif candidate == "macro:":
            if normalized.startswith(candidate):
                return forbidden
        elif candidate in {"dde", "ddelink"}:
            if normalized == candidate or normalized.startswith(f"{candidate}:"):
                return forbidden
        elif candidate in normalized:
            # A token shape without a boundary rule above keeps the
            # conservative substring match so it can never fail open.
            return forbidden
    return None


def _timeout_for_format(target_format: str) -> float:
    if target_format == "xlsx":
        return TIMEOUT_RECALC_REQUIRED
    if target_format == "pdf":
        return TIMEOUT_CONVERT
    if target_format == "png":
        return TIMEOUT_RENDER
    return TIMEOUT_LEGACY
