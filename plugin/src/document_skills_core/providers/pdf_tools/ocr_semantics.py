"""PDF page geometry and archive validation for OCR sidecars."""

import json
from pathlib import Path
from typing import Any
import zipfile

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation.runner import ValidationRunner
from document_skills_core.formats.pdf.optional_provider_contracts import MAX_OCR_PAGES
from document_skills_core.formats.pdf.page_tree import PageInfo

from .pdf_input import safe_selected_pages
from .render_semantics import expected_raster_dimensions


def build_ocr_page_semantics(
    page: PageInfo,
    *,
    dpi: int,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Bind one selected PDF page to its expected and actual OCR raster."""
    expected_width, expected_height = expected_raster_dimensions(page, dpi)
    if (width is None) != (height is None):
        raise AssertionError("OCR raster dimensions must be supplied together.")
    raster = None
    if width is not None and height is not None:
        if (width, height) != (expected_width, expected_height):
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "OCR raster dimensions do not match the selected PDF page geometry.",
                details={
                    "page": page.page_number,
                    "expected_width": expected_width,
                    "expected_height": expected_height,
                    "actual_width": width,
                    "actual_height": height,
                },
            )
        raster = {
            "width": width,
            "height": height,
            "bbox": [0, 0, width, height],
            "bounds": [0, 0, expected_width, expected_height],
            "bounded": True,
            "overflow": False,
        }
    return {
        "media_box": list(page.media_box),
        "crop_box": list(page.crop_box) if page.crop_box is not None else None,
        "rotation": page.rotation % 360,
        "dpi": dpi,
        "expected_raster": {
            "width": expected_width,
            "height": expected_height,
        },
        "raster": raster,
    }


def assert_ocr_word_bbox(
    bbox: list[int],
    *,
    raster_width: int,
    raster_height: int,
) -> None:
    """Reject a word bbox that is empty or outside the actual OCR raster."""
    left, top, width, height = bbox
    if (
        left < 0
        or top < 0
        or width <= 0
        or height <= 0
        or left + width > raster_width
        or top + height > raster_height
    ):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Tesseract word bbox is outside the bounded OCR raster.",
            details={
                "bbox_pixels": bbox,
                "raster_width": raster_width,
                "raster_height": raster_height,
            },
        )


def validate_ocr_archive(
    archive: Path,
    source: Path,
    manifest: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Return a required gate report bound to source pages and sidecar bytes."""
    runner = ValidationRunner()
    runner.run_gate(
        "ocr.page-semantics",
        lambda: _reopen_ocr_semantics(archive, source, manifest, arguments),
    )
    return runner.report()


def _reopen_ocr_semantics(
    archive_path: Path,
    source: Path,
    manifest: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    dpi = arguments["dpi"]
    languages = arguments["languages"]
    if (
        manifest.get("operation") != "pdf.ocr"
        or manifest.get("provider") != "poppler+tesseract"
        or manifest.get("dpi") != dpi
        or manifest.get("languages") != languages
    ):
        raise ValueError("OCR manifest settings do not match the accepted request.")
    _model, selected = safe_selected_pages(
        source,
        arguments["pages"],
        max_selected_pages=MAX_OCR_PAGES,
    )
    records = manifest.get("pages")
    if type(records) is not list or len(records) != len(selected):
        raise ValueError("OCR manifest page selection changed.")
    with zipfile.ZipFile(archive_path) as archive:
        for page, record in zip(selected, records, strict=True):
            _validate_page_record(archive, page, record, dpi, languages)
    return {
        "dpi": dpi,
        "languages": languages,
        "pages": [page.page_number for page in selected],
        "validated_sidecars": len(selected),
    }


def _validate_page_record(
    archive: zipfile.ZipFile,
    page: PageInfo,
    record: Any,
    dpi: int,
    languages: list[str],
) -> None:
    if type(record) is not dict or record.get("page") != page.page_number:
        raise ValueError("OCR manifest page ordering changed.")
    status = record.get("status")
    if status not in {"ocr_completed", "skipped_existing_text"}:
        raise ValueError("OCR manifest page status is invalid.")
    expected_width, expected_height = expected_raster_dimensions(page, dpi)
    semantics = build_ocr_page_semantics(
        page,
        dpi=dpi,
        width=expected_width if status == "ocr_completed" else None,
        height=expected_height if status == "ocr_completed" else None,
    )
    expected_json_path = f"page-{page.page_number:04d}.json"
    if record.get("json_path") != expected_json_path:
        raise ValueError("OCR JSON sidecar path changed.")
    sidecar = _read_json(archive, expected_json_path)
    if (
        sidecar.get("page") != page.page_number
        or sidecar.get("status") != status
        or sidecar.get("semantics") != semantics
        or record.get("semantics") != semantics
    ):
        raise ValueError("OCR page semantics do not match the source PDF.")
    if status == "ocr_completed":
        _validate_completed_page(
            archive,
            page.page_number,
            record,
            sidecar,
            languages,
            expected_width,
            expected_height,
        )
    elif sidecar.get("source") != "embedded_text_detection":
        raise ValueError("Skipped OCR page source evidence changed.")


def _validate_completed_page(
    archive: zipfile.ZipFile,
    page_number: int,
    record: dict[str, Any],
    sidecar: dict[str, Any],
    languages: list[str],
    width: int,
    height: int,
) -> None:
    expected_text_path = f"page-{page_number:04d}.txt"
    words = sidecar.get("words")
    if (
        sidecar.get("source") != "tesseract"
        or sidecar.get("languages") != languages
        or record.get("languages") != languages
        or record.get("text_path") != expected_text_path
        or type(words) is not list
        or record.get("word_count") != len(words)
        or record.get("confidence") != sidecar.get("confidence")
        or sidecar.get("raster") != {"width": width, "height": height, "dpi": record["semantics"]["dpi"]}
    ):
        raise ValueError("Completed OCR sidecar evidence changed.")
    for word in words:
        if type(word) is not dict or type(word.get("bbox_pixels")) is not list:
            raise ValueError("OCR word evidence is malformed.")
        assert_ocr_word_bbox(
            word["bbox_pixels"],
            raster_width=width,
            raster_height=height,
        )
    expected_text = " ".join(str(word.get("text", "")) for word in words)
    expected_payload = (expected_text + ("\n" if expected_text else "")).encode("utf-8")
    if archive.read(expected_text_path) != expected_payload:
        raise ValueError("OCR text sidecar does not match its word evidence.")


def _read_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name).decode("utf-8", errors="strict"))
    except (KeyError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("OCR JSON sidecar is missing or malformed.") from error
    if type(value) is not dict:
        raise ValueError("OCR JSON sidecar root is invalid.")
    return value
