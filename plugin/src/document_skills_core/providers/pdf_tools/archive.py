"""Deterministic sidecar archives and validation for PDF render/OCR."""

import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any
import zipfile

from PIL import Image

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import assert_source_preserved, file_record
from document_skills_core.core.validation.runner import ValidationRunner
from document_skills_core.formats.pdf.image_extraction_archive import (
    write_deterministic_image_zip,
)
from document_skills_core.formats.pdf.optional_provider_contracts import (
    MAX_RENDER_PAGES,
)

from .pdf_input import safe_selected_pages
from .render_semantics import expected_raster_dimensions


def manifest_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def write_archive(path: Path, payloads: dict[str, bytes]) -> None:
    write_deterministic_image_zip(path, payloads)


def validate_archive(
    archive: Path,
    *,
    payload_records: list[dict[str, Any]],
    manifest: dict[str, Any],
    source: Path,
    source_sha256: str,
    reference: Path | None = None,
    reference_sha256: str | None = None,
    render_comparison: dict[str, Any] | None = None,
    render_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = ValidationRunner()
    runner.run_gate("artifact.exists-size", lambda: _identity(archive))
    runner.run_gate(
        "archive.sidecar-reopen",
        lambda: _reopen(archive, payload_records, manifest),
    )
    runner.run_gate(
        "source.preservation",
        lambda: _preserved(source, source_sha256),
    )
    if render_arguments is not None:
        runner.run_gate(
            "render.page-semantics",
            lambda: _render_page_semantics(
                archive,
                source,
                manifest,
                render_arguments,
            ),
            validator="document-skills-core+pillow",
        )
    if reference is not None and reference_sha256 is not None:
        runner.run_gate(
            "reference.preservation",
            lambda: _preserved(reference, reference_sha256),
        )
    if render_comparison is not None:
        runner.run_gate(
            "visual.page-render-diff",
            lambda: _render_diff(render_comparison),
            validator="poppler+pillow",
        )
    return runner.report()


def payload_record(name: str, payload: bytes) -> dict[str, Any]:
    return {
        "archive_path": name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _identity(path: Path) -> dict[str, Any]:
    record = file_record(path, "output")
    if record.bytes <= 0:
        raise ValueError("Provider sidecar archive is empty.")
    return {"sha256": record.sha256, "bytes": record.bytes}


def _reopen(
    path: Path,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected = {record["archive_path"]: record for record in records}
    expected["manifest.json"] = payload_record("manifest.json", manifest_bytes(manifest))
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names != sorted(names) or set(names) != set(expected):
            raise ValueError("Provider sidecar entries are not canonical.")
        if archive.testzip() is not None:
            raise ValueError("Provider sidecar archive contains a corrupt entry.")
        for name, record in expected.items():
            payload = archive.read(name)
            if len(payload) != record["bytes"]:
                raise ValueError("Provider sidecar byte count changed.")
            if hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError("Provider sidecar hash changed.")
        if json.loads(archive.read("manifest.json")) != manifest:
            raise ValueError("Provider sidecar manifest changed.")
    return {"entries": len(expected)}


def _preserved(path: Path, expected_sha256: str) -> dict[str, Any]:
    assert_source_preserved(path, expected_sha256)
    return {"sha256": expected_sha256}


def _render_diff(comparison: dict[str, Any]) -> dict[str, Any]:
    if comparison.get("policy_pass") is not True:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Rendered page differences exceed the caller-selected policy.",
            details=comparison,
        )
    return comparison


def _render_page_semantics(
    archive_path: Path,
    source: Path,
    manifest: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    dpi = arguments["dpi"]
    output_format = arguments["format"]
    if (
        manifest.get("operation") != "pdf.render"
        or manifest.get("provider") != "poppler"
        or manifest.get("dpi") != dpi
        or manifest.get("format") != output_format
    ):
        raise ValueError("Render manifest settings do not match the accepted request.")
    _model, selected = safe_selected_pages(
        source,
        arguments["pages"],
        max_selected_pages=MAX_RENDER_PAGES,
    )
    records = manifest.get("pages")
    if type(records) is not list or len(records) != len(selected):
        raise ValueError("Render manifest page selection changed.")
    extension = "png" if output_format == "png" else "jpg"
    image_format = "PNG" if output_format == "png" else "JPEG"
    with zipfile.ZipFile(archive_path) as archive:
        for page, record in zip(selected, records, strict=True):
            if type(record) is not dict:
                raise ValueError("Render manifest page record is invalid.")
            expected_width, expected_height = expected_raster_dimensions(page, dpi)
            expected_path = f"page-{page.page_number:04d}.{extension}"
            try:
                image_payload = archive.read(expected_path)
            except KeyError as error:
                raise ValueError("Rendered page image is missing.") from error
            with Image.open(BytesIO(image_payload)) as image:
                actual_format = image.format
                actual_width, actual_height = image.size
                image.verify()
            if actual_format != image_format:
                raise ValueError("Rendered page image format changed.")
            if (actual_width, actual_height) != (expected_width, expected_height):
                raise ValueError("Rendered page dimensions do not match PDF geometry.")
            base_record = payload_record(expected_path, image_payload)
            expected_record = {
                **base_record,
                "page": page.page_number,
                "format": output_format,
                "media_box": list(page.media_box),
                "crop_box": list(page.crop_box) if page.crop_box is not None else None,
                "rotation": _right_angle_rotation(page.rotation),
                "dpi": dpi,
                "width": actual_width,
                "height": actual_height,
                "pixels": actual_width * actual_height,
                "raster_evidence": {
                    "expected_width": expected_width,
                    "expected_height": expected_height,
                    "bbox": [0, 0, actual_width, actual_height],
                    "bounds": [0, 0, expected_width, expected_height],
                    "bounded": True,
                    "overflow": False,
                },
            }
            if record != expected_record:
                raise ValueError("Render page semantics changed after provider output.")
    return {
        "dpi": dpi,
        "format": output_format,
        "pages": [page.page_number for page in selected],
        "validated_images": len(selected),
    }


def _right_angle_rotation(value: int) -> int:
    rotation = value % 360
    if rotation not in {0, 90, 180, 270}:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Render semantic validation requires right-angle page rotation.",
            status="enhancement_required",
            details={"rotation": value},
        )
    return rotation
