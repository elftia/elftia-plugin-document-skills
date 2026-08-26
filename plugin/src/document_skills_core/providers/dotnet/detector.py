"""DotnetOpenXmlDetector — dual callability validation.

Validates BOTH (a) ``dotnet --list-runtimes`` reports ``Microsoft.NETCore.App 8.x``
AND (b) the helper ``--probe-json`` returns ``assembly_loaded: true`` + a parseable
``openxml_version``.  An executable alone (no .NET 8 runtime) is reported as
``unavailable``; a runtime without the assembly is also ``unavailable``
(the dotnet lesson, double-applied).

Module provenance: original Elftia-authored clean-room implementation.
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ...core.capabilities.catalog import DetectionEvidence
from ...core.contracts.errors import DocumentSkillsError
from ...core.process import ProcessPolicy, ProcessResult, ProcessRunner
from .constants import (
    DOTNET_PRIVATE_ENVIRONMENT,
    HELPER_PROJECT_NAME,
    LOCKED_RESTORE_FLAGS,
    PROBE_OUTPUT_LIMIT,
    PROBE_PROTOCOL_VERSION,
    PROBE_RUNTIME_MAJOR,
    RUNTIME_PREFIX,
    RUNTIME_PROBE_OUTPUT_LIMIT,
    TIMEOUT_LOCKED_RESTORE,
    TIMEOUT_NO_RESTORE_BUILD,
    TIMEOUT_PROBE,
    TIMEOUT_RUNTIME_PROBE,
    platform_known_paths,
)


class _ProbeRunner(Protocol):
    """Minimal interface for running probes (real or fake)."""

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


class DotnetOpenXmlDetector:
    """Detect dotnet and validate BOTH .NET 8 runtime AND OpenXML assembly."""

    def __init__(
        self,
        project_root: Path,
        helper_dir: Path | None = None,
        runner: _ProbeRunner | None = None,
        policy: ProcessPolicy | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        if helper_dir is not None:
            self._helper_dir = helper_dir.resolve()
        else:
            self._helper_dir = Path(__file__).resolve().parent / "helper"
        self._helper_project = self._helper_dir / HELPER_PROJECT_NAME
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

    def detect(self) -> DetectionEvidence:
        candidate = self._find_candidate()
        if candidate is None:
            return DetectionEvidence(
                available=False,
                reason="no dotnet candidate found on PATH or platform locations",
            )
        runtime_ok = self._validate_runtime(candidate)
        if runtime_ok is None:
            return DetectionEvidence(
                available=False,
                reason="Microsoft.NETCore.App 8.x is not installed",
                path=candidate,
            )
        return self._validate_assembly(candidate)

    def detect_and_authorize(
        self,
        bind_authorized_executable: Callable[[str | Path], None],
    ) -> DetectionEvidence:
        """Bind operation launch to the executable record used by the probe."""

        evidence = self.detect()
        if not evidence.available or evidence.path is None:
            return evidence
        try:
            bind_authorized_executable(evidence.path)
        except DocumentSkillsError:
            return DetectionEvidence(
                available=False,
                reason=(
                    "dotnet executable identity changed between the successful "
                    "probe and operation authorization"
                ),
                path=evidence.path,
            )
        return evidence

    def _find_candidate(self) -> str | None:
        found = shutil.which("dotnet")
        if found:
            return found
        for path in platform_known_paths():
            if Path(path).is_file():
                return path
        return None

    def _validate_runtime(self, candidate: str) -> str | None:
        """Return the runtime line if .NET 8 is present, else None."""
        try:
            resolved = self._resolve_executable(candidate, "runtime-detection")
        except DocumentSkillsError:
            return None
        try:
            result = self._runner.run(
                "runtime-detection",
                resolved,
                ["--list-runtimes"],
                timeout_seconds=TIMEOUT_RUNTIME_PROBE,
                output_limit=RUNTIME_PROBE_OUTPUT_LIMIT,
                private_environment=DOTNET_PRIVATE_ENVIRONMENT,
            )
        except DocumentSkillsError:
            return None
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(RUNTIME_PREFIX):
                return stripped
        return None

    def _validate_assembly(self, candidate: str) -> DetectionEvidence:
        """Run the helper --probe-json to validate the OpenXML assembly."""
        try:
            resolved = self._resolve_executable(candidate, "dotnet-openxml")
        except DocumentSkillsError:
            return DetectionEvidence(
                available=False,
                reason=f"dotnet detected at {candidate} but could not be resolved for assembly probe",
                path=candidate,
            )
        restore_argv = _build_locked_restore_argv(self._helper_project)
        try:
            restored = self._runner.run(
                "dotnet-openxml",
                resolved,
                restore_argv,
                cwd=self.project_root,
                timeout_seconds=TIMEOUT_LOCKED_RESTORE,
                output_limit=PROBE_OUTPUT_LIMIT,
                private_environment=DOTNET_PRIVATE_ENVIRONMENT,
            )
        except DocumentSkillsError as error:
            category = _classify_error(error)
            return DetectionEvidence(
                available=False,
                reason=(
                    f"dotnet detected at {candidate} but locked helper restore "
                    f"failed: {category}"
                ),
                path=candidate,
            )
        if restored.returncode != 0:
            return DetectionEvidence(
                available=False,
                reason=(
                    "dotnet detected but the checked-in OpenXML dependency lock "
                    f"could not be restored (exit {restored.returncode})"
                ),
                path=candidate,
            )
        build_argv = _build_no_restore_build_argv(self._helper_project)
        try:
            built = self._runner.run(
                "dotnet-openxml",
                resolved,
                build_argv,
                cwd=self.project_root,
                timeout_seconds=TIMEOUT_NO_RESTORE_BUILD,
                output_limit=PROBE_OUTPUT_LIMIT,
                private_environment=DOTNET_PRIVATE_ENVIRONMENT,
            )
        except DocumentSkillsError as error:
            category = _classify_error(error)
            return DetectionEvidence(
                available=False,
                reason=(
                    f"dotnet detected at {candidate} but no-restore helper "
                    f"build failed: {category}"
                ),
                path=candidate,
            )
        if built.returncode != 0:
            return DetectionEvidence(
                available=False,
                reason=(
                    "dotnet detected but the locked OpenXML helper could not "
                    f"be built without restore (exit {built.returncode})"
                ),
                path=candidate,
            )
        argv = [
            "run",
            "--no-restore",
            "--no-build",
            "--project",
            str(self._helper_dir),
            "--",
            "--probe-json",
        ]
        try:
            result = self._runner.run(
                "dotnet-openxml",
                resolved,
                argv,
                cwd=self.project_root,
                timeout_seconds=TIMEOUT_PROBE,
                output_limit=PROBE_OUTPUT_LIMIT,
                stdin_json={},
                private_environment=DOTNET_PRIVATE_ENVIRONMENT,
            )
        except DocumentSkillsError as error:
            category = _classify_error(error)
            return DetectionEvidence(
                available=False,
                reason=f"dotnet detected at {candidate} but assembly probe failed: {category}",
                path=candidate,
            )
        if result.returncode != 0:
            return DetectionEvidence(
                available=False,
                reason=f"dotnet detected at {candidate} but --probe-json exited {result.returncode}",
                path=candidate,
            )
        try:
            payload = result.json()
        except DocumentSkillsError:
            return DetectionEvidence(
                available=False,
                reason="dotnet detected but probe returned unparseable JSON",
                path=candidate,
            )
        if not isinstance(payload, dict):
            return DetectionEvidence(
                available=False,
                reason="dotnet detected but probe returned non-object JSON",
                path=candidate,
            )
        if payload.get("protocol_version") != PROBE_PROTOCOL_VERSION:
            return DetectionEvidence(
                available=False,
                reason="dotnet detected but probe protocol_version is invalid",
                path=candidate,
            )
        if payload.get("runtime_major") != PROBE_RUNTIME_MAJOR:
            return DetectionEvidence(
                available=False,
                reason="dotnet detected but probe runtime_major is not 8",
                path=candidate,
            )
        if payload.get("assembly_loaded") is not True:
            return DetectionEvidence(
                available=False,
                reason="The DocumentFormat.OpenXml assembly is not resolvable from the user environment",
                path=candidate,
            )
        version = payload.get("openxml_version")
        if not isinstance(version, str):
            return DetectionEvidence(
                available=False,
                reason="dotnet detected but openxml_version is not a parseable string",
                path=candidate,
            )
        return DetectionEvidence(
            available=True,
            version=version,
            path=candidate,
        )

    def _resolve_executable(self, candidate: str, provider_id: str) -> Path:
        if not isinstance(self._runner, ProcessRunner):
            return Path(candidate).absolute()
        return self._policy.allow_executable(provider_id, candidate)


def _classify_error(error: DocumentSkillsError) -> str:
    from ...core.contracts.errors import ErrorCode

    if error.code == ErrorCode.PROCESS_TIMEOUT:
        return "timeout"
    return error.code.value.lower().replace("ds_", "")


def _build_locked_restore_argv(helper_project: Path) -> list[str]:
    """Build the only dependency-materialization command the detector permits."""
    return ["restore", str(helper_project), *LOCKED_RESTORE_FLAGS]


def _build_no_restore_build_argv(helper_project: Path) -> list[str]:
    """Build only the graph materialized by the preceding locked restore."""

    return ["build", str(helper_project), "--no-restore", "--nologo"]
