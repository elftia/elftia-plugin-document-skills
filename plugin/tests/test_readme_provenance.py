"""Exact provenance coverage for the layered README hierarchy."""

from tools.regenerate_provenance import (
    README_SYSTEM_REQUIREMENT,
    readme_system_profile,
    regenerate,
)


README_DATA = {
    "README.md",
    "consumer_validation/README.md",
    "provenance/README.md",
    "schemas/README.md",
    "skills/README.md",
    "src/document_skills_core/README.md",
    "src/document_skills_core/formats/docx/README.md",
    "src/document_skills_core/formats/pdf/README.md",
    "src/document_skills_core/formats/pptx/README.md",
    "src/document_skills_core/formats/xlsx/README.md",
    "tests/README.md",
}
README_MODULES = {
    "runtime/node/README.md",
    "src/document_skills_core/providers/README.md",
    "tests/test_readme_provenance.py",
    "tools/README.md",
}


def test_readme_profile_is_exact_and_excludes_unrelated_fixture_readme():
    for path in README_DATA | README_MODULES:
        assert readme_system_profile(path) is not None
    assert readme_system_profile("tests/fixtures/pptx/ecosystem_bc/README.md") is None


def test_generated_records_bind_new_readmes_to_the_readme_change(project_root):
    manifest, _digest = regenerate(project_root)
    records = {
        record["artifact"]: record
        for record in manifest["data_classifications"]
        if record["artifact"] in README_DATA
    }
    records.update({
        record["module"]: record
        for record in manifest["modules"]
        if record["module"] in README_MODULES
    })

    assert records.keys() == README_DATA | README_MODULES
    for path, record in records.items():
        assert (
            README_SYSTEM_REQUIREMENT.removeprefix("Rasen ")
            in record["requirement_source"]
        )
        assert "README navigation" in record["modifications"]
        assert "tests/test_readme_provenance.py" in record["artifact_tests"]
        assert (project_root / path).is_file()

    root_readme = records["README.md"]
    for historical_requirement in (
        "html-to-editable-pptx",
        "pptx-ecosystem-phase-bc-b7",
        "document-skills-core-xlsx",
        "document-skills-xlsx-completion",
        "document-skills-xlsx-advanced-authoring",
    ):
        assert historical_requirement in root_readme["requirement_source"]
