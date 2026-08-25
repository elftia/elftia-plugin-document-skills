"""Public-boundary regressions for the round-one PDF rewrite findings."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest
from pypdf import PdfReader

from document_skills_core.formats.pdf.content_streams import (
    extract_content_stream,
    walk_text_operators,
)
from document_skills_core.formats.pdf import rewrite as rewrite_module
from document_skills_core.formats.pdf.mutation_writer import write_pdf_mutation
from document_skills_core.formats.pdf.object_model import PdfObjectModel, parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.rewrite_operator_targeting import OperatorLocator
from document_skills_core.formats.pdf.service import PdfService


def _public(project_root: Path, request: Path) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv", "run", "--project", str(project_root), "--frozen", "python",
            str(project_root / "skills/document-pdf/scripts/run.py"),
            "run", "--request", str(request),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def _write_request(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_pdf(
    path: Path,
    page_contents: list[list[int]],
    streams: dict[int, bytes],
    *,
    font: bytes | None = None,
) -> Path:
    page_count = len(page_contents)
    font_object = 3 + page_count
    page_objects = list(range(3, 3 + page_count))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{item} 0 R' for item in page_objects)}] "
            f"/Count {page_count} >>"
        ).encode("ascii"),
        font_object: font or b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_object, references in zip(page_objects, page_contents, strict=True):
        contents = " ".join(f"{item} 0 R" for item in references)
        if len(references) > 1:
            contents = f"[{contents}]"
        objects[page_object] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_object} 0 R >> >> "
            f"/Contents {contents} >>"
        ).encode("ascii")
    for object_number, stream in streams.items():
        objects[object_number] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
    return _serialize_pdf(path, objects)


def _serialize_pdf(path: Path, objects: dict[int, bytes]) -> Path:
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


def _font(project_root: Path) -> dict[str, str]:
    path = project_root / "tests/fixtures/pdf-fonts/elftia-pdf-cjk-test.ttf"
    return {
        "id": "cjk",
        "filename": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _style() -> dict[str, object]:
    return {
        "font_family": "cjk",
        "font_size": 12.0,
        "font_weight": "normal",
        "font_style": "normal",
        "color": [0.0, 0.0, 0.0],
        "line_height": 14.0,
        "alignment": "left",
        "fallback_fonts": [],
        "direction": "ltr",
        "language": "zh-Hans",
    }


def _rewrite_request(
    source: Path,
    output: Path,
    blocks: list[dict[str, object]],
    replacement: str,
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    selected = dict(blocks[0])
    if project_root is not None:
        bbox = list(selected["bbox"])
        bbox[2] = max(float(bbox[2]), float(bbox[0]) + 240.0)
        selected["bbox"] = bbox
    arguments: dict[str, object] = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "blocks": [selected],
        "rewrites": [{"block_index": 0, "text": replacement}],
    }
    if project_root is not None:
        arguments["fonts"] = [_font(project_root)]
        arguments["rewrites"][0]["style"] = _style()
    return {
        "schema_version": "1.0",
        "operation": "pdf.rewrite.apply",
        "input": str(source),
        "output": str(output),
        "arguments": arguments,
    }


@pytest.mark.parametrize("replacement", ["Changed", "中文测试"])
def test_public_rewrite_rejects_page_scoped_shared_contents(
    project_root: Path,
    tmp_path: Path,
    replacement: str,
) -> None:
    stream = b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Shared) Tj ET\n"
    source = _write_pdf(tmp_path / "shared.pdf", [[6], [6]], {6: stream})
    output = tmp_path / "shared-output.pdf"
    output.write_bytes(b"existing destination")
    request = _rewrite_request(
        source,
        output,
        _blocks(source),
        replacement,
        project_root=project_root if replacement != "Changed" else None,
    )

    result = _public(project_root, _write_request(tmp_path / "shared.json", request))

    assert result["status"] in {"failed", "enhancement_required"}, result
    assert output.read_bytes() == b"existing destination"


@pytest.mark.parametrize(
    ("page_contents", "streams", "preserved", "emptied"),
    [
        (
            [[5]],
            {5: (
                b"/Span << /ActualText (Title) >> BDC EMC\n"
                b"BT /F1 12 Tf 1 0 0 1 72 720 Tm <5469746C65> Tj ET\n"
            )},
            b"/ActualText (Title)",
            b"<> Tj",
        ),
        (
            [[5, 6]],
            {
                5: b"/Span << /ActualText (Title) >> BDC EMC\n",
                6: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm [(Ti) -20 <746C65>] TJ ET\n",
            },
            b"/ActualText (Title)",
            b"[] TJ",
        ),
    ],
    ids=["hex-tj-actualtext", "mixed-tj-multiple-streams"],
)
def test_public_unicode_rewrite_uses_exact_operator_locator(
    project_root: Path,
    tmp_path: Path,
    page_contents: list[list[int]],
    streams: dict[int, bytes],
    preserved: bytes,
    emptied: bytes,
) -> None:
    source = _write_pdf(tmp_path / "unicode-target.pdf", page_contents, streams)
    output = tmp_path / "unicode-target-output.pdf"
    request = _rewrite_request(
        source,
        output,
        _blocks(source),
        "中文测试",
        project_root=project_root,
    )

    result = _public(project_root, _write_request(tmp_path / "unicode-target.json", request))

    assert result["status"] == "success", result
    raw = output.read_bytes()
    assert preserved in raw
    assert emptied in raw
    assert raw.count(b"Title") == 1
    assert [block["text"] for block in _blocks(output) if block["text"]] == [
        "中文测试"
    ]


@pytest.mark.parametrize("encoding", ["MacRomanEncoding", "WinAnsiEncoding"])
def test_public_rewrite_encodes_text_for_named_target_font_within_bounds(
    project_root: Path,
    tmp_path: Path,
    encoding: str,
) -> None:
    source = _write_pdf(
        tmp_path / f"{encoding}-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Cafe) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            + f"/Encoding /{encoding} >>".encode("ascii")
        ),
    )
    output = tmp_path / f"{encoding}-output.pdf"
    request = _rewrite_request(source, output, _blocks(source), "é")

    result = _public(
        project_root,
        _write_request(tmp_path / f"{encoding}-rewrite.json", request),
    )

    assert result["status"] == "success", result
    assert PdfReader(output).pages[0].extract_text() == "é"


def test_public_rewrite_rejects_replacement_outside_selector_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-overflow-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (A) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-overflow-output.pdf"
    output.write_bytes(b"existing destination")
    request = _rewrite_request(source, output, _blocks(source), "W" * 20)

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-overflow.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_public_rewrite_rejects_ctm_scaled_overflow_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-ctm-overflow-source.pdf",
        [[5]],
        {
            5: (
                b"q 2 0 0 2 -72 -720 cm "
                b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (A) Tj ET Q\n"
            )
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-ctm-overflow-output.pdf"
    output.write_bytes(b"existing destination")
    blocks = _blocks(source)
    blocks[0]["bbox"] = [72.0, 717.6, 97.0, 729.6]
    request = _rewrite_request(source, output, blocks, "WW")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-ctm-overflow.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-layout-bounds"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_public_rewrite_rejects_non_default_tz_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-tz-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 200 Tz 1 0 0 1 72 720 Tm (A) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-tz-output.pdf"
    output.write_bytes(b"existing destination")
    request = _rewrite_request(source, output, _blocks(source), "W")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-tz.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-text-state"
    )
    assert result["errors"][0]["details"]["operators"] == ["Tz"]
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


@pytest.mark.parametrize(
    ("state_operator", "expected_operator"),
    [(b"1 Tr", "Tr"), (b"/GS1 gs", "gs")],
    ids=["non-default-rendering-mode", "external-graphics-state"],
)
def test_public_rewrite_rejects_unmodeled_graphics_text_state_atomically(
    project_root: Path,
    tmp_path: Path,
    state_operator: bytes,
    expected_operator: str,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-graphics-text-state-source.pdf",
        [[5]],
        {
            5: (
                b"BT /F1 12 Tf "
                + state_operator
                + b" 1 0 0 1 72 720 Tm (A) Tj ET\n"
            )
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-graphics-text-state-output.pdf"
    output.write_bytes(b"existing destination")
    request = _rewrite_request(source, output, _blocks(source), "W")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-graphics-text-state.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-text-state"
    )
    assert result["errors"][0]["details"]["operators"] == [
        expected_operator
    ]
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_public_rewrite_accepts_explicit_default_text_state(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-default-text-state-source.pdf",
        [[5]],
        {
            5: (
                b"BT /F1 12 Tf 0 Tc 0 Tw 100 Tz 0 Tr 0 Ts "
                b"1 0 0 1 72 720 Tm (A) Tj ET\n"
            )
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    output = tmp_path / "rewrite-default-text-state-output.pdf"
    blocks = _blocks(source)
    blocks[0]["bbox"] = [72.0, 717.6, 97.0, 729.6]
    request = _rewrite_request(source, output, blocks, "WW")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-default-text-state.json", request),
    )

    assert result["status"] == "success", result
    assert PdfReader(output).pages[0].extract_text() == "WW"


def test_public_rewrite_honors_explicit_base14_widths_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-explicit-width-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (A) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding /FirstChar 65 /Widths [667 5000] >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-explicit-width-output.pdf"
    output.write_bytes(b"existing destination")
    request = _rewrite_request(source, output, _blocks(source), "B")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-explicit-width.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-layout-bounds"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


@pytest.mark.parametrize(
    "prefix",
    [b"(A) Tj ", b"[(A) -100] TJ "],
    ids=["consecutive-tj", "tj-kerning"],
)
def test_public_rewrite_advances_text_matrix_between_show_operators(
    project_root: Path,
    tmp_path: Path,
    prefix: bytes,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-text-advance-source.pdf",
        [[5]],
        {
            5: (
                b"BT /F1 12 Tf 1 0 0 1 72 720 Tm "
                + prefix
                + b"(B) Tj ET\n"
            )
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-text-advance-output.pdf"
    output.write_bytes(b"existing destination")
    target = _blocks(source)[1]
    target["bbox"] = [72.0, 717.6, 97.0, 729.6]
    request = _rewrite_request(source, output, [target], "WW")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-text-advance.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-layout-bounds"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_public_rewrite_carries_ctm_and_text_state_across_contents(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-cross-stream-source.pdf",
        [[5, 6]],
        {
            5: b"q 2 0 0 2 -72 -720 cm BT /F1 12 Tf 1 0 0 1 72 720 Tm\n",
            6: b"(A) Tj ET Q\n",
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-cross-stream-output.pdf"
    output.write_bytes(b"existing destination")
    blocks = _blocks(source)
    blocks[0]["bbox"] = [72.0, 717.6, 97.0, 729.6]
    request = _rewrite_request(source, output, blocks, "WW")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-cross-stream.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-layout-bounds"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_public_rewrite_restores_ctm_after_q_q(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-restored-ctm-source.pdf",
        [[5]],
        {
            5: (
                b"q 2 0 0 2 -72 -720 cm Q "
                b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (A) Tj ET\n"
            )
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    output = tmp_path / "rewrite-restored-ctm-output.pdf"
    blocks = _blocks(source)
    blocks[0]["bbox"] = [72.0, 717.6, 97.0, 729.6]
    request = _rewrite_request(source, output, blocks, "WW")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-restored-ctm.json", request),
    )

    assert result["status"] == "success", result
    assert PdfReader(output).pages[0].extract_text() == "WW"


def test_public_rewrite_tracks_tl_before_t_star_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "rewrite-leading-source.pdf",
        [[5]],
        {
            5: (
                b"BT /F1 12 Tf 20 TL 1 0 0 1 72 10 Tm "
                b"T* (A) Tj ET\n"
            )
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "rewrite-leading-output.pdf"
    output.write_bytes(b"existing destination")
    blocks = _blocks(source)
    blocks[0]["bbox"] = [72.0, -13.0, 97.0, 20.0]
    request = _rewrite_request(source, output, blocks, "A")

    result = _public(
        project_root,
        _write_request(tmp_path / "rewrite-leading.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-layout-bounds"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_public_rewrite_uses_consistent_target_font_to_unicode_mapping(
    project_root: Path,
    tmp_path: Path,
) -> None:
    cmap = (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin begincmap\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        b"1 beginbfchar\n<E9> <00E9>\nendbfchar\n"
        b"endcmap CMapName currentdict /CMap defineresource pop end end\n"
    )
    source = _write_pdf(
        tmp_path / "tounicode-source.pdf",
        [[5]],
        {
            5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Cafe) Tj ET\n",
            6: cmap,
        },
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding /ToUnicode 6 0 R >>"
        ),
    )
    output = tmp_path / "tounicode-output.pdf"
    request = _rewrite_request(source, output, _blocks(source), "é")

    result = _public(
        project_root,
        _write_request(tmp_path / "tounicode-rewrite.json", request),
    )

    assert result["status"] == "success", result
    assert PdfReader(output).pages[0].extract_text() == "é"


def test_public_rewrite_uses_embedded_overlay_for_unproven_simple_encoding(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "macexpert-overlay-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Cafe) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /MacExpertEncoding >>"
        ),
    )
    output = tmp_path / "macexpert-overlay-output.pdf"
    request = _rewrite_request(
        source,
        output,
        _blocks(source),
        "Done",
        project_root=project_root,
    )

    result = _public(
        project_root,
        _write_request(tmp_path / "macexpert-overlay.json", request),
    )

    assert result["status"] == "success", result
    assert PdfReader(output).pages[0].extract_text() == "Done"


def test_public_rewrite_rejects_unproven_encoding_without_overlay_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "macexpert-reject-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Cafe) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /MacExpertEncoding >>"
        ),
    )
    source_before = source.read_bytes()
    output = tmp_path / "macexpert-reject-output.pdf"
    output.write_bytes(b"existing destination")
    request = _rewrite_request(source, output, _blocks(source), "é")

    result = _public(
        project_root,
        _write_request(tmp_path / "macexpert-reject.json", request),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.rewrite-font-encoding"
    )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing destination"


def test_core_rewrite_semantic_gate_rejects_wrong_macroman_operand(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_pdf(
        tmp_path / "macroman-gate-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Cafe) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /MacRomanEncoding >>"
        ),
    )
    output = tmp_path / "macroman-gate-output.pdf"
    output.write_bytes(b"existing destination")

    def write_latin_1_operand(
        model: PdfObjectModel,
        locators: list[OperatorLocator],
        _rewrite_map: dict[int, str],
    ) -> tuple[bytes, set[int]]:
        object_number = locators[0].content_object
        payload = model.objects[object_number].payload_bytes
        replacement = payload.replace(b"(Cafe)", b"(\\351)", 1)
        return (
            write_pdf_mutation(
                model,
                {object_number: replacement},
                {},
                set(),
            ),
            {object_number},
        )

    monkeypatch.setattr(
        rewrite_module,
        "apply_targeted_rewrites",
        write_latin_1_operand,
    )
    request = _rewrite_request(source, output, _blocks(source), "é")

    result = PdfService(project_root).execute("pdf.rewrite.apply", request)

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == b"existing destination"


def test_core_rewrite_semantic_gate_rejects_candidate_bbox_overflow(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_pdf(
        tmp_path / "bbox-gate-source.pdf",
        [[5]],
        {5: b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (A) Tj ET\n"},
        font=(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    )
    output = tmp_path / "bbox-gate-output.pdf"
    output.write_bytes(b"existing destination")
    replacement_text = "W" * 20

    def write_overflow_operand(
        model: PdfObjectModel,
        locators: list[OperatorLocator],
        _rewrite_map: dict[int, str],
    ) -> tuple[bytes, set[int]]:
        object_number = locators[0].content_object
        payload = model.objects[object_number].payload_bytes
        operand = b"(" + replacement_text.encode("ascii") + b")"
        delta = len(operand) - len(b"(A)")
        replacement = re.sub(
            rb"/Length\s+(\d+)",
            lambda match: f"/Length {int(match.group(1)) + delta}".encode("ascii"),
            payload.replace(b"(A)", operand, 1),
            count=1,
        )
        return (
            write_pdf_mutation(
                model,
                {object_number: replacement},
                {},
                set(),
            ),
            {object_number},
        )

    monkeypatch.setattr(
        rewrite_module,
        "replacement_fits_layout",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        rewrite_module,
        "apply_targeted_rewrites",
        write_overflow_operand,
    )
    request = _rewrite_request(source, output, _blocks(source), replacement_text)

    result = PdfService(project_root).execute("pdf.rewrite.apply", request)

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == b"existing destination"
