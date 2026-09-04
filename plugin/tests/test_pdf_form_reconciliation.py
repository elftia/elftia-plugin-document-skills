"""Public page-operation coverage for AcroForm graph reconciliation."""

import hashlib
import json
from pathlib import Path
import subprocess

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

from pypdf import PdfReader


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
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    assert process.stderr == b""
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _request(
    tmp_path: Path,
    name: str,
    source: Path,
    output: Path,
    primitive: dict[str, object],
) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"primitives": [primitive]},
        }),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _one_page_form(path: Path, field_name: str) -> Path:
    name = field_name.encode("ascii")
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 7 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T ("
            + name
            + b") /V () /Rect [20 300 180 330] /P 3 0 R "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
        (
            b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
    ])


def _two_page_form(path: Path) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 10 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 6 0 R "
            b"/Annots [8 0 R] >>"
        ),
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 7 0 R "
            b"/Annots [9 0 R] >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Length 0 >>\nstream\n\nendstream",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (first) /V (A) "
            b"/Rect [20 300 180 330] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (second) /V (B) "
            b"/Rect [20 300 180 330] /P 4 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
        (
            b"<< /Fields [8 0 R 9 0 R] /DR << /Font << /Helv 5 0 R >> >> "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
    ])


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
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


def test_page_sequence_removes_fields_with_deleted_widget_pages(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _two_page_form(tmp_path / "two-page-form.pdf")
    output = tmp_path / "selected-form.pdf"
    result = _public(
        project_root,
        _request(
            tmp_path,
            "select-form-page.json",
            source,
            output,
            {"type": "page_sequence", "pages": [2]},
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["form_fields"] == ["second"]
    reader = PdfReader(output)
    assert list((reader.get_fields() or {})) == ["second"]
    assert len(reader.pages) == 1
    widget = reader.pages[0]["/Annots"][0].get_object()
    assert widget["/T"] == "second"
    assert widget.raw_get("/P").idnum == reader.pages[0].indirect_reference.idnum


def test_page_insert_merges_compatible_form_roots(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _one_page_form(tmp_path / "destination-form.pdf", "destination")
    donor = _one_page_form(tmp_path / "donor-form.pdf", "donor")
    output = tmp_path / "inserted-form.pdf"
    result = _public(
        project_root,
        _request(
            tmp_path,
            "insert-form-page.json",
            source,
            output,
            {
                "type": "page_insert",
                "input": str(donor),
                "source_sha256": hashlib.sha256(donor.read_bytes()).hexdigest(),
                "at": 1,
                "pages": [1],
            },
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["form_fields"] == ["destination", "donor"]
    reader = PdfReader(output)
    assert set(reader.get_fields() or {}) == {"destination", "donor"}
    assert len(reader.pages) == 2
    assert reader.pages[0]["/Annots"][0].get_object()["/T"] == "donor"
    assert reader.pages[1]["/Annots"][0].get_object()["/T"] == "destination"


def test_split_reconciles_fields_for_retained_pages(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _two_page_form(tmp_path / "split-source-form.pdf")
    output = tmp_path / "split-form.pdf"
    result = _public(
        project_root,
        _request(
            tmp_path,
            "split-form.json",
            source,
            output,
            {"type": "split", "page_ranges": [[2, 2]]},
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["form_fields"] == ["second"]
    assert list((PdfReader(output).get_fields() or {})) == ["second"]


def test_merge_combines_compatible_form_roots(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _one_page_form(tmp_path / "merge-first-form.pdf", "first")
    donor = _one_page_form(tmp_path / "merge-second-form.pdf", "second")
    output = tmp_path / "merged-form.pdf"
    result = _public(
        project_root,
        _request(
            tmp_path,
            "merge-forms.json",
            source,
            output,
            {
                "type": "merge",
                "inputs": [
                    {
                        "input": str(path),
                        "source_sha256": hashlib.sha256(
                            path.read_bytes()
                        ).hexdigest(),
                    }
                    for path in (source, donor)
                ],
            },
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["form_fields"] == ["first", "second"]
    assert set(PdfReader(output).get_fields() or {}) == {"first", "second"}


def test_page_insert_rejects_duplicate_field_names_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _one_page_form(tmp_path / "duplicate-destination.pdf", "duplicate")
    donor = _one_page_form(tmp_path / "duplicate-donor.pdf", "duplicate")
    output = tmp_path / "duplicate-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    result = _public(
        project_root,
        _request(
            tmp_path,
            "insert-duplicate-form.json",
            source,
            output,
            {
                "type": "page_insert",
                "input": str(donor),
                "source_sha256": hashlib.sha256(donor.read_bytes()).hexdigest(),
                "at": 2,
            },
        ),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.acroform-page-reconciliation"
    )
    assert output.read_bytes() == destination_before
