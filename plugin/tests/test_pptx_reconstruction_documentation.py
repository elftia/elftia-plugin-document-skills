"""Public documentation truth for layered PPTX reconstruction."""

from __future__ import annotations

import json
from pathlib import Path
import re


def test_reconstruction_reference_exposes_the_exact_request_and_failure_truth(
    project_root: Path,
) -> None:
    skill = (project_root / "skills/document-pptx/SKILL.md").read_text(encoding="utf-8")
    reference = (
        project_root / "skills/document-pptx/references/layered-reconstruction.md"
    ).read_text(encoding="utf-8")
    readme = (project_root / "README.md").read_text(encoding="utf-8")

    assert "`pptx.reconstruct.from-image`" in skill
    assert "`references/layered-reconstruction.md`" in skill
    match = re.search(r"```json\s+(\{.*?\})\s+```", reference, re.DOTALL)
    assert match is not None
    request = json.loads(match.group(1))
    assert request["operation"] == "pptx.reconstruct.from-image"
    assert request["arguments"]["provider_policy"] == {
        "provider": "ocr-vision",
        "on_unavailable": "fail",
    }
    assert request["arguments"]["audit_asset_policy"] in {"retain", "discard"}
    assert "unavailable by default" in reference
    assert "single-image" in reference
    assert "by_area" in reference and "by_object_count" in reference
    assert "whole_slide_raster" in reference
    assert "caller-owned input" in reference
    assert "pptx.reconstruct.from-image" in readme
    assert "no production OCR/vision adapter is configured" in readme
