"""Transactional LibreOffice-backed PPTX render and PDF conversion operations."""

from pathlib import Path
import shutil
import time
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.serialization import render_json_bytes
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
    sha256_file,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.validation import validate_artifact
from document_skills_core.formats.pdf.validation import reopen_pdf

from .contracts import ParsedPptxRequest, parse_pptx_request
from .deep_validation import validate_deep_package
from .package import OpcPackage, write_deterministic_zip
from .png_compare import inspect_png
from .render_validation import (
    MAX_BUNDLE_BYTES,
    MAX_PDF_BYTES,
    MAX_PNG_BYTES,
    MAX_TOTAL_PNG_BYTES,
    assert_pdf_pages,
    bounded_file,
    bounded_slide_count,
    payload_sha256,
    render_bundle_validation,
    slide_aspect_ratio,
)
from .slide_render import write_single_slide_candidate
from .transaction import promote_candidate, write_candidate_result

_RENDER_BUDGET_SECONDS = 120.0
_PER_CONVERSION_SECONDS = 30.0


def execute_pptx_libreoffice_operation(
    operation: str,
    request: dict[str, Any],
    runner: Any,
    *,
    project_root: Path,
    version: str | None,
) -> dict[str, Any]:
    parsed = parse_pptx_request(request)
    if parsed.operation != operation:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "LibreOffice PPTX provider binding does not match the request operation.",
            status="invalid_request",
        )
    if operation == "pptx.convert.pdf":
        return _convert_pdf(parsed, runner, project_root=project_root, version=version)
    if operation == "pptx.render":
        return _render_bundle(parsed, runner, project_root=project_root, version=version)
    raise DocumentSkillsError(
        ErrorCode.OPERATION_UNKNOWN,
        "The LibreOffice PPTX operation is not implemented.",
    )


def _convert_pdf(
    request: ParsedPptxRequest,
    runner: Any,
    *,
    project_root: Path,
    version: str | None,
) -> dict[str, Any]:
    assert request.input_path is not None and request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    try:
        with OperationTempRoot() as private_root:
            staged_input = _stage_source(request.input_path, source.sha256, private_root)
            deep = validate_deep_package(staged_input)
            slide_count = bounded_slide_count(deep)
            output_dir = private_root / "pdf-output"
            output_dir.mkdir()
            staged = runner.convert(
                staged_input,
                "pdf",
                output_dir,
                timeout_seconds=_PER_CONVERSION_SECONDS,
            )
            bounded_file(staged, MAX_PDF_BYTES, "Rendered PDF")
            validation = validate_artifact(
                staged,
                expected_format="pdf",
                source_path=source.path,
                source_sha256=source.sha256,
                reopen=reopen_pdf,
                assertions=[
                    ("pptx-source-deep-validation", lambda _path: deep),
                    (
                        "pptx-pdf-page-count",
                        lambda path: assert_pdf_pages(path, slide_count),
                    ),
                ],
            )
            if validation["status"] != "pass":
                _validation_failure(
                    "LibreOffice PPTX-to-PDF conversion failed validation.",
                    validation,
                )
            pdf = reopen_pdf(staged)
            result = write_candidate_result(
                request=request,
                schemas=_schema_catalog(project_root),
                staged=staged,
                validation=validation,
                operation_result={
                    "conversion": {
                        "format": "pdf",
                        "pages": pdf["pages"],
                        "provider": "libreoffice",
                        "provider_version": version,
                    }
                },
                warnings=[],
                source=source,
                achieved_fidelity="enhanced",
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _render_bundle(
    request: ParsedPptxRequest,
    runner: Any,
    *,
    project_root: Path,
    version: str | None,
) -> dict[str, Any]:
    assert request.input_path is not None and request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    started = time.monotonic()
    deadline = started + _RENDER_BUDGET_SECONDS
    try:
        with OperationTempRoot() as private_root:
            staged_input = _stage_source(request.input_path, source.sha256, private_root)
            deep = validate_deep_package(staged_input)
            slide_count = bounded_slide_count(deep)
            package = OpcPackage.open(staged_input)
            slide_ratio = slide_aspect_ratio(package)
            pdf_dir = private_root / "pdf-output"
            pdf_dir.mkdir()
            pdf_path = runner.convert(
                staged_input,
                "pdf",
                pdf_dir,
                timeout_seconds=_remaining_timeout(deadline),
            )
            pdf_size = bounded_file(pdf_path, MAX_PDF_BYTES, "Rendered PDF")
            pdf_info = assert_pdf_pages(pdf_path, slide_count)
            pdf_bytes = pdf_path.read_bytes()
            image_records, image_parts = _render_slide_images(
                package,
                runner,
                private_root,
                slide_count,
                slide_ratio,
                deadline,
            )
            manifest = {
                "schema_version": "1.0",
                "source_sha256": source.sha256,
                "slides": slide_count,
                "pdf": {
                    "bytes": pdf_size,
                    "pages": pdf_info["pages"],
                    "path": "deck.pdf",
                    "sha256": payload_sha256(pdf_bytes),
                },
                "images": image_records,
            }
            parts = {
                "deck.pdf": pdf_bytes,
                "manifest.json": render_json_bytes(manifest),
                **image_parts,
            }
            staged = private_root / "pptx-render.zip"
            write_deterministic_zip(staged, parts)
            bounded_file(staged, MAX_BUNDLE_BYTES, "PPTX render bundle")
            assert_source_preserved(source.path, source.sha256)
            elapsed_ms = int((time.monotonic() - started) * 1_000)
            validation, bundle_evidence = render_bundle_validation(
                staged,
                manifest,
                deep,
                source_sha256=source.sha256,
                version=version,
                duration_ms=elapsed_ms,
            )
            result = write_candidate_result(
                request=request,
                schemas=_schema_catalog(project_root),
                staged=staged,
                validation=validation,
                operation_result={
                    "render": {
                        "bundle": bundle_evidence,
                        "images": image_records,
                        "pdf": manifest["pdf"],
                        "provider": "libreoffice",
                        "provider_version": version,
                        "slides": slide_count,
                    }
                },
                warnings=[],
                source=source,
                achieved_fidelity="enhanced",
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _render_slide_images(
    package: OpcPackage,
    runner: Any,
    private_root: Path,
    slide_count: int,
    slide_ratio: float,
    deadline: float,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    records: list[dict[str, Any]] = []
    parts: dict[str, bytes] = {}
    total_bytes = 0
    candidates = private_root / "slide-candidates"
    candidates.mkdir()
    for slide in range(1, slide_count + 1):
        stem = f"slide-{slide:03d}"
        candidate = write_single_slide_candidate(
            package,
            slide,
            candidates / f"{stem}.pptx",
        )
        output_dir = private_root / f"image-output-{slide:03d}"
        output_dir.mkdir()
        image_path = runner.convert(
            candidate,
            "png",
            output_dir,
            timeout_seconds=_remaining_timeout(deadline),
        )
        size = bounded_file(image_path, MAX_PNG_BYTES, "Rendered slide PNG")
        payload = image_path.read_bytes()
        dimensions = inspect_png(payload)
        rendered_ratio = dimensions["width"] / dimensions["height"]
        if abs(rendered_ratio - slide_ratio) / slide_ratio > 0.05:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Rendered slide PNG has an unexpected aspect ratio.",
                details={"slide": slide},
            )
        total_bytes += size
        if total_bytes > MAX_TOTAL_PNG_BYTES:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Rendered slide PNGs exceed the aggregate output limit.",
                details={"ceiling": MAX_TOTAL_PNG_BYTES},
            )
        member = f"slides/{stem}.png"
        parts[member] = payload
        records.append({
            "bytes": size,
            "height": dimensions["height"],
            "path": member,
            "sha256": payload_sha256(payload),
            "slide": slide,
            "width": dimensions["width"],
        })
    return records, parts


def _stage_source(source: Path, expected_sha256: str, private_root: Path) -> Path:
    staged = private_root / "input.pptx"
    shutil.copyfile(source, staged)
    if sha256_file(staged) != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX source changed while it was staged for LibreOffice.",
            details={"source_changed_during_staging": True},
        )
    return staged


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "LibreOffice PPTX rendering exceeded its total time budget.",
        )
    return min(_PER_CONVERSION_SECONDS, remaining)


def _validation_failure(message: str, validation: dict[str, Any]) -> None:
    failed = [
        gate["id"]
        for gate in validation["gates"]
        if gate["required"] and gate["outcome"] != "pass"
    ]
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        details={"failed_gates": failed},
        validation=validation,
    )


def _schema_catalog(project_root: Path) -> Any:
    from document_skills_core.core.contracts.schemas import SchemaCatalog

    return SchemaCatalog(project_root)
