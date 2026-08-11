"""Data models for identity-bound artifact promotion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .parent_anchor import DestinationParentAnchor, FileIdentity


@dataclass(frozen=True)
class ArtifactRecord:
    role: str
    path: str
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True)
class DestinationSnapshot:
    path: Path
    exists: bool
    sha256: str | None
    device: int | None = None
    inode: int | None = None


@dataclass(frozen=True)
class StagedArtifact:
    path: Path
    name: str
    identity: FileIdentity
    record: ArtifactRecord


@dataclass(frozen=True)
class PromotionOutcome:
    artifact: ArtifactRecord
    state: str
    transaction_residues: tuple[dict[str, object], ...] = ()

    @property
    def role(self) -> str:
        return self.artifact.role

    @property
    def path(self) -> str:
        return self.artifact.path

    @property
    def sha256(self) -> str:
        return self.artifact.sha256

    @property
    def bytes(self) -> int:
        return self.artifact.bytes

    def promotion_details(self) -> dict[str, object]:
        residues = [dict(item) for item in self.transaction_residues]
        capture = next(
            (item for item in residues if item["role"] == "destination_capture"),
            None,
        )
        capture_preserved = bool(
            capture is not None
            and capture.get("stable") is True
            and capture.get("identity_matches_expected") is True
        )
        return {
            "state": self.state,
            "promotion_committed": True,
            "output_sha256": self.sha256,
            "output_bytes": self.bytes,
            "destination_capture_preserved": capture_preserved,
            "transaction_residues": residues,
            "transaction_residue_paths": [
                str(item["path"]) for item in residues
            ],
            "residue_observation_stable": all(
                item.get("stable") is True for item in residues
            ),
        }


@dataclass(frozen=True)
class ResidueReference:
    role: str
    name: str
    expected_identity: FileIdentity | None


@dataclass
class PromotionState:
    parent: DestinationParentAnchor
    references: list[ResidueReference] = field(default_factory=list)

    def track(
        self,
        role: str,
        path_or_name: str | Path,
        expected_identity: FileIdentity | None,
    ) -> None:
        self.references.append(
            ResidueReference(role, Path(path_or_name).name, expected_identity)
        )
