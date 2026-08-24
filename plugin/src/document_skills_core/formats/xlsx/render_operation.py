"""Provider-gated XLSX-to-PDF rendering with atomic promotion."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.validation import validate_artifact
from document_skills_core.formats.pdf.validation import reopen_pdf

from .contracts import parse_xlsx_request
from .formula_security import assert_provider_formula_safe
from .render_package import RenderPackageIndex
from .render_sampling import sample_render_source
from .source_snapshot import stage_source_snapshot
from .transaction import promote_candidate, write_candidate_result


def execute_render(
    request: dict[str, Any],
    *,
    project_root: Path,
    converter: Callable[[Path], bytes],
) -> dict[str, Any]:
    """Render a safe XLSX through LibreOffice and publish a validated PDF."""

    parsed = parse_xlsx_request(request)
    if parsed.operation != "xlsx.render":
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "XLSX render provider binding does not match the request operation.",
            status="invalid_request",
        )
    assert parsed.input_path is not None
    assert parsed.output_path is not None
    assert_distinct_paths(parsed.input_path, parsed.output_path, in_place=False)
    source = file_record(parsed.input_path, "input")
    destination = destination_snapshot(parsed.output_path)
    try:
        with OperationTempRoot() as private_root:
            provider_source = stage_source_snapshot(source, private_root)
            package = RenderPackageIndex.open(provider_source)
            source_evidence, warnings = sample_render_source(
                provider_source,
                parsed.arguments,
                package=package,
            )
            assert_provider_formula_safe(provider_source, package=package)
            staged = private_root / "rendered.pdf"
            staged.write_bytes(converter(provider_source))
            validation = validate_artifact(
                staged,
                expected_format="pdf",
                source_path=source.path,
                source_sha256=source.sha256,
                reopen=reopen_pdf,
                assertions=[(
                    "xlsx-render-sampling",
                    lambda _candidate: _sampling_gate_evidence(source_evidence),
                )],
                visual_available=True,
                schema_available=False,
            )
            validation = _with_render_gate(validation, source_evidence)
            pdf_evidence = _reopen_evidence(validation)
            operation_result = {
                "render": {
                    "source_format": "xlsx",
                    "target_format": "pdf",
                    "provider": "libreoffice",
                    "pdf": pdf_evidence,
                    "sampling": source_evidence,
                }
            }
            result = write_candidate_result(
                SchemaCatalog(project_root),
                parsed,
                staged,
                validation,
                operation_result,
                warnings=warnings,
                source=source,
                achieved_fidelity="enhanced",
            )
            return promote_candidate(
                parsed,
                staged,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _sampling_gate_evidence(source_evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "sheet_count": source_evidence["sheet_count"],
        "sampled_sheet_count": source_evidence["sampled_sheet_count"],
        "truncated_sheet_count": source_evidence["truncated_sheet_count"],
        "risk_finding_counts": source_evidence["risk_finding_counts"],
        "scope": source_evidence["scope"],
    }


def _with_render_gate(
    validation: dict[str, Any],
    source_evidence: dict[str, Any],
) -> dict[str, Any]:
    reopened = any(
        gate["id"] == "provider.reopen" and gate["outcome"] == "pass"
        for gate in validation["gates"]
    )
    gates = [
        gate_record(
            "xlsx.package-security",
            "pass",
            evidence={
                "policy": "reject",
                "workbook_format": source_evidence["workbook_format"],
                "security": source_evidence["security"],
            },
        )
    ]
    gates.extend([
        gate_record(
            "visual.render",
            "pass" if reopened else "fail",
            validator="libreoffice",
            evidence={
                "target_format": "pdf",
                "source_sheet_count": source_evidence["sheet_count"],
                "sampled_sheet_count": source_evidence["sampled_sheet_count"],
                "pdf_reopened": reopened,
                "claim_scope": "render-produced-and-pdf-reopened",
            },
        )
        if gate["id"] == "visual.render"
        else gate
        for gate in validation["gates"]
    ])
    return {
        "schema_version": validation["schema_version"],
        "status": (
            "pass"
            if all(not gate["required"] or gate["outcome"] == "pass" for gate in gates)
            else "fail"
        ),
        "gates": gates,
    }


def _reopen_evidence(validation: dict[str, Any]) -> dict[str, Any]:
    for gate in validation["gates"]:
        if gate["id"] == "provider.reopen" and gate["outcome"] == "pass":
            result = gate["evidence"].get("result")
            if type(result) is dict:
                return result
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Rendered PDF did not retain successful reopen evidence.",
        validation=validation,
    )
