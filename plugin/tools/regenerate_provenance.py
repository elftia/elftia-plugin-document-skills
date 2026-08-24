"""Regenerate exact all-file provenance from final release bytes."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .audit_execution import runtime_source_allowlist
from .html_pptx_provenance import (
    HTML_PPTX_REQUIREMENT,
    SHARED_PROVENANCE_REQUIREMENT,
    html_pptx_data_profile,
    html_pptx_module_profile,
)
from .provenance_records import mapping_digest
from .release_inventory import release_artifacts

PENDING_REVIEWER = "PENDING independent review"
CONSUMER_GATES_REQUIREMENT = (
    "Rasen document-skills-consumer-gates-and-truthful-contracts"
)
DOCX_CONSUMER_GATES_REQUIREMENT = (
    "Rasen document-skills-core-docx + "
    "document-skills-consumer-gates-and-truthful-contracts"
)
XLSX_REQUIREMENT = "Rasen document-skills-core-xlsx"
_XLSX_SHARED_MODULES = {
    "src/document_skills_core/core/io/ooxml_security.py",
    "src/document_skills_core/core/process/executable.py",
    "src/document_skills_core/core/process/runner.py",
    "src/document_skills_core/core/process/windows_handles.py",
    "src/document_skills_core/formats/pdf/byte_preflight.py",
    "src/document_skills_core/providers/defaults.py",
    "src/document_skills_core/providers/dotnet/constants.py",
    "src/document_skills_core/providers/dotnet/detector.py",
    "src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj",
    "src/document_skills_core/providers/dotnet/helper/Program.cs",
    "src/document_skills_core/providers/dotnet/helper/packages.lock.json",
    "src/document_skills_core/providers/dotnet/runner.py",
    "src/document_skills_core/providers/dotnet/schema.py",
    "src/document_skills_core/providers/dotnet/service.py",
    "src/document_skills_core/providers/libreoffice/constants.py",
    "src/document_skills_core/providers/libreoffice/convert.py",
    "src/document_skills_core/providers/libreoffice/detector.py",
    "src/document_skills_core/providers/libreoffice/input_snapshot.py",
    "src/document_skills_core/providers/libreoffice/legacy.py",
    "src/document_skills_core/providers/libreoffice/output.py",
    "src/document_skills_core/providers/libreoffice/quota.py",
    "src/document_skills_core/providers/libreoffice/recalc.py",
    "src/document_skills_core/providers/libreoffice/render.py",
    "src/document_skills_core/providers/libreoffice/runner.py",
    "src/document_skills_core/providers/libreoffice/service.py",
    "src/document_skills_core/public_cli/supervisor.py",
    "tests/test_consumer_validation.py",
    "tests/test_dotnet_provider.py",
    "tests/test_html_provenance.py",
    "tests/test_input_snapshot_security.py",
    "tests/test_libreoffice_hard_quota.py",
    "tests/test_libreoffice_provider.py",
    "tests/test_process_executable_identity.py",
    "tests/test_runtime.py",
    "tests/test_safety.py",
    "tests/test_strategy3.py",
    "tests/test_structure.py",
    "tests/test_supply_chain.py",
    "tests/test_truthful_results.py",
    "tools/audit.py",
    "tools/audit_execution.py",
    "tools/provenance_records.py",
    "tools/python_policy_definitions.py",
    "tools/regenerate_provenance.py",
    "tools/release_inventory.py",
    "tools/supply_chain.py",
}
_XLSX_SHARED_DATA_ARTIFACTS = {
    "THIRD_PARTY_NOTICES.md",
    "provenance/dependency-allowlist.json",
    "provenance/dependency-licenses.json",
    "provenance/runtime-source-allowlist.json",
    "sbom.cdx.json",
}
_XLSX_SHARED_TESTS = [
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
    "tests/test_runtime.py",
    "tests/test_safety.py",
    "tests/test_strategy2.py",
    "tests/test_strategy3.py",
    "tests/test_structure.py",
    "tests/test_supply_chain.py",
]
_XLSX_NUGET_DESCRIPTION = (
    "Exact NuGet dependency lock, allowlist, license, notice, and SBOM evidence "
    "for the bounded OpenXML helper used by Core XLSX schema validation."
)
_XLSX_RUNTIME_SOURCE_DESCRIPTION = (
    "Strict value-flow runtime file inventory for the Core XLSX Python source set "
    "and its execution-boundary audit."
)
_XLSX_SHARED_DESCRIPTION = (
    "Shared Core XLSX provider execution, managed CLI supervision, and exact "
    "supply-chain policy for bounded OpenXML validation and LibreOffice rendering."
)
_XLSX_ATOMIC_LAUNCH_ONLY_MODULES = {
    "src/document_skills_core/core/process/executable.py",
    "src/document_skills_core/core/process/windows_handles.py",
    "tests/test_process_executable_identity.py",
}
_XLSX_ATOMIC_LAUNCH_COMPOSED_MODULES = {
    "src/document_skills_core/core/process/runner.py",
    "src/document_skills_core/providers/dotnet/detector.py",
    "src/document_skills_core/providers/dotnet/runner.py",
    "src/document_skills_core/providers/dotnet/service.py",
    "src/document_skills_core/providers/libreoffice/detector.py",
}
_XLSX_ATOMIC_LAUNCH_DESCRIPTION = (
    "Identity-bound top-level native executable launch: Windows hashes and resolves "
    "one followed handle, then holds canonical parent and executable handles through "
    "CreateProcess; Linux executes the verified fd via /proc/self/fd with pass_fds. "
    "Pre-lease identity drift and detector-to-operation races fail closed; final-window "
    "same-path replacement cannot redirect the pinned launch object. Windows share "
    "mode blocks hardlink-alias writes, and partial handle acquisition closes each "
    "owned handle exactly once. Identity capture or change, non-Linux POSIX or script "
    "native-unavailable cases, and spawn failures use sanitized typed categories "
    "without raw OS details. The binding excludes argv-selected helpers and the "
    "dynamic DLL or dependency closure."
)


def regenerate(
    root: Path,
    *,
    reviewer: str = PENDING_REVIEWER,
    review: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    artifacts = release_artifacts(root)
    modules = []
    data = []
    metadata = []
    for artifact in artifacts:
        if _is_metadata(artifact.path):
            metadata.append(
                {
                    "artifact": artifact.path,
                    "classification": "self-referential-audit-metadata",
                    "reason": (
                        "This audit metadata contains or reports the mapping digest, so "
                        "raw self-hashing would be circular; exact scope and "
                        "classification require independent review."
                    ),
                    "reviewer": reviewer,
                    "review_evidence": ["PROVENANCE.md"],
                }
            )
        elif artifact.risky:
            modules.append(_module_record(artifact, reviewer))
        else:
            data.append(_data_record(artifact, reviewer))
    digest = mapping_digest(modules, [], data, metadata)
    reviews = []
    if review is not None:
        if review["reviewed_mapping_sha256"] != digest:
            raise ValueError("review does not bind the regenerated mapping")
        report = root / review["report_evidence"]
        review["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
        reviews.append(review)
        evidence = [review["report_evidence"]]
        for record in [*modules, *data, *metadata]:
            record["review_evidence"] = evidence
    manifest = {
        "schema_version": "1.0",
        "modules": modules,
        "adopted_sources": [],
        "executable_exclusions": [],
        "data_classifications": data,
        "metadata_exclusions": metadata,
        "review_attestations": reviews,
    }
    return manifest, digest


def _module_record(artifact: Any, reviewer: str) -> dict[str, Any]:
    html_profile = html_pptx_module_profile(artifact.path)
    xlsx_shared_profile = xlsx_shared_module_profile(artifact.path)
    is_consumer_gate = artifact.path.startswith("consumer_validation/") or artifact.path in {
        "tests/test_consumer_validation.py",
        "tests/test_consumer_validation_strategy3.py",
        "tests/test_cross_format_transactions.py",
    }
    is_docx_consumer_gate = artifact.path in {
        "tests/fixtures/recipes/docx_fixtures.py",
        "tests/test_docx_fixtures.py",
    }
    is_docx = (
        "/docx/" in artifact.path
        or "document-docx" in artifact.path
        or "docx_" in artifact.path
        or "docx-" in artifact.path
    )
    is_xlsx = (
        "/xlsx/" in artifact.path
        or "document-xlsx" in artifact.path
        or "xlsx_" in artifact.path
        or "xlsx-" in artifact.path
    )
    tests = _merged_values(html_profile[1], xlsx_shared_profile[1]) if (
        html_profile and xlsx_shared_profile
    ) else _merged_values(
        [
            "tests/test_consumer_validation.py",
            "tests/test_consumer_validation_strategy3.py",
            "tests/test_cross_format_transactions.py",
        ],
        xlsx_shared_profile[1],
    ) if is_consumer_gate and xlsx_shared_profile else html_profile[1] if (
        html_profile
    ) else xlsx_shared_profile[1] if (
        xlsx_shared_profile
    ) else (
        ["tests/test_docx_fixtures.py", "tests/test_supply_chain.py"]
        if is_docx_consumer_gate
        else [
            "tests/test_consumer_validation.py",
            "tests/test_consumer_validation_strategy3.py",
            "tests/test_cross_format_transactions.py",
        ]
        if is_consumer_gate
        else [
            "tests/test_docx_contracts.py",
            "tests/test_docx_operations.py",
            "tests/test_docx_public.py",
            "tests/test_supply_chain.py",
        ]
        if is_docx
        else [
            "tests/test_xlsx_contracts.py",
            "tests/test_xlsx_operations.py",
            "tests/test_xlsx_pivot.py",
            "tests/test_xlsx_provider_qa.py",
            "tests/test_xlsx_public.py",
            "tests/test_xlsx_recalculation.py",
            "tests/test_supply_chain.py",
        ]
        if is_xlsx
        else
        [
            "tests/test_strategy2.py",
            "tests/test_strategy3.py",
            "tests/test_runtime.py",
        ]
        if artifact.path.startswith(("src/", "runtime/", "skills/"))
        else [
            "tests/test_strategy2.py",
            "tests/test_strategy3.py",
            "tests/test_supply_chain.py",
        ]
    )
    return {
        "module": artifact.path,
        "sha256": artifact.sha256,
        "source_class": "original",
        "requirement_source": (
            _with_xlsx_requirement(SHARED_PROVENANCE_REQUIREMENT)
            if artifact.path == "tools/regenerate_provenance.py" and xlsx_shared_profile
            else SHARED_PROVENANCE_REQUIREMENT
            if artifact.path == "tools/regenerate_provenance.py"
            else _with_xlsx_requirement(HTML_PPTX_REQUIREMENT)
            if html_profile and xlsx_shared_profile
            else _with_xlsx_requirement(CONSUMER_GATES_REQUIREMENT)
            if is_consumer_gate and xlsx_shared_profile
            else HTML_PPTX_REQUIREMENT
            if html_profile
            else XLSX_REQUIREMENT
            if xlsx_shared_profile
            else DOCX_CONSUMER_GATES_REQUIREMENT
            if is_docx_consumer_gate
            else CONSUMER_GATES_REQUIREMENT
            if is_consumer_gate
            else "Rasen document-skills-core-docx"
            if is_docx
            else "Rasen document-skills-core-xlsx"
            if is_xlsx
            else "Rasen document-skills-foundation strategy-attempt-3"
        ),
        "implementation_source": "Original Elftia project code",
        "third_party_files": [],
        "license": "GPL-3.0",
        "modifications": (
            f"{html_profile[0]} {xlsx_shared_profile[0]}"
            if html_profile and xlsx_shared_profile
            else (
                "Independent bounded consumer validation, truthful PDF identity, "
                "typed Office timeout cleanup, cross-format preservation, or their "
                f"direct Strategy-4 regression evidence. {xlsx_shared_profile[0]}"
            )
            if is_consumer_gate and xlsx_shared_profile
            else html_profile[0]
            if html_profile
            else xlsx_shared_profile[0]
            if xlsx_shared_profile
            else
            (
                "Deterministic DOCX fixture generation and nested frozen-uv consumer "
                "qualification isolated from outer project environments."
            )
            if is_docx_consumer_gate
            else
            (
                "Independent bounded consumer validation, truthful PDF identity, "
                "typed Office timeout cleanup, cross-format preservation, or their "
                "direct Strategy-4 regression evidence."
            )
            if is_consumer_gate
            else
            (
                "Original Core DOCX contract, package, projection, mutation, "
                "validation, Skill guidance, tests, or release evidence."
            )
            if is_docx
            else (
                "Original Core XLSX contract, package, projection, mutation, "
                "provider validation/rendering, Skill guidance, tests, or release evidence."
            )
            if is_xlsx
            else (
                "Strategy-attempt-3 semantic loader/reflection, command discovery, "
                "portable release inventory, tests, or release evidence."
            )
        ),
        "reviewer": reviewer,
        "review_evidence": ["PROVENANCE.md"],
        "clean_room": True,
        "artifact_tests": tests,
    }


def _data_record(artifact: Any, reviewer: str) -> dict[str, Any]:
    html_profile = html_pptx_data_profile(artifact.path)
    xlsx_profile = xlsx_shared_data_profile(artifact.path)
    modifications = (
        f"{html_profile[0]} {xlsx_profile[0]}"
        if html_profile and xlsx_profile
        else html_profile[0]
        if html_profile
        else xlsx_profile[0]
        if xlsx_profile
        else None
    )
    record = {
        "artifact": artifact.path,
        "sha256": artifact.sha256,
        "classification": artifact.classification,
        "reason": (
            modifications
            if modifications
            else (
                "Exact non-execution release bytes are classified by the shared "
                "release inventory and require independent review."
            )
        ),
        "reviewer": reviewer,
        "review_evidence": ["PROVENANCE.md"],
    }
    if modifications:
        requirement = (
            _with_xlsx_requirement(HTML_PPTX_REQUIREMENT)
            if html_profile and xlsx_profile
            else HTML_PPTX_REQUIREMENT
            if html_profile
            else XLSX_REQUIREMENT
        )
        tests = (
            _merged_values(html_profile[1], xlsx_profile[1])
            if html_profile and xlsx_profile
            else html_profile[1]
            if html_profile
            else xlsx_profile[1]
        )
        record.update({
            "requirement_source": requirement,
            "modifications": modifications,
            "artifact_tests": tests,
        })
    return record


def xlsx_shared_module_profile(path: str) -> tuple[str, list[str]] | None:
    if path not in _XLSX_SHARED_MODULES:
        return None
    if path.endswith("/dotnet/helper/packages.lock.json"):
        return (_XLSX_NUGET_DESCRIPTION, _XLSX_SHARED_TESTS)
    if path in _XLSX_ATOMIC_LAUNCH_ONLY_MODULES:
        return (_XLSX_ATOMIC_LAUNCH_DESCRIPTION, _XLSX_SHARED_TESTS)
    if path in _XLSX_ATOMIC_LAUNCH_COMPOSED_MODULES:
        return (
            f"{_XLSX_SHARED_DESCRIPTION} {_XLSX_ATOMIC_LAUNCH_DESCRIPTION}",
            _XLSX_SHARED_TESTS,
        )
    return (_XLSX_SHARED_DESCRIPTION, _XLSX_SHARED_TESTS)


def xlsx_shared_data_profile(path: str) -> tuple[str, list[str]] | None:
    if path not in _XLSX_SHARED_DATA_ARTIFACTS:
        return None
    if path == "provenance/runtime-source-allowlist.json":
        return (_XLSX_RUNTIME_SOURCE_DESCRIPTION, _XLSX_SHARED_TESTS)
    return (
        _XLSX_NUGET_DESCRIPTION,
        _XLSX_SHARED_TESTS,
    )


def _with_xlsx_requirement(requirement: str) -> str:
    return f"{requirement} + document-skills-core-xlsx"


def _merged_values(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


def _is_metadata(path: str) -> bool:
    return path in {
        "provenance/audit-report.json",
        "provenance/modules.json",
        "provenance/reviews/clean-room-parity-and-hardening-review-cycle-round-1.md",
        "provenance/reviews/core-docx-review-cycle-round-1.md",
        "provenance/reviews/core-pdf-review-cycle-round-1.md",
        "provenance/reviews/core-pptx-review-cycle-round-1.md",
        "provenance/reviews/core-xlsx-review-cycle-round-1.md",
        "provenance/reviews/docx-create-optional-content-review-cycle-round-1.md",
        "provenance/reviews/document-skills-0.2.0-release.md",
        "provenance/reviews/document-skills-0.5.1-consumer-gates-implementation-audit.md",
        "provenance/reviews/document-skills-0.5.1-node20-process-review.md",
        "provenance/reviews/document-skills-0.5.2-ci-repair-and-version-bump-review.md",
        "provenance/reviews/document-skills-0.5.3-packaging-hygiene-review.md",
        "provenance/reviews/foundation-review-cycle-round-1.md",
        "provenance/reviews/html-to-editable-pptx-review-cycle-round-1.md",
        "provenance/reviews/libreoffice-enhancement-review-cycle-round-1.md",
        "provenance/reviews/openxml-dotnet-enhancement-review-cycle-round-1.md",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-source-output", type=Path)
    parser.add_argument("--reuse-review-from", type=Path)
    parser.add_argument("--print-mapping-only", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    manifest, digest = regenerate(root)
    if args.print_mapping_only:
        if args.output or args.runtime_source_output or args.reuse_review_from:
            parser.error("--print-mapping-only cannot be combined with output options")
        print(digest)
        return 0
    if args.output is None and args.runtime_source_output is None:
        parser.error("at least one generated output is required")
    if args.reuse_review_from:
        previous = json.loads(args.reuse_review_from.read_text(encoding="utf-8"))
        reviews = previous.get("review_attestations", [])
        if len(reviews) != 1:
            parser.error("--reuse-review-from requires exactly one review attestation")
        review = reviews[0]
        review["reviewed_mapping_sha256"] = digest
        manifest, rebound = regenerate(
            root,
            reviewer=review["reviewer"],
            review=review,
        )
        if rebound != digest:
            raise RuntimeError("review rebinding changed the provenance mapping")
    if args.output:
        args.output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if args.runtime_source_output:
        args.runtime_source_output.write_text(
            json.dumps(runtime_source_allowlist(root), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
