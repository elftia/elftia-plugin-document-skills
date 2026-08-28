"""Bounded Poppler-to-Tesseract OCR sidecar pipeline."""

import csv
from io import StringIO
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.content_streams import (
    extract_content_stream,
    TextBlock,
)
from document_skills_core.formats.pdf.mapping import map_text_blocks
from document_skills_core.formats.pdf.object_model import PdfObjectModel
from document_skills_core.formats.pdf.optional_provider_contracts import MAX_OCR_PAGES
from document_skills_core.formats.pdf.page_tree import PageInfo
from document_skills_core.formats.pdf.xobject_draws import walk_xobject_draws

from .archive import manifest_bytes, payload_record, write_archive
from .deadline import OperationDeadline
from .ocr_semantics import (
    assert_ocr_word_bbox,
    build_ocr_page_semantics,
)
from .pdf_input import safe_selected_pages
from .render import _read_bounded_output, assert_estimated_pixel_budget, image_dimensions
from .runner import PdfToolRunner

MAX_OCR_WORDS_PER_PAGE = 100_000
_MIN_SKIP_TEXT_BLOCKS = 3
_MIN_SKIP_TEXT_CHARACTERS = 80
_MIN_SKIP_VERTICAL_COVERAGE = 0.25


def ocr_pdf(
    source: Path,
    output: Path,
    arguments: dict[str, Any],
    *,
    private_root: Path,
    runner: PdfToolRunner,
    deadline: OperationDeadline,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    model, pages = safe_selected_pages(
        source,
        arguments["pages"],
        max_selected_pages=MAX_OCR_PAGES,
    )
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
        deadline.check()
        blocks = blocks_by_page[page.page_number]
        skip_evidence = (
            _embedded_text_skip_evidence(model, page, blocks)
            if arguments["skip_text_pages"]
            else None
        )
        if skip_evidence is not None:
            semantics = build_ocr_page_semantics(page, dpi=arguments["dpi"])
            sidecar = {
                "page": page.page_number,
                "status": "skipped_existing_text",
                "source": "embedded_text_detection",
                "detected_blocks": len(blocks),
                "skip_evidence": skip_evidence,
                "semantics": semantics,
            }
            json_path = f"page-{page.page_number:04d}.json"
            json_payload = _json_bytes(sidecar)
            total_working_bytes += len(json_payload)
            if total_working_bytes > arguments["max_total_bytes"]:
                _unsafe("OCR sidecar bytes exceed the caller-selected limit.")
            payloads[json_path] = json_payload
            payload_records.append(payload_record(json_path, json_payload))
            page_records.append(sidecar | {"json_path": json_path})
            continue
        remaining_bytes = arguments["max_total_bytes"] - total_working_bytes
        if remaining_bytes <= 0:
            _unsafe("OCR working bytes exceed the caller-selected limit.")
        prefix = private_root / f"ocr-render-{page.page_number:04d}"
        image = runner.render_page(
            source,
            prefix,
            page=page.page_number,
            dpi=arguments["dpi"],
            output_format="png",
            max_output_bytes=remaining_bytes,
            timeout_seconds=deadline.remaining(30.0),
        )
        deadline.check()
        image_payload = _read_bounded_output(
            image,
            remaining_bytes,
            "OCR raster image",
        )
        width, height = image_dimensions(image_payload, "png")
        semantics = build_ocr_page_semantics(
            page,
            dpi=arguments["dpi"],
            width=width,
            height=height,
        )
        total_pixels += width * height
        total_working_bytes += len(image_payload)
        if total_pixels > arguments["max_pixels"]:
            _unsafe("OCR raster pixels exceed the caller-selected limit.")
        if total_working_bytes > arguments["max_total_bytes"]:
            _unsafe("OCR working bytes exceed the caller-selected limit.")
        remaining_bytes = arguments["max_total_bytes"] - total_working_bytes
        if remaining_bytes <= 0:
            _unsafe("OCR working bytes exceed the caller-selected limit.")
        tsv = runner.ocr_tsv(
            image,
            languages=arguments["languages"],
            max_output_bytes=remaining_bytes,
            timeout_seconds=deadline.remaining(45.0),
        )
        deadline.check()
        total_working_bytes += len(tsv.encode("utf-8"))
        if total_working_bytes > arguments["max_total_bytes"]:
            _unsafe("OCR TSV bytes exceed the caller-selected limit.")
        words = _parse_tsv(
            tsv,
            raster_width=width,
            raster_height=height,
        )
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
            "semantics": semantics,
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
                "semantics": semantics,
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


def _embedded_text_skip_evidence(
    model: PdfObjectModel,
    page: PageInfo,
    blocks: list[TextBlock],
) -> dict[str, Any] | None:
    if not blocks:
        return None
    content = extract_content_stream(model, page.contents, page.page_number)
    xobjects, inline_images = walk_xobject_draws(content, page.page_number)
    if xobjects or inline_images:
        return None
    visible = [block for block in blocks if block.text.strip()]
    character_count = sum(len("".join(block.text.split())) for block in visible)
    box = page.crop_box or page.media_box
    page_bottom, page_top = sorted((float(box[1]), float(box[3])))
    page_height = max(page_top - page_bottom, 1.0)
    lows = [
        max(page_bottom, min(float(block.bbox[1]), float(block.bbox[3])))
        for block in visible
    ]
    highs = [
        min(page_top, max(float(block.bbox[1]), float(block.bbox[3])))
        for block in visible
    ]
    vertical_coverage = (
        max(0.0, max(highs) - min(lows)) / page_height
        if visible
        else 0.0
    )
    if (
        len(visible) < _MIN_SKIP_TEXT_BLOCKS
        or character_count < _MIN_SKIP_TEXT_CHARACTERS
        or vertical_coverage < _MIN_SKIP_VERTICAL_COVERAGE
    ):
        return None
    return {
        "policy": "sufficient_embedded_text_without_image_evidence",
        "detected_blocks": len(visible),
        "detected_characters": character_count,
        "vertical_coverage": round(vertical_coverage, 6),
    }


def _parse_tsv(
    value: str,
    *,
    raster_width: int,
    raster_height: int,
) -> list[dict[str, Any]]:
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
        if level != 5 or confidence < 0:
            continue
        assert_ocr_word_bbox(
            bbox,
            raster_width=raster_width,
            raster_height=raster_height,
        )
        words.append(
            {
                "text": text,
                "confidence": round(confidence, 3),
                "bbox_pixels": bbox,
            }
        )
        if len(words) > MAX_OCR_WORDS_PER_PAGE:
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
