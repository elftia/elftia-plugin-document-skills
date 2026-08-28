"""Bounded Poppler page rendering into a deterministic sidecar archive."""

from pathlib import Path
import struct
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.optional_provider_contracts import MAX_RENDER_PAGES

from .archive import manifest_bytes, payload_record, write_archive
from .deadline import OperationDeadline
from .pdf_input import safe_selected_pages
from .render_diff import aggregate_render_diff, compare_rendered_page
from .render_semantics import expected_raster_dimensions, render_page_record
from .runner import PdfToolRunner

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def render_pdf(
    source: Path,
    output: Path,
    arguments: dict[str, Any],
    *,
    private_root: Path,
    runner: PdfToolRunner,
    deadline: OperationDeadline,
    reference: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    _model, pages = safe_selected_pages(
        source,
        arguments["pages"],
        max_selected_pages=MAX_RENDER_PAGES,
    )
    assert_estimated_pixel_budget(pages, arguments["dpi"], arguments["max_pixels"])
    if reference is not None:
        _reference_model, selected_reference_pages = safe_selected_pages(
            reference,
            arguments["pages"],
            max_selected_pages=MAX_RENDER_PAGES,
        )
        candidate_page_numbers = [page.page_number for page in pages]
        reference_page_numbers = [page.page_number for page in selected_reference_pages]
        if reference_page_numbers != candidate_page_numbers:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Candidate and reference render page selections differ.",
                details={
                    "candidate_pages": candidate_page_numbers,
                    "reference_pages": reference_page_numbers,
                },
            )
        region_pages = {
            region["page"] for region in arguments["expected_change_regions"]
        }
        unrendered_region_pages = sorted(region_pages - set(candidate_page_numbers))
        if unrendered_region_pages:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Expected change regions must target selected render pages.",
                status="invalid_request",
                details={"pages": unrendered_region_pages},
            )
        assert_estimated_pixel_budget(
            selected_reference_pages,
            arguments["dpi"],
            arguments["max_pixels"],
        )
    payloads: dict[str, bytes] = {}
    page_records: list[dict[str, Any]] = []
    payload_records: list[dict[str, Any]] = []
    comparison_records: list[dict[str, Any]] = []
    total_bytes = 0
    total_pixels = 0
    reference_total_bytes = 0
    reference_total_pixels = 0
    extension = "png" if arguments["format"] == "png" else "jpg"
    for page in pages:
        deadline.check()
        remaining_bytes = arguments["max_total_bytes"] - total_bytes
        if remaining_bytes <= 0:
            _unsafe("Rendered image bytes exceed the caller-selected limit.")
        prefix = private_root / f"render-{page.page_number:04d}"
        rendered = runner.render_page(
            source,
            prefix,
            page=page.page_number,
            dpi=arguments["dpi"],
            output_format=arguments["format"],
            max_output_bytes=remaining_bytes,
            timeout_seconds=deadline.remaining(30.0),
        )
        deadline.check()
        payload = _read_bounded_output(rendered, remaining_bytes, "Poppler image")
        width, height = image_dimensions(payload, arguments["format"])
        total_bytes += len(payload)
        total_pixels += width * height
        if total_bytes > arguments["max_total_bytes"]:
            _unsafe("Rendered image bytes exceed the caller-selected limit.")
        if total_pixels > arguments["max_pixels"]:
            _unsafe("Rendered pixels exceed the caller-selected limit.")
        archive_path = f"page-{page.page_number:04d}.{extension}"
        base_record = payload_record(archive_path, payload)
        record = render_page_record(
            page,
            dpi=arguments["dpi"],
            output_format=arguments["format"],
            payload_record=base_record,
            width=width,
            height=height,
        )
        payloads[archive_path] = payload
        page_records.append(record)
        payload_records.append(base_record)
        if reference is not None:
            reference_remaining = (
                arguments["max_total_bytes"] - reference_total_bytes
            )
            if reference_remaining <= 0:
                _unsafe("Reference render bytes exceed the caller-selected limit.")
            reference_prefix = private_root / f"reference-{page.page_number:04d}"
            reference_rendered = runner.render_page(
                reference,
                reference_prefix,
                page=page.page_number,
                dpi=arguments["dpi"],
                output_format=arguments["format"],
                max_output_bytes=reference_remaining,
                timeout_seconds=deadline.remaining(30.0),
            )
            deadline.check()
            reference_payload = _read_bounded_output(
                reference_rendered,
                reference_remaining,
                "Poppler reference image",
            )
            reference_width, reference_height = image_dimensions(
                reference_payload,
                arguments["format"],
            )
            reference_total_bytes += len(reference_payload)
            reference_total_pixels += reference_width * reference_height
            if reference_total_bytes > arguments["max_total_bytes"]:
                _unsafe("Reference render bytes exceed the caller-selected limit.")
            if reference_total_pixels > arguments["max_pixels"]:
                _unsafe("Reference render pixels exceed the caller-selected limit.")
            comparison_records.append(
                compare_rendered_page(
                    payload,
                    reference_payload,
                    page,
                    arguments["expected_change_regions"],
                    channel_tolerance=arguments["channel_tolerance"],
                )
            )
    comparison = None
    if reference is not None:
        comparison = aggregate_render_diff(
            comparison_records,
            reference_sha256=arguments["reference_sha256"],
            channel_tolerance=arguments["channel_tolerance"],
            max_unexpected_change_ratio=arguments["max_unexpected_change_ratio"],
            minimum_expected_change_ratio=arguments[
                "minimum_expected_change_ratio"
            ],
        )
        comparison["reference_render_bytes"] = reference_total_bytes
        comparison["reference_render_pixels"] = reference_total_pixels
    manifest = {
        "schema_version": "1.0",
        "operation": "pdf.render",
        "provider": "poppler",
        "dpi": arguments["dpi"],
        "format": arguments["format"],
        "pages": page_records,
    }
    if comparison is not None:
        manifest["comparison"] = comparison
    payloads["manifest.json"] = manifest_bytes(manifest)
    write_archive(output, payloads)
    return (
        {
            "render": {
                "provider": "poppler",
                "dpi": arguments["dpi"],
                "format": arguments["format"],
                "page_count": len(page_records),
                "total_pixels": total_pixels,
                "total_image_bytes": total_bytes,
                "pages": page_records,
                **({"comparison": comparison} if comparison is not None else {}),
            }
        },
        manifest,
        payload_records,
    )


def assert_estimated_pixel_budget(
    pages: list[Any],
    dpi: int,
    limit: int,
) -> None:
    estimated = 0
    for page in pages:
        width, height = expected_raster_dimensions(page, dpi)
        estimated += width * height
    if estimated > limit:
        _unsafe("Estimated rendered pixels exceed the caller-selected limit.")


def image_dimensions(payload: bytes, output_format: str) -> tuple[int, int]:
    if output_format == "png":
        if len(payload) < 24 or not payload.startswith(_PNG_MAGIC):
            _failed("Poppler produced an invalid PNG image.")
        width, height = struct.unpack(">II", payload[16:24])
    else:
        width, height = _jpeg_dimensions(payload)
    if width <= 0 or height <= 0:
        _failed("Poppler produced invalid image dimensions.")
    return width, height


def _read_bounded_output(path: Path, maximum: int, label: str) -> bytes:
    if not path.is_file():
        _failed(f"{label} output is missing.")
    if path.stat().st_size > maximum:
        _unsafe(f"{label} output exceeds the remaining byte budget.")
    with path.open("rb") as stream:
        payload = stream.read(maximum + 1)
    if len(payload) > maximum:
        _unsafe(f"{label} output exceeds the remaining byte budget.")
    return payload


def _jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 4 or not payload.startswith(b"\xff\xd8"):
        _failed("Poppler produced an invalid JPEG image.")
    offset = 2
    while offset + 4 <= len(payload):
        if payload[offset] != 0xFF:
            _failed("Poppler produced a malformed JPEG marker stream.")
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            _failed("Poppler produced a truncated JPEG marker stream.")
        marker = payload[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        length = struct.unpack(">H", payload[offset : offset + 2])[0]
        if length < 2 or offset + length > len(payload):
            _failed("Poppler produced a truncated JPEG image.")
        if marker in {0xC0, 0xC1, 0xC2}:
            height, width = struct.unpack(">HH", payload[offset + 3 : offset + 7])
            return width, height
        if marker == 0xDA:
            break
        offset += length
    _failed("Poppler JPEG output has no supported frame header.")


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message)
