"""Bounded render-inspect-repair loop for deterministic layout findings."""

from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
    sha256_file,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .constants import qn
from .contracts import ParsedDocxRequest
from .conversion import validate_pdf_conversion
from .layout_inspection import inspect_rendered_layout
from .package import OpcPackage
from .rendering import _provider_identity, _render_page_evidence
from .semantic_nodes import semantic_node_for
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_mutation
from .xml_utils import xml_bytes

_WIDTH_CODE = "DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH"
_EMU_PER_TWIP = 635


def layout_repair_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    if libreoffice is None:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Layout repair requires the LibreOffice render provider.",
            status="unavailable",
        )
    try:
        original = OpcPackage.open(request.input_path)
        with OperationTempRoot() as private_root:
            current_path = request.input_path
            current_package = original
            current_layout, initial_render = _inspect(
                current_path,
                request,
                libreoffice,
                private_root,
                label="initial",
            )
            initial_layout = current_layout
            current_score = _score(current_layout)
            initial_score = current_score
            seen = {source.sha256}
            repaired_ids: set[str] = set()
            history = []
            stop_reason = "max_rounds"
            for round_number in range(1, request.arguments["max_rounds"] + 1):
                repairable = _repairable_findings(current_layout, request.arguments)
                if not repairable:
                    stop_reason = "resolved_repairable"
                    break
                candidate = private_root / f"repair-{round_number}.docx"
                applied = _repair_widths(current_package, repairable, candidate)
                if not applied:
                    stop_reason = "no_applicable_repair"
                    break
                candidate_hash = sha256_file(candidate)
                if candidate_hash in seen:
                    stop_reason = "oscillation"
                    break
                seen.add(candidate_hash)
                candidate_layout, candidate_render = _inspect(
                    candidate,
                    request,
                    libreoffice,
                    private_root,
                    label=f"round-{round_number}",
                )
                candidate_score = _score(candidate_layout)
                improved = candidate_score < current_score
                history.append(
                    {
                        "round": round_number,
                        "before_score": current_score,
                        "after_score": candidate_score,
                        "improved": improved,
                        "applied_node_ids": sorted(applied),
                        "render": candidate_render,
                    }
                )
                if not improved:
                    stop_reason = "no_improvement"
                    break
                current_path = candidate
                current_package = OpcPackage.open(candidate)
                current_layout = candidate_layout
                current_score = candidate_score
                repaired_ids.update(applied)
                if not _repairable_findings(current_layout, request.arguments):
                    stop_reason = "resolved_repairable"
                    break
            if current_path == request.input_path:
                copied = private_root / "repair-noop.docx"
                original.write_copy(copied, changed_parts={})
                current_path = copied
                current_package = OpcPackage.open(copied)
            manifest = original.compare_preservation(
                current_package,
                allowed_changed={"word/document.xml"},
            )
            validation = validate_mutation(
                current_path,
                source=request.input_path,
                source_sha256=source.sha256,
                manifest=manifest,
                assertion=lambda _candidate: {
                    "bounded_rounds": len(history),
                    "final_layout_status": current_layout["status"],
                    "unresolved_findings": len(current_layout["findings"]),
                },
            )
            operation_result = {
                "layout_repair": {
                    "rounds": len(history),
                    "max_rounds": request.arguments["max_rounds"],
                    "stop_reason": stop_reason,
                    "initial_score": initial_score,
                    "final_score": current_score,
                    "improved": current_score < initial_score,
                    "repaired_node_ids": sorted(repaired_ids),
                    "initial_layout": initial_layout,
                    "final_layout": current_layout,
                    "initial_render": initial_render,
                    "round_history": history,
                    "unresolved_findings": current_layout["findings"],
                    "visual_comparison": "unavailable",
                    "render_engine": _provider_identity(libreoffice),
                },
                "preservation": manifest.as_dict(),
            }
            warnings = (
                [
                    {
                        "code": "DS_LAYOUT_FINDINGS_REMAIN",
                        "message": "Bounded layout repair left unresolved findings.",
                        "details": {
                            "count": len(current_layout["findings"]),
                            "stop_reason": stop_reason,
                        },
                    }
                ]
                if current_layout["findings"]
                else []
            )
            result = write_candidate_result(
                schemas,
                request,
                current_path,
                validation,
                operation_result,
                warnings=warnings,
                source=source,
                achieved_fidelity="enhanced",
            )
            return promote_candidate(
                request,
                current_path,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _inspect(
    source: Path,
    request: ParsedDocxRequest,
    libreoffice: Any,
    private_root: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pdf = private_root / f"{label}.pdf"
    payload = libreoffice.convert_pdf(
        source,
        request.arguments["max_total_bytes"],
    )
    if type(payload) is not bytes:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice returned an invalid PDF during layout repair.",
        )
    pdf.write_bytes(payload)
    _, evidence = validate_pdf_conversion(
        pdf,
        source=source,
        source_sha256=sha256_file(source),
        max_output_bytes=request.arguments["max_total_bytes"],
    )
    page_count = int(evidence["pages"])
    if page_count > request.arguments["max_pages"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Layout repair render exceeds the page limit.",
            details={"pages": page_count, "max_pages": request.arguments["max_pages"]},
        )
    page_root = private_root / f"{label}-pages"
    page_root.mkdir()
    page_evidence, internal_pages = _render_page_evidence(
        pdf,
        original_range="all",
        maximum_page_bytes=4 * 1024 * 1024,
        maximum_total_bytes=request.arguments["max_png_total_bytes"],
        libreoffice=libreoffice,
        private_root=page_root,
    )
    layout = inspect_rendered_layout(source, internal_pages, dpi=96)
    render = {
        "page_count": page_count,
        "pdf_sha256": sha256(payload).hexdigest(),
        "page_pngs": [
            {
                key: value
                for key, value in page.items()
                if key != "png_base64"
            }
            for page in page_evidence
        ],
    }
    return layout, render


def _repairable_findings(
    layout: dict[str, Any],
    arguments: dict[str, Any],
) -> list[dict[str, Any]]:
    allowed = set(arguments["finding_codes"])
    return [finding for finding in layout["findings"] if finding["code"] in allowed]


def _repair_widths(
    package: OpcPackage,
    findings: list[dict[str, Any]],
    output: Path,
) -> set[str]:
    root = package.xml("word/document.xml")
    requested_ids = {
        finding["semantic_node_id"]
        for finding in findings
        if finding["code"] == _WIDTH_CODE and finding["semantic_node_id"] is not None
    }
    available = _available_width_emu(root)
    applied: set[str] = set()
    for paragraph in root.iter(qn("w", "p")):
        semantic = semantic_node_for(paragraph)
        if semantic is None or semantic.node_id not in requested_ids:
            continue
        for extent in paragraph.iter(qn("wp", "extent")):
            try:
                old_width = int(extent.attrib["cx"])
                old_height = int(extent.attrib["cy"])
            except (KeyError, ValueError):
                continue
            if old_width <= available:
                continue
            new_height = max(1, round(old_height * available / old_width))
            extent.attrib["cx"] = str(available)
            extent.attrib["cy"] = str(new_height)
            for drawing_extent in paragraph.iter(qn("a", "ext")):
                drawing_extent.attrib["cx"] = str(available)
                drawing_extent.attrib["cy"] = str(new_height)
            applied.add(semantic.node_id)
    if not applied:
        return set()
    package.write_copy(
        output,
        changed_parts={"word/document.xml": xml_bytes(root)},
    )
    return applied


def _available_width_emu(root: Any) -> int:
    section = next(root.iter(qn("w", "sectPr")), None)
    if section is None:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Layout repair requires explicit section geometry.",
        )
    size = section.find(qn("w", "pgSz"))
    margins = section.find(qn("w", "pgMar"))
    try:
        width = int(size.attrib[qn("w", "w")])
        left = int(margins.attrib[qn("w", "left")])
        right = int(margins.attrib[qn("w", "right")])
    except (AttributeError, KeyError, ValueError) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Layout repair could not resolve section width.",
        ) from error
    return (width - left - right) * _EMU_PER_TWIP


def _score(layout: dict[str, Any]) -> int:
    weights = {"error": 100, "warning": 10, "info": 1}
    return sum(weights.get(finding["severity"], 1) for finding in layout["findings"])
