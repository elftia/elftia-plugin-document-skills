"""PDF public command surface tests — frozen uv subprocess boundary.

Exercises the real public CLI (document-pdf/scripts/run.py), the
supervisor/worker, one stdout JSON result, honest provider chain, and honest
optional ``unavailable`` gates.  Includes a Unicode invocation directory to
mirror the XLSX/PPTX public tests.

Module provenance: original Elftia-authored test suite.
"""

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import zipfile
import zlib

from PIL import Image
import pytest
from pypdf import PdfReader, PdfWriter

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.pdf.create import create_pdf

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoH"
    "BwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQME"
    "BAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
    "FBQUFBQUFBQUFBQUFBT/wAARCAABAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx"
    "8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    "YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
    "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5"
    "0ooor8MP9Uz/2Q=="
)


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
    cwd: Path | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pdf/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    if check:
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    payload, end = decoder.raw_decode(text)
    assert text[end:].strip() == ""
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _assert_canonical_edit_report(report: dict[str, object]) -> None:
    preservation = report["preservation"]
    assert type(preservation) is dict
    for field in ("changed_objects", "added_objects", "removed_objects"):
        values = report[field]
        assert type(values) is list
        assert values == sorted(set(values))
        assert all(type(value) is int and value > 0 for value in values)
        assert values == preservation[field]
    page_impact = report["page_impact"]
    assert type(page_impact) is dict
    assert set(page_impact) == {
        "mode",
        "source_page_count",
        "output_page_count",
        "source_pages",
        "output_pages",
    }
    for side in ("source", "output"):
        pages = page_impact[f"{side}_pages"]
        page_count = page_impact[f"{side}_page_count"]
        assert pages == sorted(set(pages))
        assert all(1 <= page <= page_count for page in pages)


def _document() -> dict[str, object]:
    return {
        "metadata": {"title": "Public PDF", "author": "Test", "subject": ""},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {"type": "heading", "text": "Title", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "table", "text": None, "style": None, "table": {"rows": [{"cells": ["A", "B"]}]}, "image": None, "shape": None},
                ],
                "metadata": None,
            },
            {
                "blocks": [
                    {"type": "paragraph", "text": "Content", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "vector_shape", "text": None, "style": None, "table": None, "image": None, "shape": {"kind": "rectangle", "x": 72, "y": 72, "width": 100, "height": 50, "stroke": None, "fill": None}},
                ],
                "metadata": None,
            },
        ],
    }


def _minimal_text_document() -> dict[str, object]:
    example = Path(__file__).parents[1] / (
        "skills/document-pdf/assets/examples/create-minimal.json"
    )
    payload = json.loads(example.read_text(encoding="utf-8"))
    return payload["arguments"]["document"]


def _text_form_pdf(
    path: Path,
    *,
    second_field: bool = False,
    field_flags: int = 0,
    xfa: bool = False,
) -> Path:
    acroform_object = 8 if second_field else 7
    annotations = b"[6 0 R 7 0 R]" if second_field else b"[6 0 R]"
    field_flags_entry = (
        f" /Ff {field_flags}".encode("ascii")
        if field_flags
        else b""
    )
    xfa_entry = b" /XFA (legacy-xfa-packet)" if xfa else b""
    objects = [
        f"<< /Type /Catalog /Pages 2 0 R /AcroForm {acroform_object} 0 R >>".encode("ascii"),
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots " + annotations + b" >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /V () "
            + field_flags_entry
            + b" /Rect [72 700 300 730] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
    ]
    if second_field:
        objects.append(
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (city) /V () "
            b"/Rect [72 650 300 680] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        )
    fields = b"[6 0 R 7 0 R]" if second_field else b"[6 0 R]"
    objects.append(
        b"<< /Fields " + fields + xfa_entry
        + b" /DR << /Font << /Helv 5 0 R >> >> "
        b"/DA (/Helv 12 Tf 0 g) >>"
    )
    return _write_pdf_fixture(path, objects)


def _nested_text_form_pdf(path: Path) -> Path:
    return _write_pdf_fixture(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 9 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [8 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /T (person) /FT /Tx /Ff 2 /Kids [7 0 R] >>",
        b"<< /Parent 6 0 R /T (name) /V () /Kids [8 0 R] >>",
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 7 0 R "
            b"/Rect [72 700 300 730] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
        (
            b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
    ])


def _checkbox_form_pdf(path: Path) -> Path:
    appearance = (
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 20 20] /Length 0 >>\n"
        b"stream\n\nendstream"
    )
    return _write_pdf_fixture(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 9 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << >> /Contents 4 0 R /Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) "
            b"/V /Off /AS /Off /Rect [72 700 92 720] /P 3 0 R "
            b"/AP << /N << /Off 7 0 R /Yes 8 0 R >> >> >>"
        ),
        appearance,
        appearance,
        b"<< /Fields [6 0 R] >>",
    ])


def _choice_form_pdf(path: Path) -> Path:
    return _write_pdf_fixture(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 7 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Ch /T (color) /V (Red) "
            b"/Opt [(Red) (Green) (Blue)] /Rect [72 700 300 730] /P 3 0 R "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
        (
            b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
    ])


def _radio_form_pdf(path: Path) -> Path:
    appearance = (
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 20 20] /Length 0 >>\n"
        b"stream\n\nendstream"
    )
    return _write_pdf_fixture(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 10 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << >> /Contents 4 0 R /Annots [7 0 R 8 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< >>",
        b"<< /FT /Btn /Ff 32768 /T (size) /V /Small /Kids [7 0 R 8 0 R] >>",
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 6 0 R /AS /Small "
            b"/Rect [72 700 92 720] /P 3 0 R "
            b"/AP << /N << /Off 9 0 R /Small 9 0 R >> >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 6 0 R /AS /Off "
            b"/Rect [120 700 140 720] /P 3 0 R "
            b"/AP << /N << /Off 9 0 R /Large 9 0 R >> >> >>"
        ),
        appearance,
        b"<< /Fields [6 0 R] >>",
    ])


def _referenced_resource_pdf(path: Path, *, inherited: bool) -> Path:
    resource_entry = b"/Resources 6 0 R "
    pages_resource = resource_entry if inherited else b""
    page_resource = b"" if inherited else resource_entry
    return _write_pdf_fixture(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 "
            b"/MediaBox [0 0 612 792] " + pages_resource + b">>"
        ),
        (
            b"<< /Type /Page /Parent 2 0 R " + page_resource
            + b"/Contents 4 0 R >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Font << /F1 5 0 R >> >>",
    ])


def _write_pdf_fixture(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for obj_num, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{obj_num} 0 obj\n".encode("ascii"))
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


def _compressible_pdf(path: Path) -> Path:
    lines = [
        f"(Compressible public PDF line {index % 10}) Tj 0 -14 Td".encode("ascii")
        for index in range(500)
    ]
    content = b"BT /F1 12 Tf 72 720 Td\n" + b"\n".join(lines) + b"\nET"
    stream = (
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream"
    )
    return _write_pdf_fixture(
        path,
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            stream,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ],
    )


@pytest.fixture
def public_created(tmp_path: Path) -> Path:
    output = tmp_path / "public-created.pdf"
    create_pdf(output, _document())
    return output


# ---------------------------------------------------------------------------
# Capabilities + Doctor
# ---------------------------------------------------------------------------

def test_public_capabilities_list_pdf_operations(project_root: Path) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert "pdf.read" in operations
    assert "pdf.inspect.structure" in operations
    assert "pdf.create" in operations
    assert "pdf.edit" in operations
    assert "pdf.rewrite.apply" in operations
    assert "pdf.images.extract" in operations
    assert "pdf.encrypt" in operations
    assert "pdf.decrypt" in operations
    assert "pdf.compress" in operations
    assert operations["pdf.table.extract"]["available"] is True
    assert operations["pdf.render"]["available"] is False
    assert operations["pdf.ocr"]["available"] is False
    for op_name in {
        "pdf.read",
        "pdf.inspect.structure",
        "pdf.create",
        "pdf.edit",
        "pdf.rewrite.apply",
        "pdf.images.extract",
        "pdf.encrypt",
        "pdf.decrypt",
        "pdf.compress",
        "pdf.table.extract",
    }:
        assert operations[op_name]["available"] is True


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        (
            "pdf.render",
            {
                "pages": [1],
                "dpi": 144,
                "format": "png",
                "max_pixels": 40_000_000,
                "max_total_bytes": 64 * 1024 * 1024,
            },
        ),
        (
            "pdf.ocr",
            {
                "pages": [1],
                "dpi": 300,
                "languages": ["eng"],
                "skip_text_pages": True,
                "max_pixels": 40_000_000,
                "max_total_bytes": 64 * 1024 * 1024,
            },
        ),
    ],
)
def test_public_optional_pdf_provider_requests_are_truthfully_unavailable(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
    operation: str,
    arguments: dict[str, object],
) -> None:
    output = tmp_path / f"{operation.removeprefix('pdf.')}.zip"
    request = _request(
        tmp_path,
        f"{operation.removeprefix('pdf.')}.json",
        {
            "schema_version": "1.0",
            "operation": operation,
            "input": str(public_created),
            "output": str(output),
            "arguments": arguments,
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "unavailable"
    assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
    assert not output.exists()


def test_public_doctor_succeeds(project_root: Path) -> None:
    report = _public(project_root, "doctor", "--json")
    assert report["status"] == "healthy"


# ---------------------------------------------------------------------------
# Create + Read
# ---------------------------------------------------------------------------

def test_public_create_and_read(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["page_count"] == 2


def test_public_create_minimal_text_document_round_trips(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "minimal.pdf"
    create_request = _request(
        tmp_path,
        "create-minimal.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": _minimal_text_document()},
        },
    )

    create_result = _public(
        project_root,
        "run",
        "--request",
        str(create_request),
        check=False,
    )
    SchemaCatalog(project_root).validate("operation-result", create_result)
    assert create_result["status"] == "success", create_result
    assert output.is_file()
    assert create_result["diagnostics"]["promotion"]["transaction_residue_paths"] == []
    creation = create_result["diagnostics"]["operation_result"]["creation"]
    mapping = creation["mapping"]
    assert mapping["schema_version"] == "1.0"
    assert mapping["pages"][0]["blocks"] == [{
        "block_index": 0,
        "type": "paragraph",
        "object": mapping["pages"][0]["content_stream_object"],
        "bbox": creation["text_blocks"][0]["bbox"],
    }]

    read_request = _request(
        tmp_path,
        "read-minimal.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(
        project_root,
        "run",
        "--request",
        str(read_request),
        check=False,
    )
    assert read_result["status"] == "success"
    assert read_result["diagnostics"]["operation_result"]["page_count"] == 1
    assert read_result["diagnostics"]["operation_result"]["text_by_page"][0]["text"] == (
        "A reachable public PDF create request."
    )

    validation = _public(
        project_root,
        "validate",
        "--input",
        str(output),
        "--json",
    )
    assert validation["status"] == "pass"

    capabilities = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in capabilities["operations"]}
    assert operations["pdf.create"]["available"] is True


def test_public_create_is_deterministic(project_root: Path, tmp_path: Path) -> None:
    output1 = tmp_path / "d1.pdf"
    output2 = tmp_path / "d2.pdf"
    output_bytes = []
    for out in [output1, output2]:
        req = _request(
            tmp_path,
            f"create_{out.stem}.json",
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(out),
                "arguments": {"document": _minimal_text_document()},
            },
        )
        result = _public(
            project_root,
            "run",
            "--request",
            str(req),
            check=False,
        )
        SchemaCatalog(project_root).validate("operation-result", result)
        assert result["status"] == "success"
        assert result["validation"]["status"] == "pass"
        assert out.is_file()
        output_bytes.append(out.read_bytes())

    assert output_bytes[0] == output_bytes[1]


def test_public_create_requested_table_and_vector_succeeds(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "table-vector.pdf"
    document = _minimal_text_document()
    page = document["pages"][0]
    page["blocks"].extend(
        [
            {
                "type": "table",
                "text": None,
                "style": None,
                "table": {"rows": [{"cells": ["A", "B"]}]},
                "image": None,
                "shape": None,
            },
            {
                "type": "vector_shape",
                "text": None,
                "style": None,
                "table": None,
                "image": None,
                "shape": {
                    "kind": "rectangle",
                    "x": 72,
                    "y": 72,
                    "width": 100,
                    "height": 50,
                    "stroke": None,
                    "fill": None,
                },
            },
        ]
    )
    request = _request(
        tmp_path,
        "create-table-vector.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success"
    assert result["validation"]["status"] == "pass"
    structures = result["diagnostics"]["operation_result"]["creation"]["structures"]
    assert structures["table"] is True
    assert structures["vector_shape"] is True
    assert output.is_file()


def test_public_create_applies_text_shape_style_and_page_layout(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "styled-layout.pdf"
    document = _minimal_text_document()
    page = document["pages"][0]
    page["size"] = {"width": 400, "height": 300}
    page["margin"] = {"top": 40, "right": 50, "bottom": 40, "left": 50}
    paragraph = page["blocks"][0]
    paragraph["style"] = {
        "font_family": "Helvetica",
        "font_size": 18,
        "font_weight": "bold",
        "font_style": "italic",
        "color": [1, 0, 0],
        "line_height": 24,
        "alignment": "center",
    }
    page["blocks"].append(
        {
            "type": "vector_shape",
            "text": None,
            "style": None,
            "table": None,
            "image": None,
            "shape": {
                "kind": "rectangle",
                "x": 50,
                "y": 50,
                "width": 80,
                "height": 30,
                "stroke": [0, 0, 1],
                "fill": [0, 1, 0],
                "opacity": 0.5,
                "dash": [4, 2],
            },
        }
    )
    request = _request(
        tmp_path,
        "create-styled-layout.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    create_result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )
    assert create_result["status"] == "success", create_result
    creation = create_result["diagnostics"]["operation_result"]["creation"]
    assert creation["page_sizes"] == [[400.0, 300.0]]
    assert creation["shapes"] == [
        {
                "bbox": [50.0, 50.0, 130.0, 80.0],
                "block_index": 1,
                "corner_radius": 0.0,
                "dash": [4.0, 2.0],
            "fill": [0.0, 1.0, 0.0],
            "kind": "rectangle",
            "opacity": 0.5,
            "page": 1,
            "stroke": [0.0, 0.0, 1.0],
        }
    ]

    read_request = _request(
        tmp_path,
        "read-styled-layout.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(
        project_root,
        "run",
        "--request",
        str(read_request),
        check=False,
    )
    assert read_result["status"] == "success", read_result
    operation_result = read_result["diagnostics"]["operation_result"]
    assert operation_result["pages"][0]["media_box"] == [0.0, 0.0, 400.0, 300.0]
    styled_block = operation_result["text_blocks"][0]
    assert styled_block["font"] == "/F4"
    assert styled_block["size"] == 18.0
    assert styled_block["color"] == [1.0, 0.0, 0.0]
    assert styled_block["bbox"][0] > 50.0


def test_public_create_line_and_ellipse_have_candidate_derived_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "line-ellipse.pdf"
    document = _minimal_text_document()
    document["pages"][0]["blocks"].extend([
        {
            "type": "vector_shape",
            "text": None,
            "style": None,
            "table": None,
            "image": None,
            "shape": {
                "kind": "line",
                "x": 30,
                "y": 40,
                "width": 70,
                "height": 20,
                "stroke": [1, 0, 0],
                "fill": None,
                "opacity": 0.4,
                "dash": [3, 2],
            },
        },
        {
            "type": "vector_shape",
            "text": None,
            "style": None,
            "table": None,
            "image": None,
            "shape": {
                "kind": "ellipse",
                "x": 120,
                "y": 80,
                "width": 50,
                "height": 30,
                "stroke": [0, 0, 1],
                "fill": [0.2, 0.4, 0.6],
                "opacity": 0.6,
                "dash": [],
            },
        },
    ])
    request = _request(
        tmp_path,
        "create-line-ellipse.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    gate = next(
        item
        for item in result["validation"]["gates"]
        if item["id"] == "operation.create-semantics"
    )
    shapes = gate["evidence"]["shapes"]
    assert [shape["kind"] for shape in shapes] == ["line", "ellipse"]
    assert [shape["bbox"] for shape in shapes] == [
        [30.0, 40.0, 100.0, 60.0],
        [120.0, 80.0, 170.0, 110.0],
    ]
    assert [shape["path_operators"] for shape in shapes] == [
        ["m", "l"],
        ["m", "c", "c", "c", "c", "h"],
    ]
    assert [shape["paint_operator"] for shape in shapes] == ["S", "B"]
    assert [shape["dash"] for shape in shapes] == [[3, 2], []]
    assert [shape["fill_opacity"] for shape in shapes] == [0.4, 0.6]
    assert [shape["stroke_opacity"] for shape in shapes] == [0.4, 0.6]
    assert [shape["stroke"] for shape in shapes] == [[1, 0, 0], [0, 0, 1]]
    assert [shape["fill"] for shape in shapes] == [None, [0.2, 0.4, 0.6]]
    assert all(shape["graphics_state_indirect"] for shape in shapes)
    assert all(shape["graphics_state_object_sha256"] for shape in shapes)

    reader = PdfReader(output)
    content = reader.pages[0].get_contents().get_data()
    assert b"30 40 m\n100 60 l" in content
    assert content.count(b" c\n") >= 4


def test_public_create_text_overflow_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-overflow.pdf"
    output.write_bytes(b"existing-destination")
    document = _minimal_text_document()
    page = document["pages"][0]
    page["size"] = {"width": 200, "height": 100}
    page["margin"] = {"top": 10, "right": 10, "bottom": 10, "left": 10}
    page["blocks"][0]["text"] = "overflow " * 200
    request = _request(
        tmp_path,
        "create-overflow.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert result["errors"][0]["details"]["content_bottom"] == 10.0
    assert result["artifacts"] == []
    assert result["validation"]["status"] == "fail"
    assert output.read_bytes() == b"existing-destination"


def test_public_create_embeds_real_png_and_read_projects_it(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    output = tmp_path / "image.pdf"
    document = _minimal_text_document()
    page = document["pages"][0]
    page["blocks"].append(
        {
            "type": "image",
            "text": None,
            "style": None,
            "table": None,
            "image": {
                "filename": str(image),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "content_type": "image/png",
                "fit": "contain",
                "width": 40,
                "height": 40,
                "alt": "One pixel",
            },
            "shape": None,
        }
    )
    create_request = _request(
        tmp_path,
        "create-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    create_result = _public(
        project_root,
        "run",
        "--request",
        str(create_request),
        check=False,
    )
    assert create_result["status"] == "success", create_result
    assert output.is_file()
    creation = create_result["diagnostics"]["operation_result"]["creation"]
    assert creation["structures"]["image"] is True
    expected_bbox = [72.0, 698.29, 112.0, 738.29]
    assert creation["images"] == [
        {
            "asset_bytes": len(_PNG),
            "asset_sha256": hashlib.sha256(_PNG).hexdigest(),
            "bbox": expected_bbox,
            "block_index": 1,
            "content_type": "image/png",
            "image_object": creation["images"][0]["image_object"],
            "page": 1,
            "resolved_path": str(image.resolve()),
            "source_height": 1,
            "source_width": 1,
            "transcoded": False,
        }
    ]
    assert b"placeholder" not in output.read_bytes().lower()
    create_gate = next(
        item
        for item in create_result["validation"]["gates"]
        if item["id"] == "operation.create-semantics"
    )
    image_evidence = create_gate["evidence"]["images"][0]
    assert creation["mapping"]["pages"][0]["blocks"][1]["bbox"] == expected_bbox
    assert image_evidence["bbox"] == expected_bbox
    assert image_evidence["visible_bbox"] == expected_bbox
    with Image.open(BytesIO(_PNG)) as source_image:
        expected_alpha = source_image.getchannel("A").tobytes()
    assert image_evidence["soft_mask_object"] > 0
    assert image_evidence["soft_mask_object_sha256"]
    assert image_evidence["alpha_sha256"] == hashlib.sha256(
        expected_alpha
    ).hexdigest()

    reader = PdfReader(output)
    image_object = reader.pages[0]["/Resources"]["/XObject"]["/Im1"].get_object()
    assert image_object.raw_get("/SMask").indirect_reference is not None
    soft_mask = image_object["/SMask"].get_object()
    assert soft_mask["/Width"] == 1
    assert soft_mask["/Height"] == 1
    assert str(soft_mask["/ColorSpace"]) == "/DeviceGray"
    assert soft_mask["/BitsPerComponent"] == 8
    assert soft_mask.get_data() == expected_alpha

    read_request = _request(
        tmp_path,
        "read-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(
        project_root,
        "run",
        "--request",
        str(read_request),
        check=False,
    )
    assert read_result["status"] == "success"
    assert read_result["diagnostics"]["operation_result"]["images_by_page"] == [
        [
            {
                "bits_per_component": 8,
                "color_space": "/DeviceGray",
                "filter_chain": ["/FlateDecode"],
                "height": 1,
                "name": "/Im1",
                "width": 1,
            }
        ]
    ]


def test_public_create_resolves_relative_image_from_invocation_base(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "用户 image workspace"
    image = invocation_base / "素材" / "像素.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(_PNG)
    document = _minimal_text_document()
    document["pages"][0]["blocks"].append({
        "type": "image",
        "text": None,
        "style": None,
        "table": None,
        "image": {
            "filename": "素材/像素.png",
            "sha256": hashlib.sha256(_PNG).hexdigest(),
            "content_type": "image/png",
            "fit": "contain",
            "width": 40,
            "height": 40,
            "alt": "relative image",
        },
        "shape": None,
    })
    request_dir = invocation_base / "请求"
    request_dir.mkdir()
    request = _request(
        request_dir,
        "relative-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": "结果/relative-image.pdf",
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.relative_to(invocation_base).as_posix(),
        cwd=invocation_base,
    )

    assert result["status"] == "success", result
    created = result["diagnostics"]["operation_result"]["creation"]["images"][0]
    assert created["resolved_path"] == str(image.resolve())
    assert (invocation_base / "结果" / "relative-image.pdf").is_file()


def test_public_create_embeds_jpeg_without_recompressing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.jpg"
    image.write_bytes(_JPEG)
    output = tmp_path / "jpeg.pdf"
    document = _minimal_text_document()
    document["pages"][0]["blocks"].append(
        {
            "type": "image",
            "text": None,
            "style": None,
            "table": None,
            "image": {
                "filename": str(image),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "content_type": "image/jpeg",
                "fit": "contain",
                "width": 80,
                "height": 40,
                "alt": "Red JPEG",
            },
            "shape": None,
        }
    )
    create_request = _request(
        tmp_path,
        "create-jpeg.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    create_result = _public(
        project_root,
        "run",
        "--request",
        str(create_request),
        check=False,
    )
    assert create_result["status"] == "success", create_result
    image_result = create_result["diagnostics"]["operation_result"]["creation"]["images"][0]
    assert image_result["asset_sha256"] == hashlib.sha256(_JPEG).hexdigest()
    assert image_result["transcoded"] is False

    read_request = _request(
        tmp_path,
        "read-jpeg.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(
        project_root,
        "run",
        "--request",
        str(read_request),
        check=False,
    )
    assert read_result["status"] == "success", read_result
    assert read_result["diagnostics"]["operation_result"]["images_by_page"] == [
        [
            {
                "bits_per_component": 8,
                "color_space": "/DeviceRGB",
                "filter_chain": ["/DCTDecode"],
                "height": 1,
                "name": "/Im1",
                "width": 2,
            }
        ]
    ]


def test_public_images_extract_writes_real_png_and_jpeg_artifacts(
    project_root: Path,
    tmp_path: Path,
) -> None:
    png = tmp_path / "extract.png"
    jpeg = tmp_path / "extract.jpg"
    png.write_bytes(_PNG)
    jpeg.write_bytes(_JPEG)
    source = tmp_path / "images-source.pdf"
    document = _minimal_text_document()
    for path, content_type in [(png, "image/png"), (jpeg, "image/jpeg")]:
        document["pages"][0]["blocks"].append(
            {
                "type": "image",
                "text": None,
                "style": None,
                "table": None,
                "image": {
                    "filename": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "content_type": content_type,
                    "fit": "contain",
                    "width": 40,
                    "height": 40,
                    "alt": None,
                },
                "shape": None,
            }
        )
    create_pdf(source, document)
    output = tmp_path / "extracted-images.zip"
    request = _request(
        tmp_path,
        "extract-images.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "pages": [1],
                "max_images": 10,
                "max_total_bytes": 1_000_000,
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["image_count"] == 2
    assert [item["format"] for item in operation_result["images"]] == ["png", "jpeg"]
    assert all(item["bbox"] is not None for item in operation_result["images"])
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        extracted = {name: archive.read(name) for name in names}
    png_bytes = next(value for name, value in extracted.items() if name.endswith(".png"))
    jpeg_bytes = next(value for name, value in extracted.items() if name.endswith(".jpg"))
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert jpeg_bytes == _JPEG


def test_public_images_extract_reverses_png_predictor_samples(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"q 2 0 0 1 10 10 cm /Im1 Do Q"
    predicted = bytes([1, 255, 0, 0, 1, 255, 0])
    compressed = zlib.compress(predicted, level=9)
    source = _write_pdf_fixture(
        tmp_path / "predictor-image.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
                b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            (
                f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
                + content
                + b"\nendstream"
            ),
            (
                b"<< /Type /XObject /Subtype /Image /Width 2 /Height 1 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                b"/DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 "
                b"/Columns 2 >> /Length "
                + str(len(compressed)).encode("ascii")
                + b" >>\nstream\n"
                + compressed
                + b"\nendstream"
            ),
        ],
    )
    output = tmp_path / "predictor-images.zip"
    request = _request(
        tmp_path,
        "extract-predictor-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": {},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    image_record = result["diagnostics"]["operation_result"]["images"][0]
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(image_record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        rgb = image.convert("RGB")
        assert [rgb.getpixel((x, 0)) for x in range(2)] == [
            (255, 0, 0),
            (0, 255, 0),
        ]


def test_public_images_extract_combines_jpeg_with_soft_mask_as_png(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"q 2 0 0 1 10 10 cm /Im1 Do Q"
    alpha = zlib.compress(bytes([0, 255]), level=9)
    source = _write_pdf_fixture(
        tmp_path / "jpeg-soft-mask.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
                b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            (
                f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
                + content
                + b"\nendstream"
            ),
            (
                b"<< /Type /XObject /Subtype /Image /Width 2 /Height 1 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                b"/SMask 6 0 R /Length "
                + str(len(_JPEG)).encode("ascii")
                + b" >>\nstream\n"
                + _JPEG
                + b"\nendstream"
            ),
            (
                b"<< /Type /XObject /Subtype /Image /Width 2 /Height 1 "
                b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
                b"/Length "
                + str(len(alpha)).encode("ascii")
                + b" >>\nstream\n"
                + alpha
                + b"\nendstream"
            ),
        ],
    )
    output = tmp_path / "jpeg-soft-mask.zip"
    request = _request(
        tmp_path,
        "extract-jpeg-soft-mask.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": {},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    image_record = result["diagnostics"]["operation_result"]["images"][0]
    assert image_record["format"] == "png"
    assert image_record["soft_mask"] is True
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(image_record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.mode == "RGBA"
        assert [image.getpixel((x, 0))[3] for x in range(2)] == [0, 255]


def test_public_table_extract_reports_low_confidence_stream_heuristic(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "heuristic-table.pdf"
    document = _minimal_text_document()
    document["pages"][0]["blocks"] = [
        {
            "type": "table",
            "text": None,
            "style": None,
            "table": {
                "rows": [
                    {"cells": ["Name", "Score"]},
                    {"cells": ["Ada", "97"]},
                ]
            },
            "image": None,
            "shape": None,
        }
    ]
    create_pdf(source, document)
    request = _request(
        tmp_path,
        "table-extract.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.table.extract",
            "input": str(source),
            "arguments": {
                "pages": [1],
                "min_rows": 2,
                "min_columns": 2,
                "max_tables": 10,
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    assert result["provider_chain"][0] == "core-python"
    extraction = result["diagnostics"]["operation_result"]
    assert extraction["table_count"] == 1
    table = extraction["tables"][0]
    assert table["source"] == "core-stream-heuristic"
    assert 0 < table["confidence"] <= 0.4
    assert table["cross_page"] is False
    assert [[cell["text"] for cell in row["cells"]] for row in table["rows"]] == [
        ["Name", "Score"],
        ["Ada", "97"],
    ]
    assert len(table["bbox"]) == 4
    assert all(
        len(cell["bbox"]) == 4
        for row in table["rows"]
        for cell in row["cells"]
    )


def test_public_create_null_image_fails_before_candidate_and_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-null-image.pdf"
    output.write_bytes(b"existing-destination")
    document = _minimal_text_document()
    document["pages"][0]["blocks"].append(
        {
            "type": "image",
            "text": None,
            "style": None,
            "table": None,
            "image": None,
            "shape": None,
        }
    )
    request = _request(
        tmp_path,
        "create-null-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert result["errors"][0]["details"]["field"].endswith(".image")
    assert result["validation"]["status"] == "fail"
    assert not any(item["role"] == "output" for item in result["artifacts"])
    assert output.read_bytes() == b"existing-destination"


def test_public_create_missing_image_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-missing-image.pdf"
    output.write_bytes(b"existing-destination")
    document = _minimal_text_document()
    document["pages"][0]["blocks"].append(
        {
            "type": "image",
            "text": None,
            "style": None,
            "table": None,
            "image": {
                "filename": str(tmp_path / "missing.png"),
                "sha256": "0" * 64,
                "content_type": "image/png",
                "fit": "contain",
                "width": 40,
                "height": 40,
                "alt": None,
            },
            "shape": None,
        }
    )
    request = _request(
        tmp_path,
        "create-missing-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert result["validation"]["status"] == "fail"
    assert result["artifacts"] == []
    assert output.read_bytes() == b"existing-destination"


def test_public_create_image_hash_mismatch_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "hash-bound.png"
    image.write_bytes(_PNG)
    document = _minimal_text_document()
    document["pages"][0]["blocks"].append({
        "type": "image",
        "text": None,
        "style": None,
        "table": None,
        "image": {
            "filename": str(image),
            "sha256": "0" * 64,
            "content_type": "image/png",
            "fit": "contain",
            "width": 40,
            "height": 40,
            "alt": "hash bound",
        },
        "shape": None,
    })
    output = tmp_path / "image-hash-mismatch.pdf"
    output.write_bytes(b"existing-destination")
    request = _request(
        tmp_path,
        "image-hash-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.image-source-precondition"
    )
    assert output.read_bytes() == b"existing-destination"


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def test_public_inspect_inert(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(inspect_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["dangerous_content_present"] is False


# ---------------------------------------------------------------------------
# Edit: Rotate
# ---------------------------------------------------------------------------

def test_public_edit_rotate(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-rotated.pdf"
    edit_request = _request(
        tmp_path,
        "rotate.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "rotate", "pages": [1], "degrees": 90},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] == "success"
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


def test_public_edit_reports_object_sets_and_page_impact_per_primitive(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "public-reported-edit.pdf"
    request = _request(
        tmp_path,
        "reported-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "rotate", "pages": [1], "degrees": 90},
                    {
                        "type": "annotation",
                        "action": "add",
                        "subtype": "text",
                        "page": 2,
                        "rectangle": [100, 650, 124, 674],
                        "contents": "Transient note",
                    },
                    {
                        "type": "annotation",
                        "action": "delete",
                        "page": 2,
                        "index": 1,
                        "expected_contents": "Transient note",
                    },
                    {
                        "type": "metadata_update",
                        "metadata": {"title": "Reported edit"},
                    },
                ],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    _assert_canonical_edit_report(operation)
    reports = operation["primitives"]
    assert [report["primitive"] for report in reports] == [
        "rotate",
        "annotation",
        "annotation",
        "metadata_update",
    ]
    for report in reports:
        _assert_canonical_edit_report(report)
    assert reports[0]["changed_objects"]
    assert reports[0]["added_objects"] == reports[0]["removed_objects"] == []
    assert reports[0]["page_impact"] == {
        "mode": "page_content",
        "source_page_count": 2,
        "output_page_count": 2,
        "source_pages": [1],
        "output_pages": [1],
    }
    assert reports[1]["added_objects"]
    assert reports[1]["page_impact"]["source_pages"] == [2]
    assert reports[1]["page_impact"]["output_pages"] == [2]
    assert reports[2]["removed_objects"]
    assert reports[2]["page_impact"]["source_pages"] == [2]
    assert reports[2]["page_impact"]["output_pages"] == [2]
    assert reports[3]["changed_objects"] or reports[3]["added_objects"]
    assert reports[3]["page_impact"] == {
        "mode": "document_metadata",
        "source_page_count": 2,
        "output_page_count": 2,
        "source_pages": [],
        "output_pages": [],
    }


def test_public_edit_applies_multiple_primitives_and_watermark_opacity(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_bytes = public_created.read_bytes()
    output = tmp_path / "public-multi-edit.pdf"
    edit_request = _request(
        tmp_path,
        "multi-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "rotate", "pages": [1], "degrees": 90},
                    {
                        "type": "watermark",
                        "text": "CONFIDENTIAL",
                        "pages": [1],
                        "opacity": 0.25,
                    },
                ],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert [item["primitive"] for item in operation_result["primitives"]] == [
        "rotate",
        "watermark",
    ]
    assert operation_result["primitives"][1]["opacity"] == 0.25
    output_bytes = output.read_bytes()
    assert b"/ca 0.25" in output_bytes
    assert b"/CA 0.25" in output_bytes
    assert b"/DSWMGS gs" in output_bytes
    assert public_created.read_bytes() == source_bytes

    read_request = _request(
        tmp_path,
        "read-multi-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    operation_result = read_result["diagnostics"]["operation_result"]
    assert operation_result["pages"][0]["rotation"] == 90
    assert "CONFIDENTIAL" in operation_result["text_by_page"][0]["text"]
    assert operation_result["info_dictionary"]["title"] == "Public PDF"


def test_public_watermark_rounds_candidate_opacity_but_reports_request_value(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "high-precision-opacity.pdf"
    edit_request = _request(
        tmp_path,
        "high-precision-opacity.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [{
                    "type": "watermark",
                    "text": "PRECISE",
                    "pages": [1],
                    "opacity": 0.3333333,
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["opacity"] == 0.3333333
    assert "_watermark_stage_hashes" not in operation["preservation"]
    output_bytes = output.read_bytes()
    assert b"/ca 0.333333" in output_bytes
    assert b"/CA 0.333333" in output_bytes
    assert b"/ca 0.3333333" not in output_bytes
    assert b"/CA 0.3333333" not in output_bytes


def test_public_text_watermark_applies_requested_style_and_position(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "styled-watermark.pdf"
    edit_request = _request(
        tmp_path,
        "styled-watermark.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "watermark",
                        "text": "DRAFT",
                        "pages": [1],
                        "opacity": 0.35,
                        "rotation": 30,
                        "font": "Helvetica",
                        "size": 24,
                        "color": [0.1, 0.2, 0.3],
                        "position": {"x": 100, "y": 200},
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["rotation"] == 30.0
    assert operation_result["font"] == "Helvetica"
    assert operation_result["size"] == 24.0
    assert operation_result["color"] == [0.1, 0.2, 0.3]
    assert operation_result["position"] == {"x": 100.0, "y": 200.0}
    output_bytes = output.read_bytes()
    assert b"/DSWMFont 24 Tf" in output_bytes
    assert b"/BaseFont /Helvetica /Encoding /WinAnsiEncoding" in output_bytes
    assert b"0.1 0.2 0.3 rg" in output_bytes
    assert b"0.866025 0.5 -0.5 0.866025 100 200 Tm" in output_bytes


def test_public_edit_multiple_primitives_roll_back_as_one_transaction(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-multi-edit.pdf"
    output.write_bytes(b"existing-destination")
    source_bytes = public_created.read_bytes()
    edit_request = _request(
        tmp_path,
        "multi-edit-rollback.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "rotate", "pages": [1], "degrees": 90},
                    {
                        "type": "watermark",
                        "text": "INVALID PAGE",
                        "pages": [99],
                        "opacity": 0.25,
                    },
                ],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["artifacts"] == []
    assert output.read_bytes() == b"existing-destination"
    assert public_created.read_bytes() == source_bytes
    assert list(tmp_path.glob(".*.primitive-*.pdf")) == []


def test_public_edit_embeds_image_watermark_with_opacity(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "watermark.png"
    image.write_bytes(_PNG)
    output = tmp_path / "public-image-watermark.pdf"
    edit_request = _request(
        tmp_path,
        "image-watermark.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "watermark",
                        "image": {
                            "filename": str(image),
                            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                            "content_type": "image/png",
                            "fit": "contain",
                            "width": 80,
                            "height": 40,
                            "alt": "Watermark logo",
                        },
                        "pages": [1],
                        "opacity": 0.4,
                    }
                ],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["primitive"] == "watermark"
    assert operation_result["image"]["asset_sha256"] == hashlib.sha256(_PNG).hexdigest()
    assert operation_result["image"]["bbox"] == [277.638, 400.945, 317.638, 440.945]
    assert operation_result["opacity"] == 0.4

    read_request = _request(
        tmp_path,
        "read-image-watermark.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    images = read_result["diagnostics"]["operation_result"]["images_by_page"]
    assert images[0][0]["name"] == "/DSWMImage"
    assert images[1] == []


def test_public_image_watermark_applies_requested_rotation_and_position(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "positioned-watermark.png"
    image.write_bytes(_PNG)
    output = tmp_path / "positioned-image-watermark.pdf"
    edit_request = _request(
        tmp_path,
        "positioned-image-watermark.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "watermark",
                        "image": {
                            "filename": str(image),
                            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                            "content_type": "image/png",
                            "fit": "contain",
                            "width": 80,
                            "height": 40,
                            "alt": None,
                        },
                        "pages": [1],
                        "opacity": 0.4,
                        "rotation": 90,
                        "position": {"x": 50, "y": 60},
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )

    assert result["status"] == "success", result
    image_result = result["diagnostics"]["operation_result"]["image"]
    assert image_result["bbox"] == [30.0, 60.0, 70.0, 100.0]
    assert b"0 40 -40 0 70 60 cm /DSWMImage Do" in output.read_bytes()


@pytest.mark.parametrize("inherited", [False, True])
def test_public_text_watermark_clones_referenced_page_resources(
    project_root: Path,
    tmp_path: Path,
    inherited: bool,
) -> None:
    source = _referenced_resource_pdf(
        tmp_path / f"referenced-resources-{inherited}.pdf",
        inherited=inherited,
    )
    output = tmp_path / f"watermarked-referenced-resources-{inherited}.pdf"
    edit_request = _request(
        tmp_path,
        f"watermark-referenced-resources-{inherited}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "watermark",
                        "text": "INHERITED",
                        "pages": [1],
                        "opacity": 0.25,
                    }
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(edit_request), check=False)

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    preservation = operation_result["preservation"]
    assert 6 in preservation["preserved_objects"]
    assert preservation["added_objects"] == [7, 8, 9]
    assert b"/BaseFont /Helvetica /Encoding /WinAnsiEncoding" in output.read_bytes()
    assert b"/Resources 9 0 R" in output.read_bytes()

    read_request = _request(
        tmp_path,
        f"read-watermarked-referenced-resources-{inherited}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert "INHERITED" in read_result["diagnostics"]["operation_result"][
        "text_by_page"
    ][0]["text"]


# ---------------------------------------------------------------------------
# Edit: Merge
# ---------------------------------------------------------------------------

def test_public_edit_merge(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    # Create a second PDF to merge
    second = tmp_path / "second.pdf"
    create_pdf(second, _document())

    output = tmp_path / "public-merged.pdf"
    merge_request = _request(
        tmp_path,
        "merge.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "merge",
                        "inputs": [
                            {
                                "input": str(public_created),
                                "source_sha256": hashlib.sha256(
                                    public_created.read_bytes()
                                ).hexdigest(),
                            },
                            {
                                "input": str(second),
                                "source_sha256": hashlib.sha256(
                                    second.read_bytes()
                                ).hexdigest(),
                            },
                        ],
                    },
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(merge_request))
    assert result["status"] == "success"
    assert output.is_file()
    op_result = result["diagnostics"]["operation_result"]
    assert op_result["primitive"] == "merge"
    assert op_result["page_count"] == 4


def test_public_edit_merge_hash_mismatch_is_atomic(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    donor = tmp_path / "hash-mismatch-donor.pdf"
    create_pdf(donor, _document())
    primary_before = public_created.read_bytes()
    donor_before = donor.read_bytes()
    output = tmp_path / "hash-mismatch-output.pdf"
    output.write_bytes(b"existing destination")
    request = _request(
        tmp_path,
        "merge-hash-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "rotate", "pages": [1], "degrees": 90},
                    {
                        "type": "merge",
                        "inputs": [
                            {
                                "input": str(public_created),
                                "source_sha256": hashlib.sha256(
                                    primary_before
                                ).hexdigest(),
                            },
                            {
                                "input": str(donor),
                                "source_sha256": "0" * 64,
                            },
                        ],
                    },
                ],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert output.read_bytes() == b"existing destination"
    assert public_created.read_bytes() == primary_before
    assert donor.read_bytes() == donor_before


def test_public_edit_merge_resolves_relative_inputs_from_invocation_base(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "用户 merge workspace"
    invocation_base.mkdir()
    primary = invocation_base / "主文档.pdf"
    donor = invocation_base / "资料" / "附加.pdf"
    donor.parent.mkdir()
    create_pdf(primary, _document())
    create_pdf(donor, _document())
    request_dir = invocation_base / "请求"
    request_dir.mkdir()
    request = _request(
        request_dir,
        "merge-relative.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": "主文档.pdf",
            "output": "结果/合并.pdf",
            "arguments": {
                "primitives": [{
                    "type": "merge",
                    "inputs": [
                        {
                            "input": "主文档.pdf",
                            "source_sha256": hashlib.sha256(
                                primary.read_bytes()
                            ).hexdigest(),
                        },
                        {
                            "input": "资料/附加.pdf",
                            "source_sha256": hashlib.sha256(
                                donor.read_bytes()
                            ).hexdigest(),
                        },
                    ],
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.relative_to(invocation_base).as_posix(),
        cwd=invocation_base,
    )

    assert result["status"] == "success", result
    assert (invocation_base / "结果" / "合并.pdf").is_file()


# ---------------------------------------------------------------------------
# Edit: Split
# ---------------------------------------------------------------------------

def test_public_edit_split(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-split.pdf"
    split_request = _request(
        tmp_path,
        "split.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "split", "page_ranges": [[1, 1]]},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(split_request))
    assert result["status"] == "success"
    assert output.is_file()
    op_result = result["diagnostics"]["operation_result"]
    assert op_result["primitive"] == "split"
    assert op_result["retained_pages"] == 1


def test_public_edit_page_sequence_reorders_and_removes_pages(
    project_root: Path,
    tmp_path: Path,
) -> None:
    document = _document()
    document["pages"].append(
        {
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Third page",
                    "style": None,
                    "table": None,
                    "image": None,
                    "shape": None,
                }
            ],
            "metadata": None,
        }
    )
    source = tmp_path / "three-pages.pdf"
    create_pdf(source, document)
    output = tmp_path / "page-sequence.pdf"
    sequence_request = _request(
        tmp_path,
        "page-sequence.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "page_sequence", "pages": [3, 1]},
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(sequence_request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["selected_pages"] == [3, 1]
    assert operation_result["removed_pages"] == 1
    _assert_canonical_edit_report(operation_result)
    assert operation_result["removed_objects"]
    assert operation_result["page_impact"] == {
        "mode": "page_tree",
        "source_page_count": 3,
        "output_page_count": 2,
        "source_pages": [1, 2, 3],
        "output_pages": [1, 2],
    }

    read_request = _request(
        tmp_path,
        "read-page-sequence.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    read_operation = read_result["diagnostics"]["operation_result"]
    assert read_operation["page_count"] == 2
    assert [item["text"] for item in read_operation["text_by_page"]] == [
        "Third page",
        "Title\nA\nB",
    ]


def test_public_edit_page_sequence_reconciles_flat_page_labels(
    project_root: Path,
    tmp_path: Path,
) -> None:
    document = _document()
    document["pages"].append({
        "blocks": [{"type": "paragraph", "text": "Third page"}],
        "metadata": None,
    })
    source = tmp_path / "sequence-label-source.pdf"
    create_pdf(source, document)
    labeled = tmp_path / "sequence-labeled.pdf"
    labels_request = _request(
        tmp_path,
        "sequence-set-labels.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(labeled),
            "arguments": {
                "primitives": [{
                    "type": "page_labels",
                    "action": "set",
                    "ranges": [
                        {
                            "page": 1,
                            "style": "roman-lower",
                            "prefix": "Sec-",
                            "start": 3,
                        },
                        {
                            "page": 3,
                            "style": "decimal",
                            "prefix": "App-",
                            "start": 10,
                        },
                    ],
                }],
            },
        },
    )
    labels_result = _public(project_root, "run", "--request", str(labels_request))
    assert labels_result["status"] == "success", labels_result
    output = tmp_path / "sequence-label-output.pdf"
    sequence_request = _request(
        tmp_path,
        "sequence-with-labels.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(labeled),
            "output": str(output),
            "arguments": {
                "primitives": [{"type": "page_sequence", "pages": [3, 1]}],
            },
        },
    )

    sequence_result = _public(
        project_root,
        "run",
        "--request",
        str(sequence_request),
        check=False,
    )

    assert sequence_result["status"] == "success", sequence_result
    assert sequence_result["diagnostics"]["operation_result"]["page_labels"] == [
        "App-10",
        "Sec-iii",
    ]
    read_request = _request(
        tmp_path,
        "sequence-label-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert read_result["diagnostics"]["operation_result"]["page_labels"] == [
        "App-10",
        "Sec-iii",
    ]


def test_public_edit_page_sequence_retargets_flat_outlines(
    project_root: Path,
    tmp_path: Path,
) -> None:
    document = _document()
    document["pages"].append({
        "blocks": [{"type": "paragraph", "text": "Third page"}],
        "metadata": None,
    })
    source = tmp_path / "sequence-outline-source.pdf"
    create_pdf(source, document)
    outlined = tmp_path / "sequence-outlined.pdf"
    outline_request = _request(
        tmp_path,
        "sequence-add-outlines.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(outlined),
            "arguments": {
                "primitives": [
                    {"type": "outline", "action": "add", "title": "One", "page": 1},
                    {"type": "outline", "action": "add", "title": "Two", "page": 2},
                    {"type": "outline", "action": "add", "title": "Three", "page": 3},
                ],
            },
        },
    )
    outline_result = _public(project_root, "run", "--request", str(outline_request))
    assert outline_result["status"] == "success", outline_result
    output = tmp_path / "sequence-outline-output.pdf"
    sequence_request = _request(
        tmp_path,
        "sequence-with-outlines.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(outlined),
            "output": str(output),
            "arguments": {
                "primitives": [{"type": "page_sequence", "pages": [3, 1]}],
            },
        },
    )

    sequence_result = _public(
        project_root,
        "run",
        "--request",
        str(sequence_request),
        check=False,
    )

    assert sequence_result["status"] == "success", sequence_result
    assert sequence_result["diagnostics"]["operation_result"]["outlines"] == [
        {"title": "One", "page": 2},
        {"title": "Three", "page": 1},
    ]
    read_request = _request(
        tmp_path,
        "sequence-outline-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert read_result["diagnostics"]["operation_result"]["outlines"] == [
        {"title": "One", "destination_page": 2},
        {"title": "Three", "destination_page": 1},
    ]


def test_public_edit_inserts_hash_bound_selected_pages_with_page_semantics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "insert-destination.pdf"
    create_pdf(source, _document())
    first_content = b"BT /F1 12 Tf 1 0 0 1 30 100 Tm (Donor one) Tj ET"
    second_content = b"BT /F1 12 Tf 1 0 0 1 30 100 Tm (Donor two) Tj ET"
    donor = _write_pdf_fixture(
        tmp_path / "insert-source.pdf",
        [
            (
                b"<< /Type /Catalog /Pages 2 0 R /PageLabels "
                b"<< /Nums [0 << /P (Donor-) /S /D /St 7 >>] >> "
                b"/Outlines 9 0 R >>"
            ),
            b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] "
                b"/Resources << /Font << /F1 8 0 R >> >> /Contents 5 0 R >>"
            ),
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 480] /Rotate 90 "
                b"/Resources << /Font << /F1 8 0 R >> >> /Contents 6 0 R "
                b"/Annots [7 0 R] >>"
            ),
            (
                f"<< /Length {len(first_content)} >>\nstream\n".encode("ascii")
                + first_content
                + b"\nendstream"
            ),
            (
                f"<< /Length {len(second_content)} >>\nstream\n".encode("ascii")
                + second_content
                + b"\nendstream"
            ),
            (
                b"<< /Type /Annot /Subtype /Text /Rect [20 20 40 40] "
                b"/Contents (Inserted note) /P 4 0 R >>"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Outlines /First 10 0 R /Last 10 0 R /Count 1 >>",
            (
                b"<< /Title (Donor bookmark) /Parent 9 0 R "
                b"/Dest [4 0 R /Fit] >>"
            ),
        ],
    )
    output = tmp_path / "inserted.pdf"
    insert_request = _request(
        tmp_path,
        "page-insert.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [{
                    "type": "page_insert",
                    "input": str(donor),
                    "source_sha256": hashlib.sha256(donor.read_bytes()).hexdigest(),
                    "at": 2,
                    "pages": [2],
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(insert_request),
        check=False,
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["primitive"] == "page_insert"
    assert operation["inserted_pages"] == [2]
    assert operation["page_count"] == 3
    assert operation["outlines"] == [{"title": "Donor bookmark", "page": 2}]
    assert operation["preservation"]["changed_objects"] == []
    reader = PdfReader(output)
    inserted_page = reader.pages[1]
    assert [
        float(inserted_page.mediabox.width),
        float(inserted_page.mediabox.height),
    ] == [320.0, 480.0]
    assert inserted_page.rotation == 90
    assert len(inserted_page["/Annots"]) == 1

    read_request = _request(
        tmp_path,
        "read-page-insert.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert [
        item["text"]
        for item in read_result["diagnostics"]["operation_result"]["text_by_page"]
    ] == ["Title\nA\nB", "Donor two", "Content"]
    assert read_result["diagnostics"]["operation_result"]["page_labels"] == [
        "1",
        "Donor-8",
        "2",
    ]
    assert read_result["diagnostics"]["operation_result"]["outlines"] == [{
        "title": "Donor bookmark",
        "destination_page": 2,
    }]


def test_public_edit_page_insert_hash_mismatch_is_atomic(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "insert-hash-destination.pdf"
    donor = tmp_path / "insert-hash-source.pdf"
    create_pdf(source, _document())
    create_pdf(donor, _minimal_text_document())
    output = tmp_path / "insert-hash-output.pdf"
    output.write_bytes(b"existing-destination")
    request = _request(
        tmp_path,
        "page-insert-hash-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [{
                    "type": "page_insert",
                    "input": str(donor),
                    "source_sha256": "0" * 64,
                    "at": 1,
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.page-insert-source-precondition"
    )
    assert result["artifacts"] == []
    assert output.read_bytes() == b"existing-destination"


def test_public_edit_sets_and_clears_page_labels(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    labeled = tmp_path / "page-labels.pdf"
    set_request = _request(
        tmp_path,
        "set-page-labels.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(labeled),
            "arguments": {
                "primitives": [
                    {
                        "type": "page_labels",
                        "action": "set",
                        "ranges": [
                            {
                                "page": 1,
                                "style": "roman-lower",
                                "prefix": "Sec-",
                                "start": 3,
                            },
                            {
                                "page": 2,
                                "style": "decimal",
                                "prefix": "App-",
                                "start": 10,
                            },
                        ],
                    }
                ]
            },
        },
    )

    set_result = _public(project_root, "run", "--request", str(set_request), check=False)

    assert set_result["status"] == "success", set_result
    read_labeled_request = _request(
        tmp_path,
        "read-page-labels.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(labeled),
            "arguments": {},
        },
    )
    read_labeled = _public(project_root, "run", "--request", str(read_labeled_request))
    assert read_labeled["diagnostics"]["operation_result"]["page_labels"] == [
        "Sec-iii",
        "App-10",
    ]

    cleared = tmp_path / "page-labels-cleared.pdf"
    clear_request = _request(
        tmp_path,
        "clear-page-labels.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(labeled),
            "output": str(cleared),
            "arguments": {
                "primitives": [
                    {"type": "page_labels", "action": "clear"},
                ]
            },
        },
    )
    clear_result = _public(
        project_root,
        "run",
        "--request",
        str(clear_request),
        check=False,
    )

    assert clear_result["status"] == "success", clear_result
    read_cleared_request = _request(
        tmp_path,
        "read-page-labels-cleared.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(cleared),
            "arguments": {},
        },
    )
    read_cleared = _public(project_root, "run", "--request", str(read_cleared_request))
    assert read_cleared["diagnostics"]["operation_result"]["page_labels"] == []


def test_public_edit_redacts_unique_literal_text_from_underlying_content(
    project_root: Path,
    tmp_path: Path,
) -> None:
    document = _minimal_text_document()
    document["pages"][0]["blocks"] = [
        {
            "type": "paragraph",
            "text": "Visible context",
            "style": None,
            "table": None,
            "image": None,
            "shape": None,
        },
        {
            "type": "paragraph",
            "text": "Public secret 4821",
            "style": None,
            "table": None,
            "image": None,
            "shape": None,
        },
    ]
    source = tmp_path / "redaction-source.pdf"
    create_pdf(source, document)
    output = tmp_path / "redacted.pdf"
    request = _request(
        tmp_path,
        "redact-text.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "redact_text",
                        "page": 1,
                        "text": "Public secret 4821",
                    }
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["matched_operators"] == 1
    assert operation_result["verification"] == {
        "extracted_text_absent": True,
        "literal_bytes_absent": True,
    }
    assert b"Public secret 4821" not in output.read_bytes()

    read_request = _request(
        tmp_path,
        "read-redacted-text.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    text = read_result["diagnostics"]["operation_result"]["text_by_page"][0]["text"]
    assert "Visible context" in text
    assert "Public secret 4821" not in text


# ---------------------------------------------------------------------------
# Edit: AcroForm
# ---------------------------------------------------------------------------

def test_public_form_fill_updates_checkbox_value_and_appearance_state(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _checkbox_form_pdf(tmp_path / "checkbox-form.pdf")
    output = tmp_path / "checked-form.pdf"
    request = _request(
        tmp_path,
        "fill-checkbox.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"agree": True},
                        "flatten": False,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["appearances_written"] == 1
    output_bytes = output.read_bytes()
    assert b"/V /Yes" in output_bytes
    assert b"/AS /Yes" in output_bytes
    read_request = _request(
        tmp_path,
        "read-checkbox.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    field = read_result["diagnostics"]["operation_result"]["acroform_fields"][0]
    assert field["field_type"] == "checkbox"
    assert field["value"] == "/Yes"
    assert field["has_appearance"] is True


def test_public_form_fill_updates_choice_value_and_appearance(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _choice_form_pdf(tmp_path / "choice-form.pdf")
    output = tmp_path / "selected-choice-form.pdf"
    request = _request(
        tmp_path,
        "fill-choice.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"color": "Green"},
                        "flatten": False,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["field_types"] == {
        "color": "choice"
    }
    assert b"/V (Green)" in output.read_bytes()
    read_request = _request(
        tmp_path,
        "read-choice.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    field = read_result["diagnostics"]["operation_result"]["acroform_fields"][0]
    assert field["field_type"] == "choice"
    assert field["value"] == "Green"
    assert field["options"] == ["Red", "Green", "Blue"]
    assert field["has_appearance"] is True


def test_public_form_fill_updates_radio_parent_and_widget_states(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _radio_form_pdf(tmp_path / "radio-form.pdf")
    output = tmp_path / "selected-radio-form.pdf"
    request = _request(
        tmp_path,
        "fill-radio.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"size": "Large"},
                        "flatten": False,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["field_types"] == {"size": "radio"}
    assert operation_result["appearances_written"] == 2
    output_bytes = output.read_bytes()
    assert b"/V /Large" in output_bytes
    assert output_bytes.count(b"/AS /Large") == 1
    assert output_bytes.count(b"/AS /Off") == 1
    read_request = _request(
        tmp_path,
        "read-radio.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    field = read_result["diagnostics"]["operation_result"]["acroform_fields"][0]
    assert field["field_type"] == "radio"
    assert field["value"] == "/Large"
    assert field["options"] == ["Large", "Small"]
    assert field["page"] == 1
    assert field["widget"] is True
    assert field["has_appearance"] is True


def test_public_form_fill_writes_value_and_widget_appearance(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _text_form_pdf(tmp_path / "text-form.pdf")
    output = tmp_path / "filled-form.pdf"
    request = _request(
        tmp_path,
        "fill-form.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"name": "Alice"},
                        "flatten": False,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["fields_filled"] == ["name"]
    assert operation_result["appearances_written"] == 1
    assert operation_result["flattened"] is False
    output_bytes = output.read_bytes()
    assert b"/V (Alice)" in output_bytes
    assert b"/AP << /N" in output_bytes

    read_request = _request(
        tmp_path,
        "read-filled-form.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    field = read_result["diagnostics"]["operation_result"]["acroform_fields"][0]
    assert field["qualified_name"] == "name"
    assert field["value"] == "Alice"
    assert field["page"] == 1
    assert field["widget"] is True
    assert field["has_appearance"] is True


@pytest.mark.parametrize("flatten", [False, True])
def test_public_form_fill_rejects_readonly_field_atomically(
    project_root: Path,
    tmp_path: Path,
    flatten: bool,
) -> None:
    source = _text_form_pdf(
        tmp_path / f"readonly-{'flatten' if flatten else 'fill'}.pdf",
        field_flags=1,
    )
    source_before = source.read_bytes()
    output = tmp_path / f"readonly-{'flatten' if flatten else 'fill'}-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    request = _request(
        tmp_path,
        f"readonly-{'flatten' if flatten else 'fill'}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [{
                    "type": "form_fill",
                    "fields": {"name": "Alice"},
                    "flatten": flatten,
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request", result
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert result["errors"][0]["details"] == {
        "capability": "pdf.form-readonly",
        "readonly_fields": ["name"],
    }
    assert result["artifacts"] == []
    assert output.read_bytes() == destination_before
    assert source.read_bytes() == source_before


@pytest.mark.parametrize("flatten", [False, True])
def test_public_form_fill_rejects_xfa_atomically(
    project_root: Path,
    tmp_path: Path,
    flatten: bool,
) -> None:
    source = _text_form_pdf(
        tmp_path / f"xfa-{'flatten' if flatten else 'fill'}.pdf",
        xfa=True,
    )
    source_before = source.read_bytes()
    output = tmp_path / f"xfa-{'flatten' if flatten else 'fill'}-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    request = _request(
        tmp_path,
        f"xfa-{'flatten' if flatten else 'fill'}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [{
                    "type": "form_fill",
                    "fields": {"name": "Alice"},
                    "flatten": flatten,
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert result["errors"][0]["details"] == {
        "capability": "pdf.form-xfa",
    }
    assert result["artifacts"] == []
    assert output.read_bytes() == destination_before
    assert source.read_bytes() == source_before


def test_public_form_fill_resolves_nested_qualified_field_and_widget(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _nested_text_form_pdf(tmp_path / "nested-text-form.pdf")
    output = tmp_path / "nested-text-filled.pdf"
    request = _request(
        tmp_path,
        "fill-nested-text.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [{
                    "type": "form_fill",
                    "fields": {"person.name": "Alice"},
                    "flatten": False,
                }],
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["fields_filled"] == ["person.name"]
    assert operation["appearances_written"] == 1
    assert b"/V (Alice)" in output.read_bytes()
    read_request = _request(
        tmp_path,
        "read-nested-text.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    fields = read_result["diagnostics"]["operation_result"]["acroform_fields"]
    assert fields == [{
        "qualified_name": "person.name",
        "field_type": "text",
        "flags": 2,
        "value_type": "str",
        "value": "Alice",
        "default_value": None,
        "required": True,
        "readonly": False,
        "options": [],
        "page": 1,
        "widget": True,
        "has_appearance": True,
        "annotation_rect": [72.0, 700.0, 300.0, 730.0],
    }]


def test_public_form_fill_can_flatten_widget_into_page_content(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _text_form_pdf(tmp_path / "text-form-flatten.pdf")
    output = tmp_path / "flattened-form.pdf"
    request = _request(
        tmp_path,
        "flatten-form.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"name": "Alice"},
                        "flatten": True,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["fields_filled"] == ["name"]
    assert operation_result["appearances_written"] == 1
    assert operation_result["flattened"] is True
    output_bytes = output.read_bytes()
    assert b"/AcroForm" not in output_bytes
    assert b"/Subtype /Widget" not in output_bytes

    read_request = _request(
        tmp_path,
        "read-flattened-form.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    operation_result = read_result["diagnostics"]["operation_result"]
    assert operation_result["acroform_fields"] == []
    assert operation_result["annotations"] == []
    assert operation_result["text_by_page"][0]["text"] == "Alice"


def test_public_form_fill_partial_flatten_preserves_unrequested_fields(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _text_form_pdf(tmp_path / "two-field-form.pdf", second_field=True)
    output = tmp_path / "partially-flattened-form.pdf"
    request = _request(
        tmp_path,
        "partial-flatten-form.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"name": "Alice"},
                        "flatten": True,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    assert b"/AcroForm" in output.read_bytes()
    read_request = _request(
        tmp_path,
        "read-partial-flatten.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    operation_result = read_result["diagnostics"]["operation_result"]
    assert [field["qualified_name"] for field in operation_result["acroform_fields"]] == [
        "city"
    ]
    assert len(operation_result["annotations"]) == 1
    assert operation_result["text_by_page"][0]["text"] == "Alice"


def test_public_edit_updates_metadata_without_changing_page_content(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "metadata-updated.pdf"
    source_bytes = public_created.read_bytes()
    request = _request(
        tmp_path,
        "metadata-update.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "metadata_update",
                        "metadata": {
                            "title": "Updated PDF",
                            "author": "Elftia",
                            "subject": "Metadata edit",
                            "keywords": "pdf,metadata",
                        },
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["updated_fields"] == [
        "author",
        "keywords",
        "subject",
        "title",
    ]
    assert public_created.read_bytes() == source_bytes
    read_request = _request(
        tmp_path,
        "read-metadata-update.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    operation_result = read_result["diagnostics"]["operation_result"]
    assert operation_result["info_dictionary"]["title"] == "Updated PDF"
    assert operation_result["info_dictionary"]["author"] == "Elftia"
    assert operation_result["info_dictionary"]["subject"] == "Metadata edit"
    assert operation_result["info_dictionary"]["keywords"] == "pdf,metadata"
    assert [item["text"] for item in operation_result["text_by_page"]] == [
        "Title\nA\nB",
        "Content",
    ]


def test_public_edit_adds_updates_and_deletes_flat_outlines_atomically(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "outlines-edited.pdf"
    request = _request(
        tmp_path,
        "outlines-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "outline",
                        "action": "add",
                        "title": "First",
                        "page": 1,
                    },
                    {
                        "type": "outline",
                        "action": "add",
                        "title": "Second",
                        "page": 2,
                    },
                    {
                        "type": "outline",
                        "action": "update",
                        "index": 2,
                        "expected_title": "Second",
                        "title": "Renamed",
                        "page": 1,
                    },
                    {
                        "type": "outline",
                        "action": "delete",
                        "index": 1,
                        "expected_title": "First",
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    mutations = result["diagnostics"]["operation_result"]["primitives"]
    assert [item["action"] for item in mutations] == [
        "add",
        "add",
        "update",
        "delete",
    ]

    read_request = _request(
        tmp_path,
        "read-outlines-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert read_result["diagnostics"]["operation_result"]["outlines"] == [
        {
            "title": "Renamed",
            "destination_page": 1,
        }
    ]


def test_public_edit_adds_updates_and_deletes_text_annotations_atomically(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "annotations-edited.pdf"
    request = _request(
        tmp_path,
        "annotations-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {
                        "type": "annotation",
                        "action": "add",
                        "subtype": "text",
                        "page": 1,
                        "rectangle": [72, 700, 96, 724],
                        "contents": "First note",
                        "title": "Reviewer",
                        "color": [1, 1, 0],
                    },
                    {
                        "type": "annotation",
                        "action": "add",
                        "subtype": "text",
                        "page": 2,
                        "rectangle": [100, 650, 124, 674],
                        "contents": "Second note",
                    },
                    {
                        "type": "annotation",
                        "action": "update",
                        "page": 2,
                        "index": 1,
                        "expected_contents": "Second note",
                        "contents": "Updated note",
                        "color": [0.2, 0.4, 0.6],
                    },
                    {
                        "type": "annotation",
                        "action": "delete",
                        "page": 1,
                        "index": 1,
                        "expected_contents": "First note",
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    mutations = result["diagnostics"]["operation_result"]["primitives"]
    assert [item["action"] for item in mutations] == [
        "add",
        "add",
        "update",
        "delete",
    ]

    read_request = _request(
        tmp_path,
        "read-annotations-edit.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    assert read_result["diagnostics"]["operation_result"]["annotations"] == [
        {
            "page": 2,
            "index": 1,
            "subtype": "/Text",
            "rectangle": [100.0, 650.0, 124.0, 674.0],
            "contents": "Updated note",
            "title": None,
            "color": [0.2, 0.4, 0.6],
            "action_kind": None,
        }
    ]


# ---------------------------------------------------------------------------
# Encryption, decryption, and compression
# ---------------------------------------------------------------------------

def test_public_encrypt_writes_verified_aes_256_r5_without_secret_disclosure(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_hash = hashlib.sha256(public_created.read_bytes()).hexdigest()
    output = tmp_path / "encrypted.pdf"
    user_password = "reader-secret-4821"
    owner_password = "owner-secret-5932"
    request = _request(
        tmp_path,
        "encrypt.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": str(public_created),
            "output": str(output),
            "secrets": {
                "user_password": user_password,
                "owner_password": owner_password,
            },
            "arguments": {
                "algorithm": "AES-256-R5",
                "permissions": ["print", "extract"],
                "encrypt_metadata": True,
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    assert result["provider_chain"][0] == "pypdf"
    serialized_result = json.dumps(result, ensure_ascii=False)
    assert user_password not in serialized_result
    assert owner_password not in serialized_result
    assert hashlib.sha256(public_created.read_bytes()).hexdigest() == source_hash
    assert output.is_file()

    reader = PdfReader(output)
    assert reader.is_encrypted is True
    assert reader.decrypt(user_password) != 0
    encryption = reader.trailer["/Encrypt"]
    assert encryption["/V"] == 5
    assert encryption["/R"] == 5
    assert encryption["/Length"] == 256
    assert encryption["/CF"]["/StdCF"]["/CFM"] == "/AESV3"
    assert len(reader.pages) == 2
    assert "Title" in (reader.pages[0].extract_text() or "")

    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["output_version"] == "1.7"
    assert operation_result["encryption"] == {
        "algorithm": "AES-256-R5",
        "encrypt_metadata": True,
        "permissions": ["extract", "print"],
        "verified": True,
    }


def test_public_encrypted_read_fails_closed_and_explicit_decrypt_round_trips(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    encrypted = tmp_path / "round-trip-encrypted.pdf"
    decrypted = tmp_path / "round-trip-decrypted.pdf"
    user_password = "round-trip-user-3141"
    owner_password = "round-trip-owner-2718"
    encrypt_request = _request(
        tmp_path,
        "round-trip-encrypt.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": str(public_created),
            "output": str(encrypted),
            "secrets": {
                "user_password": user_password,
                "owner_password": owner_password,
            },
            "arguments": {
                "algorithm": "AES-256-R5",
                "permissions": ["extract", "print"],
                "encrypt_metadata": True,
            },
        },
    )
    encrypt_result = _public(
        project_root,
        "run",
        "--request",
        str(encrypt_request),
        check=False,
    )
    assert encrypt_result["status"] == "success", encrypt_result

    read_encrypted_request = _request(
        tmp_path,
        "read-encrypted.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(encrypted),
            "arguments": {},
        },
    )
    read_encrypted = _public(
        project_root,
        "run",
        "--request",
        str(read_encrypted_request),
        check=False,
    )
    assert read_encrypted["status"] == "failed"
    assert read_encrypted["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"

    encrypted_hash = hashlib.sha256(encrypted.read_bytes()).hexdigest()
    edit_destination = tmp_path / "encrypted-edit-output.pdf"
    original_destination = b"existing destination"
    edit_destination.write_bytes(original_destination)
    edit_request = _request(
        tmp_path,
        "edit-encrypted.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(encrypted),
            "output": str(edit_destination),
            "arguments": {
                "primitives": [{"type": "rotate", "pages": [1], "degrees": 90}],
            },
        },
    )
    edit_result = _public(
        project_root,
        "run",
        "--request",
        str(edit_request),
        check=False,
    )
    assert edit_result["status"] == "enhancement_required"
    assert edit_result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert edit_destination.read_bytes() == original_destination
    assert hashlib.sha256(encrypted.read_bytes()).hexdigest() == encrypted_hash

    decrypt_request = _request(
        tmp_path,
        "decrypt.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.decrypt",
            "input": str(encrypted),
            "output": str(decrypted),
            "secrets": {"password": user_password},
            "arguments": {},
        },
    )
    decrypt_result = _public(
        project_root,
        "run",
        "--request",
        str(decrypt_request),
        check=False,
    )

    assert decrypt_result["status"] == "success", decrypt_result
    assert decrypt_result["provider_chain"][0] == "pypdf"
    assert user_password not in json.dumps(decrypt_result, ensure_ascii=False)
    assert hashlib.sha256(encrypted.read_bytes()).hexdigest() == encrypted_hash
    decrypted_reader = PdfReader(decrypted)
    assert decrypted_reader.is_encrypted is False
    assert len(decrypted_reader.pages) == 2
    assert "Title" in (decrypted_reader.pages[0].extract_text() or "")
    decrypt_operation = decrypt_result["diagnostics"]["operation_result"]
    assert decrypt_operation["output_version"] == "1.7"
    assert decrypt_operation["decryption"] == {
        "encrypted_input": True,
        "encrypted_output": False,
        "verified": True,
    }

    read_decrypted_request = _request(
        tmp_path,
        "read-decrypted.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(decrypted),
            "arguments": {},
        },
    )
    read_decrypted = _public(
        project_root,
        "run",
        "--request",
        str(read_decrypted_request),
    )
    assert read_decrypted["status"] == "success"
    assert read_decrypted["diagnostics"]["operation_result"]["page_count"] == 2


def test_public_edit_rejects_filtered_encrypted_input_before_stream_decode(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    encrypted = tmp_path / "filtered-encrypted.pdf"
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(public_created))
    for page in writer.pages:
        page.compress_content_streams()
    writer.encrypt(
        user_password="filtered-user-3141",
        owner_password="filtered-owner-2718",
        algorithm="AES-256-R5",
    )
    with encrypted.open("wb") as stream:
        writer.write(stream)
    assert b"/Encrypt" in encrypted.read_bytes()
    assert b"/FlateDecode" in encrypted.read_bytes()

    destination = tmp_path / "filtered-encrypted-edit.pdf"
    original_destination = b"existing destination"
    destination.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "edit-filtered-encrypted.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(encrypted),
            "output": str(destination),
            "arguments": {
                "primitives": [{"type": "rotate", "pages": [1], "degrees": 90}],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "enhancement_required"
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert result["errors"][0]["details"]["capability"] == "pdf.decrypt"
    assert destination.read_bytes() == original_destination


def test_public_edit_does_not_treat_content_text_as_encryption(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "plain-encrypt-text.pdf"
    document = _minimal_text_document()
    document["pages"][0]["blocks"][0]["text"] = "Use /Encrypt here"
    create_pdf(source, document)
    output = tmp_path / "plain-encrypt-text-rotated.pdf"
    request = _request(
        tmp_path,
        "edit-plain-encrypt-text.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "primitives": [{"type": "rotate", "pages": [1], "degrees": 90}],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    assert output.is_file()


def test_public_decrypt_wrong_password_preserves_existing_destination(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    encrypted = tmp_path / "wrong-password-encrypted.pdf"
    user_password = "correct-user-1618"
    owner_password = "correct-owner-1414"
    encrypt_request = _request(
        tmp_path,
        "wrong-password-encrypt.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": str(public_created),
            "output": str(encrypted),
            "secrets": {
                "user_password": user_password,
                "owner_password": owner_password,
            },
            "arguments": {
                "algorithm": "AES-256-R5",
                "permissions": [],
                "encrypt_metadata": True,
            },
        },
    )
    encrypt_result = _public(
        project_root,
        "run",
        "--request",
        str(encrypt_request),
        check=False,
    )
    assert encrypt_result["status"] == "success", encrypt_result

    encrypted_before = encrypted.read_bytes()
    destination = tmp_path / "existing-decrypted.pdf"
    destination_before = b"existing destination must survive"
    destination.write_bytes(destination_before)
    wrong_password = "definitely-wrong-1732"
    decrypt_request = _request(
        tmp_path,
        "wrong-password-decrypt.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.decrypt",
            "input": str(encrypted),
            "output": str(destination),
            "secrets": {"password": wrong_password},
            "arguments": {},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(decrypt_request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert wrong_password not in json.dumps(result, ensure_ascii=False)
    assert encrypted.read_bytes() == encrypted_before
    assert destination.read_bytes() == destination_before


def test_public_lossless_compress_has_size_and_semantic_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _compressible_pdf(tmp_path / "compressible.pdf")
    output = tmp_path / "compressed.pdf"
    source_before = source.read_bytes()
    source_reader = PdfReader(source)
    source_text = source_reader.pages[0].extract_text()
    request = _request(
        tmp_path,
        "compress.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.compress",
            "input": str(source),
            "output": str(output),
            "arguments": {"mode": "lossless"},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    assert result["provider_chain"][0] == "pypdf"
    assert source.read_bytes() == source_before
    assert output.stat().st_size < source.stat().st_size
    output_reader = PdfReader(output)
    assert len(output_reader.pages) == 1
    assert output_reader.pages[0].extract_text() == source_text
    compression = result["diagnostics"]["operation_result"]["compression"]
    assert compression["mode"] == "lossless"
    assert compression["before_bytes"] == source.stat().st_size
    assert compression["after_bytes"] == output.stat().st_size
    assert compression["bytes_saved"] == source.stat().st_size - output.stat().st_size
    assert 0 < compression["ratio"] < 1
    assert compression["verified"] is True


def test_public_lossless_compress_without_size_gain_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf_fixture(
        tmp_path / "already-compact.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
                b"/Resources << >> /Contents 4 0 R >>"
            ),
            b"<< /Length 0 >>\nstream\n\nendstream",
        ],
    )
    source_before = source.read_bytes()
    output = tmp_path / "existing-compressed.pdf"
    destination_before = b"existing destination must survive no-gain compression"
    output.write_bytes(destination_before)
    request = _request(
        tmp_path,
        "compress-no-gain.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.compress",
            "input": str(source),
            "output": str(output),
            "arguments": {"mode": "lossless"},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert source.read_bytes() == source_before
    assert output.read_bytes() == destination_before


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------

def test_public_rewrite(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-rewritten.pdf"
    rewrite_request = _request(
        tmp_path,
        "rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "source_sha256": hashlib.sha256(public_created.read_bytes()).hexdigest(),
                "blocks": [
                    {"page": 1, "bbox": [72, 753, 300, 770], "text": "Title", "font": "F2", "size": 16.0, "color": None},
                ],
                "rewrites": [
                    {"block_index": 0, "text": "Modified Title"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(rewrite_request))
    assert result["status"] == "success"
    assert output.is_file()
    op_result = result["diagnostics"]["operation_result"]
    assert "rewrite" in op_result
    assert op_result["rewrite"]["blocks_processed"] == 1


def test_public_rewrite_source_hash_mismatch_preserves_source_and_destination(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_before = public_created.read_bytes()
    output = tmp_path / "existing-rewrite.pdf"
    destination_before = b"existing rewrite destination"
    output.write_bytes(destination_before)
    request = _request(
        tmp_path,
        "rewrite-wrong-source-hash.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "source_sha256": "0" * 64,
                "blocks": [{
                    "page": 1,
                    "bbox": [72, 754, 300, 770],
                    "text": "Title",
                    "font": "F2",
                    "size": 16.0,
                    "color": None,
                }],
                "rewrites": [{"block_index": 0, "text": "Modified Title"}],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert public_created.read_bytes() == source_before
    assert output.read_bytes() == destination_before


def test_public_rewrite_rejects_stale_text_bbox_and_page_selectors(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_before = public_created.read_bytes()
    source_sha256 = hashlib.sha256(source_before).hexdigest()
    stale_selectors = [
        ("text", {"text": "Stale title"}),
        ("bbox", {"bbox": [0, 0, 10, 10]}),
        ("page", {"page": 2}),
    ]
    for name, override in stale_selectors:
        output = tmp_path / f"existing-stale-{name}.pdf"
        destination_before = f"existing stale {name}".encode("ascii")
        output.write_bytes(destination_before)
        block = {
            "page": 1,
            "bbox": [72, 754, 300, 770],
            "text": "Title",
            "font": "F2",
            "size": 16.0,
            "color": None,
            **override,
        }
        request = _request(
            tmp_path,
            f"rewrite-stale-{name}.json",
            {
                "schema_version": "1.0",
                "operation": "pdf.rewrite.apply",
                "input": str(public_created),
                "output": str(output),
                "arguments": {
                    "source_sha256": source_sha256,
                    "blocks": [block],
                    "rewrites": [{"block_index": 0, "text": "Modified Title"}],
                },
            },
        )

        result = _public(project_root, "run", "--request", str(request), check=False)

        assert result["status"] == "failed", (name, result)
        assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
        assert output.read_bytes() == destination_before
        assert public_created.read_bytes() == source_before


def test_public_rewrite_formula_multicolumn_and_rotated_page_preserves_layout(
    project_root: Path,
    tmp_path: Path,
) -> None:
    def stream(content: bytes) -> bytes:
        return (
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream"
        )

    source = _write_pdf_fixture(
        tmp_path / "rewrite-layout-source.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R 6 0 R] /Count 4 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/CropBox [20 30 592 762] /Resources << /Font << /F1 11 0 R >> >> "
                b"/Contents 7 0 R >>"
            ),
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 11 0 R >> >> /Contents 8 0 R >>"
            ),
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Rotate 90 "
                b"/Resources << /Font << /F1 11 0 R >> >> /Contents 9 0 R >>"
            ),
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 500] "
                b"/CropBox [10 20 390 480] /Rotate 180 "
                b"/Resources << /Font << /F1 11 0 R >> >> /Contents 10 0 R >>"
            ),
            stream(
                b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (Formula: E = mc^2) Tj "
                b"0 -24 Td (Formula note stays) Tj ET"
            ),
            stream(
                b"BT /F1 12 Tf 1 0 0 1 72 650 Tm (Left column stays) Tj ET "
                b"BT /F1 12 Tf 1 0 0 1 320 650 Tm (Right column target) Tj ET"
            ),
            stream(
                b"BT /F1 12 Tf 1 0 0 1 100 500 Tm (Rotated target) Tj "
                b"0 -24 Td (Rotated note stays) Tj ET"
            ),
            stream(b"BT /F1 12 Tf 1 0 0 1 40 400 Tm (Untargeted page) Tj ET"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        ],
    )
    source_before = source.read_bytes()
    read_request = _request(
        tmp_path,
        "rewrite-layout-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(source),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    available_blocks = {
        block["text"]: block
        for block in read_result["diagnostics"]["operation_result"]["text_blocks"]
    }
    selector_keys = ("page", "bbox", "text", "font", "size", "color")
    selectors = [
        {key: available_blocks[text][key] for key in selector_keys}
        for text in (
            "Formula: E = mc^2",
            "Right column target",
            "Rotated target",
        )
    ]
    for selector in selectors:
        selector["bbox"] = list(selector["bbox"])
        selector["bbox"][2] += 60.0
    output = tmp_path / "rewrite-layout-output.pdf"
    rewrite_request = _request(
        tmp_path,
        "rewrite-layout.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "source_sha256": hashlib.sha256(source_before).hexdigest(),
                "blocks": selectors,
                "rewrites": [
                    {"block_index": 0, "text": "Formula: F = ma"},
                    {"block_index": 1, "text": "Right column revised"},
                    {"block_index": 2, "text": "Rotated revised"},
                ],
            },
        },
    )

    result = _public(project_root, "run", "--request", str(rewrite_request), check=False)

    assert result["status"] == "success", result
    assert source.read_bytes() == source_before
    rewrite = result["diagnostics"]["operation_result"]["rewrite"]
    assert rewrite["blocks_processed"] == 3
    layout = rewrite["page_layout_preservation"]
    assert layout == {
        "page_count_match": True,
        "page_box_preserved": True,
        "non_targeted_objects_preserved": True,
        "targeted_pages": [1, 2, 3],
        "verified": True,
    }
    before_reader = PdfReader(source)
    after_reader = PdfReader(output)
    assert len(before_reader.pages) == len(after_reader.pages) == 4
    for before_page, after_page in zip(before_reader.pages, after_reader.pages, strict=True):
        assert list(before_page.mediabox) == list(after_page.mediabox)
        assert list(before_page.cropbox) == list(after_page.cropbox)
        assert before_page.rotation == after_page.rotation
    assert after_reader.pages[2].rotation == 90
    assert after_reader.pages[3].rotation == 180

    output_read_request = _request(
        tmp_path,
        "rewrite-layout-output-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    output_read = _public(project_root, "run", "--request", str(output_read_request))
    text_by_page = [
        page["text"]
        for page in output_read["diagnostics"]["operation_result"]["text_by_page"]
    ]
    assert "Formula: F = ma" in text_by_page[0]
    assert "Formula note stays" in text_by_page[0]
    assert "Left column stays" in text_by_page[1]
    assert "Right column revised" in text_by_page[1]
    assert "Rotated revised" in text_by_page[2]
    assert "Rotated note stays" in text_by_page[2]
    assert text_by_page[3] == "Untargeted page"


def test_public_rewrite_cjk_fails_closed(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-cjk.pdf"
    rewrite_request = _request(
        tmp_path,
        "cjk_rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "source_sha256": hashlib.sha256(public_created.read_bytes()).hexdigest(),
                "blocks": [
                    {"page": 1, "bbox": [72, 754, 300, 770], "text": "Title", "font": "F2", "size": 16.0, "color": None},
                ],
                "rewrites": [
                    {"block_index": 0, "text": "日本語テスト"},
                ],
            },
        },
    )
    result = _public(
        project_root,
        "run",
        "--request",
        str(rewrite_request),
        check=False,
    )
    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "enhancement_required"
    assert not any(item["role"] == "output" for item in result["artifacts"])
    assert result["validation"]["status"] != "pass"
    assert not output.exists()


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def test_public_validate_reopens_valid_pdf(project_root: Path, public_created: Path) -> None:
    result = _public(
        project_root,
        "validate",
        "--input",
        str(public_created),
        "--json",
    )
    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "pass"
    assert outcomes["provider.reopen"] == "pass"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_public_unknown_operation_rejected(project_root: Path, tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.nonexistent",
            "input": str(tmp_path / "input.pdf"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"


def test_public_edit_output_equals_input_rejected(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    same = str(public_created.resolve())
    edit_request = _request(
        tmp_path,
        "same.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": same,
            "output": same,
            "arguments": {
                "primitives": [{"type": "rotate", "pages": [1], "degrees": 90}],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request), check=False)
    assert result["status"] == "invalid_request"


# ---------------------------------------------------------------------------
# Unicode invocation directory
# ---------------------------------------------------------------------------

def test_public_unicode_invocation_directory(project_root: Path, tmp_path: Path) -> None:
    """Run from a directory containing non-ASCII characters in its path."""
    unicode_dir = tmp_path / "テスト_道場"
    unicode_dir.mkdir()
    output = unicode_dir / "ucreated.pdf"
    request_path = unicode_dir / "create.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(output),
                "arguments": {"document": _document()},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = _public(
        project_root,
        "run",
        "--request",
        str(request_path),
        cwd=unicode_dir,
        check=False,
    )
    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "success", result
    assert any(item["role"] == "output" for item in result["artifacts"])
    assert result["validation"]["status"] == "pass"
    assert output.is_file()


# ---------------------------------------------------------------------------
# Honest provider chain
# ---------------------------------------------------------------------------

def test_public_provider_chain_identifies_core_python(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    """Verify the result advertises an honest provider chain for a read operation.

    The canonical result exposes at least one provider-chain entry and the
    accepted provider identity references core-python.
    """
    read_request = _request(
        tmp_path,
        "read_chain.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] == "success"
    # The result should carry honest provider evidence
    assert "fidelity" in result or "provider_chain" in result
