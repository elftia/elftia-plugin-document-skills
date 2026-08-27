"""Security and resource tests for the OCR/vision reconstruction seam."""

from copy import deepcopy
import os
from pathlib import Path
import struct
from typing import Any, Callable
import zlib

import pytest

from document_skills_core.core.capabilities import DetectionEvidence, ProviderCatalog
from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx import reconstruction_models
from document_skills_core.formats.pptx.reconstruction_models import (
    MAX_RASTER_BYTES,
    parse_reconstruction_observations,
    screen_reconstruction_raster,
)
from document_skills_core.providers.ocr_vision import build_ocr_vision_provider


def _request(source: Path, output: Path) -> dict[str, Any]:
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
            "audit_asset_policy": "discard",
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


def _png_header(width: int, height: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(header)) + b"IHDR" + header


def _jpeg(width: int = 400, height: int = 225) -> bytes:
    frame = b"\x08" + struct.pack(">HH", height, width)
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame + b"\xff\xd9"


def _observation() -> dict[str, Any]:
    return {
        "canvas": {"width": 400, "height": 225},
        "elements": [
            {
                "confidence": 0.95,
                "geometry": {"x": 20, "y": 20, "width": 170, "height": 90},
                "id": "card",
                "kind": "shape",
                "reading_order": 0,
                "source_region": {
                    "x": 20,
                    "y": 20,
                    "width": 170,
                    "height": 90,
                },
                "style": {
                    "border_color": "#2457A6",
                    "border_width": 2,
                    "color": "#102030",
                    "fill": "#DCE8FF",
                    "font_family": "Arial",
                    "font_size": 28,
                    "font_weight": 400,
                    "radius": 8,
                    "text_align": "left",
                },
                "text": "",
            }
        ],
    }


class _Adapter:
    def __init__(self, observation: dict[str, Any]) -> None:
        self.observation = observation
        self.observe_calls = 0

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(True, version="security-fixture-1")

    def observe(self, _source: Path) -> dict[str, Any]:
        self.observe_calls += 1
        return deepcopy(self.observation)


def _execute(project_root: Path, source: Path, output: Path, adapter: _Adapter) -> dict:
    catalog = ProviderCatalog()
    catalog.register_provider(build_ocr_vision_provider(project_root, adapter=adapter))
    return catalog.execute(_request(source, output))


@pytest.mark.parametrize(
    ("source_name", "payload"),
    [
        ("source.png", b"not-a-png"),
        ("source.jpg", _png()),
        ("source.png", _png(width=8_193, height=1)),
        ("source.png", _png_header(width=8_000, height=6_000)),
        ("source.png", _png() + (b"x" * MAX_RASTER_BYTES)),
    ],
    ids=[
        "malformed-magic",
        "suffix-mismatch",
        "dimension-limit",
        "pixel-limit",
        "byte-limit",
    ],
)
def test_unsafe_raster_fails_before_provider_execution(
    project_root: Path,
    tmp_path: Path,
    source_name: str,
    payload: bytes,
):
    source = tmp_path / source_name
    output = tmp_path / "prior.pptx"
    source.write_bytes(payload)
    output.write_bytes(b"prior-destination")
    adapter = _Adapter(_observation())

    result = _execute(project_root, source, output, adapter)

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert adapter.observe_calls == 0
    assert source.read_bytes() == payload
    assert output.read_bytes() == b"prior-destination"


def test_bounded_jpeg_header_is_accepted(project_root: Path, tmp_path: Path):
    source = tmp_path / "source.jpeg"
    output = tmp_path / "reconstructed.pptx"
    source.write_bytes(_jpeg())
    adapter = _Adapter(_observation())

    result = _execute(project_root, source, output, adapter)

    assert result["status"] == "success"
    assert output.is_file()
    assert adapter.observe_calls == 1


def _duplicate_id(value: dict[str, Any]) -> None:
    duplicate = deepcopy(value["elements"][0])
    duplicate["reading_order"] = 1
    value["elements"].append(duplicate)


def _duplicate_order(value: dict[str, Any]) -> None:
    duplicate = deepcopy(value["elements"][0])
    duplicate["id"] = "other"
    value["elements"].append(duplicate)


def _out_of_canvas(value: dict[str, Any]) -> None:
    value["elements"][0]["geometry"]["x"] = 399


def _non_finite(value: dict[str, Any]) -> None:
    value["elements"][0]["confidence"] = float("nan")


def _source_region_out_of_canvas(value: dict[str, Any]) -> None:
    value["elements"][0]["source_region"]["height"] = 500


def _canvas_mismatch(value: dict[str, Any]) -> None:
    value["canvas"]["width"] = 401


def _unknown_path_control(value: dict[str, Any]) -> None:
    value["elements"][0]["output_path"] = "attacker-controlled.pptx"


def _invalid_kind_text(value: dict[str, Any]) -> None:
    value["elements"][0]["kind"] = "text"


def _invalid_style(value: dict[str, Any]) -> None:
    value["elements"][0]["style"]["fill"] = "url(file:///secret)"


def _unhashable_kind(value: dict[str, Any]) -> None:
    value["elements"][0]["kind"] = []


def _unhashable_text_align(value: dict[str, Any]) -> None:
    value["elements"][0]["style"]["text_align"] = {}


def _excessive_text(value: dict[str, Any]) -> None:
    value["elements"][0]["kind"] = "text"
    value["elements"][0]["text"] = "x" * 64_001


@pytest.mark.parametrize(
    "mutate",
    [
        _duplicate_id,
        _duplicate_order,
        _out_of_canvas,
        _non_finite,
        _source_region_out_of_canvas,
        _canvas_mismatch,
        _unknown_path_control,
        _invalid_kind_text,
        _invalid_style,
        _unhashable_kind,
        _unhashable_text_align,
        _excessive_text,
    ],
    ids=[
        "duplicate-id",
        "duplicate-order",
        "out-of-canvas",
        "non-finite",
        "source-region-out-of-canvas",
        "canvas-mismatch",
        "path-control",
        "kind-text-mismatch",
        "invalid-style",
        "unhashable-kind",
        "unhashable-text-align",
        "excessive-text",
    ],
)
def test_invalid_provider_observation_fails_without_artifact_changes(
    project_root: Path,
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
):
    source = tmp_path / "source.png"
    output = tmp_path / "prior.pptx"
    source.write_bytes(_png())
    output.write_bytes(b"prior-destination")
    observation = _observation()
    mutate(observation)
    adapter = _Adapter(observation)

    result = _execute(project_root, source, output, adapter)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_PROVIDER_FAILED"
    assert result["artifacts"] == []
    assert adapter.observe_calls == 1
    assert source.read_bytes() == _png()
    assert output.read_bytes() == b"prior-destination"


def test_provider_element_limit_is_enforced(project_root: Path, tmp_path: Path):
    source = tmp_path / "source.png"
    output = tmp_path / "never-created.pptx"
    source.write_bytes(_png())
    observation = _observation()
    template = observation["elements"][0]
    observation["elements"] = [
        {
            **deepcopy(template),
            "id": f"element-{index}",
            "reading_order": index,
        }
        for index in range(513)
    ]
    adapter = _Adapter(observation)

    result = _execute(project_root, source, output, adapter)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_PROVIDER_FAILED"
    assert not output.exists()


@pytest.mark.parametrize("invalid_case", ["top-level", "element-count", "nested-scalar"])
def test_invalid_provider_values_fail_before_canonical_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
):
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    raster = screen_reconstruction_raster(source)
    value: Any = _observation()
    if invalid_case == "top-level":
        value = ["x" * 3_000_000]
    elif invalid_case == "element-count":
        template = value["elements"][0]
        value["elements"] = [deepcopy(template) for _index in range(513)]
    else:
        value["elements"][0]["style"]["font_family"] = "x" * 3_000_000

    def reject_serialization(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("invalid provider values reached json.dumps")

    monkeypatch.setattr(reconstruction_models.json, "dumps", reject_serialization)

    with pytest.raises(DocumentSkillsError) as caught:
        parse_reconstruction_observations(value, raster)

    assert caught.value.code.value == "DS_PROVIDER_FAILED"


def test_concurrent_raster_growth_is_bounded_during_the_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    real_open = Path.open
    read_sizes: list[int] = []

    class GrowingHandle:
        def __init__(self) -> None:
            self.handle = real_open(source, "rb")
            self.grown = False

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            self.handle.close()

        def fileno(self) -> int:
            return self.handle.fileno()

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            if not self.grown:
                self.grown = True
                growth = MAX_RASTER_BYTES + 1 - source.stat().st_size
                with real_open(source, "ab") as writer:
                    writer.write(b"x" * growth)
            return self.handle.read(size)

    def growing_open(path: Path, *args: object, **kwargs: object):
        if path == source and args and args[0] == "rb":
            return GrowingHandle()
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)

    with pytest.raises(DocumentSkillsError):
        screen_reconstruction_raster(source)

    assert read_sizes == [MAX_RASTER_BYTES + 1]


def test_raster_path_identity_change_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    real_lstat = Path.lstat
    target_calls = 0

    def changed_lstat(path: Path):
        nonlocal target_calls
        value = real_lstat(path)
        if path != source:
            return value
        target_calls += 1
        if target_calls == 1:
            return value
        fields = list(value)
        fields[1] += 1
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "lstat", changed_lstat)

    with pytest.raises(DocumentSkillsError):
        screen_reconstruction_raster(source)

    assert target_calls == 2


def test_whole_canvas_raster_proposal_is_refused(project_root: Path, tmp_path: Path):
    source = tmp_path / "source.png"
    output = tmp_path / "prior.pptx"
    payload = _png()
    source.write_bytes(payload)
    output.write_bytes(b"prior-destination")
    observation = _observation()
    element = observation["elements"][0]
    element["confidence"] = 0.5
    element["geometry"] = {"x": 0, "y": 0, "width": 400, "height": 225}
    element["source_region"] = {"x": 0, "y": 0, "width": 400, "height": 225}
    adapter = _Adapter(observation)

    result = _execute(project_root, source, output, adapter)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["whole_slide_raster"] is True
    assert source.read_bytes() == payload
    assert output.read_bytes() == b"prior-destination"


def test_full_slide_raster_geometry_is_refused_even_with_a_small_source_crop(
    project_root: Path,
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    output = tmp_path / "prior.pptx"
    payload = _png()
    source.write_bytes(payload)
    output.write_bytes(b"prior-destination")
    observation = _observation()
    element = observation["elements"][0]
    element["confidence"] = 0.5
    element["geometry"] = {"x": 0, "y": 0, "width": 400, "height": 225}
    element["source_region"] = {"x": 20, "y": 20, "width": 170, "height": 90}
    adapter = _Adapter(observation)

    result = _execute(project_root, source, output, adapter)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["whole_slide_raster"] is True
    assert source.read_bytes() == payload
    assert output.read_bytes() == b"prior-destination"
