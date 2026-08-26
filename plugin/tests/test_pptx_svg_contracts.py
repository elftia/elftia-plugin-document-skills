"""Public contracts for the constrained SVG and scene-export slice."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.contracts import parse_pptx_request
from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
)


def _contract_binding(root: Path) -> dict[str, str]:
    return {
        "manifest_sha256": PRESENTATION_CONTRACT_V1_PIN.manifest_sha256,
        "root": str(root),
    }


def test_parse_create_from_svg_defaults_to_native_only(tmp_path: Path) -> None:
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.create.from-svg",
        "input": str(tmp_path / "slide.svg"),
        "output": str(tmp_path / "slide.pptx"),
        "arguments": {},
    })

    assert parsed.arguments == {
        "fallback_policy": "reject",
        "metadata": {
            "creator": "Elftia Document Skills",
            "subject": "",
            "title": "Elftia SVG Presentation",
        },
    }


def test_parse_create_from_svg_accepts_bounded_element_fallback(tmp_path: Path) -> None:
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.create.from-svg",
        "input": str(tmp_path / "slide.svg"),
        "output": str(tmp_path / "slide.pptx"),
        "arguments": {
            "fallback_policy": "element-rasterize",
            "metadata": {"creator": "Elftia", "subject": "B5", "title": "SVG"},
        },
    })

    assert parsed.arguments["fallback_policy"] == "element-rasterize"
    assert parsed.arguments["metadata"]["title"] == "SVG"


@pytest.mark.parametrize(
    ("input_name", "output_name", "arguments"),
    [
        ("slide.svgz", "slide.pptx", {}),
        ("slide.svg", "slide.pdf", {}),
        ("slide.svg", "slide.pptx", {"fallback_policy": "slide-rasterize"}),
        ("slide.svg", "slide.pptx", {"unknown": True}),
    ],
)
def test_parse_create_from_svg_rejects_ambiguous_surface(
    tmp_path: Path,
    input_name: str,
    output_name: str,
    arguments: dict[str, object],
) -> None:
    with pytest.raises(DocumentSkillsError) as error:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.create.from-svg",
            "input": str(tmp_path / input_name),
            "output": str(tmp_path / output_name),
            "arguments": arguments,
        })
    assert error.value.code.value == "DS_REQUEST_INVALID"


def test_parse_scene_export_binds_contract_and_stable_identity(tmp_path: Path) -> None:
    contract_root = tmp_path / "presentation-contracts"
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.scene.export",
        "input": str(tmp_path / "source.pptx"),
        "output": str(tmp_path / "scene-bundle"),
        "arguments": {
            "contract": _contract_binding(contract_root),
            "identity": {
                "namespace": "example.synthetic",
                "source_template_id": "svg-roundtrip",
                "source_template_version": "1.0.0",
            },
            "mode": "strict",
        },
    })

    assert parsed.output_path == tmp_path / "scene-bundle"
    assert parsed.arguments["contract"]["root"] == contract_root
    assert parsed.arguments["mode"] == "strict"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {
            "contract": {"root": "contracts", "manifest_sha256": "sha256:" + "0" * 64},
            "identity": {
                "namespace": "example.synthetic",
                "source_template_id": "svg-roundtrip",
                "source_template_version": "1.0.0",
            },
            "mode": "strict",
        },
        {
            "contract": {"root": "contracts", "manifest_sha256": PRESENTATION_CONTRACT_V1_PIN.manifest_sha256},
            "identity": {
                "namespace": "example.synthetic",
                "source_template_id": "svg-roundtrip",
                "source_template_version": "1.0.0",
            },
            "mode": "guess",
        },
        {
            "contract": {"root": "contracts", "manifest_sha256": PRESENTATION_CONTRACT_V1_PIN.manifest_sha256},
            "identity": {
                "namespace": "example.synthetic",
                "source_template_id": "Bad ID",
                "source_template_version": "1",
            },
            "mode": "strict",
        },
    ],
)
def test_parse_scene_export_rejects_unbound_or_unknown_contracts(
    tmp_path: Path,
    arguments: dict[str, object],
) -> None:
    with pytest.raises(DocumentSkillsError) as error:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.scene.export",
            "input": str(tmp_path / "source.pptx"),
            "output": str(tmp_path / "scene-bundle"),
            "arguments": arguments,
        })
    assert error.value.code.value == "DS_REQUEST_INVALID"


def test_scene_export_rejects_in_place_and_non_pptx_input(tmp_path: Path) -> None:
    arguments = {
        "contract": _contract_binding(tmp_path / "contracts"),
        "identity": {
            "namespace": "example.synthetic",
            "source_template_id": "svg-roundtrip",
            "source_template_version": "1.0.0",
        },
        "mode": "tolerant",
    }
    for input_name, output_name, options in (
        ("source.docx", "scene-bundle", {}),
        ("source.pptx", "source.pptx", {}),
        ("source.pptx", "scene-bundle", {"in_place": True}),
    ):
        with pytest.raises(DocumentSkillsError):
            parse_pptx_request({
                "schema_version": "1.0",
                "operation": "pptx.scene.export",
                "input": str(tmp_path / input_name),
                "output": str(tmp_path / output_name),
                "arguments": arguments,
                "options": options,
            })
