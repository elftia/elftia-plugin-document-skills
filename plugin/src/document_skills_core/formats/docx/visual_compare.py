"""Fixed-profile reference-aware DOCX page visual comparison."""

import base64
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.io.paths import assert_source_preserved, file_record, sha256_file
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.formats.pptx.png_compare import (
    compare_png,
    decode_png,
    encode_rgba_png,
    visual_thresholds,
)

from .contracts import ParsedDocxRequest
from .conversion import validate_pdf_conversion
from .rendering import _provider_identity, _render_page_evidence
from .results import read_validation, success_result

_SAMPLE_WIDTH = 96
_SAMPLE_HEIGHT = 54


def visual_compare_operation(
    request: ParsedDocxRequest,
    *,
    libreoffice: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    if libreoffice is None:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Reference visual comparison requires LibreOffice.",
            status="unavailable",
        )
    actual_record = file_record(request.input_path, "input")
    reference_record = file_record(request.arguments["reference"], "input")
    if reference_record.sha256 != request.arguments["expected_reference_sha256"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Visual reference precondition did not match.",
            details={"reason": "reference-sha256"},
        )
    with OperationTempRoot() as private_root:
        actual_pages = _render_docx(
            request.input_path,
            label="actual",
            request=request,
            libreoffice=libreoffice,
            private_root=private_root,
        )
        reference_pages = _reference_pages(
            request.arguments["reference"],
            request=request,
            libreoffice=libreoffice,
            private_root=private_root,
        )
        comparison = _compare_pages(
            actual_pages,
            reference_pages,
            request.arguments["page_pairs"],
        )
    assert_source_preserved(actual_record.path, actual_record.sha256)
    assert_source_preserved(reference_record.path, reference_record.sha256)
    comparison.update(
        {
            "render_profile": {
                "id": "libreoffice-96dpi-v1",
                "version": "1.0",
                "dpi": 96,
                "color_space": "sRGB-RGBA8",
            },
            "render_engine": _provider_identity(libreoffice),
            "thresholds": visual_thresholds(),
            "degradations": [
                {
                    "code": "DOCX_VISUAL_TYPOGRAPHY_SPACING_NOT_ISOLATED",
                    "message": (
                        "Raster comparison reports aggregate color/placement deltas; "
                        "typography and spacing are not independently classified."
                    ),
                }
            ],
        }
    )
    validation = read_validation(
        "operation.reference-visual-compare-executed",
        {"visual_comparison": comparison},
    )
    visual_gate = next(
        gate for gate in validation["gates"] if gate["id"] == "visual.render"
    )
    visual_gate.update(
        {
            "outcome": "pass",
            "evidence": {
                "actual_pages": len(actual_pages),
                "reference_pages": len(reference_pages),
            },
            "warnings": [],
        }
    )
    validation["gates"].append(
        gate_record(
            "operation.reference-visual-compare-result",
            "pass" if comparison["status"] == "pass" else "fail",
            required=False,
            evidence={
                "status": comparison["status"],
                "pairs": len(comparison["comparisons"]),
                "page_count_match": comparison["page_count_match"],
                "complete_pairing": comparison["complete_pairing"],
            },
        )
    )
    return success_result(
        request,
        artifacts=[actual_record.as_dict(), reference_record.as_dict()],
        operation_result={"visual_comparison": comparison},
        warnings=[],
        validation=validation,
        achieved_fidelity="enhanced",
    )


def _render_docx(
    source: Path,
    *,
    label: str,
    request: ParsedDocxRequest,
    libreoffice: Any,
    private_root: Path,
) -> list[dict[str, Any]]:
    pdf = private_root / f"{label}.pdf"
    payload = libreoffice.convert_pdf(source, request.arguments["max_total_bytes"])
    if type(payload) is not bytes:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice returned an invalid visual-comparison PDF.",
        )
    pdf.write_bytes(payload)
    _, evidence = validate_pdf_conversion(
        pdf,
        source=source,
        source_sha256=sha256_file(source),
        max_output_bytes=request.arguments["max_total_bytes"],
    )
    return _raster_pdf(
        pdf,
        int(evidence["pages"]),
        label=label,
        request=request,
        libreoffice=libreoffice,
        private_root=private_root,
    )


def _reference_pages(
    source: Path,
    *,
    request: ParsedDocxRequest,
    libreoffice: Any,
    private_root: Path,
) -> list[dict[str, Any]]:
    suffix = source.suffix.casefold()
    if suffix == ".docx":
        return _render_docx(
            source,
            label="reference",
            request=request,
            libreoffice=libreoffice,
            private_root=private_root,
        )
    if suffix == ".pdf":
        evidence = reopen_pdf(source)
        return _raster_pdf(
            source,
            int(evidence["pages"]),
            label="reference",
            request=request,
            libreoffice=libreoffice,
            private_root=private_root,
        )
    payload = source.read_bytes()
    width, height, _rgba = decode_png(payload)
    if len(payload) > request.arguments["max_png_total_bytes"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Reference PNG exceeds the comparison byte limit.",
        )
    return [
        {
            "render_index": 1,
            "source_page": 1,
            "dimensions_px": {"width": width, "height": height},
            "dimensions_points": {
                "width": round(width * 72 / 96, 3),
                "height": round(height * 72 / 96, 3),
            },
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
            "payload": payload,
        }
    ]


def _raster_pdf(
    pdf: Path,
    page_count: int,
    *,
    label: str,
    request: ParsedDocxRequest,
    libreoffice: Any,
    private_root: Path,
) -> list[dict[str, Any]]:
    if page_count > request.arguments["max_pages"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Visual comparison exceeds its page limit.",
            details={"pages": page_count},
        )
    page_root = private_root / f"{label}-pages"
    page_root.mkdir()
    _public, internal = _render_page_evidence(
        pdf,
        original_range="all",
        maximum_page_bytes=4 * 1024 * 1024,
        maximum_total_bytes=request.arguments["max_png_total_bytes"],
        libreoffice=libreoffice,
        private_root=page_root,
    )
    return internal


def _compare_pages(
    actual_pages: list[dict[str, Any]],
    reference_pages: list[dict[str, Any]],
    page_pairs: list[dict[str, int]],
) -> dict[str, Any]:
    actual = {page["source_page"]: page for page in actual_pages}
    reference = {page["source_page"]: page for page in reference_pages}
    comparisons = []
    for pair in page_pairs:
        actual_page = actual.get(pair["actual"])
        reference_page = reference.get(pair["reference"])
        if actual_page is None or reference_page is None:
            comparisons.append(
                {
                    "actual_page": pair["actual"],
                    "reference_page": pair["reference"],
                    "status": "fail",
                    "error": "paired-page-missing",
                }
            )
            continue
        comparisons.append(_compare_pair(actual_page, reference_page))
    actual_numbers = set(actual)
    reference_numbers = set(reference)
    paired_actual = {pair["actual"] for pair in page_pairs}
    paired_reference = {pair["reference"] for pair in page_pairs}
    count_match = len(actual_pages) == len(reference_pages)
    complete = paired_actual == actual_numbers and paired_reference == reference_numbers
    status = (
        "pass"
        if count_match
        and complete
        and all(item["status"] == "pass" for item in comparisons)
        else "fail"
    )
    return {
        "status": status,
        "actual_page_count": len(actual_pages),
        "reference_page_count": len(reference_pages),
        "page_count_match": count_match,
        "complete_pairing": complete,
        "page_pairs": page_pairs,
        "unpaired_actual_pages": sorted(actual_numbers - paired_actual),
        "unpaired_reference_pages": sorted(reference_numbers - paired_reference),
        "comparisons": comparisons,
    }


def _compare_pair(
    actual: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    raw = compare_png(reference["payload"], actual["payload"])
    thresholds = visual_thresholds()
    geometry_pass = raw["aspect_ratio_delta"] <= thresholds["aspect_ratio_delta_max"]
    color_pass = raw["mean_absolute_error"] <= thresholds["mean_absolute_error_max"]
    placement_pass = (
        raw["changed_pixel_ratio"] <= thresholds["changed_pixel_ratio_max"]
    )
    overlay, difference = _pair_images(actual["payload"], reference["payload"])
    status = "pass" if geometry_pass and color_pass and placement_pass else "fail"
    return {
        "actual_page": actual["source_page"],
        "reference_page": reference["source_page"],
        "status": status,
        "metrics": {
            "geometry": {
                "status": "pass" if geometry_pass else "fail",
                "actual_size": raw["rendered_size"],
                "reference_size": raw["source_size"],
                "aspect_ratio_delta": raw["aspect_ratio_delta"],
            },
            "color": {
                "status": "pass" if color_pass else "fail",
                "mean_absolute_error": raw["mean_absolute_error"],
            },
            "placement": {
                "status": "pass" if placement_pass else "fail",
                "changed_pixel_ratio": raw["changed_pixel_ratio"],
                "scope": "aggregate-raster-proxy",
            },
            "typography": {"status": "unavailable"},
            "spacing": {"status": "unavailable"},
        },
        "overlay_png": _encoded_image(overlay),
        "diff_png": _encoded_image(difference),
    }


def _pair_images(actual: bytes, reference: bytes) -> tuple[bytes, bytes]:
    actual_width, actual_height, actual_rgba = decode_png(actual)
    reference_width, reference_height, reference_rgba = decode_png(reference)
    overlay = bytearray()
    difference = bytearray()
    for y in range(_SAMPLE_HEIGHT):
        ay = min(actual_height - 1, y * actual_height // _SAMPLE_HEIGHT)
        ry = min(reference_height - 1, y * reference_height // _SAMPLE_HEIGHT)
        for x in range(_SAMPLE_WIDTH):
            ax = min(actual_width - 1, x * actual_width // _SAMPLE_WIDTH)
            rx = min(reference_width - 1, x * reference_width // _SAMPLE_WIDTH)
            left = actual_rgba[(ay * actual_width + ax) * 4 :][:4]
            right = reference_rgba[(ry * reference_width + rx) * 4 :][:4]
            overlay.extend(
                (
                    (left[0] + right[0]) // 2,
                    (left[1] + right[1]) // 2,
                    (left[2] + right[2]) // 2,
                    255,
                )
            )
            difference.extend(
                (
                    min(255, abs(left[0] - right[0]) * 4),
                    min(255, abs(left[1] - right[1]) * 4),
                    min(255, abs(left[2] - right[2]) * 4),
                    255,
                )
            )
    return (
        encode_rgba_png(_SAMPLE_WIDTH, _SAMPLE_HEIGHT, bytes(overlay)),
        encode_rgba_png(_SAMPLE_WIDTH, _SAMPLE_HEIGHT, bytes(difference)),
    )


def _encoded_image(payload: bytes) -> dict[str, Any]:
    return {
        "bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
        "base64": base64.b64encode(payload).decode("ascii"),
    }
