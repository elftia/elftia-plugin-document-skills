"""Public provider and end-to-end tests for layered raster reconstruction."""

from pathlib import Path
import hashlib
import json
import shutil
import struct
import zipfile
import zlib

import pytest

from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.capabilities.reports import build_capabilities
from document_skills_core.core.contracts.errors import (
    DocumentSkillsError,
    ErrorCode,
)
from document_skills_core.providers import build_default_registry
from document_skills_core.providers.ocr_vision import build_ocr_vision_provider
from document_skills_core.public_cli.protocol import PublicCommand
from document_skills_core.public_cli import supervisor as supervisor_module
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor
from tests.test_pptx_public import _public as _public_pptx


def _request(source: Path, output: Path, *, audit_policy: str = "retain") -> dict:
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


def _png(width: int = 400, height: int = 225) -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        checksum = zlib.crc32(kind + value) & 0xFFFFFFFF
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + (b"\xf2\xf4\xf8" * width)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height, level=9))
        + chunk(b"IEND", b"")
    )


class _DeterministicAdapter:
    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(True, version="fixture-1")

    def observe(self, _source: Path) -> dict:
        common_style = {
            "border_color": "#2457A6",
            "border_width": 2,
            "color": "#102030",
            "fill": "#DCE8FF",
            "font_family": "Arial",
            "font_size": 28,
            "font_weight": 400,
            "radius": 8,
            "text_align": "left",
        }
        return {
            "canvas": {"width": 400, "height": 225},
            "elements": [
                {
                    "confidence": 0.99,
                    "geometry": {"x": 20, "y": 20, "width": 170, "height": 90},
                    "id": "card",
                    "kind": "shape",
                    "reading_order": 0,
                    "source_region": {"x": 20, "y": 20, "width": 170, "height": 90},
                    "style": common_style,
                    "text": "",
                },
                {
                    "confidence": 0.97,
                    "geometry": {"x": 35, "y": 40, "width": 135, "height": 35},
                    "id": "title",
                    "kind": "text",
                    "reading_order": 1,
                    "source_region": {"x": 35, "y": 40, "width": 135, "height": 35},
                    "style": common_style,
                    "text": "Editable title",
                },
            ],
        }


class _MixedConfidenceAdapter(_DeterministicAdapter):
    def observe(self, _source: Path) -> dict:
        value = super().observe(_source)
        shape = value["elements"][0]
        text = value["elements"][1]
        shape["geometry"] = {"x": 0, "y": 0, "width": 200, "height": 100}
        shape["source_region"] = {"x": 0, "y": 0, "width": 200, "height": 100}
        text["geometry"] = {"x": 50, "y": 0, "width": 100, "height": 100}
        text["source_region"] = {"x": 50, "y": 0, "width": 100, "height": 100}
        fallback = {
            **shape,
            "confidence": 0.5,
            "geometry": {"x": 200, "y": 0, "width": 100, "height": 100},
            "id": "uncertain-region",
            "reading_order": 2,
            "source_region": {"x": 200, "y": 0, "width": 100, "height": 100},
        }
        value["elements"].append(fallback)
        return value


class _DestinationRaceAdapter(_DeterministicAdapter):
    def __init__(self, output: Path) -> None:
        self.output = output

    def observe(self, source: Path) -> dict:
        self.output.write_bytes(b"concurrent-destination")
        return super().observe(source)


class _RecordingAdapter(_DeterministicAdapter):
    def __init__(self) -> None:
        self.observed_source: Path | None = None

    def observe(self, source: Path) -> dict:
        self.observed_source = source
        return super().observe(source)


class _CrashAdapter(_DeterministicAdapter):
    def observe(self, _source: Path) -> dict:
        raise RuntimeError("untrusted adapter crash detail")


class _TimeoutAdapter(_DeterministicAdapter):
    def observe(self, _source: Path) -> dict:
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "OCR/vision observation timed out.",
        )


def test_ocr_vision_capability_is_truthfully_unavailable_by_default(
    project_root: Path,
    tmp_path: Path,
):
    output = tmp_path / "never-created.pptx"
    provider = build_ocr_vision_provider(project_root)
    registry = ProviderCatalog()
    registry.register_provider(provider)

    assert provider.id == ProviderId.OCR_VISION
    report = build_capabilities(project_root, "pptx", registry)
    operation = report["operations"][0]
    assert operation["operation"] == "pptx.reconstruct.from-image"
    assert operation["available"] is False
    assert operation["providers"] == []

    with pytest.raises(DocumentSkillsError) as exc:
        registry.execute(_request(tmp_path / "source.png", output))

    assert exc.value.status == "unavailable"
    assert exc.value.code.value == "DS_PROVIDER_UNAVAILABLE"
    assert not output.exists()


def test_default_registry_reports_unconfigured_ocr_vision_provider(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DOCUMENT_SKILLS_PROVIDER_PROFILE", "core-only")
    registry = build_default_registry(project_root)

    report = build_capabilities(project_root, "pptx", registry)

    provider = next(item for item in report["providers"] if item["id"] == "ocr-vision")
    operation = next(
        item
        for item in report["operations"]
        if item["operation"] == "pptx.reconstruct.from-image"
    )
    assert provider["available"] is False
    assert provider["required"] is False
    assert "not configured" in provider["reason"]
    assert operation["available"] is False
    assert operation["providers"] == []


def test_public_worker_reports_provider_unavailable_without_single_image_fallback(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    output = tmp_path / "never-created.pptx"
    source.write_bytes(_png())
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(_request(source, output, audit_policy="discard")),
        encoding="utf-8",
    )

    result = _public_pptx(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
        cwd=tmp_path,
    )

    assert result["status"] == "unavailable"
    assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
    assert result["artifacts"] == []
    assert not output.exists()


def test_reconstruction_has_an_explicit_private_worker_budget(
    project_root: Path,
    tmp_path: Path,
):
    request = tmp_path / "reconstruction-budget.json"
    request.write_text(
        json.dumps({"operation": "pptx.reconstruct.from-image"}),
        encoding="utf-8",
    )
    supervisor = PublicCommandSupervisor(project_root, timeout_seconds=8.0)

    limits = supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(request))),
        tmp_path,
    )

    assert limits == (60.0, 1_048_576)


@pytest.mark.parametrize(
    ("mode", "expected_code", "expected_reason"),
    [
        ("hang", "DS_PROCESS_TIMEOUT", "timeout"),
        ("huge-string", "DS_PROVIDER_FAILED", "overflow"),
    ],
)
def test_reconstruction_supervisor_enforces_real_worker_limits_end_to_end(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_code: str,
    expected_reason: str,
):
    source = tmp_path / "source.png"
    output = tmp_path / "prior.pptx"
    source_payload = _png()
    source.write_bytes(source_payload)
    output.write_bytes(b"prior-destination")
    request = tmp_path / "reconstruction-limit.json"
    request.write_text(
        json.dumps(_request(source, output, audit_policy="discard")),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        supervisor_module,
        "_PPTX_RECONSTRUCTION_TIMEOUT_SECONDS",
        0.25 if mode == "hang" else 8.0,
    )
    worker_root = tmp_path / "worker-project"
    shutil.copytree(project_root / "src", worker_root / "src")
    shutil.copytree(project_root / "schemas", worker_root / "schemas")
    shutil.copy2(
        project_root / "tests" / "support" / "command_worker_fixture.py",
        worker_root / "src" / "document_skills_core" / "worker" / "main.py",
    )
    nonce = f"fixture-{mode}"
    private_root = worker_root / ".document-skills-tmp" / f"invocation-{nonce}"
    supervisor = PublicCommandSupervisor(
        worker_root,
        timeout_seconds=0.1,
        nonce_factory=lambda: nonce,
    )

    payload, success = supervisor.run(
        "pptx",
        ["run", "--request", str(request)],
    )

    assert success is False
    assert payload["errors"][0]["code"] == expected_code
    assert payload["errors"][0]["details"]["reason_category"] == expected_reason
    assert source.read_bytes() == source_payload
    assert output.read_bytes() == b"prior-destination"
    assert not private_root.exists()


def test_adapter_observes_only_a_private_screened_snapshot(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    output = tmp_path / "reconstructed.pptx"
    source.write_bytes(_png())
    adapter = _RecordingAdapter()
    registry = ProviderCatalog()
    registry.register_provider(build_ocr_vision_provider(project_root, adapter=adapter))

    result = registry.execute(_request(source, output, audit_policy="discard"))

    assert result["status"] == "success"
    assert adapter.observed_source is not None
    assert adapter.observed_source != source
    assert ".document-skills-tmp" in adapter.observed_source.parts
    assert not adapter.observed_source.exists()


def test_adapter_crash_is_bounded_and_preserves_artifacts(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    output = tmp_path / "prior.pptx"
    source.write_bytes(_png())
    output.write_bytes(b"prior-destination")
    registry = ProviderCatalog()
    registry.register_provider(
        build_ocr_vision_provider(project_root, adapter=_CrashAdapter())
    )

    with pytest.raises(DocumentSkillsError) as exc:
        registry.execute(_request(source, output, audit_policy="discard"))

    assert exc.value.code == ErrorCode.PROVIDER_FAILED
    assert exc.value.details["exception_class"] == "RuntimeError"
    assert "untrusted adapter crash detail" not in repr(exc.value.details)
    assert output.read_bytes() == b"prior-destination"


def test_adapter_timeout_returns_canonical_error_result(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    output = tmp_path / "never-created.pptx"
    source.write_bytes(_png())
    registry = ProviderCatalog()
    registry.register_provider(
        build_ocr_vision_provider(project_root, adapter=_TimeoutAdapter())
    )

    result = registry.execute(_request(source, output, audit_policy="discard"))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_PROCESS_TIMEOUT"
    assert not output.exists()


def test_invalid_provider_result_is_rejected_by_catalog(tmp_path: Path):
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.OCR_VISION,
            version="invalid-result-fixture",
            detect=lambda: DetectionEvidence(True),
            execute=lambda _operation, _request: {"attacker": "controlled"},
            capabilities=[Capability("pptx.reconstruct.from-image", "core")],
        )
    )

    with pytest.raises(DocumentSkillsError) as exc:
        registry.execute(
            _request(tmp_path / "source.png", tmp_path / "output.pptx")
        )

    assert exc.value.code == ErrorCode.PROVIDER_FAILED
    assert exc.value.details["phase"] == "result"


def test_deterministic_adapter_emits_layered_editable_pptx(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "synthetic-cards.png"
    output = tmp_path / "reconstructed.pptx"
    source.write_bytes(_png())
    provider = build_ocr_vision_provider(
        project_root,
        adapter=_DeterministicAdapter(),
    )
    registry = ProviderCatalog()
    registry.register_provider(provider)

    try:
        result = registry.execute(_request(source, output, audit_policy="discard"))
    except DocumentSkillsError as error:
        pytest.fail(repr(error.details))

    assert result["status"] == "success", json.dumps(result, indent=2)
    assert result["provider_chain"] == ["ocr-vision"]
    assert output.is_file()
    reconstruction = result["diagnostics"]["operation_result"]["reconstruction"]
    assert result["diagnostics"]["operation_result"]["audit_asset"] == {
        "policy": "discard",
        "retained": False,
    }
    assert [item["id"] for item in reconstruction["elements"]] == ["card", "title"]
    assert [item["outcome"] for item in reconstruction["elements"]] == [
        "editable",
        "editable",
    ]
    assert reconstruction["ocr_text"] == ["Editable title"]
    assert reconstruction["editable_coverage"]["by_object_count"] == {
        "editable": 2,
        "total": 2,
        "ratio": 1.0,
    }
    assert reconstruction["whole_slide_raster"] is False
    assert not list(tmp_path.glob("*.source-audit-*"))


def test_mixed_confidence_rasterizes_only_the_smallest_source_region(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "low-confidence.png"
    output = tmp_path / "reconstructed.pptx"
    payload = _png()
    source.write_bytes(payload)
    provider = build_ocr_vision_provider(
        project_root,
        adapter=_MixedConfidenceAdapter(),
    )
    registry = ProviderCatalog()
    registry.register_provider(provider)

    result = registry.execute(_request(source, output, audit_policy="discard"))

    assert result["status"] == "degraded", json.dumps(result, indent=2)
    reconstruction = result["diagnostics"]["operation_result"]["reconstruction"]
    assert [item["outcome"] for item in reconstruction["elements"]] == [
        "editable",
        "editable",
        "rasterized",
    ]
    assert reconstruction["editable_coverage"]["by_area"] == {
        "editable": 20_000.0,
        "total": 30_000.0,
        "ratio": pytest.approx(2 / 3),
    }
    assert reconstruction["editable_coverage"]["by_object_count"] == {
        "editable": 2,
        "total": 3,
        "ratio": pytest.approx(2 / 3),
    }
    with zipfile.ZipFile(output) as archive:
        slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("ppt/media/")]
    assert slide.count("<p:pic>") == 1
    assert '<a:srcRect l="50000"' in slide
    assert len(media) == 1
    assert source.read_bytes() == payload


def test_retain_creates_a_distinct_hashed_audit_asset(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "synthetic-cards.png"
    output = tmp_path / "reconstructed.pptx"
    payload = _png()
    source.write_bytes(payload)
    provider = build_ocr_vision_provider(
        project_root,
        adapter=_DeterministicAdapter(),
    )
    registry = ProviderCatalog()
    registry.register_provider(provider)

    result = registry.execute(_request(source, output, audit_policy="retain"))

    assert result["status"] == "success", json.dumps(result, indent=2)
    audit = result["diagnostics"]["operation_result"]["audit_asset"]
    audit_path = Path(audit["path"])
    assert audit == {
        "policy": "retain",
        "retained": True,
        "path": str(audit_path),
        "media_type": "image/png",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert audit_path.parent == output.parent
    assert audit_path not in {source, output}
    assert audit_path.read_bytes() == payload
    assert any(
        item["role"] == "report"
        and item["path"] == str(audit_path)
        and item["sha256"] == audit["sha256"]
        for item in result["artifacts"]
    )
    with zipfile.ZipFile(output) as archive:
        assert not any(name.startswith("ppt/media/") for name in archive.namelist())
    assert source.read_bytes() == payload


def test_retain_audit_is_removed_when_output_promotion_loses_a_race(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    output = tmp_path / "reconstructed.pptx"
    payload = _png()
    source.write_bytes(payload)
    output.write_bytes(b"initial-destination")
    digest = hashlib.sha256(payload).hexdigest()
    audit_path = output.with_name(f"{output.name}.source-audit-{digest}.png")
    provider = build_ocr_vision_provider(
        project_root,
        adapter=_DestinationRaceAdapter(output),
    )
    registry = ProviderCatalog()
    registry.register_provider(provider)

    result = registry.execute(_request(source, output, audit_policy="retain"))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == b"concurrent-destination"
    assert source.read_bytes() == payload
    assert not audit_path.exists()
