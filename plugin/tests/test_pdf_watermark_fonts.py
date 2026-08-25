"""Public PDF watermark font-selection and semantic-gate regressions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.pdf.content_streams import (
    extract_content_stream,
    walk_text_operators,
)
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import _build_manifest
from document_skills_core.formats.pdf.object_model import (
    IndirectReference,
    PdfDict,
    PdfObjectModel,
    parse_pdf,
)
from document_skills_core.formats.pdf.page_tree import PageInfo, walk_pages
from document_skills_core.formats.pdf import service as service_module
from document_skills_core.formats.pdf.service import PdfService


@pytest.mark.parametrize("font", ["Helvetica", "Times-Roman", "Courier"])
def test_public_text_watermark_binds_requested_base14_font_without_collisions(
    project_root: Path,
    tmp_path: Path,
    font: str,
) -> None:
    source = _inherited_resource_pdf(tmp_path / f"source-{font}.pdf")
    source_bytes = source.read_bytes()
    output = tmp_path / f"watermarked-{font}.pdf"
    request = _request(
        tmp_path / f"watermark-{font}.json",
        source,
        output,
        [{
            "type": "watermark",
            "text": f"MARK {font}",
            "pages": [1, 2],
            "font": font,
            "opacity": 0.4,
        }],
    )

    result = _public(project_root, request)

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    operation = result["diagnostics"]["operation_result"]
    assert operation["font"] == font
    gate = next(
        item for item in result["validation"]["gates"]
        if item["id"] == "operation.mutation-semantics"
    )
    assert gate["outcome"] == "pass"
    assert gate["evidence"]["watermark"] == 2
    assert source.read_bytes() == source_bytes

    source_model = parse_pdf(source)
    output_model = parse_pdf(output)
    output_pages = walk_pages(output_model)
    resource_names = {
        _assert_watermark_font(output_model, page, f"MARK {font}", font)
        for page in output_pages[:2]
    }
    assert len(resource_names) == 1
    resource_name = resource_names.pop()
    assert resource_name not in {"/DSWMFont", "/DSWMFont1", "/Keep"}
    for page in output_pages[:2]:
        fonts = _page_fonts(output_model, page)
        assert fonts.get("/DSWMFont") == IndirectReference(9, 0)
        assert fonts.get("/DSWMFont1") == IndirectReference(9, 0)
        assert fonts.get("/Keep") == IndirectReference(10, 0)

    untouched_fonts = _page_fonts(output_model, output_pages[2])
    assert set(untouched_fonts.entries) == {"/DSWMFont", "/DSWMFont1", "/Keep"}
    manifest = operation["preservation"]
    for object_number in (1, 2, 5, 8, 9, 10, 11):
        assert source_model.objects[object_number].sha256 == output_model.objects[object_number].sha256
        assert object_number in manifest["preserved_objects"]
    assert set(operation["changed_objects"]) == {3, 4, 6, 7}
    assert operation["added_objects"]
    assert operation["removed_objects"] == []


def test_public_text_watermark_accepts_a_base14_style_variant(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _inherited_resource_pdf(tmp_path / "variant-source.pdf")
    output = tmp_path / "variant-output.pdf"
    request = _request(
        tmp_path / "variant.json",
        source,
        output,
        [{
            "type": "watermark",
            "text": "VARIANT",
            "pages": [1],
            "font": "Times-BoldItalic",
        }],
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    model = parse_pdf(output)
    _assert_watermark_font(model, walk_pages(model)[0], "VARIANT", "Times-BoldItalic")


def test_public_text_watermark_reuses_a_matching_dedicated_font_resource(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _inherited_resource_pdf(
        tmp_path / "reuse-source.pdf",
        conflict_font="Helvetica",
    )
    output = tmp_path / "reuse-output.pdf"
    request = _request(
        tmp_path / "reuse.json",
        source,
        output,
        [{
            "type": "watermark",
            "text": "REUSE",
            "pages": [1, 2],
            "font": "Helvetica",
        }],
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["added_objects"] == [12]
    model = parse_pdf(output)
    for page in walk_pages(model)[:2]:
        assert _assert_watermark_font(model, page, "REUSE", "Helvetica") == "/DSWMFont"


def test_public_unsupported_watermark_font_rolls_back_transaction(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _inherited_resource_pdf(tmp_path / "unsupported-source.pdf")
    source_before = source.read_bytes()
    output = tmp_path / "unsupported-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    request = _request(
        tmp_path / "unsupported.json",
        source,
        output,
        [
            {"type": "rotate", "pages": [1], "degrees": 90},
            {
                "type": "watermark",
                "text": "ROLL BACK",
                "pages": [1],
                "font": "ComicSansMS",
            },
        ],
    )

    result = _public(project_root, request)

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert result["errors"][0]["details"] == {
        "capability": "pdf.watermark-font",
        "field": "primitives.1.font",
        "supported_fonts": [
            "Courier",
            "Courier-Bold",
            "Courier-BoldOblique",
            "Courier-Oblique",
            "Helvetica",
            "Helvetica-Bold",
            "Helvetica-BoldOblique",
            "Helvetica-Oblique",
            "Times-Bold",
            "Times-BoldItalic",
            "Times-Italic",
            "Times-Roman",
        ],
    }
    assert result["artifacts"] == []
    assert source.read_bytes() == source_before
    assert output.read_bytes() == destination_before


def test_service_semantic_gate_rejects_wrong_watermark_basefont(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "semantic-source.pdf"
    create_pdf(source, _document())
    output = tmp_path / "semantic-output.pdf"
    output.write_bytes(b"preserve destination")
    real_edit_pdf = service_module.edit_pdf

    def wrong_font_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit_pdf(input_path, output_path, arguments)
        candidate = output_path.read_bytes()
        requested = b"/BaseFont /Courier /Encoding"
        assert candidate.count(requested) == 1
        output_path.write_bytes(candidate.replace(
            requested,
            b"/BaseFont /Symbol  /Encoding",
        ))
        output_hashes = parse_pdf(output_path).object_hashes()
        manifest = _build_manifest(
            parse_pdf(input_path).object_hashes(),
            output_hashes,
            changed=set(manifest["changed_objects"]),
            added=set(manifest["added_objects"]),
            removed=set(manifest["removed_objects"]),
        )
        operation["preservation"] = manifest
        return operation, manifest

    monkeypatch.setattr(service_module, "edit_pdf", wrong_font_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"primitives": [{
                "type": "watermark",
                "text": "SEMANTIC",
                "pages": [1],
                "font": "Courier",
            }]},
        },
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics",
    ]
    assert output.read_bytes() == b"preserve destination"


def _assert_watermark_font(
    model: PdfObjectModel,
    page: PageInfo,
    text: str,
    base_font: str,
) -> str:
    content = extract_content_stream(model, page.contents, page.page_number)
    blocks = [block for block in walk_text_operators(content, page.page_number) if block.text == text]
    assert len(blocks) == 1
    resource_name = blocks[0].font_name
    assert resource_name.startswith("/DSWMFont")
    reference = _page_fonts(model, page).get(resource_name)
    assert isinstance(reference, IndirectReference)
    font = model.get_object(reference).value
    assert isinstance(font, PdfDict)
    assert font.get("/Type") == "/Font"
    assert font.get("/Subtype") == "/Type1"
    assert font.get("/BaseFont") == f"/{base_font}"
    assert font.get("/Encoding") == "/WinAnsiEncoding"
    return resource_name


def _page_fonts(model: PdfObjectModel, page: PageInfo) -> PdfDict:
    assert isinstance(page.resources, PdfDict)
    fonts = page.resources.get("/Font")
    if isinstance(fonts, IndirectReference):
        fonts = model.get_object(fonts).value
    assert isinstance(fonts, PdfDict)
    return fonts


def _public(project_root: Path, request: Path) -> dict[str, Any]:
    completed = subprocess.run(
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
    assert completed.stderr == b""
    payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _request(
    path: Path,
    source: Path,
    output: Path,
    primitives: list[dict[str, Any]],
) -> Path:
    path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"primitives": primitives},
        }, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _inherited_resource_pdf(
    path: Path,
    *,
    conflict_font: str = "Symbol",
) -> Path:
    conflict_encoding = (
        b" /Encoding /WinAnsiEncoding"
        if conflict_font != "Symbol"
        else b""
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 "
            b"/MediaBox [0 0 300 300] /Resources << /ProcSet [/PDF /Text] "
            b"/Font 11 0 R >> >>"
        ),
        b"<< /Type /Page /Parent 2 0 R /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 7 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 8 0 R >>",
        _stream(b"BT /Keep 10 Tf 20 250 Td (PAGE ONE) Tj ET"),
        _stream(b"BT /Keep 10 Tf 20 250 Td (PAGE TWO) Tj ET"),
        _stream(b"BT /Keep 10 Tf 20 250 Td (PAGE THREE) Tj ET"),
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /"
            + conflict_font.encode("ascii")
            + conflict_encoding
            + b" >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /DSWMFont 9 0 R /DSWMFont1 9 0 R /Keep 10 0 R >>",
    ]
    return _write_pdf(path, objects)


def _stream(content: bytes) -> bytes:
    return b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream"


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
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


def _document() -> dict[str, Any]:
    return {
        "metadata": {"title": "Watermark semantics", "author": "Elftia", "subject": ""},
        "page_size": "A4",
        "pages": [{
            "blocks": [{
                "type": "paragraph",
                "text": "Source",
                "style": None,
                "table": None,
                "image": None,
                "shape": None,
            }],
            "metadata": None,
        }],
    }
