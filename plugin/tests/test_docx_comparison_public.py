"""DOCX public-boundary tests split by operation family."""

import pytest

from tests.support.docx_public import *  # noqa: F401,F403
from tests.support.docx_public import (
    _GIF,
    _PNG,
    _PNG_16,
    _public,
    _read_document,
    _require_libreoffice_or_skip,
    _report,
    _request,
    _table_values,
)

def test_public_semantic_compare_covers_spec_and_before_after(
    project_root: Path,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "semantic-baseline.docx"
    baseline_spec = {
        "version": "1.0",
        "style_profile": {"id": "professional-generic", "version": "1.0"},
        "nodes": [
            {"id": "document_title", "type": "title", "text": "Comparison"},
            {
                "id": "section_primary",
                "type": "heading",
                "level": 1,
                "text": "Scope",
            },
            {
                "id": "body_primary",
                "type": "paragraph",
                "text": "Original semantic content.",
            },
            {
                "id": "table_primary",
                "type": "table",
                "rows": [["Key", "Value"], ["Status", "Baseline"]],
            },
        ],
    }
    create_baseline = _request(
        tmp_path,
        "create-semantic-baseline.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(baseline),
            "arguments": {"document_spec": baseline_spec},
        },
    )
    assert _public(project_root, "run", "--request", str(create_baseline))["status"] == (
        "success"
    )

    compare_spec = _request(
        tmp_path,
        "compare-spec-output.json",
        {
            "schema_version": "1.0",
            "operation": "docx.compare.semantic",
            "input": str(baseline),
            "arguments": {"document_spec": baseline_spec},
        },
    )
    spec_result = _public(project_root, "run", "--request", str(compare_spec))
    assert spec_result["status"] == "success", spec_result
    spec_comparison = spec_result["diagnostics"]["operation_result"][
        "semantic_comparison"
    ]
    assert spec_comparison["mode"] == "spec-output"
    assert spec_comparison["status"] == "pass"
    assert spec_comparison["expected"] == 4
    assert spec_comparison["missing"] == []
    assert spec_comparison["unexpected"] == []
    assert spec_comparison["changed"] == []
    assert spec_comparison["degraded"] == []

    changed = tmp_path / "semantic-changed.docx"
    changed_spec = json.loads(json.dumps(baseline_spec))
    changed_spec["nodes"][2]["text"] = "Authorized replacement content."
    create_changed = _request(
        tmp_path,
        "create-semantic-changed.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(changed),
            "arguments": {"document_spec": changed_spec},
        },
    )
    assert _public(project_root, "run", "--request", str(create_changed))["status"] == (
        "success"
    )
    baseline_sha256 = sha256_file(baseline)
    compare_changed = _request(
        tmp_path,
        "compare-before-after.json",
        {
            "schema_version": "1.0",
            "operation": "docx.compare.semantic",
            "input": str(changed),
            "arguments": {
                "baseline": str(baseline),
                "expected_baseline_sha256": baseline_sha256,
                "allowed_changes": [],
            },
        },
    )
    changed_result = _public(project_root, "run", "--request", str(compare_changed))
    assert changed_result["status"] == "success", changed_result
    changed_comparison = changed_result["diagnostics"]["operation_result"][
        "semantic_comparison"
    ]
    assert changed_comparison["mode"] == "before-after"
    assert changed_comparison["status"] == "fail"
    assert [item["node_id"] for item in changed_comparison["changed"]] == [
        "body_primary"
    ]
    assert changed_comparison["allowed"] == []
    assert changed_comparison["structural_diff"]
    assert changed_comparison["preservation_manifest"]["changed_parts"] == [
        "word/document.xml"
    ]

    allowed_request = _request(
        tmp_path,
        "compare-before-after-allowed.json",
        {
            "schema_version": "1.0",
            "operation": "docx.compare.semantic",
            "input": str(changed),
            "arguments": {
                "baseline": str(baseline),
                "expected_baseline_sha256": baseline_sha256,
                "allowed_changes": ["body_primary"],
            },
        },
    )
    allowed_result = _public(project_root, "run", "--request", str(allowed_request))
    allowed_comparison = allowed_result["diagnostics"]["operation_result"][
        "semantic_comparison"
    ]
    assert allowed_comparison["status"] == "pass"
    assert allowed_comparison["changed"] == []
    assert [item["node_id"] for item in allowed_comparison["allowed"]] == [
        "body_primary"
    ]
    assert sha256_file(baseline) == baseline_sha256


@pytest.mark.slow
def test_public_reference_visual_compare_uses_explicit_fixed_page_pairing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    public_created = tmp_path / "visual-source.docx"
    create_request = _request(
        tmp_path,
        "create-visual-source.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(public_created),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {"id": "visual_title", "type": "title", "text": "Visual"},
                        {
                            "id": "visual_body",
                            "type": "paragraph",
                            "text": "A fixed one-page comparison fixture.",
                        },
                    ],
                }
            },
        },
    )
    assert _public(project_root, "run", "--request", str(create_request))["status"] == (
        "success"
    )
    source_sha256 = sha256_file(public_created)
    request = _request(
        tmp_path,
        "compare-visual-identical.json",
        {
            "schema_version": "1.0",
            "operation": "docx.compare.visual",
            "input": str(public_created),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "reference": str(public_created),
                "expected_reference_sha256": source_sha256,
                "render_profile": "libreoffice-96dpi-v1",
                "page_pairs": [{"actual": 1, "reference": 1}],
                "max_pages": 5,
                "max_total_bytes": 8 * 1024 * 1024,
                "max_png_total_bytes": 8 * 1024 * 1024,
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    if result["status"] == "unavailable":
        assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
        _require_libreoffice_or_skip(
            "LibreOffice page-raster profile is unavailable"
        )

    assert result["status"] == "success", result
    comparison = result["diagnostics"]["operation_result"]["visual_comparison"]
    assert comparison["status"] == "pass"
    assert comparison["render_profile"] == {
        "id": "libreoffice-96dpi-v1",
        "version": "1.0",
        "dpi": 96,
        "color_space": "sRGB-RGBA8",
    }
    assert comparison["page_count_match"] is True
    assert comparison["page_pairs"] == [{"actual": 1, "reference": 1}]
    pair = comparison["comparisons"][0]
    assert pair["status"] == "pass"
    assert pair["metrics"]["geometry"]["status"] == "pass"
    assert pair["metrics"]["color"]["mean_absolute_error"] == 0
    assert pair["metrics"]["placement"]["changed_pixel_ratio"] == 0
    assert pair["metrics"]["typography"]["status"] == "unavailable"
    assert pair["metrics"]["spacing"]["status"] == "unavailable"
    for key in ("overlay_png", "diff_png"):
        image = base64.b64decode(pair[key]["base64"], validate=True)
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert sha256(image).hexdigest() == pair[key]["sha256"]
    assert sha256_file(public_created) == source_sha256

    reference_png = tmp_path / "reference.png"
    reference_png.write_bytes(_PNG)
    png_request = _request(
        tmp_path,
        "compare-visual-png.json",
        {
            "schema_version": "1.0",
            "operation": "docx.compare.visual",
            "input": str(public_created),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "reference": str(reference_png),
                "expected_reference_sha256": sha256_file(reference_png),
                "render_profile": "libreoffice-96dpi-v1",
                "page_pairs": [{"actual": 1, "reference": 1}],
                "max_pages": 5,
                "max_total_bytes": 8 * 1024 * 1024,
                "max_png_total_bytes": 8 * 1024 * 1024,
            },
        },
    )
    png_result = _public(project_root, "run", "--request", str(png_request))
    png_comparison = png_result["diagnostics"]["operation_result"][
        "visual_comparison"
    ]
    assert png_comparison["status"] == "fail"
    assert png_comparison["comparisons"][0]["metrics"]["geometry"]["status"] == (
        "fail"
    )
