import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools.audit import (
    audit_fixtures,
    audit_provenance,
    audit_sbom,
    release_inventory,
    run_audits,
)
from tools.audit_execution import _audit_dependency_manifests
from tools.audit_provenance import provenance_modules
from tools.provenance_records import (
    CURRENT_REVIEW_ARTIFACT,
    SELF_REFERENTIAL_METADATA_ALLOWLIST,
    mapping_digest,
    validate_metadata_exclusion,
)
from tools.regenerate_provenance import regenerate
from tools.supply_chain import build_sbom, canonical_json
from tests.support.provenance_review_fixture import bind_test_review


def test_fixture_recipe_and_manifest_are_deterministic(project_root):
    fixture = project_root / "tests" / "fixtures" / "foundation-probe.json"
    recipe = project_root / "tests" / "fixtures" / "recipes" / "foundation_probe.py"
    generated = subprocess.run(
        [sys.executable, str(recipe)],
        check=True,
        capture_output=True,
        text=False,
        shell=False,
    ).stdout
    assert generated == fixture.read_bytes()
    manifest = json.loads(
        (project_root / "tests" / "fixtures" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit_fixtures(project_root)["fixture_count"] == len(
        manifest["fixtures"]
    )


def test_provenance_covers_implementation_modules(project_root, tmp_path):
    root = _copy_audit_project(project_root, tmp_path / "reviewed")
    bind_test_review(root)
    report = audit_provenance(root)
    assert report["module_count"] > 0
    assert (
        report["record_count"] + report["exclusion_count"]
        == len(provenance_modules(root))
    )
    assert report["release_file_count"] == len(release_inventory(root))
    assert (
        report["record_count"]
        + report["exclusion_count"]
        + report["data_classification_count"]
        + report["metadata_exclusion_count"]
        == report["release_file_count"]
    )
    assert len(report["mapping_sha256"]) == 64


def _semantic_mapping_fixture():
    reviewer = "independent-reviewer"
    evidence = ["provenance/reviews/review.md"]
    return (
        [
            {
                "module": "src/example.py",
                "sha256": "1" * 64,
                "source_class": "original",
                "clean_room": True,
                "implementation_source": "Original project code",
                "requirement_source": "Change requirement",
                "modifications": "Semantic implementation details.",
                "third_party_files": [],
                "license": "GPL-3.0",
                "artifact_tests": ["tests/test_example.py"],
                "reviewer": reviewer,
                "review_evidence": evidence,
            }
        ],
        [
            {
                "artifact": "runtime/reference.ps1",
                "sha256": "2" * 64,
                "classification": "non-executable-data",
                "reason": "Reviewed inert reference data.",
                "reviewer": reviewer,
                "review_evidence": evidence,
            }
        ],
        [
            {
                "artifact": "assets/reference.json",
                "sha256": "3" * 64,
                "classification": "reviewed-data",
                "reason": "Reviewed release data classification.",
                "reviewer": reviewer,
                "review_evidence": evidence,
            }
        ],
        [
            {
                "artifact": "provenance/modules.json",
                "classification": "self-referential-audit-metadata",
                "reason": "Reviewed circular audit metadata exclusion.",
                "reviewer": reviewer,
                "review_evidence": evidence,
            }
        ],
    )


def test_mapping_digest_binds_every_semantic_record_field():
    fixture = _semantic_mapping_fixture()
    baseline = mapping_digest(*fixture)
    for collection_index, records in enumerate(fixture):
        for field, value in records[0].items():
            if field in {"reviewer", "review_evidence"}:
                continue
            mutated = copy.deepcopy(fixture)
            if isinstance(value, bool):
                replacement = not value
            elif isinstance(value, list):
                replacement = [*value, "semantic-drift"]
            else:
                replacement = f"{value}-semantic-drift"
            mutated[collection_index][0][field] = replacement
            assert mapping_digest(*mutated) != baseline, (
                collection_index,
                field,
            )


def test_mapping_digest_excludes_review_self_reference_fields():
    fixture = _semantic_mapping_fixture()
    mutated = copy.deepcopy(fixture)
    for records in mutated:
        records[0]["reviewer"] = "replacement-reviewer"
        records[0]["review_evidence"] = [
            "provenance/reviews/replacement-review.md"
        ]
    assert mapping_digest(*mutated) == mapping_digest(*fixture)


@pytest.mark.parametrize(
    "report_name",
    [
        "core-docx-review-cycle-round-1.md",
        "core-pptx-review-cycle-round-1.md",
        "document-skills-core-xlsx-completion-review-cycle-round-1.md",
        "document-skills-0.5.3-pptx-b5-merge-review.md",
        "document-skills-0.5.3-pptx-b6-merge-review.md",
    ],
)
def test_historical_review_reports_are_hash_pinned_reviewed_data(
    project_root, tmp_path, report_name
):
    root = _copy_audit_project(
        project_root,
        tmp_path / f"historical-review-{report_name}",
    )
    bind_test_review(root)
    report = audit_provenance(root)
    assert report["review_attestations"] == 1

    manifest = json.loads(
        (root / "provenance" / "modules.json").read_text(encoding="utf-8")
    )
    artifact = f"provenance/reviews/{report_name}"
    historical = next(
        record for record in manifest["data_classifications"]
        if record["artifact"] == artifact
    )
    assert historical["classification"] == "reviewed-data"
    assert historical["sha256"] == hashlib.sha256(
        (root / artifact).read_bytes()
    ).hexdigest()
    assert artifact not in {
        record["artifact"] for record in manifest["metadata_exclusions"]
    }


def test_current_review_metadata_binding_uses_an_exact_allowlist(
    project_root, tmp_path
):
    root = _copy_audit_project(project_root, tmp_path / "current-review")
    report_name = Path(CURRENT_REVIEW_ARTIFACT).name
    bind_test_review(root)
    report = audit_provenance(root)
    assert report["review_attestations"] == 1

    manifest = json.loads(
        (root / "provenance" / "modules.json").read_text(encoding="utf-8")
    )
    core_record = next(
        record
        for record in manifest["metadata_exclusions"]
        if record["artifact"] == f"provenance/reviews/{report_name}"
    )
    reviewers = {manifest["review_attestations"][0]["reviewer"]}
    validate_metadata_exclusion(root, core_record, reviewers)

    unexpected = {
        **core_record,
        "artifact": f"{CURRENT_REVIEW_ARTIFACT}.unexpected",
    }
    with pytest.raises(
        AssertionError,
        match="outside the exact self-reference allowlist",
    ):
        validate_metadata_exclusion(root, unexpected, reviewers)


def test_metadata_exclusion_boundary_is_exactly_three_paths(project_root, tmp_path):
    root = _copy_audit_project(project_root, tmp_path / "metadata-boundary")
    manifest, _digest = regenerate(root)

    assert {
        record["artifact"] for record in manifest["metadata_exclusions"]
    } == SELF_REFERENTIAL_METADATA_ALLOWLIST


def test_historical_review_report_drift_changes_mapping_digest(
    project_root,
    tmp_path,
):
    root = _copy_audit_project(project_root, tmp_path / "historical-mapping")
    relative = "provenance/reviews/core-docx-review-cycle-round-1.md"
    report_path = root / relative
    before, before_digest = regenerate(root)
    before_record = next(
        record
        for record in before["data_classifications"]
        if record["artifact"] == relative
    )

    report_path.write_bytes(report_path.read_bytes() + b"\nHistorical drift.\n")
    after, after_digest = regenerate(root)
    after_record = next(
        record
        for record in after["data_classifications"]
        if record["artifact"] == relative
    )

    assert before_record["sha256"] != after_record["sha256"]
    assert before_digest != after_digest


def test_historical_review_report_drift_invalidates_bound_audit(
    project_root,
    tmp_path,
):
    root = _copy_audit_project(project_root, tmp_path / "historical-audit")
    bind_test_review(root)
    report_path = (
        root
        / "provenance"
        / "reviews"
        / "core-docx-review-cycle-round-1.md"
    )
    report_path.write_bytes(report_path.read_bytes() + b"\nHistorical drift.\n")

    report = run_audits(root)

    assert report["status"] == "fail"
    assert report["checks"]["provenance"]["status"] == "fail"


def test_sbom_is_deterministic_and_matches_locks(project_root):
    first = canonical_json(build_sbom(project_root))
    second = canonical_json(build_sbom(project_root))
    assert first == second
    assert json.loads(first)["bomFormat"] == "CycloneDX"
    assert (project_root / "sbom.cdx.json").read_text(encoding="utf-8") == first
    assert audit_sbom(project_root)["status"] == "pass"


def test_sbom_application_identity_matches_both_plugin_manifests(project_root):
    sbom_identity = build_sbom(project_root)["metadata"]["component"]
    manifest_identities = {
        (manifest["name"], manifest["version"])
        for manifest in (
            json.loads((project_root / "elftia-plugin.json").read_text(encoding="utf-8")),
            json.loads(
                (project_root / ".claude-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
    }

    assert manifest_identities == {
        (sbom_identity["name"], sbom_identity["version"])
    }
    assert sbom_identity["bom-ref"] == "application:document-skills"


def test_sbom_records_docx_node_provider_and_transitive_graph(project_root):
    sbom = build_sbom(project_root)
    components = {item["bom-ref"]: item for item in sbom["components"]}
    dependencies = {
        item["ref"]: item["dependsOn"] for item in sbom["dependencies"]
    }
    assert "provider:core-node-docx-template" in components
    assert "provider:html-browser-capture" in components
    assert dependencies["pkg:npm/playwright-core@1.62.1"] == []
    assert dependencies["pkg:npm/docxtemplater@3.69.3"] == [
        "pkg:npm/@xmldom/xmldom@0.9.10"
    ]
    assert dependencies["pkg:npm/pizzip@3.2.0"] == [
        "pkg:npm/pako@2.2.0"
    ]


def test_sbom_records_locked_nuget_hashes_licenses_and_edges(project_root):
    sbom = build_sbom(project_root)
    components = {item["bom-ref"]: item for item in sbom["components"]}
    dependencies = {
        item["ref"]: item["dependsOn"] for item in sbom["dependencies"]
    }
    openxml = components["pkg:nuget/DocumentFormat.OpenXml@3.0.0"]
    assert openxml["licenses"] == [{"license": {"id": "MIT"}}]
    assert openxml["hashes"][0]["alg"] == "SHA-512"
    assert len(openxml["hashes"][0]["content"]) == 128
    assert dependencies["pkg:nuget/DocumentFormat.OpenXml@3.0.0"] == [
        "pkg:nuget/DocumentFormat.OpenXml.Framework@3.0.0"
    ]
    assert dependencies[
        "pkg:nuget/DocumentFormat.OpenXml.Framework@3.0.0"
    ] == ["pkg:nuget/System.IO.Packaging@8.0.0"]
    assert dependencies["pkg:nuget/System.IO.Packaging@8.0.0"] == []
    assert "pkg:nuget/DocumentFormat.OpenXml@3.0.0" in dependencies[
        "application:document-skills"
    ]


def test_missing_nuget_lock_fails_supply_chain_audit(project_root, tmp_path):
    root = _copy_audit_project(project_root, tmp_path / "missing-nuget-lock")
    lock = (
        root
        / "src/document_skills_core/providers/dotnet/helper/packages.lock.json"
    )
    lock.unlink()
    with pytest.raises(AssertionError, match="must be present together"):
        _audit_dependency_manifests(root)


def test_drifted_nuget_lock_fails_supply_chain_audit(project_root, tmp_path):
    root = _copy_audit_project(project_root, tmp_path / "drifted-nuget-lock")
    lock = (
        root
        / "src/document_skills_core/providers/dotnet/helper/packages.lock.json"
    )
    payload = json.loads(lock.read_text(encoding="utf-8"))
    package = payload["dependencies"]["net8.0"]["DocumentFormat.OpenXml"]
    package["resolved"] = "3.0.1"
    lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="resolved version drifted"):
        _audit_dependency_manifests(root)


def test_drifted_nuget_content_hash_fails_exact_dependency_policy(
    project_root, tmp_path
):
    root = _copy_audit_project(project_root, tmp_path / "drifted-nuget-hash")
    lock = (
        root
        / "src/document_skills_core/providers/dotnet/helper/packages.lock.json"
    )
    payload = json.loads(lock.read_text(encoding="utf-8"))
    packages = payload["dependencies"]["net8.0"]
    packages["DocumentFormat.OpenXml"]["contentHash"] = packages[
        "DocumentFormat.OpenXml.Framework"
    ]["contentHash"]
    lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AssertionError, match="content hashes differ"):
        _audit_dependency_manifests(root)


def test_consumer_dependencies_are_exactly_allowlisted_but_not_in_runtime_sbom(
    project_root,
):
    policy = json.loads(
        (project_root / "provenance" / "dependency-allowlist.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["python"]["development_packages"]["openpyxl"] == "3.1.5"
    assert policy["python"]["development_packages"]["pymupdf"] == "1.27.2.2"
    assert policy["python"]["development_packages"]["python-docx"] == "1.2.0"
    assert policy["python"]["development_packages"]["python-pptx"] == "1.0.2"
    assert policy["nuget"]["packages"] == {
        "DocumentFormat.OpenXml": "3.0.0",
        "DocumentFormat.OpenXml.Framework": "3.0.0",
        "System.IO.Packaging": "8.0.0",
    }
    assert policy["nuget"]["dependencies"] == {
        "DocumentFormat.OpenXml": ["DocumentFormat.OpenXml.Framework"],
        "DocumentFormat.OpenXml.Framework": ["System.IO.Packaging"],
        "System.IO.Packaging": [],
    }
    assert set(policy["nuget"]["sha512"]) == set(
        policy["nuget"]["packages"]
    )
    runtime_names = {item["name"] for item in build_sbom(project_root)["components"]}
    assert runtime_names.isdisjoint({"openpyxl", "pymupdf", "python-docx", "python-pptx"})


def test_mammoth_evaluation_does_not_add_a_runtime_dependency(project_root):
    package = json.loads((project_root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads(
        (project_root / "package-lock.json").read_text(encoding="utf-8")
    )
    assert "mammoth" not in package.get("dependencies", {})
    assert "node_modules/mammoth" not in lock.get("packages", {})
    review = (
        project_root / "provenance/reviews/mammoth-1.12.1-evaluation.md"
    ).read_text(encoding="utf-8")
    assert "evaluated, not adopted" in review
    assert "lossy_projection" in review


def test_machine_readable_audit_report(project_root):
    report = run_audits(project_root)
    audit_path = project_root / "provenance" / "audit-report.json"
    assert audit_path.read_text(encoding="utf-8") == canonical_json(report)

    manifest = json.loads(
        (project_root / "provenance" / "modules.json").read_text(encoding="utf-8")
    )
    attestations = manifest["review_attestations"]
    if not attestations:
        assert report["status"] == "fail"
        assert report["checks"]["provenance"] == {"status": "fail"}
        assert report["errors"] == [
            {
                "check": "provenance",
                "message": "Independent review attestation is missing",
            }
        ]
    elif len(attestations) == 1:
        assert report["status"] == "pass"
        assert report["errors"] == []
        assert report["checks"]["provenance"]["status"] == "pass"
        assert report["checks"]["provenance"]["review_attestations"] == 1
    else:
        pytest.fail(f"unsupported review attestation count: {len(attestations)}")


def _copy_audit_project(project_root: Path, destination: Path) -> Path:
    return Path(
        shutil.copytree(
            project_root,
            destination,
            ignore=shutil.ignore_patterns(
                ".venv",
                "node_modules",
                ".pytest_cache",
                ".document-skills-tmp",
                "__pycache__",
                "*.pyc",
            ),
        )
    )


def test_provenance_rejects_broad_glob_unreviewed_module_and_hash_drift(
    project_root, tmp_path
):
    broad = _copy_audit_project(project_root, tmp_path / "broad")
    manifest_path = broad / "provenance" / "modules.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["modules"][0]["module"] = "src/**"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_provenance(broad)

    unreviewed = _copy_audit_project(project_root, tmp_path / "unreviewed")
    (unreviewed / "src" / "unreviewed.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_provenance(unreviewed)

    drift = _copy_audit_project(project_root, tmp_path / "drift")
    module = provenance_modules(drift)[0]
    with (drift / module).open("a", encoding="utf-8") as handle:
        handle.write("\n# unreviewed drift\n")
    with pytest.raises(AssertionError):
        audit_provenance(drift)


@pytest.mark.parametrize(
    "relative",
    [
        "runtime/provider.ps1",
        "runtime/provider.sh",
        "runtime/provider",
        "runtime/provider.dll",
        "runtime/provider.xll",
    ],
)
def test_release_inventory_requires_provenance_for_every_executable_artifact(
    project_root, tmp_path, relative
):
    case_name = Path(relative).suffix.lstrip(".") or "extensionless"
    root = _copy_audit_project(project_root, tmp_path / case_name)
    artifact = root / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"provider artifact\n")
    report = run_audits(root)
    assert report["status"] == "fail"
    assert report["checks"]["provenance"]["status"] == "fail"
    assert any(error["check"] == "provenance" for error in report["errors"])


def test_reviewed_non_executable_artifact_exclusion_is_exact_and_evidenced(
    project_root, tmp_path
):
    root = _copy_audit_project(project_root, tmp_path / "excluded")
    bind_test_review(root)
    artifact = root / "runtime" / "reference.ps1"
    artifact.write_text("# inert provenance test data\n", encoding="utf-8")
    manifest_path = root / "provenance" / "modules.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviewer = manifest["review_attestations"][0]["reviewer"]
    base_exclusions = len(manifest["executable_exclusions"])
    manifest["executable_exclusions"].append(
        {
            "artifact": "runtime/reference.ps1",
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "classification": "non-executable-data",
            "reason": "Inert audit fixture retained only as reviewed reference data.",
            "reviewer": reviewer,
            "review_evidence": [
                "provenance/reviews/foundation-review-cycle-round-1.md"
            ],
        }
    )
    mapping_sha256 = mapping_digest(
        manifest["modules"],
        manifest["executable_exclusions"],
        manifest["data_classifications"],
        manifest["metadata_exclusions"],
    )
    review = manifest["review_attestations"][0]
    evidence_path = root / review["report_evidence"]
    evidence = evidence_path.read_text(encoding="utf-8").replace(
        review["reviewed_mapping_sha256"], mapping_sha256
    )
    evidence_path.write_text(evidence, encoding="utf-8")
    review["reviewed_mapping_sha256"] = mapping_sha256
    review["report_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = audit_provenance(root)
    assert report["exclusion_count"] == base_exclusions + 1

    manifest["executable_exclusions"][-1]["review_evidence"] = ["PROVENANCE.md"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_provenance(root)


def test_complete_machine_audit_rejects_dynamic_mcp_command_and_artifact_bypasses(
    project_root, tmp_path
):
    dynamic = _copy_audit_project(project_root, tmp_path / "dynamic")
    source = dynamic / "src" / "dynamic_import.py"
    source.write_text(
        'module = __import__("mcp.server.fastmcp", fromlist=["FastMCP"])\n'
        'app = module.FastMCP("documents")\n',
        encoding="utf-8",
    )
    dynamic_report = run_audits(dynamic)
    assert dynamic_report["status"] == "fail"
    assert dynamic_report["checks"]["execution_boundary"]["status"] == "fail"

    direct = _copy_audit_project(project_root, tmp_path / "direct-command")
    with (direct / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("\n```text\nnode runtime/node/health.mjs\n```\n")
    command_report = run_audits(direct)
    assert command_report["status"] == "fail"
    assert command_report["checks"]["commands"]["status"] == "fail"

    artifact_root = _copy_audit_project(project_root, tmp_path / "artifact")
    (artifact_root / "runtime" / "provider.ps1").write_text(
        "Write-Output provider\n", encoding="utf-8"
    )
    artifact_report = run_audits(artifact_root)
    assert artifact_report["status"] == "fail"
    assert artifact_report["checks"]["provenance"]["status"] == "fail"


@pytest.mark.parametrize(
    ("relative", "payload"),
    [
        ("runtime/bin/provider.exe", b"MZ\x90\x00provider"),
        (
            "assets/provider.msi",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1provider",
        ),
        ("launch-provider", b"#!/bin/sh\nexec provider\n"),
        (".hidden/bin/provider.dat", b"provider binary"),
        ("assets/renamed-provider.dat", b"MZ\x90\x00provider"),
        ("assets/renamed-ole.dat", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1payload"),
        ("assets/macho32-be.dat", b"\xfe\xed\xfa\xcepayload"),
        ("assets/macho32-le.dat", b"\xce\xfa\xed\xfepayload"),
        ("assets/macho64-be.dat", b"\xfe\xed\xfa\xcfpayload"),
        ("assets/macho64-le.dat", b"\xcf\xfa\xed\xfepayload"),
        ("assets/macho-fat-be.dat", b"\xca\xfe\xba\xbepayload"),
        ("assets/macho-fat-le.dat", b"\xbe\xba\xfe\xcapayload"),
        ("assets/macho-fat64-be.dat", b"\xca\xfe\xba\xbfpayload"),
        ("assets/macho-fat64-le.dat", b"\xbf\xba\xfe\xcapayload"),
        ("assets/renamed-elf.dat", b"\x7fELFpayload"),
        ("assets/renamed-wasm.dat", b"\x00asmpayload"),
        ("assets/renamed-java.dat", b"\xca\xfe\xba\xbepayload"),
        ("assets/opaque-nul.dat", b"plain-looking\x00opaque"),
        ("assets/opaque-low-text.dat", bytes(range(1, 32)) * 4),
        ("assets/extensionless", b"ordinary text with no suffix\n"),
    ],
)
def test_complete_audit_sees_hidden_location_magic_installer_and_shebang_artifacts(
    project_root, tmp_path, relative, payload
):
    root = _copy_audit_project(project_root, tmp_path / "artifact-variant")
    artifact = root / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(payload)
    report = run_audits(root)
    assert report["status"] == "fail"
    assert any(
        error["check"] in {"inventory", "provenance", "execution_boundary"}
        for error in report["errors"]
    )


@pytest.mark.parametrize(
    "mutation",
    ["zero-hash", "self-reference", "placeholder-identity", "mapping-mismatch"],
)
def test_provenance_rejects_forged_or_unrooted_review_attestations(
    project_root, tmp_path, mutation
):
    root = _copy_audit_project(project_root, tmp_path / mutation)
    bind_test_review(root)
    manifest_path = root / "provenance" / "modules.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review = manifest["review_attestations"][0]
    if mutation == "zero-hash":
        review["report_sha256"] = "0" * 64
    elif mutation == "self-reference":
        review["report_evidence"] = "provenance/modules.json"
        review["report_name"] = "modules.json"
        review["report_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
    elif mutation == "placeholder-identity":
        review["identity"] = "codex-reviewer/placeholder"
    else:
        review["reviewed_mapping_sha256"] = "1" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = run_audits(root)
    assert report["status"] == "fail"
    assert report["checks"]["provenance"]["status"] == "fail"
