"""Public regressions for proof-oriented PDF simple-font encodings."""

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pdf.content_streams import (
    extract_content_stream,
    walk_text_operators,
)
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.pdf_simple_encodings import (
    MAC_ROMAN,
    STANDARD,
    WIN_ANSI,
    encode_simple_text,
)
from document_skills_core.formats.pdf.rewrite import rewrite_apply_pdf


def _public(project_root: Path, request: Path) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pdf/scripts/run.py"),
            "run",
            "--request",
            str(request),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    assert process.stderr == b""
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _stream(dictionary: bytes, content: bytes) -> bytes:
    return (
        dictionary
        + b" /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )


def _write_pdf(
    path: Path,
    font: bytes,
    *,
    extra_objects: dict[int, bytes] | None = None,
) -> Path:
    content = b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (A) Tj ET\n"
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        4: font,
        5: _stream(b"<<", content),
        **(extra_objects or {}),
    }
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for object_number in sorted(objects):
        offsets[object_number] = len(header) + len(body)
        body.extend(f"{object_number} 0 obj\n".encode("ascii"))
        body.extend(objects[object_number] + b"\nendobj\n")
    maximum = max(objects)
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {maximum + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for object_number in range(1, maximum + 1):
        if object_number in offsets:
            xref.extend(f"{offsets[object_number]:010d} 00000 n\r\n".encode("ascii"))
        else:
            xref.extend(b"0000000000 00000 f\r\n")
    xref.extend(
        f"trailer\n<< /Size {maximum + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _blocks(source: Path) -> list[dict[str, object]]:
    model = parse_pdf(source)
    return [
        {
            "page": block.page,
            "bbox": list(block.bbox),
            "text": block.text,
            "font": block.font_name.removeprefix("/"),
            "size": block.font_size,
            "color": list(block.color),
        }
        for page in walk_pages(model)
        for block in walk_text_operators(
            extract_content_stream(model, page.contents, page.page_number),
            page.page_number,
        )
    ]


def _request(source: Path, output: Path, replacement: str) -> dict[str, object]:
    selected = dict(_blocks(source)[0])
    bbox = list(selected["bbox"])
    bbox[2] = float(bbox[0]) + 240.0
    selected["bbox"] = bbox
    return {
        "schema_version": "1.0",
        "operation": "pdf.rewrite.apply",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "blocks": [selected],
            "rewrites": [{"block_index": 0, "text": replacement}],
        },
    }


def _write_request(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _assert_public_enhancement_atomically(
    project_root: Path,
    tmp_path: Path,
    source: Path,
    replacement: str,
    stem: str,
) -> None:
    source_before = source.read_bytes()
    output = tmp_path / f"{stem}-output.pdf"
    output_before = b"existing destination"
    output.write_bytes(output_before)
    result = _public(
        project_root,
        _write_request(
            tmp_path / f"{stem}.json",
            _request(source, output, replacement),
        ),
    )
    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-font-encoding"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == output_before


def _cmap(*mappings: tuple[int, int]) -> bytes:
    entries = b"".join(
        f"<{source:02X}> <{target:04X}>\n".encode("ascii")
        for source, target in mappings
    )
    return (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin begincmap\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        + f"{len(mappings)} beginbfchar\n".encode("ascii")
        + entries
        + b"endbfchar\n"
        b"endcmap CMapName currentdict /CMap defineresource pop end end\n"
    )


def test_fixed_pdf_encoding_counterexamples() -> None:
    assert len(WIN_ANSI) == len(MAC_ROMAN) == len(STANDARD) == 256
    assert WIN_ANSI[0xAD] == "-"
    assert MAC_ROMAN[0xDB] == "¤"
    assert STANDARD[0x27] == "’"
    assert encode_simple_text("/WinAnsiEncoding", "A B-C•") == b"A B-C\x95"
    assert encode_simple_text("/MacRomanEncoding", "A B") == b"A B"


@pytest.mark.parametrize(
    ("font", "replacement", "stem"),
    [
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>",
            "\u00ad",
            "winansi-soft-hyphen",
        ),
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Symbol >>",
            "B",
            "symbol-default",
        ),
    ],
)
def test_public_rewrite_rejects_unproven_simple_encoding_atomically(
    project_root: Path,
    tmp_path: Path,
    font: bytes,
    replacement: str,
    stem: str,
) -> None:
    source = _write_pdf(tmp_path / f"{stem}-source.pdf", font)
    _assert_public_enhancement_atomically(
        project_root,
        tmp_path,
        source,
        replacement,
        stem,
    )


def test_core_rewrite_rejects_macroman_euro_atomically(tmp_path: Path) -> None:
    source = _write_pdf(
        tmp_path / "macroman-euro-source.pdf",
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /MacRomanEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "macroman-euro-output.pdf"
    output_before = b"existing destination"
    output.write_bytes(output_before)
    request = _request(source, output, "€")

    with pytest.raises(DocumentSkillsError) as caught:
        rewrite_apply_pdf(source, output, request["arguments"])

    assert caught.value.details["capability"] == "pdf.rewrite-font-encoding"
    assert source.read_bytes() == source_before
    assert output.read_bytes() == output_before


def test_public_winansi_rewrite_with_canonical_space_succeeds(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "winansi-space-source.pdf",
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    output = tmp_path / "winansi-space-output.pdf"
    result = _public(
        project_root,
        _write_request(
            tmp_path / "winansi-space.json",
            _request(source, output, "A B"),
        ),
    )

    assert result["status"] == "success", result
    assert b"(A B) Tj" in output.read_bytes()


def test_public_standard_encoding_uses_quotesingle_code_a9(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "standard-quotesingle-source.pdf",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    output = tmp_path / "standard-quotesingle-output.pdf"
    result = _public(
        project_root,
        _write_request(
            tmp_path / "standard-quotesingle.json",
            _request(source, output, "'"),
        ),
    )
    assert result["status"] == "success", result
    raw = output.read_bytes()
    assert b"(\\251) Tj" in raw
    assert b"(') Tj" not in raw


def test_public_rewrite_rejects_inconsistent_to_unicode_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "inconsistent-tounicode-source.pdf",
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding /ToUnicode 6 0 R >>"
        ),
        extra_objects={6: _stream(b"<<", _cmap((0x41, 0x0041), (0x01, 0x00E9)))},
    )
    _assert_public_enhancement_atomically(
        project_root,
        tmp_path,
        source,
        "é",
        "inconsistent-tounicode",
    )


def test_public_rewrite_accepts_consistent_encoding_and_to_unicode(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "consistent-tounicode-source.pdf",
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding /ToUnicode 6 0 R >>"
        ),
        extra_objects={6: _stream(b"<<", _cmap((0x41, 0x0041), (0xE9, 0x00E9)))},
    )
    output = tmp_path / "consistent-tounicode-output.pdf"
    result = _public(
        project_root,
        _write_request(
            tmp_path / "consistent-tounicode.json",
            _request(source, output, "é"),
        ),
    )
    assert result["status"] == "success", result
    assert b"(\\351) Tj" in output.read_bytes()


def test_public_rewrite_rejects_embedded_custom_type1_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "embedded-type1-source.pdf",
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding /FontDescriptor 6 0 R >>"
        ),
        extra_objects={
            6: b"<< /Type /FontDescriptor /FontName /Helvetica /FontFile 7 0 R >>",
            7: _stream(b"<<", b"custom-font-program"),
        },
    )
    _assert_public_enhancement_atomically(
        project_root,
        tmp_path,
        source,
        "é",
        "embedded-type1",
    )
