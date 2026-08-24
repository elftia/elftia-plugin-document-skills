"""Deterministic fixture writer for PPTX ecosystem phase B/C slices."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
import unicodedata


_FIXTURE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


@dataclass(frozen=True)
class FixtureMetadata:
    fixture_id: str
    format: str
    purpose: str
    origin: str
    recipe: str
    license: str
    expected_operation: str
    expected_consumers: tuple[str, ...]
    resource_limits: Mapping[str, int]
    invariants: tuple[str, ...]
    security_classification: str
    redistributable: bool = True


class EcosystemFixtureWriter:
    """Write fixture bytes plus an adjacent, hash-bound metadata manifest."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._folded_paths: set[str] = set()

    def write_json(
        self,
        relative: str,
        value: Any,
        metadata: FixtureMetadata,
    ) -> tuple[Path, Path]:
        payload = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        return self.write_bytes(relative, payload, metadata)

    def write_bytes(
        self,
        relative: str,
        payload: bytes,
        metadata: FixtureMetadata,
    ) -> tuple[Path, Path]:
        path = self._resolve(relative)
        self._validate_metadata(metadata)
        if len(payload) > metadata.resource_limits.get("maxBytes", 0):
            raise ValueError(f"fixture exceeds maxBytes: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

        manifest_path = path.with_suffix(path.suffix + ".manifest.json")
        manifest = {
            "schemaVersion": 1,
            **asdict(metadata),
            "path": relative,
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path, manifest_path

    def _resolve(self, relative: str) -> Path:
        normalized = unicodedata.normalize("NFKC", relative)
        posix = PurePosixPath(relative)
        if (
            normalized != relative
            or "\\" in relative
            or posix.is_absolute()
            or not posix.parts
            or any(part in {"", ".", ".."} for part in posix.parts)
            or posix.as_posix() != relative
        ):
            raise ValueError(f"unsafe fixture path: {relative}")
        folded = normalized.casefold()
        if folded in self._folded_paths:
            raise ValueError(f"duplicate or case-colliding fixture path: {relative}")
        self._folded_paths.add(folded)
        return self.root.joinpath(*posix.parts)

    @staticmethod
    def _validate_metadata(metadata: FixtureMetadata) -> None:
        if not _FIXTURE_ID.fullmatch(metadata.fixture_id):
            raise ValueError(f"invalid fixture id: {metadata.fixture_id}")
        if not metadata.redistributable:
            raise ValueError("non-redistributable fixture bytes cannot be written")
        if not metadata.expected_consumers:
            raise ValueError("fixture requires at least one expected consumer")
        if metadata.resource_limits.get("maxBytes", 0) <= 0:
            raise ValueError("fixture maxBytes must be positive")
        if not metadata.invariants:
            raise ValueError("fixture requires at least one invariant")


__all__ = ["EcosystemFixtureWriter", "FixtureMetadata"]
