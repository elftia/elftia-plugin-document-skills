"""Public-service regression tests for exact PDF rewrite operator targeting."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from document_skills_core.formats.pdf.content_streams import (
    extract_content_stream,
    TextBlock,
    walk_text_operators,
)
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.service import PdfService


def _write_pdf(path: Path, streams: list[bytes]) -> Path:
    content_refs = " ".join(f"{number} 0 R" for number in range(5, 5 + len(streams)))
    contents = content_refs if len(streams) == 1 else f"[{content_refs}]"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 4 0 R >> >> /Contents {contents} >>"
        ).encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        *[
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
            for stream in streams
        ],
    ]
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} 0 obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _blocks(path: Path) -> list[TextBlock]:
    model = parse_pdf(path)
    page = walk_pages(model)[0]
    return walk_text_operators(
        extract_content_stream(model, page.contents, page.page_number),
        page.page_number,
    )


def _request(
    source: Path,
    output: Path,
    block: TextBlock,
    replacement: str,
    *,
    bbox: list[float] | None = None,
) -> dict[str, object]:
    selector_bbox = list(block.bbox) if bbox is None else bbox
    if bbox is None:
        selector_bbox[2] = max(selector_bbox[2], selector_bbox[0] + 120.0)
    return {
        "schema_version": "1.0",
        "operation": "pdf.rewrite.apply",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "blocks": [
                {
                    "page": block.page,
                    "bbox": selector_bbox,
                    "text": block.text,
                    "font": block.font_name.removeprefix("/"),
                    "size": block.font_size,
                    "color": list(block.color),
                }
            ],
            "rewrites": [{"block_index": 0, "text": replacement}],
        },
    }


def _execute(
    project_root: Path,
    source: Path,
    output: Path,
    target: TextBlock,
    replacement: str = "Changed",
) -> dict[str, object]:
    return PdfService(project_root).execute(
        "pdf.rewrite.apply",
        _request(source, output, target, replacement),
    )


def test_service_rewrite_targets_selected_duplicate_literal(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "duplicate.pdf",
        [
            b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Title) Tj "
            b"1 0 0 1 72 620 Tm (Title) Tj ET\n"
        ],
    )
    before = _blocks(source)
    output = tmp_path / "duplicate-output.pdf"

    result = _execute(project_root, source, output, before[1])

    assert result["status"] == "success", result
    assert [block.text for block in _blocks(output)] == ["Title", "Changed"]
    layout = result["diagnostics"]["operation_result"]["rewrite"][
        "page_layout_preservation"
    ]
    assert layout["verified"] is True
    evidence = result["diagnostics"]["operation_result"]["rewrite"][
        "rewrite_evidence"
    ][0]
    assert evidence["operator"] == "Tj"
    assert evidence["content_operator_index"] == 1


@pytest.mark.parametrize(
    "content",
    [
        b"BT /F1 12 Tf 1 0 0 1 72 720 Tm <5469746c65> Tj ET\n",
        b"BT /F1 12 Tf 1 0 0 1 72 720 Tm [(Ti) -20 <746c65>] TJ ET\n",
    ],
    ids=["hex-tj", "tj-array"],
)
def test_service_rewrite_supports_tokenized_text_operands(
    project_root: Path,
    tmp_path: Path,
    content: bytes,
) -> None:
    source = _write_pdf(tmp_path / "encoded.pdf", [content])
    output = tmp_path / "encoded-output.pdf"

    result = _execute(project_root, source, output, _blocks(source)[0])

    assert result["status"] == "success", result
    assert [block.text for block in _blocks(output)] == ["Changed"]


def test_service_rewrite_targets_only_selected_content_stream(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "multiple-streams.pdf",
        [
            b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Title) Tj ET\n",
            b"BT /F1 12 Tf 1 0 0 1 72 620 Tm (Title) Tj ET\n",
        ],
    )
    before = _blocks(source)
    output = tmp_path / "multiple-streams-output.pdf"

    result = _execute(project_root, source, output, before[1])

    assert result["status"] == "success", result
    assert [block.text for block in _blocks(output)] == ["Title", "Changed"]
    changed = result["diagnostics"]["operation_result"]["rewrite"][
        "rewrite_evidence"
    ][0]["content_object"]
    assert changed == 6


def test_service_rewrite_rejects_unsupported_operator_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "quote.pdf",
        [b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Title) ' ET\n"],
    )
    source_before = source.read_bytes()
    output = tmp_path / "quote-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)

    result = _execute(project_root, source, output, _blocks(source)[0])

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert source.read_bytes() == source_before
    assert output.read_bytes() == destination_before


def test_service_rewrite_uses_caller_bbox_without_source_union(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "caller-bounds.pdf",
        [b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (WWWW) Tj ET\n"],
    )
    source_before = source.read_bytes()
    target = _blocks(source)[0]
    selector_bbox = list(target.bbox)
    selector_bbox[2] = selector_bbox[0] + 10.0
    output = tmp_path / "caller-bounds-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)

    result = PdfService(project_root).execute(
        "pdf.rewrite.apply",
        _request(source, output, target, "WW", bbox=selector_bbox),
    )

    assert result["status"] == "enhancement_required", result
    assert source.read_bytes() == source_before
    assert output.read_bytes() == destination_before


def test_service_rewrite_no_match_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "stale.pdf",
        [b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Title) Tj ET\n"],
    )
    target = _blocks(source)[0]
    output = tmp_path / "stale-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    request = _request(source, output, target, "Changed", bbox=[0, 0, 10, 10])

    result = PdfService(project_root).execute("pdf.rewrite.apply", request)

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == destination_before
