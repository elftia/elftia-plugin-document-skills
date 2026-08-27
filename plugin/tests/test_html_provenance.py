"""Semantic provenance coverage for HTML-to-editable-PPTX release bytes."""

import json

from tools.html_pptx_provenance import (
    COMBINED_PPTX_REQUIREMENT,
    COMBINED_PPTX_TEMPLATE_B2_REQUIREMENT,
    HTML_PPTX_REQUIREMENT,
    PPTX_EQUATION_B6_REQUIREMENT,
    PPTX_TEMPLATE_B2_REQUIREMENT,
    PPTX_TEMPLATE_B4_REQUIREMENT,
    PPTX_SVG_B5_REQUIREMENT,
    SHARED_PROVENANCE_TEMPLATE_B2_B4_B5_B6_REQUIREMENT,
    core_pptx_module_profile,
    equation_b6_data_profile,
    equation_b6_module_profile,
    html_pptx_data_profile,
    html_pptx_module_profile,
    pptx_module_profile,
    template_b2_data_profile,
    template_b2_module_profile,
    template_b4_data_profile,
    template_b4_module_profile,
    svg_b5_data_profile,
    svg_b5_module_profile,
)
from tools.regenerate_provenance import (
    CROSS_FORMAT_CAPABILITY_REQUIREMENT,
    cross_format_capability_module_profile,
    pptx_openxml_module_profile,
    regenerate,
    xlsx_data_profile,
    xlsx_module_profile,
)

_HTML_XLSX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-xlsx + "
    "document-skills-xlsx-completion + document-skills-xlsx-advanced-authoring"
)
_HTML_TEMPLATE_B2_REQUIREMENT = (
    "Rasen html-to-editable-pptx + pptx-ecosystem-phase-bc-b2"
)
_HTML_TEMPLATE_B2_B4_REQUIREMENT = (
    _HTML_TEMPLATE_B2_REQUIREMENT + " + pptx-ecosystem-phase-bc-b4"
)
_HTML_TEMPLATE_B2_B4_B5_REQUIREMENT = (
    _HTML_TEMPLATE_B2_B4_REQUIREMENT + " + pptx-ecosystem-phase-bc-b5"
)
_HTML_SVG_B5_REQUIREMENT = (
    "Rasen html-to-editable-pptx + pptx-ecosystem-phase-bc-b5"
)
_HTML_EQUATION_B6_REQUIREMENT = (
    "Rasen html-to-editable-pptx + pptx-ecosystem-phase-bc-b6"
)
_CORE_EQUATION_B6_REQUIREMENT = (
    "Rasen document-skills-core-pptx + pptx-ecosystem-phase-bc-b6"
)
_TEMPLATE_B2_EQUATION_B6_REQUIREMENT = (
    "Rasen pptx-ecosystem-phase-bc-b2 + pptx-ecosystem-phase-bc-b6"
)
_COMBINED_TEMPLATE_B2_B5_REQUIREMENT = (
    COMBINED_PPTX_TEMPLATE_B2_REQUIREMENT + " + pptx-ecosystem-phase-bc-b5"
)
_TEMPLATE_B2_B4_REQUIREMENT = (
    "Rasen pptx-ecosystem-phase-bc-b2 + pptx-ecosystem-phase-bc-b4"
)
_FOUNDATION_REQUIREMENT = "Rasen document-skills-foundation strategy-attempt-3"
_OPENXML_REQUIREMENT = "document-skills-openxml-dotnet-enhancement"
_HTML_NUGET_XLSX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-openxml-dotnet-enhancement + "
    "document-skills-core-xlsx + document-skills-xlsx-completion"
)


def _merged_values(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


def _with_all_xlsx_requirements(base_requirement: str) -> str:
    return _compose_requirements(
        base_requirement,
        "document-skills-core-xlsx",
        "document-skills-xlsx-completion",
        "document-skills-xlsx-advanced-authoring",
    )


def _compose_requirements(*requirements: str | None) -> str:
    components: list[str] = []
    for requirement in requirements:
        if requirement is None:
            continue
        for component in requirement.removeprefix("Rasen ").split(" + "):
            if component not in components:
                components.append(component)
    return f"Rasen {' + '.join(components)}"


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
    assert core_only[2] == _CORE_EQUATION_B6_REQUIREMENT
    assert core_only[:2] == _combined_profile(
        core_pptx_module_profile(
            "src/document_skills_core/formats/pptx/create.py"
        ),
        equation_b6_module_profile(
            "src/document_skills_core/formats/pptx/create.py"
        ),
    )

    scaffold = pptx_module_profile(
        "src/document_skills_core/formats/pptx/scaffold.py"
    )
    assert scaffold is not None
    assert scaffold[2] == COMBINED_PPTX_REQUIREMENT

    public_timeout = pptx_module_profile("tests/test_html_pptx_public.py")
    assert public_timeout is not None
    assert public_timeout[2] == COMBINED_PPTX_TEMPLATE_B2_REQUIREMENT
    for path in (
        "src/document_skills_core/formats/pptx/scaffold.py",
        "tests/test_html_pptx_public.py",
    ):
        assert html_pptx_module_profile(path) is not None
        assert core_pptx_module_profile(path) is not None

    supervisor = pptx_module_profile(
        "src/document_skills_core/public_cli/supervisor.py"
    )
    assert supervisor is not None
    assert supervisor[2] == _COMBINED_TEMPLATE_B2_B5_REQUIREMENT
    assert template_b2_module_profile(
        "src/document_skills_core/public_cli/supervisor.py"
    ) is not None

    generator = pptx_module_profile("tools/regenerate_provenance.py")
    assert generator is not None
    assert generator[2] == SHARED_PROVENANCE_TEMPLATE_B2_B4_B5_B6_REQUIREMENT


def test_template_b2_profiles_are_exact_and_do_not_capture_unrelated_pptx(
    project_root,
):
    profile = pptx_module_profile(
        "src/document_skills_core/formats/pptx/template_materialize.py"
    )
    assert profile is not None
    assert profile[2] == _TEMPLATE_B2_B4_REQUIREMENT
    assert template_b2_data_profile(
        "tests/fixtures/pptx/ecosystem_bc/templates/semantic-neutral.pptx"
    ) is not None
    assert template_b4_data_profile(
        "tests/fixtures/pptx/ecosystem_bc/templates/cjk-capacity.pptx"
    ) is not None
    assert template_b2_module_profile(
        "src/document_skills_core/formats/pptx/scene_emitter.py"
    ) is None
    for path in (
        "src/document_skills_core/cli.py",
        "src/document_skills_core/formats/pptx/package.py",
        "tests/test_pptx_template_b2_hardening.py",
    ):
        assert template_b2_module_profile(path) is not None

    legacy_template_modules = {
        "src/document_skills_core/formats/pptx/template_lint.py",
        "src/document_skills_core/formats/pptx/template_sanitize.py",
        "src/document_skills_core/formats/pptx/template_sanitize_inventory.py",
    }
    for path in legacy_template_modules:
        assert template_b2_module_profile(path) is None
        assert template_b4_module_profile(path) is None
        assert pptx_module_profile(path) is None

    manifest, _digest = regenerate(project_root)
    records = {record["module"]: record for record in manifest["modules"]}
    for path in legacy_template_modules:
        assert records[path]["requirement_source"] == _FOUNDATION_REQUIREMENT

    template_create = pptx_module_profile(
        "src/document_skills_core/formats/pptx/template_create.py"
    )
    assert template_create is not None
    assert template_create[2] == PPTX_EQUATION_B6_REQUIREMENT


def test_template_b4_profiles_are_exact_and_bounded():
    for path in (
        "src/document_skills_core/formats/pptx/template_content_analysis.py",
        "src/document_skills_core/formats/pptx/template_content_fonts.py",
        "src/document_skills_core/formats/pptx/template_content_metrics.py",
        "tests/test_pptx_template_b4.py",
        "tests/test_pptx_template_b4_fonts.py",
        "tests/test_pptx_template_b4_hardening.py",
    ):
        profile = pptx_module_profile(path)
        assert profile is not None
        assert profile[2] == PPTX_TEMPLATE_B4_REQUIREMENT
        assert template_b4_module_profile(path) is not None
        assert "tests/test_pptx_template_b4.py" in profile[1]

    assert template_b4_module_profile(
        "src/document_skills_core/formats/pptx/scene_emitter.py"
    ) is None
    assert template_b4_data_profile(
        "tests/fixtures/pptx/ecosystem_bc/templates/semantic-neutral.pptx"
    ) is None


def test_svg_b5_profiles_are_exact_and_bounded():
    for path in (
        "src/document_skills_core/core/io/directory_promotion.py",
        "src/document_skills_core/formats/pptx/scene_export.py",
        "src/document_skills_core/formats/pptx/scene_export_leaf.py",
        "src/document_skills_core/formats/pptx/scene_export_support.py",
        "src/document_skills_core/formats/pptx/svg_item_projection.py",
        "src/document_skills_core/formats/pptx/svg_parser.py",
        "tests/test_pptx_svg_public.py",
        "tools/capture_pptx_powerpoint_evidence.py",
        "tools/prepare_pptx_svg_roundtrip.py",
    ):
        profile = pptx_module_profile(path)
        assert profile is not None
        assert profile[2] == PPTX_SVG_B5_REQUIREMENT
        assert svg_b5_module_profile(path) is not None
        assert "tests/test_pptx_svg_public.py" in profile[1]

    scene_emitter = pptx_module_profile(
        "src/document_skills_core/formats/pptx/scene_emitter.py"
    )
    assert scene_emitter is not None
    assert scene_emitter[2] == _HTML_SVG_B5_REQUIREMENT
    assert svg_b5_data_profile(
        "tests/fixtures/pptx/ecosystem_bc/expected/visual/"
        "b5-powerpoint-consumer.json"
    ) is not None
    assert svg_b5_data_profile(
        "tests/fixtures/pptx/ecosystem_bc/templates/semantic-neutral.pptx"
    ) is None


def test_equation_b6_profiles_match_the_exact_release_inventory(project_root):
    expected_modules = {
        "src/document_skills_core/formats/pptx/constants.py",
        "src/document_skills_core/formats/pptx/contracts.py",
        "src/document_skills_core/formats/pptx/create.py",
        "src/document_skills_core/formats/pptx/deep_graph_validation.py",
        "src/document_skills_core/formats/pptx/edit_contracts.py",
        "src/document_skills_core/formats/pptx/equation_ast.py",
        "src/document_skills_core/formats/pptx/equation_contracts.py",
        "src/document_skills_core/formats/pptx/equation_latex.py",
        "src/document_skills_core/formats/pptx/equation_omml.py",
        "src/document_skills_core/formats/pptx/equation_omml_emit.py",
        "src/document_skills_core/formats/pptx/equation_omml_read.py",
        "src/document_skills_core/formats/pptx/equation_omml_tags.py",
        "src/document_skills_core/formats/pptx/mapping.py",
        "src/document_skills_core/formats/pptx/object_contracts.py",
        "src/document_skills_core/formats/pptx/object_edit.py",
        "src/document_skills_core/formats/pptx/object_validation.py",
        "src/document_skills_core/formats/pptx/object_xml.py",
        "src/document_skills_core/formats/pptx/slide_graph.py",
        "src/document_skills_core/formats/pptx/template_create.py",
        "src/document_skills_core/formats/pptx/typed_validation.py",
        "tests/fixtures/pptx/ecosystem_bc/generate.py",
        "tests/test_html_provenance.py",
        "tests/test_pptx_deep_validation.py",
        "tests/test_pptx_equation.py",
        "tests/test_pptx_equation_contracts.py",
        "tests/test_pptx_equation_libreoffice.py",
        "tests/test_pptx_equation_powerpoint.py",
        "tests/test_pptx_equation_public.py",
        "tests/test_strategy2.py",
        "tests/test_strategy3.py",
        "tests/test_supply_chain.py",
        "tools/html_pptx_provenance.py",
        "tools/provenance_records.py",
        "tools/regenerate_provenance.py",
    }
    expected_data = {
        "provenance/reviews/document-skills-0.5.3-pptx-b5-merge-review.md",
        "provenance/runtime-source-allowlist.json",
        "skills/document-pptx/SKILL.md",
        "skills/document-pptx/references/editable-equations.md",
        "skills/document-pptx/references/typed-create.md",
        "skills/document-pptx/references/typed-edit.md",
        "tests/fixtures/manifest.json",
        "tests/fixtures/pptx/ecosystem_bc/README.md",
        "tests/fixtures/pptx/ecosystem_bc/equations/supported.json",
        "tests/fixtures/pptx/ecosystem_bc/equations/supported.json.manifest.json",
        "tests/fixtures/pptx/ecosystem_bc/equations/unsupported.json",
        "tests/fixtures/pptx/ecosystem_bc/equations/unsupported.json.manifest.json",
    }

    manifest, _digest = regenerate(project_root)
    module_paths = {record["module"] for record in manifest["modules"]}
    data_paths = {
        record["artifact"] for record in manifest["data_classifications"]
    }
    assert {
        path for path in module_paths if equation_b6_module_profile(path)
    } == expected_modules
    assert {
        path for path in data_paths if equation_b6_data_profile(path)
    } == expected_data

    records = {record["module"]: record for record in manifest["modules"]}
    assert records[
        "src/document_skills_core/formats/pptx/equation_ast.py"
    ]["requirement_source"] == PPTX_EQUATION_B6_REQUIREMENT
    assert records[
        "src/document_skills_core/formats/pptx/create.py"
    ]["requirement_source"] == _CORE_EQUATION_B6_REQUIREMENT

    data_records = {
        record["artifact"]: record for record in manifest["data_classifications"]
    }
    assert data_records[
        "skills/document-pptx/references/editable-equations.md"
    ]["requirement_source"] == _HTML_EQUATION_B6_REQUIREMENT
    assert data_records[
        "tests/fixtures/pptx/ecosystem_bc/equations/supported.json"
    ]["requirement_source"] == _TEMPLATE_B2_EQUATION_B6_REQUIREMENT
    assert data_records[
        "provenance/reviews/document-skills-0.5.3-pptx-b5-merge-review.md"
    ]["requirement_source"] == PPTX_EQUATION_B6_REQUIREMENT

    assert equation_b6_module_profile(
        "src/document_skills_core/formats/pptx/scene_export.py"
    ) is None
    assert equation_b6_data_profile(
        "skills/document-pptx/references/svg-and-scene.md"
    ) is None


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
        cross_format_profile = cross_format_capability_module_profile(
            record["module"]
        )
        pptx_openxml_profile = pptx_openxml_module_profile(record["module"])
        xlsx_profile = xlsx_module_profile(record["module"])
        expected_profile = _combined_profile(
            cross_format_profile,
            (pptx_profile[0], pptx_profile[1]),
            pptx_openxml_profile,
            xlsx_profile,
        )
        assert expected_profile is not None
        base_requirement = _compose_requirements(
            _FOUNDATION_REQUIREMENT if pptx_openxml_profile else None,
            CROSS_FORMAT_CAPABILITY_REQUIREMENT if cross_format_profile else None,
            pptx_profile[2],
            _OPENXML_REQUIREMENT if pptx_openxml_profile else None,
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
        html_profile = html_pptx_data_profile(record["artifact"])
        if html_profile is None:
            continue
        relevant_data.append(record["artifact"])
        template_profile = template_b2_data_profile(record["artifact"])
        template_b4_profile = template_b4_data_profile(record["artifact"])
        svg_b5_profile = svg_b5_data_profile(record["artifact"])
        equation_b6_profile = equation_b6_data_profile(record["artifact"])
        xlsx_profile = xlsx_data_profile(record["artifact"])
        expected_profile = _combined_profile(
            html_profile,
            template_profile,
            template_b4_profile,
            svg_b5_profile,
            equation_b6_profile,
            xlsx_profile,
        )
        assert expected_profile is not None
        if xlsx_profile:
            expected_requirement = (
                _HTML_XLSX_REQUIREMENT
                if record["artifact"] == "README.md"
                else _HTML_NUGET_XLSX_REQUIREMENT
            )
        else:
            expected_requirement = _compose_requirements(
                HTML_PPTX_REQUIREMENT,
                PPTX_TEMPLATE_B2_REQUIREMENT if template_profile else None,
                PPTX_TEMPLATE_B4_REQUIREMENT if template_b4_profile else None,
                PPTX_SVG_B5_REQUIREMENT if svg_b5_profile else None,
                PPTX_EQUATION_B6_REQUIREMENT if equation_b6_profile else None,
            )
        assert record["requirement_source"] == expected_requirement
        assert record["modifications"] == expected_profile[0]
        assert record["artifact_tests"] == expected_profile[1]

    assert "runtime/node/html_scene_capture.mjs" in relevant_modules
    assert "src/document_skills_core/formats/pptx/scene_emitter.py" in relevant_modules
    assert "tests/fixtures/recipes/html_pptx_fixtures.py" in relevant_modules
    assert "tests/test_html_provenance.py" in relevant_modules
    assert "package-lock.json" in relevant_data
    assert "tests/fixtures/html-native.expected.pptx" in relevant_data

    b2_data = next(
        record
        for record in manifest["data_classifications"]
        if record["artifact"]
        == "tests/fixtures/pptx/ecosystem_bc/templates/semantic-neutral.pptx"
    )
    b2_profile = template_b2_data_profile(b2_data["artifact"])
    assert b2_profile is not None
    assert b2_data["requirement_source"] == PPTX_TEMPLATE_B2_REQUIREMENT
    assert b2_data["modifications"] == b2_profile[0]
    assert b2_data["artifact_tests"] == b2_profile[1]
