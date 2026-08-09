"""DotnetOpenXmlDetector — dual callability validation.

Validates BOTH (a) ``dotnet --list-runtimes`` reports ``Microsoft.NETCore.App 8.x``
AND (b) the helper ``--probe-json`` returns ``assembly_loaded: true`` + a parseable
``openxml_version``.  An executable alone (no .NET 8 runtime) is reported as
``unavailable``; a runtime without the assembly is also ``unavailable``
(the dotnet lesson, double-applied).

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
import shutil
from typing import Protocol

from ...core.capabilities.catalog import DetectionEvidence
from ...core.contracts.errors import DocumentSkillsError
from ...core.process import ProcessPolicy, ProcessRunner, ProcessResult
from .constants import (
    PROBE_OUTPUT_LIMIT,
    PROBE_PROTOCOL_VERSION,
    PROBE_RUNTIME_MAJOR,
    RUNTIME_PREFIX,
    RUNTIME_PROBE_OUTPUT_LIMIT,
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
    ) -> ProcessResult: ...


class DotnetOpenXmlDetector:
    """Detect dotnet and validate BOTH .NET 8 runtime AND OpenXML assembly."""

    def __init__(
        self,
        project_root: Path,
        helper_dir: Path | None = None,
        runner: _ProbeRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        if helper_dir is not None:
            self._helper_dir = helper_dir.resolve()
        else:
            self._helper_dir = (Path(__file__).resolve().parent / "helper")
        if runner is not None:
            self._runner = runner
        else:
            policy = ProcessPolicy(self.project_root)
            self._runner = ProcessRunner(policy)

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
            resolved = self._resolve_executable(candidate)
        except DocumentSkillsError:
            return None
        try:
            result = self._runner.run(
                "runtime-detection",
                resolved,
                ["--list-runtimes"],
                timeout_seconds=TIMEOUT_RUNTIME_PROBE,
                output_limit=RUNTIME_PROBE_OUTPUT_LIMIT,
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
            resolved = self._resolve_executable(candidate)
        except DocumentSkillsError:
            return DetectionEvidence(
                available=False,
                reason=f"dotnet detected at {candidate} but could not be resolved for assembly probe",
                path=candidate,
            )
        argv = [
            "run", "--project", str(self._helper_dir), "--",
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

    def _resolve_executable(self, candidate: str) -> Path:
        policy = ProcessPolicy(self.project_root)
        return policy.allow_executable("runtime-detection", candidate)


def _classify_error(error: DocumentSkillsError) -> str:
    from ...core.contracts.errors import ErrorCode
    if error.code == ErrorCode.PROCESS_TIMEOUT:
        return "timeout"
    return error.code.value.lower().replace("ds_", "")
