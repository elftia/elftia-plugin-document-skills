"""Public request-contract tests for layered raster reconstruction."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.contracts import parse_pptx_request


def _request(tmp_path: Path, **overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "pptx.reconstruct.from-image",
        "input": str(tmp_path / "source.png"),
        "output": str(tmp_path / "reconstructed.pptx"),
        "arguments": {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
        },
    }
    request.update(overrides)
    return request


def test_parse_reconstruction_requires_explicit_closed_policies(tmp_path: Path):
    parsed = parse_pptx_request(_request(tmp_path))

    assert parsed.operation == "pptx.reconstruct.from-image"
    assert parsed.arguments == {
        "provider_policy": {
            "provider": "ocr-vision",
            "on_unavailable": "fail",
        },
        "audit_asset_policy": "retain",
        "confidence_threshold": 0.75,
        "metadata": {
            "title": "Elftia Presentation",
            "creator": "Elftia Document Skills",
            "subject": "",
        },
    }


def test_parse_reconstruction_accepts_jpeg_and_bounded_options(tmp_path: Path):
    request = _request(
        tmp_path,
        input=str(tmp_path / "source.JPEG"),
        arguments={
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "discard",
            "confidence_threshold": 0.625,
            "metadata": {
                "title": "Reconstructed",
                "creator": "Elftia",
                "subject": "B7",
            },
        },
    )

    parsed = parse_pptx_request(request)

    assert parsed.input_path == tmp_path / "source.JPEG"
    assert parsed.arguments["audit_asset_policy"] == "discard"
    assert parsed.arguments["confidence_threshold"] == 0.625
    assert parsed.arguments["metadata"]["title"] == "Reconstructed"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"audit_asset_policy": "retain"},
        {
            "provider_policy": {
                "provider": "other",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "single-image",
            },
            "audit_asset_policy": "retain",
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
                "unknown": True,
            },
            "audit_asset_policy": "retain",
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "delete-caller-source",
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": [],
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": {},
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": None,
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": True,
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
            "confidence_threshold": True,
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
            "confidence_threshold": 1.01,
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
            "confidence_threshold": -0.01,
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
            "confidence_threshold": float("nan"),
        },
        {
            "provider_policy": {
                "provider": "ocr-vision",
                "on_unavailable": "fail",
            },
            "audit_asset_policy": "retain",
            "unknown": True,
        },
    ],
)
def test_parse_reconstruction_rejects_implicit_or_open_policy(
    tmp_path: Path,
    arguments: dict[str, object],
):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request(_request(tmp_path, arguments=arguments))

    assert exc.value.code.value == "DS_REQUEST_INVALID"


@pytest.mark.parametrize("input_name", ["source.webp", "source.svg", "source.pptx"])
def test_parse_reconstruction_rejects_unsupported_raster_suffix(
    tmp_path: Path,
    input_name: str,
):
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request(_request(tmp_path, input=str(tmp_path / input_name)))


def test_parse_reconstruction_rejects_in_place_option(tmp_path: Path):
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request(_request(tmp_path, options={"in_place": True}))


def test_parse_reconstruction_rejects_same_input_and_output_path(tmp_path: Path):
    source = tmp_path / "source.png"

    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request(_request(tmp_path, output=str(source)))

    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_reconstruction_rejects_oversized_metadata(tmp_path: Path):
    request = _request(tmp_path)
    request["arguments"] = {
        "provider_policy": {
            "provider": "ocr-vision",
            "on_unavailable": "fail",
        },
        "audit_asset_policy": "retain",
        "metadata": {"title": "x" * 4_097},
    }

    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request(request)

    assert exc.value.code.value == "DS_REQUEST_INVALID"
