"""Fixture contract tests for deterministic layered reconstruction samples."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from document_skills_core.formats.pptx.reconstruction_models import (
    parse_reconstruction_observations,
    screen_reconstruction_raster,
)
from tests.support.pptx_ecosystem_fixture import EcosystemFixtureWriter
from tests.support.pptx_reconstruction_fixture import write_reconstruction_fixtures


def _fixture_root(project_root: Path) -> Path:
    return project_root / "tests/fixtures/pptx/ecosystem_bc/reconstruction"


def test_reconstruction_fixture_recipe_is_byte_deterministic(tmp_path: Path) -> None:
    roots = (tmp_path / "first", tmp_path / "second")

    summaries = [
        write_reconstruction_fixtures(EcosystemFixtureWriter(root))
        for root in roots
    ]

    assert summaries == [["B-REC-01", "B-REC-02"]] * 2
    first_files = sorted(path.relative_to(roots[0]) for path in roots[0].rglob("*"))
    second_files = sorted(path.relative_to(roots[1]) for path in roots[1].rglob("*"))
    assert first_files == second_files
    assert all(
        (roots[0] / relative).read_bytes() == (roots[1] / relative).read_bytes()
        for relative in first_files
        if (roots[0] / relative).is_file()
    )


def test_checked_reconstruction_fixtures_match_the_strict_observation_contract(
    project_root: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    expected = {
        "synthetic-cards": ("B-REC-01", 0),
        "low-confidence": ("B-REC-02", 1),
    }

    for stem, (fixture_id, low_confidence) in expected.items():
        image_path = fixture_root / f"{stem}.png"
        observations_path = fixture_root / f"{stem}.observations.json"
        raster = screen_reconstruction_raster(image_path)
        observations = parse_reconstruction_observations(
            json.loads(observations_path.read_text(encoding="utf-8")),
            raster,
        )

        assert observations.canvas == {"height": 225, "width": 400}
        assert [item["reading_order"] for item in observations.elements] == list(
            range(len(observations.elements))
        )
        assert sum(item["confidence"] < 0.75 for item in observations.elements) == low_confidence
        assert all(
            item["source_region"]
            != {"height": 225.0, "width": 400.0, "x": 0.0, "y": 0.0}
            for item in observations.elements
        )
        for path in (image_path, observations_path):
            manifest = json.loads(
                path.with_suffix(path.suffix + ".manifest.json").read_text(encoding="utf-8")
            )
            payload = path.read_bytes()
            assert manifest["fixture_id"] == fixture_id
            assert manifest["sha256"] == "sha256:" + hashlib.sha256(payload).hexdigest()
            assert manifest["sizeBytes"] == len(payload)
