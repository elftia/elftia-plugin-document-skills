"""Determinism, registry, oracle, and runtime checks for DOCX fixtures."""

import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.docx.inspect import inspect_docx
from document_skills_core.formats.docx.package import OpcPackage
from document_skills_core.formats.docx.read import read_docx
from tools.audit import audit_fixtures
from consumer_validation.harness import qualify_artifact

_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_READ_ARGUMENTS = {
    "include_headers_footers": True,
    "max_paragraphs": 5_000,
    "max_tables": 500,
    "max_table_rows": 5_000,
    "max_text_chars": 250_000,
}
_INSPECT_ARGUMENTS = {
    "include_hashes": True,
    "max_parts": 2_000,
    "max_relationships": 5_000,
}


def _fixture_root(project_root: Path) -> Path:
    return project_root / "tests" / "fixtures"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _execute(
    project_root: Path,
    request: dict[str, object],
) -> dict[str, object]:
    return execute_request(request, project_root, SchemaCatalog(project_root))


def _request(
    operation: str,
    source: Path,
    output: Path,
    arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": operation,
        "input": str(source),
        "output": str(output),
        "arguments": arguments,
    }


def test_recipe_nested_uv_is_detached_from_outer_environment(project_root: Path) -> None:
    recipe = _fixture_root(project_root) / "recipes" / "docx_fixtures.py"
    source = recipe.read_text(encoding="utf-8")
    uv_environment = source.index('environment.pop("UV_PROJECT_ENVIRONMENT", None)')
    virtual_environment = source.index('environment.pop("VIRTUAL_ENV", None)')
    nested_run = source.index("process = subprocess.run(", virtual_environment)

    assert uv_environment < nested_run
    assert virtual_environment < nested_run


def test_recipe_regenerates_twice_to_checked_in_bytes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    recipe = _fixture_root(project_root) / "recipes" / "docx_fixtures.py"
    generated_roots = [tmp_path / "first", tmp_path / "second"]
    for destination in generated_roots:
        subprocess.run(
            [
                sys.executable,
                str(recipe),
                "--output",
                str(destination),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=False,
            shell=False,
            timeout=60,
        )

    first = {
        path.name: path.read_bytes()
        for path in generated_roots[0].iterdir()
        if path.is_file()
    }
    second = {
        path.name: path.read_bytes()
        for path in generated_roots[1].iterdir()
        if path.is_file()
    }
    assert first == second

    checked = _fixture_root(project_root)
    for name, payload in first.items():
        if name != "manifest.json":
            assert (checked / name).read_bytes() == payload

    generated_manifest = _load_json(generated_roots[0] / "manifest.json")
    checked_manifest = _load_json(checked / "manifest.json")
    checked_docx = [
        record
        for record in checked_manifest["fixtures"]
        if record["path"].startswith("docx-")
    ]
    assert generated_manifest["fixtures"] == checked_docx


def test_zip_order_timestamp_and_permissions_are_fixed(project_root: Path) -> None:
    fixture_root = _fixture_root(project_root)
    for path in sorted(fixture_root.glob("docx-*.docx")):
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names), path.name
        for info in infos:
            assert info.date_time == _FIXED_TIME, (path.name, info.filename)
            assert info.create_system == 3, (path.name, info.filename)
            mode = info.external_attr >> 16
            if path.name == "docx-malicious-symlink.docx" and info.filename == "word/link":
                assert stat.S_ISLNK(mode)
            else:
                assert stat.S_ISREG(mode)
                assert stat.S_IMODE(mode) == 0o644


def test_manifest_has_exact_hashes_and_original_recipe_metadata(
    project_root: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    manifest = _load_json(fixture_root / "manifest.json")
    registered = {record["path"]: record for record in manifest["fixtures"]}
    actual = {
        path.relative_to(fixture_root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
        and path.name not in {"manifest.json", "POLICY.md"}
        and "recipes" not in path.parts
    }
    assert set(registered) == actual
    assert audit_fixtures(project_root)["fixture_count"] == len(registered)

    required = {
        "path",
        "format",
        "purpose",
        "origin",
        "authorship",
        "recipe",
        "recipe_dependencies",
        "license",
        "redistribution_allowed",
        "sha256",
        "security_classification",
    }
    for name, record in registered.items():
        assert hashlib.sha256((fixture_root / name).read_bytes()).hexdigest() == record["sha256"]
        if name.startswith("docx-"):
            assert required.issubset(record)
            assert record["origin"] == "generated"
            assert record["authorship"] == "original-elftia"
            assert record["license"] == "GPL-3.0"
            assert record["redistribution_allowed"] is True
            assert (project_root / record["recipe"]).is_file()
            assert all(
                (project_root / dependency).is_file()
                for dependency in record["recipe_dependencies"]
            )


def test_word_positive_and_negative_fixture_names_are_truthful(project_root: Path) -> None:
    fixture_root = _fixture_root(project_root)
    positive = fixture_root / "docx-public-bounded-word16-accepted.docx"
    negative = fixture_root / "docx-rich-word16-rejected.docx"
    prior_rich = fixture_root / "docx-rich.docx"

    assert hashlib.sha256(negative.read_bytes()).hexdigest() == (
        "788598c8c909a704d301563a6df68522df3c5a76f5b63015d06d17bbdbb33b5d"
    )
    assert negative.read_bytes() == prior_rich.read_bytes()
    assert positive.read_bytes() != negative.read_bytes()
    report = qualify_artifact(
        format_id="docx",
        operation="docx.create",
        artifact=positive,
        expectations={"text": ["Bounded public DOCX", "Public frozen-uv"]},
        office_policy="off",
    )
    assert report["portable"]["outcome"] == "pass"


@pytest.mark.parametrize("mutation", ["unregistered", "stale-hash"])
def test_registry_rejects_unregistered_and_stale_fixtures(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    copied = tmp_path / mutation / "tests" / "fixtures"
    shutil.copytree(_fixture_root(project_root), copied)
    if mutation == "unregistered":
        (copied / "unregistered.docx").write_bytes(b"PK\x03\x04unregistered")
    else:
        target = copied / "docx-rich.docx"
        target.write_bytes(target.read_bytes() + b"stale")
    with pytest.raises(AssertionError):
        audit_fixtures(tmp_path / mutation)


def test_rich_read_and_inspection_match_complete_oracles(project_root: Path) -> None:
    fixture_root = _fixture_root(project_root)
    rich = fixture_root / "docx-rich.docx"
    oracle = _load_json(fixture_root / "docx-rich.expected.json")
    structured, warnings = read_docx(rich, _READ_ARGUMENTS)
    inspection, inspection_warnings = inspect_docx(rich, _INSPECT_ARGUMENTS)
    assert warnings == []
    assert inspection_warnings == []
    assert structured == oracle["read"]
    assert inspection == oracle["inspection"]

    body = next(
        story
        for story in structured["document"]["stories"]
        if story["kind"] == "body"
    )
    texts = [paragraph["text"] for paragraph in body["paragraphs"]]
    assert "Core DOCX" in texts
    assert "List item" in texts
    assert "Internal reference" in texts
    assert "Normal placeholder {normal}" in texts
    template = next(item for item in body["paragraphs"] if item["text"].startswith("Template "))
    assert template["runs"][0]["bold"] is True
    assert template["runs"][1]["italic"] is True
    assert template["runs"][-1]["italic"] is True
    assert len(body["tables"]) == 1
    assert len(structured["document"]["sections"]) == 2
    assert structured["document"]["images"][0]["alt_text"] == "Elftia pixel"


def test_fixture_driven_template_replace_and_preservation(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    cases = _load_json(fixture_root / "docx-cases.expected.json")
    source = fixture_root / "docx-preservation.docx"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    replacement = cases["rich"]["replacement"]
    replaced_path = tmp_path / "replaced.docx"
    replaced = _execute(
        project_root,
        _request(
            "docx.edit.replace-text",
            source,
            replaced_path,
            {
                "replacements": [
                    {
                        "search": replacement["search"],
                        "replace": "VALUE",
                        "expected_matches": replacement["expected_matches"],
                    }
                ]
            },
        ),
    )
    assert replaced["status"] == "success", replaced
    diagnostics = replaced["diagnostics"]["operation_result"]["replacement"]
    assert diagnostics["counts_by_story"] == replacement["counts_by_story"]
    assert diagnostics["formatting_anchor"] == replacement["formatting_anchor"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha

    before = OpcPackage.open(source)
    after = OpcPackage.open(replaced_path)
    for part in cases["preservation"]["required_untouched_parts"]:
        assert after.part_hashes[part] == before.part_hashes[part]
    preservation = _load_json(fixture_root / "docx-preservation.expected.json")
    assert before.part_hashes == preservation["part_hashes"]
    assert before.unknown_parts == preservation["unknown_parts"]

    rich = fixture_root / "docx-rich.docx"
    templated_path = tmp_path / "templated.docx"
    templated = _execute(
        project_root,
        _request(
            "docx.template.apply",
            rich,
            templated_path,
            {
                "variables": {
                    "customer": {"name": "Alice"},
                    "normal": "Ready",
                    "region": "North",
                    "unused": "warning",
                }
            },
        ),
    )
    assert templated["status"] == "success", json.dumps(
        templated,
        ensure_ascii=False,
        indent=2,
    )
    assert templated["provider_chain"] == ["core-node"]
    template_result = templated["diagnostics"]["operation_result"]["template"]
    assert template_result["used"] == cases["rich"]["template"]["tokens"]
    assert template_result["unused"] == cases["rich"]["template"]["unused_case"]


def test_missing_overlap_and_protected_cases_publish_no_output(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    rich = fixture_root / "docx-rich.docx"
    missing_output = tmp_path / "missing.docx"
    missing = _execute(
        project_root,
        _request(
            "docx.template.apply",
            rich,
            missing_output,
            {"variables": {"customer": {"name": "Alice"}, "normal": "Ready"}},
        ),
    )
    assert missing["status"] == "failed"
    assert not missing_output.exists()

    overlap_output = tmp_path / "overlap.docx"
    overlap = _execute(
        project_root,
        _request(
            "docx.edit.replace-text",
            rich,
            overlap_output,
            {
                "replacements": [
                    {"search": "AAA", "replace": "first"},
                    {"search": "AA", "replace": "second"},
                ]
            },
        ),
    )
    assert overlap["status"] == "invalid_request"
    assert not overlap_output.exists()

    protected_source = fixture_root / "docx-revision-comments.docx"
    protected_output = tmp_path / "protected.docx"
    protected = _execute(
        project_root,
        _request(
            "docx.edit.replace-text",
            protected_source,
            protected_output,
            {"replacements": [{"search": "revision-only", "replace": "changed"}]},
        ),
    )
    assert protected["status"] == "enhancement_required"
    assert protected["errors"][0]["code"] == ErrorCode.ENHANCEMENT_REQUIRED
    assert not protected_output.exists()


def test_security_matrix_distinguishes_container_rejection_from_inert_inventory(
    project_root: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    cases = _load_json(fixture_root / "docx-cases.expected.json")
    for name in cases["security"]["container_reject"]:
        with pytest.raises(DocumentSkillsError) as captured:
            OpcPackage.open(
                fixture_root / name,
                allow_dangerous_inventory=True,
            )
        assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE

    active_case = cases["security"]["inert_inventory"]
    active_path = fixture_root / active_case["fixture"]
    with pytest.raises(DocumentSkillsError) as rejected:
        OpcPackage.open(active_path)
    assert rejected.value.code == ErrorCode.ARCHIVE_UNSAFE

    inventory, warnings = inspect_docx(active_path, _INSPECT_ARGUMENTS)
    positive = sorted(
        category
        for category, count in inventory["dangerous_content"]["counts"].items()
        if count > 0
    )
    assert positive == sorted(active_case["expected_positive_categories"])
    assert inventory["dangerous_content"]["dangerous"] is True
    assert inventory["mutation_authorized"] is active_case["mutation_authorized"]
    assert warnings[0]["code"] == "DS_DANGEROUS_CONTENT_INVENTORIED"


def test_revision_field_and_comment_fixture_is_readable_but_protected(
    project_root: Path,
) -> None:
    fixture_root = _fixture_root(project_root)
    cases = _load_json(fixture_root / "docx-cases.expected.json")
    source = fixture_root / "docx-revision-comments.docx"
    inspection, warnings = inspect_docx(source, _INSPECT_ARGUMENTS)
    structured, read_warnings = read_docx(source, _READ_ARGUMENTS)
    assert warnings == []
    assert read_warnings == []
    assert inspection["word_features"] == cases["protected"]["features"]
    assert any(
        paragraph["protected_text_present"]
        for story in structured["document"]["stories"]
        for paragraph in story["paragraphs"]
    )
