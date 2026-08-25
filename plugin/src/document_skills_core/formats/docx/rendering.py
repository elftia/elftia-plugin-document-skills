"""Bounded DOCX page evidence rendered through LibreOffice."""

import base64
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.formats.pdf.edit import edit_pdf
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pptx.png_compare import decode_png

from .contracts import ParsedDocxRequest
from .conversion import validate_pdf_conversion, validate_pdf_render
from .layout_inspection import inspect_rendered_layout
from .package import OpcPackage
from .transaction import promote_candidate, write_candidate_result


def render_pdf_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
) -> dict[str, Any]:
    """Convert, select the requested pages, validate, and promote PDF evidence."""

    assert request.input_path is not None
    assert request.output_path is not None
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    OpcPackage.open(request.input_path)
    if libreoffice is None:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "DOCX rendering requires the LibreOffice provider.",
            status="unavailable",
            details={"recommended_providers": ["libreoffice"]},
        )
    convert_pdf = libreoffice.convert_pdf

    try:
        with OperationTempRoot() as private_root:
            converted = private_root / "converted.pdf"
            pdf_bytes = convert_pdf(
                request.input_path,
                request.arguments["max_total_bytes"],
            )
            if type(pdf_bytes) is not bytes:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice returned an invalid PDF render payload.",
                )
            converted.write_bytes(pdf_bytes)
            _, converted_evidence = validate_pdf_conversion(
                converted,
                source=request.input_path,
                source_sha256=source_record.sha256,
                max_output_bytes=request.arguments["max_total_bytes"],
            )
            staged, expected_pages = _select_pages(
                converted,
                converted_pages=int(converted_evidence["pages"]),
                page_range=request.arguments["page_range"],
                max_pages=request.arguments["max_pages"],
                private_root=private_root,
            )
            validation, reopened = validate_pdf_render(
                staged,
                source=request.input_path,
                source_sha256=source_record.sha256,
                expected_pages=expected_pages,
                max_total_bytes=request.arguments["max_total_bytes"],
            )
            render_result = {
                "format": "pdf",
                "page_range": request.arguments["page_range"],
                "dpi": request.arguments["dpi"],
                "conversion_succeeded": True,
                "pages_generated": True,
                "page_count": reopened["pages"],
                "total_bytes": staged.stat().st_size,
                "visual_comparison": "unavailable",
            }
            if request.arguments["include_page_pngs"]:
                page_evidence, internal_pages = _render_page_evidence(
                    staged,
                    original_range=request.arguments["page_range"],
                    maximum_page_bytes=request.arguments["max_page_bytes"],
                    maximum_total_bytes=request.arguments["max_png_total_bytes"],
                    libreoffice=libreoffice,
                    private_root=private_root,
                )
                layout = inspect_rendered_layout(
                    request.input_path,
                    internal_pages,
                    dpi=request.arguments["dpi"],
                )
                identity = _provider_identity(libreoffice)
                render_result.update(
                    {
                        "render_status": "pass",
                        "page_generation_status": "pass",
                        "layout_status": layout["status"],
                        "visual_comparison_status": "unavailable",
                        "render_engine": identity,
                        "font_inventory": {
                            "status": "unavailable",
                            "fonts": [],
                        },
                        "page_evidence": page_evidence,
                        "layout": layout,
                    }
                )
                validation["gates"].append(
                    gate_record(
                        "operation.docx-render-png-pages",
                        "pass",
                        evidence={
                            "page_count": len(page_evidence),
                            "total_bytes": sum(page["bytes"] for page in page_evidence),
                            "dpi": request.arguments["dpi"],
                        },
                    )
                )
                validation["gates"].append(
                    gate_record(
                        "operation.docx-layout-rules",
                        "fail" if layout["status"] == "fail" else "pass",
                        required=False,
                        evidence={
                            "status": layout["status"],
                            "finding_count": len(layout["findings"]),
                        },
                    )
                )
            operation_result = {"render": render_result}
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=source_record,
                achieved_fidelity="enhanced",
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source_record,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(
            error,
            source_record.path,
            source_record.sha256,
        )
        raise


def _render_page_evidence(
    pdf: Path,
    *,
    original_range: str | dict[str, int],
    maximum_page_bytes: int,
    maximum_total_bytes: int,
    libreoffice: Any,
    private_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raster = (
        libreoffice.try_render_to_image
        if hasattr(libreoffice, "try_render_to_image")
        else None
    )
    if not callable(raster):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "LibreOffice provider does not expose bounded PNG raster evidence.",
            status="unavailable",
        )
    pages = walk_pages(parse_pdf(pdf))
    first_source_page = 1 if original_range == "all" else original_range["start"]
    public_pages = []
    internal_pages = []
    total_bytes = 0
    for index, page in enumerate(pages, start=1):
        if len(pages) == 1:
            one_page = pdf
        else:
            one_page = private_root / f"page-{index:04d}.pdf"
            edit_pdf(
                pdf,
                one_page,
                {"primitives": [{"type": "split", "page_ranges": [[index, index]]}]},
            )
        payload = raster(one_page)
        if type(payload) is not bytes:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice did not return a PNG page payload.",
                details={"render_index": index},
            )
        if len(payload) > maximum_page_bytes:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Rendered PNG page exceeds the caller-selected byte limit.",
                details={"render_index": index, "bytes": len(payload)},
            )
        total_bytes += len(payload)
        if total_bytes > maximum_total_bytes:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Rendered PNG pages exceed the aggregate byte limit.",
                details={"total_bytes": total_bytes},
            )
        width, height, _ = decode_png(payload)
        x0, y0, x1, y1 = page.media_box
        point_width, point_height = x1 - x0, y1 - y0
        if page.rotation % 180:
            point_width, point_height = point_height, point_width
        source_page = first_source_page + index - 1
        common = {
            "render_index": index,
            "source_page": source_page,
            "dimensions_px": {"width": width, "height": height},
            "dimensions_points": {
                "width": round(point_width, 3),
                "height": round(point_height, 3),
            },
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
        }
        public_pages.append(
            {
                **common,
                "png_base64": base64.b64encode(payload).decode("ascii"),
            }
        )
        internal_pages.append({**common, "payload": payload})
    return public_pages, internal_pages


def _provider_identity(libreoffice: Any) -> dict[str, Any]:
    detector = libreoffice.detector if hasattr(libreoffice, "detector") else None
    detect = detector.detect if detector is not None and hasattr(detector, "detect") else None
    if callable(detect):
        evidence = detect()
        return {
            "id": "libreoffice",
            "version": evidence.version if hasattr(evidence, "version") else None,
        }
    return {"id": "libreoffice", "version": None}


def _select_pages(
    converted: Path,
    *,
    converted_pages: int,
    page_range: str | dict[str, int],
    max_pages: int,
    private_root: Path,
) -> tuple[Path, int]:
    if page_range == "all":
        start, end = 1, converted_pages
    else:
        start, end = page_range["start"], page_range["end"]
        if end > converted_pages:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Requested render page range exceeds the converted document.",
                details={
                    "converted_pages": converted_pages,
                    "requested_page_range": page_range,
                },
            )
    expected_pages = end - start + 1
    if expected_pages > max_pages:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Rendered document exceeds the requested page limit.",
            details={
                "max_pages": max_pages,
                "requested_pages": expected_pages,
            },
        )
    if start == 1 and end == converted_pages:
        return converted, expected_pages

    staged = private_root / "rendered.pdf"
    edit_pdf(
        converted,
        staged,
        {"primitives": [{"type": "split", "page_ranges": [[start, end]]}]},
    )
    return staged, expected_pages
