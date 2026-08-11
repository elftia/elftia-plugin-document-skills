"""Semantic provenance coverage for HTML-to-editable-PPTX release bytes."""

import json

from tools.html_pptx_provenance import (
    HTML_PPTX_REQUIREMENT,
    SHARED_PROVENANCE_REQUIREMENT,
    html_pptx_data_profile,
    html_pptx_module_profile,
)


def test_html_pptx_release_records_use_truthful_requirement_and_tests(project_root):
    manifest = json.loads(
        (project_root / "provenance/modules.json").read_text(encoding="utf-8")
    )
    relevant_modules = []
    for record in manifest["modules"]:
        profile = html_pptx_module_profile(record["module"])
        if profile is None:
            continue
        relevant_modules.append(record["module"])
        expected_requirement = (
            SHARED_PROVENANCE_REQUIREMENT
            if record["module"] == "tools/regenerate_provenance.py"
            else HTML_PPTX_REQUIREMENT
        )
        assert record["requirement_source"] == expected_requirement
        assert record["modifications"] == profile[0]
        assert record["artifact_tests"] == profile[1]
        assert "strategy-attempt-3" not in record["modifications"]
        for test_path in record["artifact_tests"]:
            assert (project_root / test_path).is_file()

    relevant_data = []
    for record in manifest["data_classifications"]:
        profile = html_pptx_data_profile(record["artifact"])
        if profile is None:
            continue
        relevant_data.append(record["artifact"])
        assert record["requirement_source"] == HTML_PPTX_REQUIREMENT
        assert record["modifications"] == profile[0]
        assert record["artifact_tests"] == profile[1]

    assert "runtime/node/html_scene_capture.mjs" in relevant_modules
    assert "src/document_skills_core/formats/pptx/scene_emitter.py" in relevant_modules
    assert "tests/fixtures/recipes/html_pptx_fixtures.py" in relevant_modules
    assert "tests/test_html_provenance.py" in relevant_modules
    assert "package-lock.json" in relevant_data
    assert "tests/fixtures/html-native.expected.pptx" in relevant_data
