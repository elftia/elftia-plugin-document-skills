"""LibreOffice callability-validating detector.

Validates callability by running ``soffice --version`` through the existing
ProcessRunner. File-existence alone is reported as ``unavailable`` — detection
must never claim a capability that the runtime cannot deliver.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
import shutil
from typing import Protocol

from ...core.capabilities.catalog import DetectionEvidence
from ...core.contracts.errors import DocumentSkillsError
from ...core.process import ProcessPolicy, ProcessRunner, ProcessResult
from .constants import (
    EXECUTABLE_NAMES,
    TIMEOUT_VERSION_PROBE,
    VERSION_PROBE_OUTPUT_LIMIT,
    VERSION_REGEX,
    platform_known_paths,
)


class _VersionProbeRunner(Protocol):
    """Minimal interface for running the version probe (real or fake)."""

    def run(
        self,
        provider_id: str,
        executable: str | Path,
        args: list[str],
        *,
        timeout_seconds: float = ...,
        output_limit: int = ...,
    ) -> ProcessResult: ...


class LibreOfficeDetector:
    """Detect LibreOffice and validate callability via ``soffice --version``."""

    def __init__(
        self,
        project_root: Path,
        runner: _VersionProbeRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
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
                reason="no soffice/libreoffice candidate found on PATH or platform locations",
            )
        return self._validate_callability(candidate)

    def _find_candidate(self) -> str | None:
        for name in EXECUTABLE_NAMES:
            found = shutil.which(name)
            if found:
                return found
        for path in platform_known_paths():
            if Path(path).is_file():
                return path
        return None

    def _validate_callability(self, candidate: str) -> DetectionEvidence:
        try:
            resolved = self._resolve_executable(candidate)
        except DocumentSkillsError:
            return DetectionEvidence(
                available=False,
                reason=f"soffice detected at {candidate} but could not be resolved for callability probe",
                path=candidate,
            )
        try:
            result = self._runner.run(
                "runtime-detection",
                resolved,
                ["--version"],
                timeout_seconds=TIMEOUT_VERSION_PROBE,
                output_limit=VERSION_PROBE_OUTPUT_LIMIT,
            )
        except DocumentSkillsError as error:
            category = self._classify_probe_error(error)
            return DetectionEvidence(
                available=False,
                reason=f"soffice detected at {candidate} but callability probe failed: {category}",
                path=candidate,
            )
        if result.returncode != 0:
            return DetectionEvidence(
                available=False,
                reason=f"soffice detected at {candidate} but --version exited {result.returncode}",
                path=candidate,
            )
        first_line = (result.stdout or result.stderr or "").strip().splitlines()[0] if (result.stdout or result.stderr or "").strip() else ""
        match = VERSION_REGEX.search(first_line)
        if match is None:
            return DetectionEvidence(
                available=False,
                reason=f"soffice detected at {candidate} but version output was unparseable",
                path=candidate,
            )
        return DetectionEvidence(
            available=True,
            version=match.group(1),
            path=candidate,
        )

    def _resolve_executable(self, candidate: str) -> Path:
        """Resolve and allowlist the executable via ProcessPolicy."""
        policy = ProcessPolicy(self.project_root)
        return policy.allow_executable("runtime-detection", candidate)

    @staticmethod
    def _classify_probe_error(error: DocumentSkillsError) -> str:
        from ...core.contracts.errors import ErrorCode
        if error.code == ErrorCode.PROCESS_TIMEOUT:
            return "timeout"
        return error.code.value.lower().replace("ds_", "")
