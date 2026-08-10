"""Coherent observations of entries beneath a captured parent."""

from __future__ import annotations

import os
import stat
from typing import BinaryIO, Callable

from .parent_anchor import DestinationParentAnchor
from .promotion_models import ResidueReference


OpenFileHasher = Callable[[BinaryIO], str]


def observe_entry(
    parent: DestinationParentAnchor,
    reference: ResidueReference,
    *,
    hash_open_file: OpenFileHasher,
) -> dict[str, object] | None:
    try:
        initial_path = parent.entry_path(
            reference.name,
            require_bound=False,
            phase="residue_observation",
        )
        handle = parent.open_entry(reference.name)
    except FileNotFoundError:
        return None
    except OSError as error:
        return {
            "role": reference.role,
            "path": str(parent.original_path / reference.name),
            "state": "identity_unavailable",
            "stable": False,
            "reason": type(error).__name__,
        }
    with handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            return {
                "role": reference.role,
                "path": str(initial_path),
                "state": "non_regular",
                "stable": False,
            }
        try:
            digest = hash_open_file(handle)
            after = os.fstat(handle.fileno())
        except OSError as error:
            return {
                "role": reference.role,
                "path": str(initial_path),
                "state": "changed_during_observation",
                "stable": False,
                "change_reasons": [type(error).__name__],
            }
    reasons: list[str] = []
    if _metadata_token(before) != _metadata_token(after):
        reasons.append("open_file_changed")
    try:
        path_metadata = parent.entry_stat(reference.name)
        final_path = parent.entry_path(
            reference.name,
            require_bound=False,
            phase="residue_observation_complete",
        )
    except OSError:
        reasons.append("path_entry_unavailable")
        final_path = initial_path
        path_metadata = None
    if path_metadata is not None and (
        not stat.S_ISREG(path_metadata.st_mode)
        or (path_metadata.st_dev, path_metadata.st_ino)
        != (after.st_dev, after.st_ino)
    ):
        reasons.append("path_identity_changed")
    if reasons:
        entry: dict[str, object] = {
            "role": reference.role,
            "path": str(final_path),
            "state": "changed_during_observation",
            "stable": False,
            "change_reasons": sorted(set(reasons)),
        }
        if reference.expected_identity is not None:
            entry["expected_identity"] = {
                "device": reference.expected_identity[0],
                "inode": reference.expected_identity[1],
            }
        return entry
    identity = (after.st_dev, after.st_ino)
    entry = {
        "role": reference.role,
        "path": str(final_path),
        "state": "regular_file",
        "stable": True,
        "device": after.st_dev,
        "inode": after.st_ino,
        "bytes": after.st_size,
        "sha256": digest,
    }
    if reference.expected_identity is not None:
        entry["identity_matches_expected"] = identity == reference.expected_identity
    return entry


def _metadata_token(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
