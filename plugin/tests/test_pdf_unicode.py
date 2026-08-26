"""Public contract tests for embedded Unicode PDF fonts and shaping."""

import hashlib
import json
from pathlib import Path
import subprocess

from pypdf import PdfReader, PdfWriter

from document_skills_core.formats.pdf.contracts import parse_pdf_request


def _font_spec(project_root: Path, filename: str, font_id: str) -> dict[str, str]:
    path = project_root / "tests" / "fixtures" / "pdf-fonts" / filename
    return {
        "id": font_id,
        "filename": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _unicode_document(project_root: Path) -> dict[str, object]:
    return {
        "metadata": {
            "title": "Unicode 文档 العربية",
            "author": "Elftia 测试",
            "subject": "CJK 与 RTL",
        },
        "page_size": "A4",
        "fonts": [
            _font_spec(project_root, "elftia-pdf-cjk-test.ttf", "cjk"),
            _font_spec(project_root, "elftia-pdf-arabic-test.ttf", "arabic"),
        ],
        "pages": [
            {
                "blocks": [
                    {
                        "type": "heading",
                        "text": "中文测试",
                        "style": {
                            "font_family": "cjk",
                            "font_size": 18,
                            "font_weight": "normal",
                            "font_style": "normal",
                            "color": [0.1, 0.2, 0.3],
                            "line_height": 24,
                            "alignment": "left",
                            "fallback_fonts": [],
                            "direction": "ltr",
                            "language": "zh-Hans",
                        },
                        "table": None,
                        "image": None,
                        "shape": None,
                    },
                    {
                        "type": "paragraph",
                        "text": "مرحبا بالعالم 123 PDF",
                        "style": {
                            "font_family": "arabic",
                            "font_size": 16,
                            "font_weight": "normal",
                            "font_style": "normal",
                            "color": [0.0, 0.0, 0.0],
                            "line_height": 24,
                            "alignment": "right",
                            "fallback_fonts": ["cjk"],
                            "direction": "rtl",
                            "language": "ar",
                        },
                        "table": None,
                        "image": None,
                        "shape": None,
                    },
                ],
                "metadata": None,
            }
        ],
    }


def _write_request(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _rewrite_style(font_id: str) -> dict[str, object]:
    return {
        "font_family": font_id,
        "font_size": 12.0,
        "font_weight": "normal",
        "font_style": "normal",
        "color": [0.0, 0.0, 0.0],
        "line_height": 16.0,
        "alignment": "left",
        "fallback_fonts": [],
        "direction": "ltr",
        "language": "zh-Hans",
    }


def _create_plain_pages(
    project_root: Path,
    tmp_path: Path,
    name: str,
    texts: list[str],
) -> Path:
    output = tmp_path / f"{name}.pdf"
    request = _write_request(
        tmp_path / f"{name}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {"title": name, "author": "", "subject": ""},
                    "page_size": "A4",
                    "pages": [
                        {
                            "blocks": [{
                                "type": "paragraph",
                                "text": text,
                                "style": None,
                                "table": None,
                                "image": None,
                                "shape": None,
                            }],
                            "metadata": None,
                        }
                        for text in texts
                    ],
                },
            },
        },
    )
    assert _public(project_root, "run", "--request", str(request))["status"] == "success"
    return output


def _read_blocks(project_root: Path, tmp_path: Path, source: Path) -> list[dict[str, object]]:
    request = _write_request(
        tmp_path / f"read-{source.stem}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(source),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    return [
        {
            key: block[key]
            for key in ("page", "bbox", "text", "font", "size", "color")
        }
        for block in result["diagnostics"]["operation_result"]["text_blocks"]
    ]


def _public(project_root: Path, *arguments: str, check: bool = True) -> dict[str, object]:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills" / "document-pdf" / "scripts" / "run.py"),
            *arguments,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        shell=False,
        timeout=60,
    )
    if check:
        assert completed.returncode == 0, completed.stdout.decode("utf-8", errors="replace")
    assert completed.stderr == b""
    return json.loads(completed.stdout.decode("utf-8", errors="strict"))


def test_unicode_create_contract_accepts_hash_bound_local_fonts(project_root: Path) -> None:
    parsed = parse_pdf_request(
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": "unicode.pdf",
            "arguments": {"document": _unicode_document(project_root)},
        }
    )

    document = parsed.arguments["document"]
    assert [font["id"] for font in document["fonts"]] == ["cjk", "arabic"]
    assert document["pages"][0]["blocks"][1]["style"]["direction"] == "rtl"


def test_public_unicode_create_read_validate_and_determinism(
    project_root: Path,
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / "unicode-1.pdf", tmp_path / "unicode-2.pdf"]
    results = []
    for index, output in enumerate(outputs, start=1):
        request = _write_request(
            tmp_path / f"unicode-create-{index}.json",
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(output),
                "arguments": {"document": _unicode_document(project_root)},
            },
        )
        result = _public(project_root, "run", "--request", str(request), check=False)
        assert result["status"] == "success", result
        assert result["validation"]["status"] == "pass"
        results.append(result)

    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    raw = outputs[0].read_bytes()
    assert b"/Subtype /Type0" in raw
    assert b"/CIDFontType2" in raw
    assert b"/CIDToGIDMap" in raw
    assert b"/ToUnicode" in raw
    assert b"/ActualText" in raw

    creation = results[0]["diagnostics"]["operation_result"]["creation"]
    assert creation["structures"]["embedded_font"] is True
    assert [font["id"] for font in creation["fonts"]] == ["cjk", "arabic"]
    assert all(font["subset"] is True for font in creation["fonts"])
    assert all(font["license"] for font in creation["fonts"])
    assert all(font["source_sha256"] for font in creation["fonts"])
    assert any(block["direction"] == "rtl" for block in creation["text_blocks"])

    read_request = _write_request(
        tmp_path / "unicode-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(outputs[0]),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request), check=False)
    assert read_result["status"] == "success", read_result
    operation = read_result["diagnostics"]["operation_result"]
    assert operation["metadata"]["title"] == "Unicode 文档 العربية"
    assert operation["text_by_page"][0]["text"] == "中文测试\nمرحبا بالعالم 123 PDF"
    assert all(font["embedded"] is True for font in operation["fonts_by_page"][0][4:])
    assert all(font["subset"] is True for font in operation["fonts_by_page"][0][4:])
    assert all(font["cmap"] for font in operation["fonts_by_page"][0][4:])

    validation = _public(
        project_root,
        "validate",
        "--input",
        str(outputs[0]),
        "--json",
    )
    assert validation["status"] == "pass"


def test_unicode_font_hash_mismatch_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"sentinel-font-hash")
    document = _unicode_document(project_root)
    document["fonts"][0]["sha256"] = "0" * 64
    request = _write_request(
        tmp_path / "font-hash-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == b"sentinel-font-hash"


def test_unicode_missing_glyphs_are_explicit_and_do_not_publish(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing-glyph.pdf"
    document = _unicode_document(project_root)
    document["pages"][0]["blocks"][0]["text"] = "中文🧝"
    request = _write_request(
        tmp_path / "missing-glyph.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "enhancement_required"
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert result["errors"][0]["details"]["missing_glyphs"] == [
        {"character": "🧝", "codepoint": "U+1F9DD"}
    ]
    assert not output.exists()


def test_public_cjk_rewrite_embeds_font_and_checks_source_precondition(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "rewrite-source.pdf"
    create_request = _write_request(
        tmp_path / "rewrite-source.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(source),
            "arguments": {
                "document": {
                    "metadata": {"title": "Rewrite", "author": "", "subject": ""},
                    "page_size": "A4",
                    "pages": [{
                        "blocks": [{
                            "type": "paragraph",
                            "text": "Rewrite target",
                            "style": None,
                            "table": None,
                            "image": None,
                            "shape": None,
                        }],
                        "metadata": None,
                    }],
                },
            },
        },
    )
    assert _public(project_root, "run", "--request", str(create_request))["status"] == "success"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "rewrite-cjk.pdf"
    rewrite_request = _write_request(
        tmp_path / "rewrite-cjk.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "source_sha256": source_hash,
                "fonts": [
                    _font_spec(project_root, "elftia-pdf-cjk-test.ttf", "cjk"),
                ],
                "blocks": [{
                    "page": 1,
                    "bbox": [72, 750, 300, 780],
                    "text": "Rewrite target",
                    "font": "F1",
                    "size": 12.0,
                    "color": [0.0, 0.0, 0.0],
                }],
                "rewrites": [{
                    "block_index": 0,
                    "text": "中文测试",
                    "style": {
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
                    },
                }],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(rewrite_request), check=False)

    assert result["status"] == "success", result
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert b"/Subtype /Type0" in output.read_bytes()
    read_request = _write_request(
        tmp_path / "rewrite-cjk-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert read_result["diagnostics"]["operation_result"]["text_by_page"][0]["text"] == "中文测试"


def test_public_rtl_rewrite_embeds_subset_and_preserves_untargeted_page(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _create_plain_pages(
        project_root,
        tmp_path,
        "rtl-rewrite-source",
        ["Rewrite target", "Untargeted page"],
    )
    source_before = source.read_bytes()
    blocks = _read_blocks(project_root, tmp_path, source)
    target = blocks[0]
    target["bbox"] = [
        target["bbox"][0],
        target["bbox"][1] - 21.0,
        500.0,
        target["bbox"][3] + 20.0,
    ]
    rtl_style = _rewrite_style("arabic")
    rtl_style.update({
        "alignment": "right",
        "direction": "rtl",
        "language": "ar",
    })
    output = tmp_path / "rtl-rewrite-output.pdf"
    request = _write_request(
        tmp_path / "rtl-rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "source_sha256": hashlib.sha256(source_before).hexdigest(),
                "fonts": [
                    _font_spec(project_root, "elftia-pdf-arabic-test.ttf", "arabic"),
                ],
                "blocks": [target],
                "rewrites": [{
                    "block_index": 0,
                    "text": "مرحبا بالعالم 123 PDF",
                    "style": rtl_style,
                }],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    assert source.read_bytes() == source_before
    rewrite = result["diagnostics"]["operation_result"]["rewrite"]
    assert rewrite["rewrite_evidence"][0]["direction"] == "rtl"
    assert rewrite["page_layout_preservation"] == {
        "page_count_match": True,
        "page_box_preserved": True,
        "non_targeted_objects_preserved": True,
        "targeted_pages": [1],
        "verified": True,
    }
    raw = output.read_bytes()
    assert b"/Subtype /Type0" in raw
    assert b"/CIDFontType2" in raw
    assert b"/ToUnicode" in raw
    assert b"/ActualText" in raw

    read_request = _write_request(
        tmp_path / "rtl-rewrite-output-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    operation = read_result["diagnostics"]["operation_result"]
    assert [page["text"] for page in operation["text_by_page"]] == [
        "مرحبا بالعالم 123 PDF",
        "Untargeted page",
    ]
    assert any(
        font["embedded"] is True
        and font["subset"] is True
        and font["cmap"]
        for font in operation["fonts_by_page"][0]
    )


def test_public_unicode_rewrite_supports_multiline_and_mixed_latin_transaction(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _create_plain_pages(
        project_root,
        tmp_path,
        "mixed-rewrite-source",
        ["First target", "Second target"],
    )
    blocks = _read_blocks(project_root, tmp_path, source)
    blocks[0]["bbox"] = [72.0, 700.0, 300.0, 780.0]
    output = tmp_path / "mixed-rewrite-output.pdf"
    request = _write_request(
        tmp_path / "mixed-rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "fonts": [
                    _font_spec(project_root, "elftia-pdf-cjk-test.ttf", "cjk"),
                ],
                "blocks": blocks,
                "rewrites": [
                    {
                        "block_index": 0,
                        "text": "中文测试\n你好世界",
                        "style": _rewrite_style("cjk"),
                    },
                    {
                        "block_index": 1,
                        "text": "PDF Latin",
                        "style": _rewrite_style("cjk"),
                    },
                ],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    evidence = result["diagnostics"]["operation_result"]["rewrite"][
        "rewrite_evidence"
    ]
    assert evidence[0]["line_count"] == 2
    assert len(evidence[0]["line_bboxes"]) == 2
    read_blocks = _read_blocks(project_root, tmp_path, output)
    assert [block["text"] for block in read_blocks] == [
        "中文测试",
        "你好世界",
        "PDF Latin",
    ]


def test_public_unicode_rewrite_accepts_single_flate_content_stream(
    project_root: Path,
    tmp_path: Path,
) -> None:
    plain = _create_plain_pages(
        project_root,
        tmp_path,
        "flate-rewrite-plain",
        ["Compressed target"],
    )
    source = tmp_path / "flate-rewrite-source.pdf"
    reader = PdfReader(plain)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for page in writer.pages:
        page.compress_content_streams()
    with source.open("wb") as handle:
        writer.write(handle)
    blocks = _read_blocks(project_root, tmp_path, source)
    output = tmp_path / "flate-rewrite-output.pdf"
    request = _write_request(
        tmp_path / "flate-rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "fonts": [
                    _font_spec(project_root, "elftia-pdf-cjk-test.ttf", "cjk"),
                ],
                "blocks": blocks,
                "rewrites": [{
                    "block_index": 0,
                    "text": "中文测试",
                    "style": _rewrite_style("cjk"),
                }],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    assert _read_blocks(project_root, tmp_path, output)[0]["text"] == "中文测试"
