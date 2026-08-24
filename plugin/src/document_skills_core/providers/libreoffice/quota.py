"""Fail-closed hard-quota contract for LibreOffice private storage.

Polling file sizes, checking free disk space, and ``RLIMIT_FSIZE`` do not
provide an aggregate hard limit for a writable directory tree.  This module
therefore exposes no permissive fallback.  A platform backend is launchable
only when its code-level capability record guarantees every property needed
by the LibreOffice containment boundary.

Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

import os
import stat
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Protocol

from ...core.contracts.errors import DocumentSkillsError, ErrorCode

DEFAULT_HARD_QUOTA_ENTRY_LIMIT = 4_096


@dataclass(frozen=True)
class DirectoryIdentity:
    """Stable directory identity captured before an untrusted process runs."""

    device: int
    inode: int


@dataclass(frozen=True)
class HardQuotaCapability:
    """Auditable guarantees supplied by one concrete hard-quota backend."""

    backend_id: str
    platform: str
    reason_category: str
    reason: str
    aggregate_byte_limit: bool = False
    entry_count_limit: bool = False
    private_namespace: bool = False
    fail_closed_activation: bool = False

    @property
    def supported(self) -> bool:
        """Return true only when the complete storage contract is enforced."""

        return self.backend_id not in {"", "none", "invalid"} and all(
            (
                self.aggregate_byte_limit,
                self.entry_count_limit,
                self.private_namespace,
                self.fail_closed_activation,
            )
        )

    def evidence(self) -> dict[str, object]:
        """Return stable, non-sensitive detector evidence."""

        return {
            "backend": self.backend_id,
            "platform": self.platform,
            "supported": self.supported,
            "reason_category": self.reason_category,
            "guarantees": {
                "aggregate_byte_limit": self.aggregate_byte_limit,
                "entry_count_limit": self.entry_count_limit,
                "private_namespace": self.private_namespace,
                "fail_closed_activation": self.fail_closed_activation,
            },
        }


@dataclass(frozen=True)
class QuotaTreeSnapshot:
    """Final identity, entry-count, and logical-byte evidence."""

    root_identity: DirectoryIdentity
    output_identity: DirectoryIdentity
    entry_count: int
    total_bytes: int
    output_bytes: int


class HardQuotaSession(Protocol):
    """One already-enforced private filesystem allocation."""

    root: Path
    root_identity: DirectoryIdentity
    output_dir: Path
    output_identity: DirectoryIdentity
    profile_dir: Path
    byte_limit: int
    entry_limit: int

    def validate_final_tree(self, *, expected_name: str) -> QuotaTreeSnapshot:
        """Validate the stopped process's final private tree."""

        ...


class HardQuotaBackend(Protocol):
    """Backend that creates an aggregate byte- and entry-limited tree."""

    def capability(self) -> HardQuotaCapability:
        """Describe guarantees without mutating disk or launching a process."""

        ...

    def open(
        self,
        *,
        byte_limit: int,
        entry_limit: int = DEFAULT_HARD_QUOTA_ENTRY_LIMIT,
    ) -> AbstractContextManager[HardQuotaSession]:
        """Create an enforced session, or fail before returning it."""

        ...


class _UnsupportedHardQuotaBackend:
    """Explicit default until a reviewed platform implementation exists."""

    def capability(self) -> HardQuotaCapability:
        platform = _platform_name()
        return HardQuotaCapability(
            backend_id="none",
            platform=platform,
            reason_category="hard_quota_backend_unavailable",
            reason=_unsupported_reason(platform),
        )

    def open(
        self,
        *,
        byte_limit: int,
        entry_limit: int = DEFAULT_HARD_QUOTA_ENTRY_LIMIT,
    ) -> AbstractContextManager[HardQuotaSession]:
        del byte_limit, entry_limit
        _raise_unavailable(self.capability())


_DEFAULT_BACKEND = _UnsupportedHardQuotaBackend()


def hard_quota_capability(
    backend: HardQuotaBackend | None = None,
) -> HardQuotaCapability:
    """Inspect a code-selected backend without activating it."""

    selected = backend or _DEFAULT_BACKEND
    try:
        capability = selected.capability()
    except Exception as error:
        return HardQuotaCapability(
            backend_id="invalid",
            platform=_platform_name(),
            reason_category="hard_quota_capability_probe_failed",
            reason=f"Capability probe failed closed ({type(error).__name__}).",
        )
    if not isinstance(capability, HardQuotaCapability):
        return HardQuotaCapability(
            backend_id="invalid",
            platform=_platform_name(),
            reason_category="hard_quota_capability_invalid",
            reason="Capability probe returned an invalid record.",
        )
    return capability


def require_hard_quota_backend(
    backend: HardQuotaBackend | None = None,
) -> HardQuotaBackend:
    """Return a complete backend or fail before any filesystem side effect."""

    selected = backend or _DEFAULT_BACKEND
    capability = hard_quota_capability(selected)
    if not capability.supported:
        _raise_unavailable(capability)
    return selected


def capture_directory_identity(path: Path) -> DirectoryIdentity:
    """Capture one real, non-reparse directory without following links."""

    try:
        metadata = path.lstat()
    except OSError as error:
        _tree_failed(
            "Hard-quota directory identity could not be captured.",
            reason=type(error).__name__,
        )
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        _tree_failed("Hard-quota path is not one real directory.")
    return DirectoryIdentity(metadata.st_dev, metadata.st_ino)


def validate_final_quota_tree(
    *,
    root: Path,
    root_identity: DirectoryIdentity,
    output_dir: Path,
    output_identity: DirectoryIdentity,
    expected_name: str,
    byte_limit: int,
    entry_limit: int,
) -> QuotaTreeSnapshot:
    """Validate a stopped provider's final tree without following redirections.

    This is a mandatory postcondition for a real hard-quota backend.  It does
    not replace enforcement while the child is running.
    """

    if byte_limit < 1 or entry_limit < 1:
        raise ValueError("Hard-quota limits must be positive.")
    if not expected_name or Path(expected_name).name != expected_name:
        raise ValueError("Expected output must be one direct filename.")
    root_path = root.absolute()
    output_path = output_dir.absolute()
    if output_path.parent != root_path:
        _tree_failed("Hard-quota output directory escaped its session root.")
    if capture_directory_identity(root_path) != root_identity:
        _tree_failed("Hard-quota session root identity changed.")
    if capture_directory_identity(output_path) != output_identity:
        _tree_failed("Hard-quota output directory identity changed.")

    entry_count = 0
    total_bytes = 0
    output_bytes = 0
    pending = [root_path]
    expected_path = output_path / expected_name
    output_names: set[str] = set()
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    entry_count += 1
                    if entry_count > entry_limit:
                        _tree_failed(
                            "LibreOffice private tree exceeds its entry ceiling.",
                            entry_count=entry_count,
                            entry_limit=entry_limit,
                        )
                    try:
                        # Windows DirEntry.stat() reports st_nlink=0 even for
                        # hard-linked files.  os.lstat() preserves the link
                        # count needed by this containment postcondition.
                        metadata = os.lstat(entry.path)
                    except OSError as error:
                        _tree_failed(
                            "LibreOffice private tree could not be inspected safely.",
                            reason=type(error).__name__,
                        )
                    if entry.is_symlink() or _is_reparse(metadata):
                        _tree_failed(
                            "LibreOffice private tree contains a redirected entry."
                        )
                    entry_path = Path(entry.path)
                    if stat.S_ISDIR(metadata.st_mode):
                        if directory == output_path:
                            _tree_failed(
                                "LibreOffice output directory contains a subdirectory."
                            )
                        pending.append(entry_path)
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        _tree_failed(
                            "LibreOffice private tree contains a non-regular entry."
                        )
                    if metadata.st_nlink > 1:
                        _tree_failed(
                            "LibreOffice private tree contains a multiply-linked file."
                        )
                    total_bytes += metadata.st_size
                    if total_bytes > byte_limit:
                        _tree_failed(
                            "LibreOffice private tree exceeds its aggregate byte ceiling.",
                            total_bytes=total_bytes,
                            byte_limit=byte_limit,
                        )
                    if directory == output_path:
                        output_names.add(entry.name)
                        if entry_path == expected_path:
                            output_bytes = metadata.st_size
        except DocumentSkillsError:
            raise
        except OSError as error:
            _tree_failed(
                "LibreOffice private tree could not be enumerated safely.",
                reason=type(error).__name__,
            )
    if output_names != {expected_name}:
        _tree_failed(
            "LibreOffice output directory does not contain exactly the expected file.",
            output_entry_count=len(output_names),
        )
    return QuotaTreeSnapshot(
        root_identity=root_identity,
        output_identity=output_identity,
        entry_count=entry_count,
        total_bytes=total_bytes,
        output_bytes=output_bytes,
    )


def _platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    return "other"


def _unsupported_reason(platform: str) -> str:
    if platform == "windows":
        return (
            "No validated unprivileged per-session tree-quota backend is implemented "
            "for Windows; volume/user NTFS quota and free-space polling do not qualify."
        )
    if platform in {"linux", "macos"}:
        return (
            "No validated aggregate tree-quota backend is implemented for this POSIX "
            "platform; RLIMIT_FSIZE is per-file and does not qualify."
        )
    return "No validated aggregate hard-quota backend is implemented for this platform."


def _is_reparse(metadata: os.stat_result) -> bool:
    if os.name != "nt":
        return False
    return bool(
        metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _raise_unavailable(capability: HardQuotaCapability) -> NoReturn:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_UNAVAILABLE,
        "LibreOffice requires an unavailable aggregate hard-storage quota.",
        details={
            **capability.evidence(),
            "reason": capability.reason,
        },
    )


def _tree_failed(message: str, **details: object) -> NoReturn:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_FAILED,
        message,
        details=details,
    )
