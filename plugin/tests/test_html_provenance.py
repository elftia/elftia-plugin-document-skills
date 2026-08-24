"""Semantic provenance coverage for HTML-to-editable-PPTX release bytes."""

import json

from tools.html_pptx_provenance import (
    HTML_PPTX_REQUIREMENT,
    SHARED_PROVENANCE_REQUIREMENT,
    html_pptx_data_profile,
    html_pptx_module_profile,
)


_XLSX_MODIFICATIONS = (
    "Shared Core XLSX provider execution, managed CLI supervision, and exact "
    "supply-chain policy for bounded OpenXML validation and LibreOffice rendering."
)
_NUGET_MODIFICATIONS = (
    "Exact NuGet dependency lock, allowlist, license, notice, and SBOM evidence "
    "for the bounded OpenXML helper used by Core XLSX schema validation."
)
_HTML_SHARED_MODIFICATIONS = (
    "Additive public operation, provider dispatch, managed runtime, supply-chain, "
    "and exact provenance support for HTML-to-editable-PPTX."
)
_HTML_TEST_MODIFICATIONS = (
    "Regression and adversarial coverage for the bounded "
    "HTML-to-editable-PPTX capability."
)
_HTML_REGEN_MODIFICATIONS = (
    "Shared exact provenance generation for HTML-to-editable-PPTX and independent "
    "consumer-gate Strategy-4 release evidence."
)
_HTML_DATA_MODIFICATIONS = (
    "Exact playwright-core dependency lock, adoption, license, notice, and SBOM "
    "evidence for contained browser capture."
)
_HTML_SHARED_XLSX_TESTS = [
    "tests/test_pptx_contracts.py",
    "tests/test_html_pptx_public.py",
    "tests/test_runtime.py",
    "tests/test_supply_chain.py",
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_operations.py",
    "tests/test_xlsx_provider_qa.py",
    "tests/test_xlsx_public.py",
    "tests/test_xlsx_recalculation.py",
    "tests/test_dotnet_provider.py",
    "tests/test_dotnet_xlsx_schema_real.py",
    "tests/test_libreoffice_provider.py",
    "tests/test_libreoffice_hard_quota.py",
    "tests/test_provider_crash_isolation.py",
    "tests/test_process_executable_identity.py",
    "tests/test_html_provenance.py",
    "tests/test_input_snapshot_security.py",
    "tests/test_safety.py",
    "tests/test_strategy2.py",
    "tests/test_strategy3.py",
    "tests/test_structure.py",
]
_HTML_TEST_XLSX_TESTS = [
    "tests/test_html_provenance.py",
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_operations.py",
    "tests/test_xlsx_provider_qa.py",
    "tests/test_xlsx_public.py",
    "tests/test_xlsx_recalculation.py",
    "tests/test_dotnet_provider.py",
    "tests/test_dotnet_xlsx_schema_real.py",
    "tests/test_libreoffice_provider.py",
    "tests/test_libreoffice_hard_quota.py",
    "tests/test_provider_crash_isolation.py",
    "tests/test_process_executable_identity.py",
    "tests/test_input_snapshot_security.py",
    "tests/test_runtime.py",
    "tests/test_safety.py",
    "tests/test_strategy2.py",
    "tests/test_strategy3.py",
    "tests/test_structure.py",
    "tests/test_supply_chain.py",
]
_HTML_REGEN_XLSX_TESTS = [
    "tests/test_html_provenance.py",
    "tests/test_html_pptx_public.py",
    "tests/test_strategy3.py",
    "tests/test_supply_chain.py",
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_operations.py",
    "tests/test_xlsx_provider_qa.py",
    "tests/test_xlsx_public.py",
    "tests/test_xlsx_recalculation.py",
    "tests/test_dotnet_provider.py",
    "tests/test_dotnet_xlsx_schema_real.py",
    "tests/test_libreoffice_provider.py",
    "tests/test_libreoffice_hard_quota.py",
    "tests/test_provider_crash_isolation.py",
    "tests/test_process_executable_identity.py",
    "tests/test_input_snapshot_security.py",
    "tests/test_runtime.py",
    "tests/test_safety.py",
    "tests/test_strategy2.py",
    "tests/test_structure.py",
]
_HTML_DATA_XLSX_TESTS = [
    "tests/test_runtime.py",
    "tests/test_supply_chain.py",
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_operations.py",
    "tests/test_xlsx_provider_qa.py",
    "tests/test_xlsx_public.py",
    "tests/test_xlsx_recalculation.py",
    "tests/test_dotnet_provider.py",
    "tests/test_dotnet_xlsx_schema_real.py",
    "tests/test_libreoffice_provider.py",
    "tests/test_libreoffice_hard_quota.py",
    "tests/test_provider_crash_isolation.py",
    "tests/test_process_executable_identity.py",
    "tests/test_html_provenance.py",
    "tests/test_input_snapshot_security.py",
    "tests/test_safety.py",
    "tests/test_strategy2.py",
    "tests/test_strategy3.py",
    "tests/test_structure.py",
]
_COMPOSED_MODULE_EXPECTATIONS = {
    path: (
        "Rasen html-to-editable-pptx + document-skills-core-xlsx",
        f"{_HTML_SHARED_MODIFICATIONS} {_XLSX_MODIFICATIONS}",
        _HTML_SHARED_XLSX_TESTS,
    )
    for path in {
        "src/document_skills_core/providers/defaults.py",
        "src/document_skills_core/public_cli/supervisor.py",
        "tests/test_runtime.py",
        "tests/test_supply_chain.py",
        "tools/provenance_records.py",
        "tools/supply_chain.py",
    }
}
_COMPOSED_MODULE_EXPECTATIONS["tests/test_html_provenance.py"] = (
    "Rasen html-to-editable-pptx + document-skills-core-xlsx",
    f"{_HTML_TEST_MODIFICATIONS} {_XLSX_MODIFICATIONS}",
    _HTML_TEST_XLSX_TESTS,
)
_COMPOSED_MODULE_EXPECTATIONS["tools/regenerate_provenance.py"] = (
    "Rasen html-to-editable-pptx + "
    "document-skills-consumer-gates-and-truthful-contracts + "
    "document-skills-core-xlsx",
    f"{_HTML_REGEN_MODIFICATIONS} {_XLSX_MODIFICATIONS}",
    _HTML_REGEN_XLSX_TESTS,
)
_COMPOSED_DATA_EXPECTATIONS = {
    path: (
        "Rasen html-to-editable-pptx + document-skills-core-xlsx",
        f"{_HTML_DATA_MODIFICATIONS} {_NUGET_MODIFICATIONS}",
        _HTML_DATA_XLSX_TESTS,
    )
    for path in {
        "THIRD_PARTY_NOTICES.md",
        "provenance/dependency-allowlist.json",
        "provenance/dependency-licenses.json",
        "sbom.cdx.json",
    }
}


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
        expected = _COMPOSED_MODULE_EXPECTATIONS.get(record["module"])
        if expected:
            expected_requirement, expected_modifications, expected_tests = expected
        else:
            expected_requirement = (
                SHARED_PROVENANCE_REQUIREMENT
                if record["module"] == "tools/regenerate_provenance.py"
                else HTML_PPTX_REQUIREMENT
            )
            expected_modifications, expected_tests = profile
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
        expected = _COMPOSED_DATA_EXPECTATIONS.get(record["artifact"])
        if expected:
            expected_requirement, expected_modifications, expected_tests = expected
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
