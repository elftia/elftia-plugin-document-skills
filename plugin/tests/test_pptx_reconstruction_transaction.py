"""Negative publication and cleanup tests for PPTX reconstruction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from document_skills_core.core.capabilities import ProviderCatalog
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx import reconstruction_service
from document_skills_core.formats.pptx.reconstruction_models import (
    screen_reconstruction_raster,
)
from document_skills_core.formats.pptx.reconstruction_transaction import (
    audit_asset_path,
)
from document_skills_core.providers.ocr_vision import build_ocr_vision_provider
from tests.support.pptx_reconstruction_adapter import fixture_adapter


def _fixture_root(project_root: Path) -> Path:
    return project_root / "tests/fixtures/pptx/ecosystem_bc/reconstruction"


def _request(source: Path, output: Path, audit_policy: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.reconstruct.from-image",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": audit_policy,
        },
        "options": {"fidelity": "core"},
    }


def _execute(project_root: Path, adapter: object, request: dict[str, object]) -> dict:
    registry = ProviderCatalog()
    registry.register_provider(build_ocr_vision_provider(project_root, adapter=adapter))
    return registry.execute(request)


def test_occupied_audit_destination_preserves_every_caller_artifact(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    source = tmp_path / "synthetic-cards.png"
    source_bytes = (fixture_root / source.name).read_bytes()
    source.write_bytes(source_bytes)
    output = tmp_path / "prior.pptx"
    output.write_bytes(b"prior-destination")
    raster = screen_reconstruction_raster(source)
    audit_path = audit_asset_path(output, source, raster)
    audit_path.write_bytes(b"caller-owned-audit-destination")
    adapter = fixture_adapter(fixture_root, "synthetic-cards")

    result = _execute(project_root, adapter, _request(source, output, "retain"))

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_STALE_PRECONDITION"
    assert result["artifacts"] == []
    assert source.read_bytes() == source_bytes
    assert output.read_bytes() == b"prior-destination"
    assert audit_path.read_bytes() == b"caller-owned-audit-destination"
    assert adapter.observed_source is not None
    assert not adapter.observed_source.parent.exists()


@pytest.mark.parametrize("audit_policy", ["retain", "discard"])
def test_deep_validation_failure_preserves_prior_destination_and_cleans_private_tree(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    audit_policy: str,
) -> None:
    fixture_root = _fixture_root(project_root)
    source = tmp_path / "synthetic-cards.png"
    source_bytes = (fixture_root / source.name).read_bytes()
    source.write_bytes(source_bytes)
    output = tmp_path / "prior.pptx"
    output.write_bytes(b"prior-destination")
    adapter = fixture_adapter(fixture_root, "synthetic-cards")

    def fail_gate(
        _validation: dict[str, Any],
        _path: Path,
        _scene: object,
        _emission: dict[str, Any],
        _receipt: dict[str, Any],
    ) -> dict[str, Any]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Synthetic deep reconstruction gate failure.",
        )

    monkeypatch.setattr(reconstruction_service, "with_reconstruction_gate", fail_gate)

    result = _execute(project_root, adapter, _request(source, output, audit_policy))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["artifacts"] == []
    assert source.read_bytes() == source_bytes
    assert output.read_bytes() == b"prior-destination"
    assert not list(tmp_path.glob("*.source-audit-*"))
    assert adapter.observed_source is not None
    assert not adapter.observed_source.parent.exists()
