"""Regenerate exact all-file provenance from final release bytes."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .audit_execution import runtime_source_allowlist
from .html_pptx_provenance import (
    HTML_PPTX_REQUIREMENT,
    PPTX_EQUATION_B6_REQUIREMENT,
    PPTX_RECONSTRUCTION_B7_REQUIREMENT,
    PPTX_TEMPLATE_B2_REQUIREMENT,
    PPTX_TEMPLATE_B4_REQUIREMENT,
    PPTX_SVG_B5_REQUIREMENT,
    equation_b6_data_profile,
    html_pptx_data_profile,
    pptx_module_profile,
    reconstruction_b7_data_profile,
    template_b2_data_profile,
    template_b4_data_profile,
    svg_b5_data_profile,
)
from .provenance_records import SELF_REFERENTIAL_METADATA_ALLOWLIST, mapping_digest
from .release_inventory import release_artifacts

PENDING_REVIEWER = "PENDING independent review"
CONSUMER_GATES_REQUIREMENT = (
    "Rasen document-skills-consumer-gates-and-truthful-contracts"
)
DOCX_CONSUMER_GATES_REQUIREMENT = (
    "Rasen document-skills-core-docx + "
    "document-skills-consumer-gates-and-truthful-contracts"
)
PDF_COMPLETION_REQUIREMENT = (
    "Elftia docs/research/document-skills/tasks/pdf-completion-task.md "
    "(2026-08-24)"
)
XLSX_REQUIREMENT = "Rasen document-skills-core-xlsx"
XLSX_COMPLETION_REQUIREMENT = "Rasen document-skills-xlsx-completion"
XLSX_ADVANCED_REQUIREMENT = "Rasen document-skills-xlsx-advanced-authoring"
LIBREOFFICE_REQUIREMENT = "Rasen document-skills-libreoffice-enhancement"
OPENXML_DOTNET_REQUIREMENT = "Rasen document-skills-openxml-dotnet-enhancement"
CORE_DOCX_REQUIREMENT = "Rasen document-skills-core-docx"
DOCX_TEMPLATE_PACK_REQUIREMENT = "Rasen docx-template-packs-and-reference-import"
CORE_PDF_REQUIREMENT = "Rasen document-skills-core-pdf"
FOUNDATION_REQUIREMENT = "Rasen document-skills-foundation strategy-attempt-3"
CROSS_FORMAT_CAPABILITY_REQUIREMENT = (
    "Rasen document-skills-foundation strategy-attempt-3 + "
    "document-skills-core-docx + document-skills-core-pdf + "
    "document-skills-core-pptx + document-skills-core-xlsx + "
    "document-skills-xlsx-completion"
)
README_SYSTEM_REQUIREMENT = "Rasen document-skills-readme-system"

_README_SYSTEM_DATA_ARTIFACTS = {
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
_README_SYSTEM_MODULES = {
    "runtime/node/README.md",
    "src/document_skills_core/providers/README.md",
    "tests/test_readme_provenance.py",
    "tools/README.md",
}
_README_SYSTEM_DESCRIPTION = (
    "Layered producer README navigation, truthful capability and verification "
    "boundaries, executable-reference validation, or direct provenance evidence."
)
_README_SYSTEM_TESTS = [
    "tests/test_readme_provenance.py",
    "tests/test_structure.py",
    "tests/test_supply_chain.py",
]

_CROSS_FORMAT_CAPABILITY_MODULE_PROFILES: dict[
    str, tuple[str, list[str]]
] = {
    "src/document_skills_core/core/capabilities/reports.py": (
        (
            "Foundation capability-report assembly with DOCX, PDF, PPTX, and XLSX "
            "format isolation: schema and visual availability requires an available "
            "callable provider registered for the matching format operation."
        ),
        ["tests/test_strategy2.py"],
    ),
    "tests/test_strategy2.py": (
        (
            "Direct cross-format DOCX, PDF, PPTX, and XLSX regression evidence that "
            "schema and visual capability reporting rejects mismatched, unavailable, "
            "or non-callable validators and providers."
        ),
        ["tests/test_strategy2.py"],
    ),
}

_PPTX_OPENXML_MODULE_PROFILES: dict[str, tuple[str, list[str]]] = {
    "tests/test_pptx_public.py": (
        (
            "Optional dotnet-openxml schema-gate regression evidence using "
            "operation-time provider detection and truthful success or unavailable "
            "outcomes."
        ),
        ["tests/test_pptx_public.py"],
    ),
}

_DOCX_TEMPLATE_PACK_TESTS = [
    "tests/test_docx_template_packs.py",
    "tests/test_docx_template_pack_remediation.py",
    "tests/test_docx_document_spec_public.py",
    "tests/test_docx_create_gate.py",
    "tests/test_docx_public.py",
    "tests/test_strategy2.py",
    "tests/test_supply_chain.py",
]
_DOCX_TEMPLATE_PACK_MODULES = {
    "src/document_skills_core/public_cli/supervisor.py",
    "src/document_skills_core/formats/docx/authoring_validation.py",
    "src/document_skills_core/formats/docx/create.py",
    "src/document_skills_core/formats/docx/create_contract.py",
    "src/document_skills_core/formats/docx/create_validation.py",
    "src/document_skills_core/formats/docx/document_spec.py",
    "src/document_skills_core/formats/docx/story_contract.py",
    "src/document_skills_core/formats/docx/style_profiles.py",
    "src/document_skills_core/formats/docx/table.py",
    "src/document_skills_core/formats/docx/template_format_inventory.py",
    "src/document_skills_core/formats/docx/template_import.py",
    "src/document_skills_core/formats/docx/template_pack.py",
    "src/document_skills_core/formats/docx/template_pack_contract.py",
    "src/document_skills_core/formats/docx/template_pack_operation.py",
    "src/document_skills_core/formats/docx/template_regions.py",
    "tests/test_docx_template_packs.py",
    "tests/test_docx_template_pack_remediation.py",
    "tests/test_docx_public.py",
    "tools/build_docx_template_pack.py",
    "tools/ci_docx_core_evidence.py",
}
_DOCX_TEMPLATE_PACK_DESCRIPTION = (
    "Integrity-bound DOCX template-pack snapshots, truthful reference-format "
    "inventory, backward-compatible structured stories, academic typography and "
    "paragraph layout, positive table geometry/three-line borders, strict consumer "
    "assertions, bounded public/OpenXML cold-start budgets with explicit short-timeout "
    "cleanup, or focused source/distribution regression evidence."
)

_XLSX_FORMAT_PREFIX = "src/document_skills_core/formats/xlsx/"
_XLSX_CORE_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}{name}"
    for name in (
        "__init__.py",
        "calc_chain.py",
        "formula_state.py",
        "shared_strings.py",
    )
} | {
    f"tests/{name}"
    for name in (
        "test_xlsx_core_only.py",
        "test_xlsx_formula_state.py",
    )
}
_XLSX_COMPLETION_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}{name}"
    for name in (
        "conversion_contract.py",
        "conversion_model.py",
        "conversion_operation.py",
        "conversion_text.py",
        "conversion_xlsx.py",
        "legacy_conversion.py",
        "pivot_contract.py",
        "pivot_layout.py",
        "pivot_model.py",
        "pivot_operation.py",
        "pivot_package.py",
        "pivot_validation.py",
        "pivot_xml.py",
        "recalculation_operation.py",
        "render_operation.py",
        "render_package.py",
        "render_sampling.py",
        "schema_operation.py",
        "summary_contract.py",
        "summary_model.py",
        "summary_operation.py",
        "summary_support.py",
        "summary_validation.py",
        "template_operation.py",
    )
} | {
    f"tests/{name}"
    for name in (
        "test_dotnet_xlsx_schema_real.py",
        "test_xlsx_conversion.py",
        "test_xlsx_provider_qa.py",
        "test_xlsx_summary.py",
    )
}
_XLSX_ADVANCED_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}{name}"
    for name in (
        "annotations.py",
        "chart.py",
        "chart_components.py",
        "chart_contract.py",
        "chart_edit.py",
        "chart_projection.py",
        "chart_series_contract.py",
        "comment_edit.py",
        "comment_package.py",
        "conditional_format.py",
        "data_validation.py",
        "sparkline.py",
        "sparkline_contract.py",
        "sparkline_structural.py",
        "sparkline_validation.py",
        "table_edit.py",
    )
} | {
    f"tests/{name}"
    for name in (
        "test_xlsx_annotations.py",
        "test_xlsx_chart_advanced.py",
        "test_xlsx_chart_advanced_public.py",
        "test_xlsx_chart_create.py",
        "test_xlsx_chart_edit.py",
        "test_xlsx_conditional_format.py",
        "test_xlsx_data_validation.py",
        "test_xlsx_sparkline.py",
        "test_xlsx_sparkline_public.py",
        "test_xlsx_table_create.py",
        "test_xlsx_table_edit.py",
    )
}
_XLSX_CORE_ADVANCED_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}{name}"
    for name in (
        "create.py",
        "edit.py",
        "inspect.py",
        "read.py",
        "sheet_edit.py",
        "structural_edit.py",
        "structural_refs.py",
        "style_contract.py",
        "style_patch.py",
        "workbook_properties.py",
        "worksheet_edit.py",
        "worksheet_metadata.py",
    )
} | {
    f"tests/{name}"
    for name in (
        "test_xlsx_metadata_public.py",
        "test_xlsx_operations.py",
        "test_xlsx_page_setup.py",
        "test_xlsx_sheet_edit.py",
        "test_xlsx_structural_edit.py",
        "test_xlsx_structural_refs.py",
        "test_xlsx_worksheet_edit.py",
    )
}
_XLSX_COMPLETION_ADVANCED_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}{name}"
    for name in (
        "format_policy.py",
        "formula_analysis.py",
        "formula_security.py",
        "macro_policy.py",
        "pivot_projection.py",
    )
} | {
    "tests/support/xlsx_macro_fixture.py",
    "tests/test_xlsx_formula_analysis.py",
    "tests/test_xlsx_macro_template.py",
    "tests/test_xlsx_pivot.py",
    "tests/test_xlsx_pivot_public.py",
}
_XLSX_ALL_CHANGE_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}{name}"
    for name in (
        "constants.py",
        "content_types.py",
        "contracts.py",
        "mapping.py",
        "package.py",
        "projection.py",
        "relationships.py",
        "results.py",
        "service_support.py",
        "source_snapshot.py",
        "styles.py",
        "transaction.py",
        "validation.py",
        "xml_numeric.py",
    )
} | {
    "skills/document-xlsx/scripts/run.py",
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_public.py",
}
_XLSX_COMPOSED_MODULES: set[str] = set()
_XLSX_CORE_COMPLETION_LIBREOFFICE_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}recalculation.py",
    "tests/test_xlsx_recalculation.py",
}
_XLSX_CORE_ADVANCED_LIBREOFFICE_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}read_operation.py",
}
_XLSX_ALL_CHANGE_LIBREOFFICE_MODULES = {
    f"{_XLSX_FORMAT_PREFIX}recalculation_service.py",
    f"{_XLSX_FORMAT_PREFIX}service.py",
}

_XLSX_CORE_DATA_ARTIFACTS: set[str] = set()
_XLSX_COMPLETION_DATA_ARTIFACTS = {
    f"skills/document-xlsx/references/{name}"
    for name in (
        "conversion.md",
        "provider-qa.md",
        "summary.md",
    )
}
_XLSX_ADVANCED_DATA_ARTIFACTS = {
    f"skills/document-xlsx/references/{name}"
    for name in (
        "charts.md",
        "sparklines.md",
    )
}
_XLSX_CORE_ADVANCED_DATA_ARTIFACTS = {
    f"skills/document-xlsx/references/{name}"
    for name in (
        "edits.md",
        "native-objects.md",
        "styles.md",
        "worksheet-metadata.md",
    )
}
_XLSX_COMPLETION_ADVANCED_DATA_ARTIFACTS = {
    f"skills/document-xlsx/references/{name}"
    for name in (
        "formula-analysis.md",
        "macro-templates.md",
        "pivots.md",
    )
}
_XLSX_ALL_CHANGE_DATA_ARTIFACTS = {
    "README.md",
    "skills/document-xlsx/SKILL.md",
    "skills/document-xlsx/references/feature-truth-table.json",
}
_XLSX_COMPOSED_DATA_ARTIFACTS: set[str] = set()
_XLSX_CORE_COMPLETION_LIBREOFFICE_DATA_ARTIFACTS = {
    "skills/document-xlsx/references/recalculation.md",
}

_XLSX_CORE_TESTS = [
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_core_only.py",
    "tests/test_xlsx_formula_state.py",
    "tests/test_xlsx_operations.py",
    "tests/test_xlsx_public.py",
    "tests/test_supply_chain.py",
]
_XLSX_COMPLETION_TESTS = [
    "tests/test_xlsx_contracts.py",
    "tests/test_xlsx_conversion.py",
    "tests/test_xlsx_macro_template.py",
    "tests/test_xlsx_pivot.py",
    "tests/test_xlsx_pivot_public.py",
    "tests/test_xlsx_provider_qa.py",
    "tests/test_xlsx_public.py",
    "tests/test_xlsx_recalculation.py",
    "tests/test_xlsx_summary.py",
    "tests/test_dotnet_xlsx_schema_real.py",
    "tests/test_libreoffice_provider.py",
    "tests/test_supply_chain.py",
]
_XLSX_ADVANCED_TESTS = [
    "tests/test_xlsx_annotations.py",
    "tests/test_xlsx_chart_advanced.py",
    "tests/test_xlsx_chart_advanced_public.py",
    "tests/test_xlsx_chart_create.py",
    "tests/test_xlsx_chart_edit.py",
    "tests/test_xlsx_conditional_format.py",
    "tests/test_xlsx_data_validation.py",
    "tests/test_xlsx_formula_analysis.py",
    "tests/test_xlsx_metadata_public.py",
    "tests/test_xlsx_page_setup.py",
    "tests/test_xlsx_sheet_edit.py",
    "tests/test_xlsx_sparkline.py",
    "tests/test_xlsx_sparkline_public.py",
    "tests/test_xlsx_structural_edit.py",
    "tests/test_xlsx_structural_refs.py",
    "tests/test_xlsx_table_create.py",
    "tests/test_xlsx_table_edit.py",
    "tests/test_xlsx_worksheet_edit.py",
    "tests/test_xlsx_public.py",
    "tests/test_supply_chain.py",
]
_XLSX_COMPOSED_TESTS = list(
    dict.fromkeys([*_XLSX_CORE_TESTS, *_XLSX_COMPLETION_TESTS])
)
_XLSX_CORE_ADVANCED_TESTS = list(
    dict.fromkeys([*_XLSX_CORE_TESTS, *_XLSX_ADVANCED_TESTS])
)
_XLSX_COMPLETION_ADVANCED_TESTS = list(
    dict.fromkeys([*_XLSX_COMPLETION_TESTS, *_XLSX_ADVANCED_TESTS])
)
_XLSX_ALL_CHANGE_TESTS = list(
    dict.fromkeys(
        [*_XLSX_CORE_TESTS, *_XLSX_COMPLETION_TESTS, *_XLSX_ADVANCED_TESTS]
    )
)

_XLSX_CORE_DESCRIPTION = (
    "Original Core XLSX read, inspect, create, or edit contract, implementation, "
    "Skill guidance, direct tests, or release evidence."
)
_XLSX_COMPLETION_DESCRIPTION = (
    "XLSX completion recalculation, conversion, template, summary, pivot, schema, "
    "or render contract, implementation, Skill guidance, direct tests, or release evidence."
)
_XLSX_ADVANCED_DESCRIPTION = (
    "XLSX advanced authoring and typed inspection for native charts, pivots, "
    "sparklines, tables, validations, conditional formats, annotations, worksheet "
    "metadata, formula analysis, and inert macro/signature preservation."
)
_XLSX_CORE_ADVANCED_DESCRIPTION = (
    "Shared original Core and advanced-authoring XLSX read, inspect, create/edit "
    "support, typed projections, validation, direct tests, or Skill guidance."
)
_XLSX_COMPLETION_ADVANCED_DESCRIPTION = (
    "Shared XLSX completion and advanced-authoring formula, macro, template, pivot, "
    "format-policy, direct-test, or Skill-guidance support."
)
_XLSX_ALL_CHANGE_DESCRIPTION = (
    "Shared original Core, completion-operation, and advanced-authoring XLSX contracts, "
    "orchestration, validation, Skill facade, direct tests, or release evidence."
)
_XLSX_COMPOSED_DESCRIPTION = (
    "Shared Core and completion XLSX contracts, package model, orchestration, validation, "
    "Skill facade, direct tests, or release evidence."
)
_XLSX_CORE_COMPLETION_LIBREOFFICE_DESCRIPTION = (
    "Shared Core/completion XLSX formula recalculation policy, provider-result "
    "acceptance, direct tests, or Skill guidance backed by LibreOffice."
)
_XLSX_CORE_ADVANCED_LIBREOFFICE_DESCRIPTION = (
    "Shared original Core/advanced XLSX read orchestration with optional "
    "LibreOffice formula recalculation."
)
_XLSX_ALL_CHANGE_LIBREOFFICE_DESCRIPTION = (
    "Shared original Core, completion-operation, advanced-authoring, and "
    "LibreOffice XLSX recalculation or service orchestration."
)
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
    "tests/test_strategy2.py",
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
_XLSX_LIBREOFFICE_SHARED_MODULES = {
    path
    for path in _XLSX_SHARED_MODULES
    if path.startswith("src/document_skills_core/providers/libreoffice/")
} | {
    "tests/test_input_snapshot_security.py",
    "tests/test_libreoffice_hard_quota.py",
    "tests/test_libreoffice_provider.py",
}
_XLSX_DOTNET_SHARED_MODULES = {
    path
    for path in _XLSX_SHARED_MODULES
    if path.startswith("src/document_skills_core/providers/dotnet/")
} | {"tests/test_dotnet_provider.py"}
_XLSX_SHARED_ADVANCED_MODULES = (
    _XLSX_SHARED_MODULES
    - _XLSX_DOTNET_SHARED_MODULES
    - _XLSX_LIBREOFFICE_SHARED_MODULES
    - {"src/document_skills_core/formats/pdf/byte_preflight.py"}
)
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
_XLSX_SHARED_ADVANCED_TESTS = list(
    dict.fromkeys([*_XLSX_SHARED_TESTS, *_XLSX_ADVANCED_TESTS])
)
_XLSX_NUGET_DESCRIPTION = (
    "Exact NuGet dependency lock, allowlist, license, notice, and SBOM evidence "
    "for the bounded OpenXML helper used by XLSX completion schema validation."
)
_XLSX_RUNTIME_SOURCE_DESCRIPTION = (
    "Strict value-flow runtime file inventory for the Core, completion, and "
    "advanced XLSX Python source sets and their execution-boundary audit."
)
_XLSX_SHARED_DESCRIPTION = (
    "Shared Core/completion XLSX provider execution, managed CLI supervision, and exact "
    "supply-chain policy for bounded OpenXML validation and LibreOffice rendering."
)
_XLSX_SHARED_ADVANCED_DESCRIPTION = (
    "Shared Core/completion/advanced XLSX provider execution, managed CLI "
    "supervision, and exact supply-chain policy for bounded OpenXML validation "
    "and LibreOffice rendering."
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


def cross_format_capability_module_profile(
    path: str,
) -> tuple[str, list[str]] | None:
    """Return exact evidence for the cross-format capability-report contract."""
    return _CROSS_FORMAT_CAPABILITY_MODULE_PROFILES.get(path)


def pptx_openxml_module_profile(path: str) -> tuple[str, list[str]] | None:
    """Return exact evidence for optional PPTX OpenXML schema validation."""
    return _PPTX_OPENXML_MODULE_PROFILES.get(path)


def docx_template_pack_module_profile(path: str) -> tuple[str, list[str]] | None:
    if path in _DOCX_TEMPLATE_PACK_MODULES or path.startswith(
        "skills/document-docx/assets/template-packs/"
    ):
        return (_DOCX_TEMPLATE_PACK_DESCRIPTION, _DOCX_TEMPLATE_PACK_TESTS)
    return None


def docx_template_pack_data_profile(path: str) -> tuple[str, list[str]] | None:
    if (
        path == "schemas/docx-template-pack.schema.json"
        or path.startswith("skills/document-docx/assets/template-packs/")
        or "template-pack" in path
        or "template-import" in path
    ):
        return (_DOCX_TEMPLATE_PACK_DESCRIPTION, _DOCX_TEMPLATE_PACK_TESTS)
    return None


def _module_record(artifact: Any, reviewer: str) -> dict[str, Any]:
    cross_format_profile = cross_format_capability_module_profile(artifact.path)
    pptx_profile = pptx_module_profile(artifact.path)
    pptx_openxml_profile = pptx_openxml_module_profile(artifact.path)
    xlsx_profile = xlsx_module_profile(artifact.path)
    readme_profile = readme_system_profile(artifact.path)
    template_pack_profile = docx_template_pack_module_profile(artifact.path)
    pptx_record_profile = (
        (pptx_profile[0], pptx_profile[1]) if pptx_profile else None
    )
    format_profile = _combined_profile(
        cross_format_profile,
        pptx_record_profile,
        pptx_openxml_profile,
        readme_profile,
        template_pack_profile,
    )
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
    is_pdf_tools = "/pdf_tools/" in artifact.path
    is_pdf = (
        "/pdf/" in artifact.path
        or "/pypdf/" in artifact.path
        or "/pdf_tools/" in artifact.path
        or "document-pdf" in artifact.path
        or "pdf_" in artifact.path
        or "pdf-" in artifact.path
    )
    format_requirement = _compose_requirements(
        FOUNDATION_REQUIREMENT if pptx_openxml_profile else None,
        CROSS_FORMAT_CAPABILITY_REQUIREMENT
        if cross_format_profile
        else None,
        pptx_profile[2] if pptx_profile else None,
        OPENXML_DOTNET_REQUIREMENT if pptx_openxml_profile else None,
        README_SYSTEM_REQUIREMENT if readme_profile else None,
        DOCX_TEMPLATE_PACK_REQUIREMENT if template_pack_profile else None,
    )
    base_requirement = (
        format_requirement
        if format_profile
        else DOCX_CONSUMER_GATES_REQUIREMENT
        if is_docx_consumer_gate
        else CONSUMER_GATES_REQUIREMENT
        if is_consumer_gate
        else "Rasen document-skills-core-docx"
        if is_docx
        else PDF_COMPLETION_REQUIREMENT
        if is_pdf
        else FOUNDATION_REQUIREMENT
    )
    requirement = (
        _xlsx_module_requirement(artifact.path, base_requirement)
        if xlsx_profile
        else base_requirement
    )
    tests = _merged_values(format_profile[1], xlsx_profile[1]) if (
        format_profile and xlsx_profile
    ) else _merged_values(
        [
            "tests/test_consumer_validation.py",
            "tests/test_consumer_validation_strategy3.py",
            "tests/test_cross_format_transactions.py",
        ],
        xlsx_profile[1],
    ) if is_consumer_gate and xlsx_profile else format_profile[1] if (
        format_profile
    ) else xlsx_profile[1] if (
        xlsx_profile
    ) else (
        [
            "tests/test_pdf_tools_provider.py",
            "tests/test_pdf_render_diff.py",
            "tests/test_pdf_public.py",
            "tests/test_supply_chain.py",
        ]
        if is_pdf_tools
        else ["tests/test_docx_fixtures.py", "tests/test_supply_chain.py"]
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
            "tests/test_pdf_contracts.py",
            "tests/test_pdf_operations.py",
            "tests/test_pdf_public.py",
            "tests/test_supply_chain.py",
        ]
        if is_pdf
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
        "requirement_source": requirement,
        "implementation_source": "Original Elftia project code",
        "third_party_files": [],
        "license": "GPL-3.0",
        "modifications": (
            f"{format_profile[0]} {xlsx_profile[0]}"
            if format_profile and xlsx_profile
            else (
                "Independent bounded consumer validation, truthful PDF identity, "
                "typed Office timeout cleanup, cross-format preservation, or their "
                f"direct Strategy-4 regression evidence. {xlsx_profile[0]}"
            )
            if is_consumer_gate and xlsx_profile
            else format_profile[0]
            if format_profile
            else xlsx_profile[0]
            if xlsx_profile
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
                "PDF completion contracts, Core/provider implementations, atomic "
                "validation, truthful capability reporting, Skill guidance, tests, "
                "or release evidence."
            )
            if is_pdf
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
    template_b2_profile = template_b2_data_profile(artifact.path)
    template_b4_profile = template_b4_data_profile(artifact.path)
    svg_b5_profile = svg_b5_data_profile(artifact.path)
    equation_b6_profile = equation_b6_data_profile(artifact.path)
    reconstruction_b7_profile = reconstruction_b7_data_profile(artifact.path)
    xlsx_profile = xlsx_data_profile(artifact.path)
    readme_profile = readme_system_profile(artifact.path)
    template_pack_profile = docx_template_pack_data_profile(artifact.path)
    selected_profiles = [
        profile
        for profile in (
            html_profile,
            template_b2_profile,
            template_b4_profile,
            svg_b5_profile,
            equation_b6_profile,
            reconstruction_b7_profile,
            xlsx_profile,
            readme_profile,
            template_pack_profile,
        )
        if profile is not None
    ]
    modifications = (
        " ".join(profile[0] for profile in selected_profiles)
        if selected_profiles
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
        base_requirement = (
            _compose_requirements(
                HTML_PPTX_REQUIREMENT if html_profile else None,
                PPTX_TEMPLATE_B2_REQUIREMENT if template_b2_profile else None,
                PPTX_TEMPLATE_B4_REQUIREMENT if template_b4_profile else None,
                PPTX_SVG_B5_REQUIREMENT if svg_b5_profile else None,
                PPTX_EQUATION_B6_REQUIREMENT if equation_b6_profile else None,
                PPTX_RECONSTRUCTION_B7_REQUIREMENT
                if reconstruction_b7_profile
                else None,
                README_SYSTEM_REQUIREMENT if readme_profile else None,
                DOCX_TEMPLATE_PACK_REQUIREMENT if template_pack_profile else None,
            )
            if (
                html_profile
                or template_b2_profile
                or template_b4_profile
                or svg_b5_profile
                or equation_b6_profile
                or reconstruction_b7_profile
                or readme_profile
                or template_pack_profile
            )
            else None
        )
        requirement = (
            _xlsx_data_requirement(artifact.path, base_requirement)
            if xlsx_profile
            else base_requirement
        )
        tests: list[str] = []
        for profile in selected_profiles:
            tests = _merged_values(tests, profile[1])
        record.update({
            "requirement_source": requirement,
            "modifications": modifications,
            "artifact_tests": tests,
        })
    return record


def xlsx_module_profile(path: str) -> tuple[str, list[str]] | None:
    """Return direct evidence only for explicitly enumerated XLSX artifacts."""
    if path in _XLSX_CORE_MODULES:
        return (_XLSX_CORE_DESCRIPTION, _XLSX_CORE_TESTS)
    if path in _XLSX_COMPLETION_MODULES:
        return (_XLSX_COMPLETION_DESCRIPTION, _XLSX_COMPLETION_TESTS)
    if path in _XLSX_ADVANCED_MODULES:
        return (_XLSX_ADVANCED_DESCRIPTION, _XLSX_ADVANCED_TESTS)
    if path in _XLSX_CORE_ADVANCED_MODULES:
        return (_XLSX_CORE_ADVANCED_DESCRIPTION, _XLSX_CORE_ADVANCED_TESTS)
    if path in _XLSX_COMPLETION_ADVANCED_MODULES:
        return (
            _XLSX_COMPLETION_ADVANCED_DESCRIPTION,
            _XLSX_COMPLETION_ADVANCED_TESTS,
        )
    if path in _XLSX_ALL_CHANGE_MODULES:
        return (_XLSX_ALL_CHANGE_DESCRIPTION, _XLSX_ALL_CHANGE_TESTS)
    if path in _XLSX_COMPOSED_MODULES:
        return (_XLSX_COMPOSED_DESCRIPTION, _XLSX_COMPOSED_TESTS)
    if path in _XLSX_CORE_COMPLETION_LIBREOFFICE_MODULES:
        return (
            _XLSX_CORE_COMPLETION_LIBREOFFICE_DESCRIPTION,
            _XLSX_COMPOSED_TESTS,
        )
    if path in _XLSX_CORE_ADVANCED_LIBREOFFICE_MODULES:
        return (
            _XLSX_CORE_ADVANCED_LIBREOFFICE_DESCRIPTION,
            _XLSX_ALL_CHANGE_TESTS,
        )
    if path in _XLSX_ALL_CHANGE_LIBREOFFICE_MODULES:
        return (
            _XLSX_ALL_CHANGE_LIBREOFFICE_DESCRIPTION,
            _XLSX_ALL_CHANGE_TESTS,
        )
    return xlsx_shared_module_profile(path)


def readme_system_profile(path: str) -> tuple[str, list[str]] | None:
    """Return direct evidence only for the new README hierarchy artifacts."""
    if path in _README_SYSTEM_DATA_ARTIFACTS or path in _README_SYSTEM_MODULES:
        return (_README_SYSTEM_DESCRIPTION, _README_SYSTEM_TESTS)
    return None


def xlsx_data_profile(path: str) -> tuple[str, list[str]] | None:
    """Return direct evidence only for explicitly enumerated XLSX data artifacts."""
    if path in _XLSX_CORE_DATA_ARTIFACTS:
        return (_XLSX_CORE_DESCRIPTION, _XLSX_CORE_TESTS)
    if path in _XLSX_COMPLETION_DATA_ARTIFACTS:
        return (_XLSX_COMPLETION_DESCRIPTION, _XLSX_COMPLETION_TESTS)
    if path in _XLSX_ADVANCED_DATA_ARTIFACTS:
        return (_XLSX_ADVANCED_DESCRIPTION, _XLSX_ADVANCED_TESTS)
    if path in _XLSX_CORE_ADVANCED_DATA_ARTIFACTS:
        return (_XLSX_CORE_ADVANCED_DESCRIPTION, _XLSX_CORE_ADVANCED_TESTS)
    if path in _XLSX_COMPLETION_ADVANCED_DATA_ARTIFACTS:
        return (
            _XLSX_COMPLETION_ADVANCED_DESCRIPTION,
            _XLSX_COMPLETION_ADVANCED_TESTS,
        )
    if path in _XLSX_ALL_CHANGE_DATA_ARTIFACTS:
        return (_XLSX_ALL_CHANGE_DESCRIPTION, _XLSX_ALL_CHANGE_TESTS)
    if path in _XLSX_COMPOSED_DATA_ARTIFACTS:
        return (_XLSX_COMPOSED_DESCRIPTION, _XLSX_COMPOSED_TESTS)
    if path in _XLSX_CORE_COMPLETION_LIBREOFFICE_DATA_ARTIFACTS:
        return (
            _XLSX_CORE_COMPLETION_LIBREOFFICE_DESCRIPTION,
            _XLSX_COMPOSED_TESTS,
        )
    return xlsx_shared_data_profile(path)


def _xlsx_module_requirement(path: str, base_requirement: str) -> str:
    if path in _XLSX_CORE_MODULES:
        return XLSX_REQUIREMENT
    if path in _XLSX_COMPLETION_MODULES:
        return XLSX_COMPLETION_REQUIREMENT
    if path in _XLSX_ADVANCED_MODULES:
        return XLSX_ADVANCED_REQUIREMENT
    if path in _XLSX_CORE_ADVANCED_MODULES:
        return _compose_requirements(
            XLSX_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_COMPLETION_ADVANCED_MODULES:
        return _compose_requirements(
            XLSX_COMPLETION_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_ALL_CHANGE_MODULES:
        return _compose_requirements(
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_COMPOSED_MODULES:
        return _compose_requirements(
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
        )
    if path in _XLSX_CORE_COMPLETION_LIBREOFFICE_MODULES:
        return _compose_requirements(
            LIBREOFFICE_REQUIREMENT,
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
        )
    if path in _XLSX_CORE_ADVANCED_LIBREOFFICE_MODULES:
        return _compose_requirements(
            LIBREOFFICE_REQUIREMENT,
            XLSX_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_ALL_CHANGE_LIBREOFFICE_MODULES:
        return _compose_requirements(
            LIBREOFFICE_REQUIREMENT,
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_LIBREOFFICE_SHARED_MODULES:
        base_requirement = LIBREOFFICE_REQUIREMENT
    elif path in _XLSX_DOTNET_SHARED_MODULES:
        base_requirement = OPENXML_DOTNET_REQUIREMENT
    requirements = [
        base_requirement,
        XLSX_REQUIREMENT,
        XLSX_COMPLETION_REQUIREMENT,
    ]
    if path in _XLSX_SHARED_ADVANCED_MODULES:
        requirements.append(XLSX_ADVANCED_REQUIREMENT)
    return _compose_requirements(*requirements)


def _xlsx_data_requirement(path: str, base_requirement: str | None) -> str:
    if path in _XLSX_CORE_DATA_ARTIFACTS:
        return XLSX_REQUIREMENT
    if path in _XLSX_COMPLETION_DATA_ARTIFACTS:
        return XLSX_COMPLETION_REQUIREMENT
    if path in _XLSX_ADVANCED_DATA_ARTIFACTS:
        return XLSX_ADVANCED_REQUIREMENT
    if path in _XLSX_CORE_ADVANCED_DATA_ARTIFACTS:
        return _compose_requirements(
            XLSX_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_COMPLETION_ADVANCED_DATA_ARTIFACTS:
        return _compose_requirements(
            XLSX_COMPLETION_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_ALL_CHANGE_DATA_ARTIFACTS:
        return _compose_requirements(
            base_requirement,
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    if path in _XLSX_COMPOSED_DATA_ARTIFACTS:
        return _compose_requirements(
            base_requirement,
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
        )
    if path in _XLSX_CORE_COMPLETION_LIBREOFFICE_DATA_ARTIFACTS:
        return _compose_requirements(
            LIBREOFFICE_REQUIREMENT,
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
        )
    if path == "provenance/runtime-source-allowlist.json":
        return _compose_requirements(
            base_requirement,
            XLSX_REQUIREMENT,
            XLSX_COMPLETION_REQUIREMENT,
            XLSX_ADVANCED_REQUIREMENT,
        )
    return _compose_requirements(
        base_requirement,
        OPENXML_DOTNET_REQUIREMENT,
        XLSX_REQUIREMENT,
        XLSX_COMPLETION_REQUIREMENT,
    )


def xlsx_shared_module_profile(path: str) -> tuple[str, list[str]] | None:
    if path not in _XLSX_SHARED_MODULES:
        return None
    tests = (
        _XLSX_SHARED_ADVANCED_TESTS
        if path in _XLSX_SHARED_ADVANCED_MODULES
        else _XLSX_SHARED_TESTS
    )
    shared_description = (
        _XLSX_SHARED_ADVANCED_DESCRIPTION
        if path in _XLSX_SHARED_ADVANCED_MODULES
        else _XLSX_SHARED_DESCRIPTION
    )
    if path.endswith("/dotnet/helper/packages.lock.json"):
        return (_XLSX_NUGET_DESCRIPTION, tests)
    if path in _XLSX_ATOMIC_LAUNCH_ONLY_MODULES:
        return (_XLSX_ATOMIC_LAUNCH_DESCRIPTION, tests)
    if path in _XLSX_ATOMIC_LAUNCH_COMPOSED_MODULES:
        return (
            f"{shared_description} {_XLSX_ATOMIC_LAUNCH_DESCRIPTION}",
            tests,
        )
    return (shared_description, tests)


def xlsx_shared_data_profile(path: str) -> tuple[str, list[str]] | None:
    if path not in _XLSX_SHARED_DATA_ARTIFACTS:
        return None
    if path == "provenance/runtime-source-allowlist.json":
        return (
            _XLSX_RUNTIME_SOURCE_DESCRIPTION,
            _XLSX_SHARED_ADVANCED_TESTS,
        )
    return (
        _XLSX_NUGET_DESCRIPTION,
        _XLSX_SHARED_TESTS,
    )


def _compose_requirements(*requirements: str | None) -> str:
    components: list[str] = []
    for requirement in requirements:
        if not requirement:
            continue
        normalized = requirement.removeprefix("Rasen ")
        for component in normalized.split(" + "):
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


def _merged_values(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


def _is_metadata(path: str) -> bool:
    return path in SELF_REFERENTIAL_METADATA_ALLOWLIST


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
