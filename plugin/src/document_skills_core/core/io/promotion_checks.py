"""Identity and content checks used by artifact promotion."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .parent_anchor import DestinationParentAnchor, FileIdentity
from .promotion_models import (
    ArtifactRecord,
    DestinationSnapshot,
    ResidueReference,
)


EntryObserver = Callable[
    [DestinationParentAnchor, ResidueReference],
    dict[str, object] | None,
]
FileHasher = Callable[[str | Path], str]


def matches_snapshot(
    path: Path,
    expected: DestinationSnapshot,
    *,
    parent: DestinationParentAnchor,
    observe: EntryObserver,
) -> bool:
    observation = observe(parent, ResidueReference("destination", path.name, None))
    return bool(
        observation is not None
        and observation.get("stable") is True
        and observation.get("device") == expected.device
        and observation.get("inode") == expected.inode
        and observation.get("sha256") == expected.sha256
    )


def matches_record(
    path: Path,
    identity: FileIdentity,
    record: ArtifactRecord,
    *,
    parent: DestinationParentAnchor,
    observe: EntryObserver,
) -> bool:
    observation = observe(parent, ResidueReference("candidate", path.name, identity))
    return bool(
        observation is not None
        and observation.get("stable") is True
        and observation.get("identity_matches_expected") is True
        and observation.get("bytes") == record.bytes
        and observation.get("sha256") == record.sha256
    )


def assert_destination_unchanged(
    path: Path,
    expected: DestinationSnapshot,
    *,
    parent: DestinationParentAnchor,
    observe: EntryObserver,
) -> None:
    parent.assert_bound("destination_compare")
    if path != expected.path:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Destination snapshot does not match the promotion path.",
        )
    try:
        observation = observe(
            parent,
            ResidueReference("destination", path.name, None),
        )
    except OSError:
        observation = None
    exists = observation is not None
    unchanged = (
        not expected.exists
        if not exists
        else bool(
            expected.exists
            and observation.get("stable") is True
            and observation.get("device") == expected.device
            and observation.get("inode") == expected.inode
            and observation.get("sha256") == expected.sha256
        )
    )
    if not unchanged:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Destination changed while the document operation was in progress.",
            details={"destination_race": True},
        )


def assert_source_preserved(
    path: str | Path,
    expected_sha256: str,
    *,
    hash_file: FileHasher,
) -> None:
    try:
        actual = hash_file(path)
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Source artifact became unavailable during a non-destructive operation.",
            details={"reason": type(error).__name__},
        ) from error
    if actual != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Source artifact changed during a non-destructive operation.",
            details={"expected_sha256": expected_sha256, "actual_sha256": actual},
        )
