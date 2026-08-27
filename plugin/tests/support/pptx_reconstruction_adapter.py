"""Hash-bound deterministic OCR/vision adapter for reconstruction tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.capabilities import DetectionEvidence


class FixtureObservationAdapter:
    """Return checked-in observations only for the matching raster bytes."""

    def __init__(self, image: Path, observations: Path) -> None:
        self.image = image
        self.observations = observations
        self.expected_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
        manifest = json.loads(
            image.with_suffix(image.suffix + ".manifest.json").read_text(encoding="utf-8")
        )
        self.fixture_id = manifest["fixture_id"]
        self.observed_source: Path | None = None

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(True, version=f"fixture-{self.fixture_id}")

    def observe(self, source: Path) -> dict[str, Any]:
        self.observed_source = source
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != self.expected_sha256:
            raise AssertionError("fixture adapter received an unexpected raster snapshot")
        value = json.loads(self.observations.read_text(encoding="utf-8"))
        if type(value) is not dict:
            raise AssertionError("fixture observations must be a JSON object")
        return value


def fixture_adapter(fixture_root: Path, stem: str) -> FixtureObservationAdapter:
    return FixtureObservationAdapter(
        fixture_root / f"{stem}.png",
        fixture_root / f"{stem}.observations.json",
    )


__all__ = ["FixtureObservationAdapter", "fixture_adapter"]
