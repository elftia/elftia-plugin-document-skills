"""Bounded Poppler page rendering into a deterministic sidecar archive."""

import math
from pathlib import Path
import struct
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .archive import manifest_bytes, payload_record, write_archive
from .pdf_input import safe_selected_pages
from .runner import PdfToolRunner

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def render_pdf(
    source: Path,
    output: Path,
    arguments: dict[str, Any],
    *,
    private_root: Path,
    runner: PdfToolRunner,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    _model, pages = safe_selected_pages(source, arguments["pages"])
    assert_estimated_pixel_budget(pages, arguments["dpi"], arguments["max_pixels"])
    payloads: dict[str, bytes] = {}
    page_records: list[dict[str, Any]] = []
    payload_records: list[dict[str, Any]] = []
    total_bytes = 0
    total_pixels = 0
    extension = "png" if arguments["format"] == "png" else "jpg"
    for page in pages:
        prefix = private_root / f"render-{page.page_number:04d}"
        rendered = runner.render_page(
            source,
            prefix,
            page=page.page_number,
            dpi=arguments["dpi"],
            output_format=arguments["format"],
        )
        payload = rendered.read_bytes()
        width, height = image_dimensions(payload, arguments["format"])
        total_bytes += len(payload)
        total_pixels += width * height
        if total_bytes > arguments["max_total_bytes"]:
            _unsafe("Rendered image bytes exceed the caller-selected limit.")
        if total_pixels > arguments["max_pixels"]:
            _unsafe("Rendered pixels exceed the caller-selected limit.")
        archive_path = f"page-{page.page_number:04d}.{extension}"
        base_record = payload_record(archive_path, payload)
        record = {
            **base_record,
            "page": page.page_number,
            "format": arguments["format"],
            "width": width,
            "height": height,
            "pixels": width * height,
        }
        payloads[archive_path] = payload
        page_records.append(record)
        payload_records.append(base_record)
    manifest = {
        "schema_version": "1.0",
        "operation": "pdf.render",
        "provider": "poppler",
        "dpi": arguments["dpi"],
        "format": arguments["format"],
        "pages": page_records,
    }
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
        box = page.crop_box or page.media_box
        width = abs(box[2] - box[0])
        height = abs(box[3] - box[1])
        if page.rotation in {90, 270}:
            width, height = height, width
        estimated += math.ceil(width * dpi / 72) * math.ceil(height * dpi / 72)
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
