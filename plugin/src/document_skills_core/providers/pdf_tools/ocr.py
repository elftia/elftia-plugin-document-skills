"""Bounded Poppler-to-Tesseract OCR sidecar pipeline."""

import csv
from io import StringIO
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.mapping import map_text_blocks

from .archive import manifest_bytes, payload_record, write_archive
from .pdf_input import safe_selected_pages
from .render import assert_estimated_pixel_budget, image_dimensions
from .runner import PdfToolRunner


def ocr_pdf(
    source: Path,
    output: Path,
    arguments: dict[str, Any],
    *,
    private_root: Path,
    runner: PdfToolRunner,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    model, pages = safe_selected_pages(source, arguments["pages"])
    assert_estimated_pixel_budget(pages, arguments["dpi"], arguments["max_pixels"])
    existing_blocks = map_text_blocks(model, pages, max_blocks_per_page=5_000)
    blocks_by_page = {
        page.page_number: [
            block for block in existing_blocks if block.page == page.page_number
        ]
        for page in pages
    }
    payloads: dict[str, bytes] = {}
    payload_records: list[dict[str, Any]] = []
    page_records: list[dict[str, Any]] = []
    total_pixels = 0
    total_working_bytes = 0
    confidences: list[float] = []
    for page in pages:
        blocks = blocks_by_page[page.page_number]
        if arguments["skip_text_pages"] and blocks:
            sidecar = {
                "page": page.page_number,
                "status": "skipped_existing_text",
                "source": "embedded_text_detection",
                "detected_blocks": len(blocks),
            }
            json_path = f"page-{page.page_number:04d}.json"
            json_payload = _json_bytes(sidecar)
            payloads[json_path] = json_payload
            payload_records.append(payload_record(json_path, json_payload))
            page_records.append(sidecar | {"json_path": json_path})
            continue
        prefix = private_root / f"ocr-render-{page.page_number:04d}"
        image = runner.render_page(
            source,
            prefix,
            page=page.page_number,
            dpi=arguments["dpi"],
            output_format="png",
        )
        image_payload = image.read_bytes()
        width, height = image_dimensions(image_payload, "png")
        total_pixels += width * height
        total_working_bytes += len(image_payload)
        if total_pixels > arguments["max_pixels"]:
            _unsafe("OCR raster pixels exceed the caller-selected limit.")
        if total_working_bytes > arguments["max_total_bytes"]:
            _unsafe("OCR working bytes exceed the caller-selected limit.")
        words = _parse_tsv(runner.ocr_tsv(image, languages=arguments["languages"]))
        text = " ".join(word["text"] for word in words)
        page_confidences = [word["confidence"] for word in words]
        confidences.extend(page_confidences)
        confidence = (
            round(sum(page_confidences) / len(page_confidences), 3)
            if page_confidences
            else None
        )
        text_path = f"page-{page.page_number:04d}.txt"
        json_path = f"page-{page.page_number:04d}.json"
        text_payload = (text + ("\n" if text else "")).encode("utf-8")
        sidecar = {
            "page": page.page_number,
            "status": "ocr_completed",
            "source": "tesseract",
            "languages": arguments["languages"],
            "confidence": confidence,
            "raster": {"width": width, "height": height, "dpi": arguments["dpi"]},
            "words": words,
        }
        json_payload = _json_bytes(sidecar)
        total_working_bytes += len(text_payload) + len(json_payload)
        if total_working_bytes > arguments["max_total_bytes"]:
            _unsafe("OCR sidecar bytes exceed the caller-selected limit.")
        payloads[text_path] = text_payload
        payloads[json_path] = json_payload
        payload_records.extend(
            [payload_record(text_path, text_payload), payload_record(json_path, json_payload)]
        )
        page_records.append(
            {
                "page": page.page_number,
                "status": "ocr_completed",
                "source": "tesseract",
                "languages": arguments["languages"],
                "confidence": confidence,
                "word_count": len(words),
                "text_path": text_path,
                "json_path": json_path,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "operation": "pdf.ocr",
        "provider": "poppler+tesseract",
        "dpi": arguments["dpi"],
        "languages": arguments["languages"],
        "pages": page_records,
    }
    payloads["manifest.json"] = manifest_bytes(manifest)
    write_archive(output, payloads)
    completed = [page for page in page_records if page["status"] == "ocr_completed"]
    ocr_source = "tesseract" if completed else "not_run_existing_text"
    return (
        {
            "ocr": {
                "provider": "poppler+tesseract",
                "source": ocr_source,
                "languages": arguments["languages"],
                "selected_page_count": len(page_records),
                "ocr_page_count": len(completed),
                "skipped_text_page_count": len(page_records) - len(completed),
                "mean_confidence": (
                    round(sum(confidences) / len(confidences), 3)
                    if confidences
                    else None
                ),
                "pages": page_records,
            }
        },
        manifest,
        payload_records,
    )


def _parse_tsv(value: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(StringIO(value), delimiter="\t")
    required = {"level", "left", "top", "width", "height", "conf", "text"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        _failed("Tesseract TSV output does not match the accepted schema.")
    words: list[dict[str, Any]] = []
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row["conf"])
            bbox = [
                int(row["left"]),
                int(row["top"]),
                int(row["width"]),
                int(row["height"]),
            ]
            level = int(row["level"])
        except (TypeError, ValueError):
            _failed("Tesseract TSV contains invalid numeric evidence.")
        if level != 5 or confidence < 0 or any(value < 0 for value in bbox):
            continue
        words.append(
            {
                "text": text,
                "confidence": round(confidence, 3),
                "bbox_pixels": bbox,
            }
        )
        if len(words) > 100_000:
            _unsafe("OCR word count exceeds the bounded policy.")
    return words


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message)
