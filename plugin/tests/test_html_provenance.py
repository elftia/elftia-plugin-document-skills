"""Semantic provenance coverage for HTML-to-editable-PPTX release bytes."""

import json

from tools.html_pptx_provenance import (
    COMBINED_PPTX_REQUIREMENT,
    CORE_PPTX_REQUIREMENT,
    HTML_PPTX_REQUIREMENT,
    SHARED_PROVENANCE_REQUIREMENT,
    core_pptx_module_profile,
    html_pptx_data_profile,
    html_pptx_module_profile,
    pptx_module_profile,
)


def test_html_pptx_release_records_use_truthful_requirement_and_tests(project_root):
    manifest = json.loads(
        (project_root / "provenance/modules.json").read_text(encoding="utf-8")
    )
    relevant_modules = []
    for record in manifest["modules"]:
        profile = pptx_module_profile(record["module"])
        if profile is None:
            continue
        relevant_modules.append(record["module"])
        assert record["requirement_source"] == profile[2]
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


def test_core_pptx_profiles_cover_repair_and_shared_public_evidence():
    core_only = pptx_module_profile(
        "src/document_skills_core/formats/pptx/create.py"
    )
    assert core_only is not None
    assert core_only[2] == CORE_PPTX_REQUIREMENT
    assert core_only[:2] == core_pptx_module_profile(
        "src/document_skills_core/formats/pptx/create.py"
    )

    for path in (
        "src/document_skills_core/formats/pptx/scaffold.py",
        "src/document_skills_core/public_cli/supervisor.py",
        "tests/test_html_pptx_public.py",
    ):
        combined = pptx_module_profile(path)
        assert combined is not None
        assert combined[2] == COMBINED_PPTX_REQUIREMENT
        assert html_pptx_module_profile(path) is not None
        assert core_pptx_module_profile(path) is not None

    generator = pptx_module_profile("tools/regenerate_provenance.py")
    assert generator is not None
    assert generator[2] == SHARED_PROVENANCE_REQUIREMENT
