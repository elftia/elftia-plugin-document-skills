"""LibreOffice callability-validating detector.

Requires a trusted hard-quota backend, captures a stable executable identity,
and validates callability by running ``soffice --version`` through the existing
ProcessRunner. File-existence alone is reported as ``unavailable``.

Module provenance: original Elftia-authored clean-room implementation.
"""

import hashlib
import math
import os
import shutil
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

from ...core.capabilities.catalog import DetectionEvidence
from ...core.contracts.errors import DocumentSkillsError
from ...core.process import ProcessPolicy, ProcessResult, ProcessRunner
from .constants import (
    EXECUTABLE_NAMES,
    TIMEOUT_VERSION_PROBE,
    VERSION_PROBE_OUTPUT_LIMIT,
    VERSION_REGEX,
    platform_known_paths,
)
from .quota import HardQuotaBackend, HardQuotaCapability, hard_quota_capability

_IDENTITY_HASH_CHUNK_BYTES = 64 * 1024
_MAX_EXECUTABLE_IDENTITY_BYTES = 64 * 1024 * 1024
_DEFAULT_POSITIVE_CACHE_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class _ExecutableIdentity:
    """Stable launch-path and target identity with no-follow metadata."""

    launch_path: Path
    resolved_path: Path
    launch_device: int
    launch_inode: int
    launch_size: int
    launch_mtime_ns: int
    target_device: int
    target_inode: int
    target_size: int
    target_mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class _DetectionCacheEntry:
    evidence: DetectionEvidence
    identity: _ExecutableIdentity
    quota_capability: HardQuotaCapability
    validated_at: float


class _ExecutableIdentityError(Exception):
    """The candidate could not be captured as one stable regular file."""


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
        *,
        policy: ProcessPolicy | None = None,
        quota_backend: HardQuotaBackend | None = None,
        cache_ttl_seconds: float = _DEFAULT_POSITIVE_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(cache_ttl_seconds) or cache_ttl_seconds < 0:
            raise ValueError("LibreOffice cache TTL must be finite and non-negative.")
        self.project_root = project_root.resolve()
        self._cache_entry: _DetectionCacheEntry | None = None
        self._detection_lock = Lock()
        self._quota_backend = quota_backend
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
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
        with self._detection_lock:
            return self._detect_locked()

    def detect_and_authorize(
        self,
        authorize_executable: Callable[[str | Path], None],
    ) -> DetectionEvidence:
        """Detect and bind the exact probed identity before an operation starts."""

        with self._detection_lock:
            evidence = self._detect_locked()
            cached = self._cache_entry
            if not evidence.available or evidence.path is None or cached is None:
                return evidence
            try:
                before_authorize = self._capture_identity(evidence.path)
            except _ExecutableIdentityError:
                self._cache_entry = None
                return self._identity_changed_evidence(evidence.path)
            if before_authorize != cached.identity:
                self._cache_entry = None
                return self._identity_changed_evidence(evidence.path)
            authorize_executable(evidence.path)
            try:
                after_authorize = self._capture_identity(evidence.path)
            except _ExecutableIdentityError:
                self._cache_entry = None
                return self._identity_changed_evidence(evidence.path)
            if after_authorize != cached.identity:
                self._cache_entry = None
                return self._identity_changed_evidence(evidence.path)
            return evidence

    def _detect_locked(self) -> DetectionEvidence:
        quota_capability = hard_quota_capability(self._quota_backend)
        if not quota_capability.supported:
            self._cache_entry = None
            return DetectionEvidence(
                available=False,
                reason=(
                    "LibreOffice hard quota unavailable "
                    f"({quota_capability.reason_category}): "
                    f"{quota_capability.reason}"
                ),
            )
        candidate = self._find_candidate()
        if candidate is None:
            self._cache_entry = None
            return DetectionEvidence(
                available=False,
                reason=(
                    "no soffice/libreoffice candidate found on PATH or "
                    "platform locations"
                ),
            )
        try:
            identity = self._capture_identity(candidate)
        except _ExecutableIdentityError:
            self._cache_entry = None
            return DetectionEvidence(
                available=False,
                reason=(
                    f"soffice detected at {candidate} but its executable "
                    "identity could not be captured safely"
                ),
                path=candidate,
            )
        cached = self._cache_entry
        if (
            cached is not None
            and cached.identity == identity
            and cached.quota_capability == quota_capability
        ):
            cache_age = self._clock() - cached.validated_at
            if 0 <= cache_age < self._cache_ttl_seconds:
                return cached.evidence
        self._cache_entry = None
        launch_path = str(identity.launch_path)
        evidence = self._validate_callability(launch_path)
        if not evidence.available:
            return evidence
        try:
            after_probe = self._capture_identity(launch_path)
        except _ExecutableIdentityError:
            return self._identity_changed_evidence(launch_path)
        if after_probe != identity:
            return self._identity_changed_evidence(launch_path)
        self._cache_entry = _DetectionCacheEntry(
            evidence,
            identity,
            quota_capability,
            self._clock(),
        )
        return evidence

    @staticmethod
    def _identity_changed_evidence(candidate: str) -> DetectionEvidence:
        return DetectionEvidence(
            available=False,
            reason=(
                f"soffice detected at {candidate} but its executable identity "
                "changed during detection or operation authorization"
            ),
            path=candidate,
        )

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
                "libreoffice",
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
            path=str(resolved),
        )

    @staticmethod
    def _capture_identity(candidate: str) -> _ExecutableIdentity:
        launch_path = Path(candidate).absolute()
        try:
            launch_before = os.stat(launch_path, follow_symlinks=False)
            resolved_path = launch_path.resolve(strict=True)
            target_before = os.stat(resolved_path, follow_symlinks=False)
            if not stat.S_ISREG(target_before.st_mode):
                raise _ExecutableIdentityError
            if target_before.st_size > _MAX_EXECUTABLE_IDENTITY_BYTES:
                raise _ExecutableIdentityError
            digest = hashlib.sha256()
            with resolved_path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if _stat_identity(opened) != _stat_identity(target_before):
                    raise _ExecutableIdentityError
                bytes_hashed = 0
                while chunk := stream.read(_IDENTITY_HASH_CHUNK_BYTES):
                    bytes_hashed += len(chunk)
                    if bytes_hashed > _MAX_EXECUTABLE_IDENTITY_BYTES:
                        raise _ExecutableIdentityError
                    digest.update(chunk)
                opened_after = os.fstat(stream.fileno())
            launch_after = os.stat(launch_path, follow_symlinks=False)
            target_after = os.stat(resolved_path, follow_symlinks=False)
        except (OSError, RuntimeError) as error:
            raise _ExecutableIdentityError from error
        if (
            _stat_identity(launch_before) != _stat_identity(launch_after)
            or _stat_identity(target_before) != _stat_identity(target_after)
            or _stat_identity(opened) != _stat_identity(opened_after)
        ):
            raise _ExecutableIdentityError
        return _ExecutableIdentity(
            launch_path=launch_path,
            resolved_path=resolved_path,
            launch_device=launch_before.st_dev,
            launch_inode=launch_before.st_ino,
            launch_size=launch_before.st_size,
            launch_mtime_ns=launch_before.st_mtime_ns,
            target_device=target_before.st_dev,
            target_inode=target_before.st_ino,
            target_size=target_before.st_size,
            target_mtime_ns=target_before.st_mtime_ns,
            sha256=digest.hexdigest(),
        )

    def _resolve_executable(self, candidate: str) -> Path:
        """Resolve and allowlist the executable via ProcessPolicy."""
        return self._policy.allow_executable("libreoffice", candidate)

    @staticmethod
    def _classify_probe_error(error: DocumentSkillsError) -> str:
        from ...core.contracts.errors import ErrorCode
        if error.code == ErrorCode.PROCESS_TIMEOUT:
            return "timeout"
        return error.code.value.lower().replace("ds_", "")


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )
