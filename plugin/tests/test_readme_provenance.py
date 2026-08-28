"""Exact provenance coverage for the layered README hierarchy."""

import hashlib

from tools.provenance_records import (
    README_SYSTEM_REVIEW_ARTIFACT,
    validate_metadata_exclusion,
)
from tools.regenerate_provenance import (
    README_SYSTEM_REQUIREMENT,
    readme_system_review_metadata_profile,
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
README_REVIEW = "provenance/reviews/document-skills-readme-system-review.md"
PPTX_B7_REVIEW = (
    "provenance/reviews/document-skills-0.5.3-pptx-b7-merge-review.md"
)


def test_readme_profile_is_exact_and_excludes_unrelated_fixture_readme():
    for path in README_DATA | README_MODULES:
        assert readme_system_profile(path) is not None
    assert readme_system_profile("tests/fixtures/pptx/ecosystem_bc/README.md") is None


def test_readme_review_metadata_profile_is_exact():
    assert README_SYSTEM_REVIEW_ARTIFACT == README_REVIEW
    assert readme_system_review_metadata_profile(README_REVIEW) is True
    assert readme_system_review_metadata_profile(PPTX_B7_REVIEW) is False


def test_readme_review_is_metadata_and_pptx_b7_history_remains_hash_pinned(
    project_root,
):
    manifest, _digest = regenerate(project_root)
    metadata_records = {
        record["artifact"]: record
        for record in manifest["metadata_exclusions"]
    }
    data_records = {
        record["artifact"]: record
        for record in manifest["data_classifications"]
    }

    assert README_REVIEW in metadata_records
    assert README_REVIEW not in data_records
    assert PPTX_B7_REVIEW not in metadata_records
    assert data_records[PPTX_B7_REVIEW]["sha256"] == hashlib.sha256(
        (project_root / PPTX_B7_REVIEW).read_bytes()
    ).hexdigest()
    readme_review_record = metadata_records[README_REVIEW]
    validate_metadata_exclusion(
        project_root,
        readme_review_record,
        {readme_review_record["reviewer"]},
    )


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
