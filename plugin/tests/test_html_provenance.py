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
from tools.regenerate_provenance import (
    pptx_openxml_module_profile,
    regenerate,
    xlsx_data_profile,
    xlsx_module_profile,
)

_HTML_XLSX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-xlsx + "
    "document-skills-xlsx-completion + document-skills-xlsx-advanced-authoring"
)
_PPTX_PUBLIC_OPENXML_REQUIREMENT = (
    "Rasen document-skills-foundation strategy-attempt-3 + "
    "document-skills-core-pptx + document-skills-openxml-dotnet-enhancement"
)
_HTML_NUGET_XLSX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-openxml-dotnet-enhancement + "
    "document-skills-core-xlsx + document-skills-xlsx-completion"
)


def _merged_values(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


def _with_all_xlsx_requirements(base_requirement: str) -> str:
    return (
        f"{base_requirement} + document-skills-core-xlsx + "
        "document-skills-xlsx-completion + "
        "document-skills-xlsx-advanced-authoring"
    )


def _combined_profile(
    *profiles: tuple[str, list[str]] | None,
) -> tuple[str, list[str]] | None:
    selected = [profile for profile in profiles if profile is not None]
    if not selected:
        return None
    tests: list[str] = []
    for _description, profile_tests in selected:
        tests = _merged_values(tests, profile_tests)
    return (" ".join(description for description, _tests in selected), tests)


def test_pptx_public_openxml_profile_is_exact():
    assert pptx_openxml_module_profile("tests/test_pptx_public.py") == (
        (
            "Optional dotnet-openxml schema-gate regression evidence using "
            "operation-time provider detection and truthful success or unavailable "
            "outcomes."
        ),
        ["tests/test_pptx_public.py"],
    )
    assert pptx_openxml_module_profile("tests/test_pptx_operations.py") is None


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


def test_html_readme_uses_the_complete_xlsx_profile(project_root):
    manifest, _digest = regenerate(project_root)
    record = next(
        item
        for item in manifest["data_classifications"]
        if item["artifact"] == "README.md"
    )
    html_profile = html_pptx_data_profile("README.md")
    xlsx_profile = xlsx_data_profile("README.md")
    assert html_profile is not None
    assert xlsx_profile is not None
    assert record["requirement_source"] == _HTML_XLSX_REQUIREMENT
    assert record["modifications"] == f"{html_profile[0]} {xlsx_profile[0]}"
    assert record["artifact_tests"] == _merged_values(
        html_profile[1],
        xlsx_profile[1],
    )


def test_html_pptx_release_records_use_truthful_requirement_and_tests(project_root):
    manifest = json.loads(
        (project_root / "provenance/modules.json").read_text(encoding="utf-8")
    )
    relevant_modules = []
    for record in manifest["modules"]:
        pptx_profile = pptx_module_profile(record["module"])
        if pptx_profile is None:
            continue
        relevant_modules.append(record["module"])
        pptx_openxml_profile = pptx_openxml_module_profile(record["module"])
        xlsx_profile = xlsx_module_profile(record["module"])
        expected_profile = _combined_profile(
            (pptx_profile[0], pptx_profile[1]),
            pptx_openxml_profile,
            xlsx_profile,
        )
        assert expected_profile is not None
        base_requirement = (
            _PPTX_PUBLIC_OPENXML_REQUIREMENT
            if pptx_openxml_profile
            else pptx_profile[2]
        )
        if xlsx_profile:
            expected_requirement = _with_all_xlsx_requirements(base_requirement)
        else:
            expected_requirement = base_requirement
        assert record["requirement_source"] == expected_requirement
        assert record["modifications"] == expected_profile[0]
        assert record["artifact_tests"] == expected_profile[1]
        assert "strategy-attempt-3" not in record["modifications"]
        for test_path in record["artifact_tests"]:
            assert (project_root / test_path).is_file()

    relevant_data = []
    for record in manifest["data_classifications"]:
        profile = html_pptx_data_profile(record["artifact"])
        if profile is None:
            continue
        relevant_data.append(record["artifact"])
        xlsx_profile = xlsx_data_profile(record["artifact"])
        if xlsx_profile:
            expected_requirement = (
                _HTML_XLSX_REQUIREMENT
                if record["artifact"] == "README.md"
                else _HTML_NUGET_XLSX_REQUIREMENT
            )
            expected_modifications = f"{profile[0]} {xlsx_profile[0]}"
            expected_tests = _merged_values(profile[1], xlsx_profile[1])
        else:
            expected_requirement = HTML_PPTX_REQUIREMENT
            expected_modifications, expected_tests = profile
        assert record["requirement_source"] == expected_requirement
        assert record["modifications"] == expected_modifications
        assert record["artifact_tests"] == expected_tests

    assert "runtime/node/html_scene_capture.mjs" in relevant_modules
    assert "src/document_skills_core/formats/pptx/scene_emitter.py" in relevant_modules
    assert "tests/fixtures/recipes/html_pptx_fixtures.py" in relevant_modules
    assert "tests/test_html_provenance.py" in relevant_modules
    assert "package-lock.json" in relevant_data
    assert "tests/fixtures/html-native.expected.pptx" in relevant_data
