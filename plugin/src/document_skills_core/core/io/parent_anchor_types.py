"""Shared types for identity-bound destination-parent operations."""

from __future__ import annotations

from pathlib import Path


FileIdentity = tuple[int, int]


class ParentSafetyError(OSError):
    """The destination parent cannot support a safe anchored transaction."""

    def __init__(
        self,
        reason: str,
        *,
        phase: str,
        original_path: Path,
        current_path: Path | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.phase = phase
        self.original_path = original_path
        self.current_path = current_path
