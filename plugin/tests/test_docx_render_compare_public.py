"""DOCX public-boundary tests split by operation family."""

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

def test_public_create_output_converts_through_real_libreoffice(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "public-created.pdf"
    request = _request(
        tmp_path,
        "convert-pdf.json",
        {
            "schema_version": "1.0",
            "operation": "docx.convert.pdf",
            "input": str(public_created),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_output_bytes": 8 * 1024 * 1024},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    if result["status"] == "unavailable":
        assert result["provider_chain"] == []
        assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
        assert not output.exists()
        _require_libreoffice_or_skip(
            "LibreOffice provider profile is unavailable"
        )

    assert result["status"] == "success", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
    assert result["provider_chain"] == ["libreoffice"]
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["provider.reopen"]["outcome"] == "pass"
    assert gates["operation.docx-convert-pdf"]["outcome"] == "pass"
    assert gates["visual.render"]["outcome"] == "unavailable"
    assert output.read_bytes().startswith(b"%PDF-")
    assert result["diagnostics"]["operation_result"]["conversion"]["pages"] >= 1
    assert sha256_file(public_created) == source_sha256


def test_public_render_output_through_real_libreoffice(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "public-rendered.pdf"
    request = _request(
        tmp_path,
        "render-pdf.json",
        {
            "schema_version": "1.0",
            "operation": "docx.render",
            "input": str(public_created),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "format": "pdf",
                "page_range": {"start": 1, "end": 1},
                "dpi": None,
                "max_pages": 1,
                "max_total_bytes": 8 * 1024 * 1024,
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    if result["status"] == "unavailable":
        assert result["provider_chain"] == []
        assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
        assert not output.exists()
        _require_libreoffice_or_skip(
            "LibreOffice provider profile is unavailable"
        )

    assert result["status"] == "success", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
    assert result["provider_chain"] == ["libreoffice"]
    render = result["diagnostics"]["operation_result"]["render"]
    assert render["conversion_succeeded"] is True
    assert render["pages_generated"] is True
    assert render["page_count"] == 1
    assert render["visual_comparison"] == "unavailable"
    assert reopen_pdf(output)["pages"] == 1
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["provider.reopen"]["outcome"] == "pass"
    assert gates["operation.docx-render-pages"]["outcome"] == "pass"
    assert gates["visual.render"]["outcome"] == "unavailable"
    assert sha256_file(public_created) == source_sha256


def test_public_render_returns_bounded_png_and_layout_evidence(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "public-layout-evidence.pdf"
    request = _request(
        tmp_path,
        "render-layout-evidence.json",
        {
            "schema_version": "1.0",
            "operation": "docx.render",
            "input": str(public_created),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "format": "pdf",
                "page_range": {"start": 1, "end": 1},
                "include_page_pngs": True,
                "dpi": 96,
                "layout_profile": "professional-v1",
                "max_pages": 1,
                "max_page_bytes": 2 * 1024 * 1024,
                "max_png_total_bytes": 1_000_000,
                "max_total_bytes": 8 * 1024 * 1024,
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    if result["status"] == "unavailable":
        assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
        assert not output.exists()
        _require_libreoffice_or_skip(
            "LibreOffice page-raster profile is unavailable"
        )

    assert result["status"] == "success", result
    render = result["diagnostics"]["operation_result"]["render"]
    assert render["render_status"] == "pass"
    assert render["page_generation_status"] == "pass"
    assert render["layout_status"] in {"pass", "review_required", "fail"}
    assert render["visual_comparison_status"] == "unavailable"
    assert render["render_engine"]["id"] == "libreoffice"
    assert render["render_engine"]["version"]
    assert render["font_inventory"]["status"] == "unavailable"
    assert len(render["page_evidence"]) == 1
    page = render["page_evidence"][0]
    png = base64.b64decode(page["png_base64"], validate=True)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert sha256(png).hexdigest() == page["sha256"]
    assert page["bytes"] == len(png)
    assert page["dimensions_px"]["width"] > 0
    assert page["dimensions_px"]["height"] > 0
    assert render["layout"]["profile"] == {
        "id": "professional-v1",
        "version": "1.0",
    }
    assert all(
        set(finding) == {
            "code",
            "severity",
            "page",
            "semantic_node_id",
            "evidence",
            "suggestion",
        }
        for finding in render["layout"]["findings"]
    )
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["operation.docx-render-png-pages"]["outcome"] == "pass"
    assert gates["operation.docx-layout-rules"]["outcome"] in {"pass", "fail"}
    assert sha256_file(public_created) == source_sha256


def test_public_layout_repair_runs_bounded_improvement_loop(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "oversized.png"
    image.write_bytes(_PNG_16)
    source = tmp_path / "oversized.docx"
    create_request = _request(
        tmp_path,
        "create-oversized.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(source),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "resources": {"wide": {"type": "image", "path": str(image)}},
                    "nodes": [
                        {"id": "document_title", "type": "title", "text": "Repair"},
                        {
                            "id": "figure_wide",
                            "type": "figure",
                            "resource": "wide",
                            "alt_text": "Oversized figure",
                            "width_inches": 10,
                        },
                    ],
                }
            },
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    source_sha256 = sha256_file(source)

    output = tmp_path / "repaired.docx"
    repair_request = _request(
        tmp_path,
        "repair-layout.json",
        {
            "schema_version": "1.0",
            "operation": "docx.layout.repair",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "max_rounds": 2,
                "finding_codes": ["DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH"],
                "max_pages": 5,
                "max_total_bytes": 8 * 1024 * 1024,
                "max_png_total_bytes": 8 * 1024 * 1024,
            },
        },
    )
    result = _public(project_root, "run", "--request", str(repair_request), check=False)
    if result["status"] == "unavailable":
        assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
        assert not output.exists()
        _require_libreoffice_or_skip(
            "LibreOffice page-raster profile is unavailable"
        )

    assert result["status"] == "success", result
    repair = result["diagnostics"]["operation_result"]["layout_repair"]
    assert repair["rounds"] == 1
    assert repair["max_rounds"] == 2
    assert repair["stop_reason"] == "resolved_repairable"
    assert repair["initial_score"] > repair["final_score"]
    assert repair["improved"] is True
    assert repair["repaired_node_ids"] == ["figure_wide"]
    assert all(
        finding["code"] != "DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH"
        for finding in repair["final_layout"]["findings"]
    )
    assert repair["visual_comparison"] == "unavailable"
    assert sha256_file(source) == source_sha256
    assert output.is_file()
