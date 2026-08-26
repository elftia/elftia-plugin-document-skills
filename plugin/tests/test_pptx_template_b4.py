from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.service import PptxService
from document_skills_core.formats.pptx.template_content_analysis import (
    inspect_template_content,
)
from tests.support.pptx_template_fixture import build_semantic_template

_EXPECTED_B4_CODES = {
    "cjk-capacity-exceeded",
    "ellipsis-content",
    "placeholder-content",
    "speaker-notes-leak",
    "type-scale-hierarchy",
}


def _public_run(project_root: Path, request_path: Path) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pptx/scripts/run.py"),
            "run",
            "--request",
            str(request_path),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        shell=False,
        timeout=75,
    )
    assert process.returncode in {0, 2}, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def _write_request(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _inspect_request(source: Path) -> dict[str, object]:
    return {
        "arguments": {
            "catalog_ref": None,
            "contact_sheet": False,
            "descriptor": None,
            "expected_input_sha256": sha256(source.read_bytes()).hexdigest(),
            "mode": "strict",
        },
        "input": str(source),
        "operation": "pptx.template.inspect",
        "schema_version": "1.0",
    }


def test_public_inspect_reports_all_b_tpl_03_content_findings(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/pptx/ecosystem_bc/templates/cjk-capacity.pptx"
    request_path = tmp_path / "inspect-b-tpl-03.json"
    _write_request(request_path, _inspect_request(source))

    result = _public_run(project_root, request_path)

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    report = operation["content_lint"]
    assert report["status"] == "failed"
    assert report["mutation_authorized"] is False
    assert report["summary"] == {code: 1 for code in sorted(_EXPECTED_B4_CODES)}
    assert {item["code"] for item in report["findings"]} == _EXPECTED_B4_CODES
    capacity = next(
        item for item in report["findings"] if item["code"] == "cjk-capacity-exceeded"
    )
    assert capacity["actual_characters"] == 35
    assert capacity["capacity_policy"] == "geometry-font-heuristic"
    gate = next(
        item
        for item in result["validation"]["gates"]
        if item["id"] == "operation.template-content-lint"
    )
    assert gate["outcome"] == "fail"
    assert gate["required"] is False


def test_content_lint_passes_a_clean_descriptor_bound_template(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    request = _inspect_request(fixture.source)
    request["arguments"].update({
        "catalog_ref": fixture.catalog_ref,
        "descriptor": fixture.descriptor,
    })

    result = PptxService(project_root).execute("pptx.template.inspect", request)

    assert result["status"] == "success", result
    report = result["diagnostics"]["operation_result"]["content_lint"]
    assert report["status"] == "passed"
    assert report["finding_count"] == 0
    assert report["findings"] == []
    assert report["truncated"] is False


def test_template_creation_rejects_placeholder_before_promotion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    fixture = build_semantic_template(fixture_root, project_root)
    inspection = PptxService(project_root).execute(
        "pptx.template.inspect",
        {
            **_inspect_request(fixture.source),
            "arguments": {
                **_inspect_request(fixture.source)["arguments"],
                "catalog_ref": fixture.catalog_ref,
                "descriptor": fixture.descriptor,
            },
        },
    )
    slot = inspection["diagnostics"]["operation_result"]["pages"][0]["semantic_slots"][0]
    output = tmp_path / "must-not-exist.pptx"
    request = {
        "arguments": {
            "catalog_ref": fixture.catalog_ref,
            "delivery_profile": "development",
            "descriptor": fixture.descriptor,
            "expected_input_sha256": sha256(fixture.source.read_bytes()).hexdigest(),
            "pages": [{
                "bindings": [{
                    "expected_hash": slot["expected_hash"],
                    "slot_id": slot["slot_id"],
                    "value": {"text": "[PLACEHOLDER]", "type": "text"},
                }],
                "output_slide_id": "slide_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source_slide_id": fixture.slide_ids[0],
            }],
            "unbound_required_slot": "reject",
            "unselected_content": "physical_purge",
        },
        "input": str(fixture.source),
        "operation": "pptx.create.from-template",
        "output": str(output),
        "schema_version": "1.0",
    }
    request_path = tmp_path / "reject-placeholder.json"
    _write_request(request_path, request)

    result = _public_run(project_root, request_path)

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    findings = result["errors"][0]["details"]["findings"]
    assert any(item["code"] == "placeholder-content" for item in findings)
    assert not output.exists()


def test_content_lint_report_is_deterministic_and_bounded(
    project_root: Path,
    monkeypatch,
) -> None:
    source = project_root / "tests/fixtures/pptx/ecosystem_bc/templates/cjk-capacity.pptx"
    package = OpcPackage.open(source)
    first = inspect_template_content(package)
    second = inspect_template_content(package)
    assert first == second
    assert len(first["findings"]) <= first["limits"]["max_findings"]

    import document_skills_core.formats.pptx.template_content_analysis as analysis

    monkeypatch.setattr(analysis, "MAX_CONTENT_LINT_FINDINGS", 2)
    bounded = analysis.inspect_template_content(package)
    assert bounded["finding_count"] == 5
    assert len(bounded["findings"]) == 2
    assert bounded["truncated"] is True

    monkeypatch.setattr(analysis, "MAX_CONTENT_LINT_FINDINGS", 64)
    monkeypatch.setattr(analysis, "MAX_SHAPES_PER_SLIDE", 1)
    shape_limited = analysis.inspect_template_content(package)
    assert shape_limited["summary"]["content-lint-shape-limit"] == 3
    assert shape_limited["truncated"] is True
