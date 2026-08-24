"""Bounds and validation reports for LibreOffice PPTX render outputs."""

import hashlib
import json
from pathlib import Path
from typing import Any
import zipfile

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.io.paths import file_record
from document_skills_core.formats.pdf.validation import reopen_pdf

from .constants import local_name
from .package import OpcPackage
from .png_compare import inspect_png

MAX_RENDER_SLIDES = 50
MAX_PDF_BYTES = 128 * 1024 * 1024
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_TOTAL_PNG_BYTES = 256 * 1024 * 1024
MAX_BUNDLE_BYTES = 384 * 1024 * 1024


def bounded_slide_count(deep: dict[str, Any]) -> int:
    count = deep["inventory"]["slides"]
    if not 1 <= count <= MAX_RENDER_SLIDES:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "LibreOffice PPTX output requires a bounded non-empty deck.",
            status="invalid_request",
            details={"ceiling": MAX_RENDER_SLIDES, "slides": count},
        )
    return count


def slide_aspect_ratio(package: OpcPackage) -> float:
    presentation = package.xml("ppt/presentation.xml")
    size = next(
        (node for node in presentation if local_name(node.tag) == "sldSz"),
        None,
    )
    try:
        width = int(size.attrib["cx"])
        height = int(size.attrib["cy"])
    except (AttributeError, KeyError, TypeError, ValueError):
        width = height = 0
    if width <= 0 or height <= 0:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX slide size is invalid for rendering.",
        )
    return width / height


def assert_pdf_pages(path: Path, expected: int) -> dict[str, int]:
    pages = int(reopen_pdf(path)["pages"])
    if pages != expected:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "LibreOffice PDF page count does not match the PPTX slide count.",
            details={"actual": pages, "expected": expected},
        )
    return {"pages": pages, "slides": expected}


def bounded_file(path: Path, ceiling: int, label: str) -> int:
    if not path.is_file():
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            f"{label} is missing.",
        )
    size = path.stat().st_size
    if not 0 < size <= ceiling:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            f"{label} exceeds its output limit.",
            details={"bytes": size, "ceiling": ceiling},
        )
    return size


def render_bundle_validation(
    path: Path,
    manifest: dict[str, Any],
    deep: dict[str, Any],
    *,
    source_sha256: str,
    version: str | None,
    duration_ms: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle_evidence = validate_render_bundle(path, manifest)
    output = file_record(path, "output")
    validation = {
        "schema_version": "1.0",
        "status": "pass",
        "gates": [
            gate_record(
                "artifact.exists-size",
                "pass",
                evidence={"bytes": output.bytes, "sha256": output.sha256},
            ),
            gate_record(
                "pptx.source-deep-validation",
                "pass",
                evidence=deep,
            ),
            gate_record(
                "provider.reopen",
                "pass",
                evidence=bundle_evidence,
            ),
            gate_record(
                "source.preservation",
                "pass",
                evidence={"sha256": source_sha256},
            ),
            gate_record(
                "visual.render",
                "pass",
                validator="libreoffice",
                version=version,
                duration_ms=duration_ms,
                evidence={
                    "bundle_format": "pdf-plus-per-slide-png",
                    "pages": manifest["pdf"]["pages"],
                    "slides_rendered": len(manifest["images"]),
                    "visual_parity_reference": "not_applicable",
                },
            ),
            gate_record(
                "schema.full",
                "not_applicable",
                required=False,
                evidence={"reason": "The output is a render evidence bundle."},
            ),
        ],
    }
    return validation, bundle_evidence


def validate_render_bundle(
    path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    images = manifest["images"]
    slides = manifest["slides"]
    if (
        manifest["pdf"]["pages"] != slides
        or len(images) != slides
        or [item["slide"] for item in images] != list(range(1, slides + 1))
    ):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX render bundle slide inventory is inconsistent.",
        )
    expected = {
        "deck.pdf",
        "manifest.json",
        *(item["path"] for item in images),
    }
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        names = [item.filename.replace("\\", "/") for item in members]
        if len(names) != len(set(names)) or set(names) != expected:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "PPTX render bundle members do not match the manifest.",
            )
        actual_manifest = json.loads(archive.read("manifest.json"))
        if actual_manifest != manifest:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "PPTX render bundle manifest is inconsistent.",
            )
        pdf_payload = archive.read("deck.pdf")
        if (
            len(pdf_payload) != manifest["pdf"]["bytes"]
            or payload_sha256(pdf_payload) != manifest["pdf"]["sha256"]
        ):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "PPTX render bundle PDF hash is inconsistent.",
            )
        for record in images:
            payload = archive.read(record["path"])
            dimensions = {
                "height": record["height"],
                "width": record["width"],
            }
            if (
                len(payload) != record["bytes"]
                or payload_sha256(payload) != record["sha256"]
                or inspect_png(payload) != dimensions
            ):
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "PPTX render bundle PNG evidence is inconsistent.",
                    details={"slide": record["slide"]},
                )
    return {
        "members": len(expected),
        "pdf_pages": manifest["pdf"]["pages"],
        "slides": manifest["slides"],
    }


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
