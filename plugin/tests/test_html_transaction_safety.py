"""HTML-to-PPTX failures preserve source, destination, and private-root hygiene."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.formats.pptx import service as pptx_service
from document_skills_core.formats.pptx.scene_normalizer import NormalizedScene


@pytest.mark.parametrize(
    ("code", "details"),
    [
        (ErrorCode.PROVIDER_FAILED, {}),
        (ErrorCode.PROCESS_TIMEOUT, {"reason_category": "timeout"}),
        (ErrorCode.PROVIDER_FAILED, {"reason_category": "cancelled"}),
        (ErrorCode.PROVIDER_FAILED, {"reason_category": "overflow"}),
    ],
)
def test_capture_failure_modes_preserve_source_destination_and_cleanup(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: ErrorCode,
    details: dict[str, str],
):
    source, output, source_hash, output_hash = _artifacts(tmp_path)
    temp_base = tmp_path / "document-skills-operations"
    error = DocumentSkillsError(code, "contained capture failure", details=details)

    class _FailingCapture:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def capture(self, *_args, **_kwargs):
            raise error

    monkeypatch.setattr(pptx_service, "HtmlDeckCapture", _FailingCapture)
    monkeypatch.setattr(
        pptx_service,
        "OperationTempRoot",
        lambda base=None: OperationTempRoot(base=temp_base),
    )
    service = pptx_service.PptxService(
        project_root,
        html_browser_detector=object(),
    )

    result = service.execute("pptx.create.from-html", _request(source, output))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == code.value
    _assert_preserved(source, output, source_hash, output_hash, temp_base)


def test_required_validation_failure_preserves_source_destination_and_cleanup(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, output, source_hash, output_hash = _artifacts(tmp_path)
    temp_base = tmp_path / "document-skills-operations"

    class _Captured:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def capture(self, *_args, **_kwargs) -> object:
            return object()

    scene = NormalizedScene(
        slides=((_item(),),),
        assets={},
        diagnostics={"outcomes": {"native": 1}},
    )

    def _emit(path: Path, *_args, **_kwargs) -> dict[str, object]:
        path.write_bytes(b"staged-candidate")
        return {"items": [], "objects": 0, "slides": 1, "media": 0}

    def _reject(*_args, **_kwargs):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "required scene gate failed",
        )

    monkeypatch.setattr(pptx_service, "HtmlDeckCapture", _Captured)
    monkeypatch.setattr(pptx_service, "normalize_scene", lambda _capture: scene)
    monkeypatch.setattr(pptx_service, "emit_scene_pptx", _emit)
    monkeypatch.setattr(pptx_service, "validate_scene_created", _reject)
    monkeypatch.setattr(
        pptx_service,
        "OperationTempRoot",
        lambda base=None: OperationTempRoot(base=temp_base),
    )
    service = pptx_service.PptxService(
        project_root,
        html_browser_detector=object(),
    )

    result = service.execute("pptx.create.from-html", _request(source, output))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED.value
    _assert_preserved(source, output, source_hash, output_hash, temp_base)


def _artifacts(tmp_path: Path) -> tuple[Path, Path, str, str]:
    source = tmp_path / "deck.html"
    source.write_text(
        '<section class="slide" style="width:1920px;height:1080px"></section>',
        encoding="utf-8",
    )
    output = tmp_path / "deck.pptx"
    output.write_bytes(b"pre-existing-destination")
    return source, output, _sha256(source), _sha256(output)


def _request(source: Path, output: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.create.from-html",
        "input": str(source),
        "output": str(output),
        "arguments": {},
        "options": {"fidelity": "core"},
    }


def _assert_preserved(
    source: Path,
    output: Path,
    source_hash: str,
    output_hash: str,
    temp_base: Path,
) -> None:
    assert _sha256(source) == source_hash
    assert _sha256(output) == output_hash
    assert not list(temp_base.glob("operation-*"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _item() -> dict[str, object]:
    return {
        "source_id": "item",
        "kind": "rectangle",
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 50,
        "rotation": 0,
        "opacity": 1,
        "fill": "rgb(255, 255, 255)",
        "border_color": "rgb(0, 0, 0)",
        "border_width": 0,
        "radius": 0,
        "text": "",
        "paragraphs": [],
        "outcome": "native",
        "asset_id": None,
    }
