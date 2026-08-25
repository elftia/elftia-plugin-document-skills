"""Semantic provenance coverage for HTML-to-editable-PPTX release bytes."""

import json

from tools.html_pptx_provenance import (
    HTML_PPTX_REQUIREMENT,
    SHARED_PROVENANCE_REQUIREMENT,
    html_pptx_data_profile,
    html_pptx_module_profile,
)
from tools.regenerate_provenance import (
    CORE_PPTX_REQUIREMENT,
    core_pptx_module_profile,
    pptx_openxml_module_profile,
    regenerate,
    xlsx_data_profile,
    xlsx_module_profile,
)

_HTML_XLSX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-xlsx + "
    "document-skills-xlsx-completion + document-skills-xlsx-advanced-authoring"
)
_CORE_HTML_REQUIREMENT = (
    "Rasen document-skills-core-pptx + html-to-editable-pptx"
)
_CORE_HTML_XLSX_REQUIREMENT = (
    "Rasen document-skills-core-pptx + html-to-editable-pptx + "
    "document-skills-core-xlsx + document-skills-xlsx-completion + "
    "document-skills-xlsx-advanced-authoring"
)
_CORE_HTML_REGEN_XLSX_REQUIREMENT = (
    "Rasen document-skills-core-pptx + html-to-editable-pptx + "
    "document-skills-consumer-gates-and-truthful-contracts + "
    "document-skills-core-xlsx + document-skills-xlsx-completion + "
    "document-skills-xlsx-advanced-authoring"
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


_EXPECTED_CORE_PPTX_PROFILES = {
    "src/document_skills_core/formats/pptx/create.py": (
        (
            "Original Core PPTX deterministic creation and schema-valid shape, table, "
            "chart, notes, relationship, and PresentationML emission."
        ),
        [
            "tests/test_pptx_design.py",
            "tests/test_pptx_operations.py",
            "tests/test_pptx_schema_validation.py",
        ],
    ),
    "src/document_skills_core/formats/pptx/scaffold.py": (
        (
            "Core PPTX Office-valid theme, slide master, slide layout, relationship, "
            "document-property, and PresentationML scaffold emission."
        ),
        [
            "tests/test_pptx_design.py",
            "tests/test_pptx_operations.py",
            "tests/test_pptx_schema_validation.py",
        ],
    ),
    "src/document_skills_core/formats/pptx/scene_emitter.py": (
        (
            "Core PPTX schema compatibility for editable scene PresentationML, "
            "including canonical group-transform child ordering."
        ),
        [
            "tests/test_html_scene_emitter.py",
            "tests/test_html_scene_opc_safety.py",
            "tests/test_pptx_schema_validation.py",
        ],
    ),
    "src/document_skills_core/public_cli/supervisor.py": (
        (
            "Core PPTX public create/edit mutation supervision with bounded worker "
            "timeouts and result budgets."
        ),
        [
            "tests/test_html_pptx_public.py",
            "tests/test_pptx_public.py",
            "tests/test_runtime.py",
        ],
    ),
    "tests/test_pptx_design.py": (
        (
            "Direct Core PPTX regression evidence for schema-valid theme gradients "
            "and body-shape child ordering."
        ),
        ["tests/test_pptx_design.py"],
    ),
    "tests/test_pptx_operations.py": (
        (
            "Direct Core PPTX regression evidence for schema-valid graphic-frame "
            "transforms and deterministic package creation."
        ),
        ["tests/test_pptx_operations.py"],
    ),
    "tests/test_pptx_public.py": (
        (
            "Direct Core PPTX public-command regression evidence for internally "
            "consistent create artifacts and schema validation gates."
        ),
        ["tests/test_pptx_public.py"],
    ),
    "tests/test_html_scene_emitter.py": (
        (
            "Direct Core PPTX regression evidence for schema-valid editable scene "
            "group transforms."
        ),
        ["tests/test_html_scene_emitter.py"],
    ),
    "tests/test_html_pptx_public.py": (
        (
            "Direct Core PPTX regression evidence for bounded public create/edit "
            "mutation supervision."
        ),
        ["tests/test_html_pptx_public.py"],
    ),
    "tools/regenerate_provenance.py": (
        (
            "Exact Core PPTX provenance profiling and cross-owner requirement, "
            "modification, and direct-test composition."
        ),
        [
            "tests/test_html_provenance.py",
            "tests/test_strategy3.py",
            "tests/test_supply_chain.py",
        ],
    ),
    "tests/test_html_provenance.py": (
        (
            "Direct exact-attribution regression evidence for Core PPTX provenance "
            "and shared-owner composition."
        ),
        ["tests/test_html_provenance.py"],
    ),
}


def test_core_pptx_profiles_are_exact():
    actual = {
        path: core_pptx_module_profile(path)
        for path in _EXPECTED_CORE_PPTX_PROFILES
    }
    assert actual == _EXPECTED_CORE_PPTX_PROFILES
    assert core_pptx_module_profile("tests/test_pptx_contracts.py") is None


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


def test_core_pptx_records_compose_all_actual_owners(project_root):
    manifest, _digest = regenerate(project_root)
    records = {record["module"]: record for record in manifest["modules"]}
    expected_requirements = {
        "src/document_skills_core/formats/pptx/create.py": CORE_PPTX_REQUIREMENT,
        "src/document_skills_core/formats/pptx/scaffold.py": _CORE_HTML_REQUIREMENT,
        "src/document_skills_core/formats/pptx/scene_emitter.py": (
            _CORE_HTML_REQUIREMENT
        ),
        "src/document_skills_core/public_cli/supervisor.py": (
            _CORE_HTML_XLSX_REQUIREMENT
        ),
        "tests/test_pptx_design.py": CORE_PPTX_REQUIREMENT,
        "tests/test_pptx_operations.py": CORE_PPTX_REQUIREMENT,
        "tests/test_pptx_public.py": _PPTX_PUBLIC_OPENXML_REQUIREMENT,
        "tests/test_html_scene_emitter.py": _CORE_HTML_REQUIREMENT,
        "tests/test_html_pptx_public.py": _CORE_HTML_REQUIREMENT,
        "tools/regenerate_provenance.py": _CORE_HTML_REGEN_XLSX_REQUIREMENT,
        "tests/test_html_provenance.py": _CORE_HTML_XLSX_REQUIREMENT,
    }

    for path, core_profile in _EXPECTED_CORE_PPTX_PROFILES.items():
        html_profile = html_pptx_module_profile(path)
        pptx_openxml_profile = pptx_openxml_module_profile(path)
        xlsx_profile = xlsx_module_profile(path)
        expected_profile = _combined_profile(
            core_profile,
            html_profile,
            pptx_openxml_profile,
            xlsx_profile,
        )
        assert expected_profile is not None
        record = records[path]
        assert record["requirement_source"] == expected_requirements[path]
        assert record["modifications"] == expected_profile[0]
        assert record["artifact_tests"] == expected_profile[1]
        assert "strategy-attempt-3" not in record["modifications"]


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
        html_profile = html_pptx_module_profile(record["module"])
        if html_profile is None:
            continue
        relevant_modules.append(record["module"])
        core_pptx_profile = core_pptx_module_profile(record["module"])
        pptx_profile = _combined_profile(core_pptx_profile, html_profile)
        assert pptx_profile is not None
        xlsx_profile = xlsx_module_profile(record["module"])
        if xlsx_profile:
            expected_requirement = (
                _CORE_HTML_REGEN_XLSX_REQUIREMENT
                if record["module"] == "tools/regenerate_provenance.py"
                else _CORE_HTML_XLSX_REQUIREMENT
                if core_pptx_profile
                else _HTML_XLSX_REQUIREMENT
            )
            expected_modifications = f"{pptx_profile[0]} {xlsx_profile[0]}"
            expected_tests = _merged_values(pptx_profile[1], xlsx_profile[1])
        else:
            expected_requirement = (
                _CORE_HTML_REQUIREMENT
                if core_pptx_profile
                else SHARED_PROVENANCE_REQUIREMENT
                if record["module"] == "tools/regenerate_provenance.py"
                else HTML_PPTX_REQUIREMENT
            )
            expected_modifications, expected_tests = pptx_profile
        assert record["requirement_source"] == expected_requirement
        assert record["modifications"] == expected_modifications
        assert record["artifact_tests"] == expected_tests
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
