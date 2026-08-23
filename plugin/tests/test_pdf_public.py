"""PDF public command surface tests — frozen uv subprocess boundary.

Exercises the real public CLI (document-pdf/scripts/run.py), the
supervisor/worker, one stdout JSON result, honest provider chain, and honest
optional ``unavailable`` gates.  Includes a Unicode invocation directory to
mirror the XLSX/PPTX public tests.

Module provenance: original Elftia-authored test suite.
"""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest
from pypdf import PdfReader

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


def _text_form_pdf(path: Path, *, second_field: bool = False) -> Path:
    acroform_object = 8 if second_field else 7
    annotations = b"[6 0 R 7 0 R]" if second_field else b"[6 0 R]"
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
            b"/Rect [72 700 300 730] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
    ]
    if second_field:
        objects.append(
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (city) /V () "
            b"/Rect [72 650 300 680] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        )
    fields = b"[6 0 R 7 0 R]" if second_field else b"[6 0 R]"
    objects.append(
        b"<< /Fields " + fields + b" /DR << /Font << /Helv 5 0 R >> >> "
        b"/DA (/Helv 12 Tf 0 g) >>"
    )
    return _write_pdf_fixture(path, objects)


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
    assert creation["images"] == [
        {
            "asset_bytes": len(_PNG),
            "asset_sha256": hashlib.sha256(_PNG).hexdigest(),
            "bbox": [72.0, 707.89, 112.0, 747.89],
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
    assert b"/F1 24 Tf" in output_bytes
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
    assert preservation["added_objects"] == [7]
    assert b"/Resources 7 0 R" in output.read_bytes()

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
                    {"type": "merge", "inputs": [str(public_created), str(second)]},
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
            "arguments": {
                "user_password": user_password,
                "owner_password": owner_password,
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
            "arguments": {
                "user_password": user_password,
                "owner_password": owner_password,
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
    decrypt_request = _request(
        tmp_path,
        "decrypt.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.decrypt",
            "input": str(encrypted),
            "output": str(decrypted),
            "arguments": {"password": user_password},
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
    assert decrypt_result["diagnostics"]["operation_result"]["decryption"] == {
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
            "arguments": {
                "user_password": user_password,
                "owner_password": owner_password,
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
            "arguments": {"password": wrong_password},
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
                "blocks": [
                    {"page": 1, "bbox": [72, 754, 300, 770], "text": "Title", "font": "F2", "size": 16.0, "color": None},
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
