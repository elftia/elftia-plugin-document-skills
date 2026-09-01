"""Public visual-state and graph-pruning tests for AcroForm flattening."""

import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
import zlib

from pypdf import PdfReader
import pytest


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
    operation: str,
    source: Path,
    *,
    output: Path | None = None,
    arguments: dict[str, object] | None = None,
) -> Path:
    path = tmp_path / name
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": operation,
        "input": str(source),
        "arguments": arguments or {},
    }
    if output is not None:
        payload["output"] = str(output)
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _form_request(
    tmp_path: Path,
    name: str,
    source: Path,
    output: Path,
    fields: dict[str, object],
) -> Path:
    return _request(
        tmp_path,
        name,
        "pdf.edit",
        source,
        output=output,
        arguments={
            "primitives": [{
                "type": "form_fill",
                "fields": fields,
                "flatten": True,
            }]
        },
    )


def _nested_sibling_form(path: Path) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 11 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [9 0 R 10 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /T (person) /FT /Tx /Kids [7 0 R 8 0 R] >>",
        b"<< /Parent 6 0 R /T (first) /Kids [9 0 R] >>",
        b"<< /Parent 6 0 R /T (second) /Kids [10 0 R] >>",
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 7 0 R "
            b"/Rect [20 300 180 330] /P 3 0 R /DA (/Helv 12 Tf 0 g) "
            b"/MK << /BG [1 1 0] /BC [0 0 1] >> /BS << /W 2 /S /S >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 8 0 R "
            b"/Rect [20 250 180 280] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
        (
            b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> "
            b"/DA (/Helv 12 Tf 0 g) >>"
        ),
    ])


def _checkbox_form(path: Path) -> Path:
    off = b"0.8 g 0 0 20 20 re f"
    on = b"0 1 0 rg 0 0 20 20 re f"
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 9 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << >> /Contents 4 0 R /Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) "
            b"/V /Off /AS /Off /Rect [20 300 40 320] /P 3 0 R "
            b"/AP << /N << /Off 7 0 R /Yes 8 0 R >> >> >>"
        ),
        _appearance(off),
        _appearance(on),
        b"<< /Fields [6 0 R] >>",
    ])


def _radio_form(path: Path) -> Path:
    off = b"0.8 g 0 0 20 20 re f"
    small = b"1 0 0 rg 0 0 20 20 re f"
    large = b"0 0 1 rg 0 0 20 20 re f"
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 12 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << >> /Contents 4 0 R /Annots [7 0 R 8 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< >>",
        b"<< /FT /Btn /Ff 32768 /T (size) /V /Small /Kids [7 0 R 8 0 R] >>",
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 6 0 R /AS /Small "
            b"/Rect [20 300 40 320] /P 3 0 R "
            b"/AP << /N << /Off 9 0 R /Small 10 0 R >> >> >>"
        ),
        (
            b"<< /Type /Annot /Subtype /Widget /Parent 6 0 R /AS /Off "
            b"/Rect [60 300 80 320] /P 3 0 R "
            b"/AP << /N << /Off 9 0 R /Large 11 0 R >> >> >>"
        ),
        _appearance(off),
        _appearance(small),
        _appearance(large),
        b"<< /Fields [6 0 R] >>",
    ])


def _flate_text_form(path: Path) -> tuple[Path, bytes, bytes]:
    original = b"BT /Helv 12 Tf 20 100 Td (ORIGINAL) Tj ET"
    compressed = zlib.compress(original)
    source = _write_pdf(
        path,
        [
            b"<< /Type /Catalog /Pages 2 0 R /AcroForm 7 1 R >>",
            b"<< /Type /Pages /Kids [3 0 R 8 0 R] /Count 2 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
                b"/Resources << /Font << /Helv 5 2 R >> >> /Contents 4 3 R "
                b"/Annots [6 4 R] >>"
            ),
            (
                f"<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n".encode(
                    "ascii"
                )
                + compressed
                + b"\nendstream"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            (
                b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) "
                b"/Rect [20 300 180 330] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
            ),
            b"<< /Fields [6 4 R] /DR << /Font << /Helv 5 2 R >> >> >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
                b"/Resources << /Font << /Helv 5 2 R >> >> /Contents 4 3 R >>"
            ),
        ],
        generations={4: 3, 5: 2, 6: 4, 7: 1},
    )
    return source, original, compressed


def _tagged_checkbox_form(path: Path) -> Path:
    off = b"0.8 g 0 0 20 20 re f"
    on = b"0 1 0 rg 0 0 20 20 re f"
    return _write_pdf(path, [
        (
            b"<< /Type /Catalog /Pages 2 0 R /AcroForm 9 0 R "
            b"/StructTreeRoot 10 0 R >>"
        ),
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << >> /Contents 4 0 R /Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) "
            b"/V /Off /AS /Off /Rect [20 300 40 320] /P 3 0 R "
            b"/AP << /N << /Off 7 0 R /Yes 8 0 R >> >> >>"
        ),
        _appearance(off),
        _appearance(on),
        b"<< /Fields [6 0 R] >>",
        b"<< /Type /StructTreeRoot /K 11 0 R >>",
        (
            b"<< /Type /StructElem /K "
            b"<< /Type /OBJR /Obj 6 0 R /Pg 3 0 R >> >>"
        ),
    ])


def _f1_text_form(path: Path) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 7 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) "
            b"/Rect [20 300 180 330] /P 3 0 R /DA (/F1 12 Tf 0 g) >>"
        ),
        b"<< /Fields [6 0 R] /DR << /Font << /F1 5 0 R >> >> >>",
    ])


def _combo_choice_form(path: Path) -> Path:
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
            b"<< /Type /Annot /Subtype /Widget /FT /Ch /Ff 131072 /T (color) "
            b"/V (Red) /Opt [(Red) (Green) (Blue)] /Rect [20 300 180 330] "
            b"/P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
        b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> >>",
    ])


def _unsupported_style_text_form(path: Path, tail: bytes) -> Path:
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
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) "
            b"/Rect [20 300 180 330] /P 3 0 R /DA (/Helv 12 Tf 0 g) "
            + tail
            + b" >>"
        ),
        b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> >>",
    ])


def _appearance(stream: bytes) -> bytes:
    return (
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 20 20] "
        f"/Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"\nendstream"
    )


def _write_pdf(
    path: Path,
    objects: list[bytes],
    *,
    generations: dict[int, int] | None = None,
) -> Path:
    generations = generations or {}
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        generation = generations.get(object_number, 0)
        body.extend(f"{object_number} {generation} obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for object_number, offset in enumerate(offsets, start=1):
        generation = generations.get(object_number, 0)
        xref.extend(f"{offset:010d} {generation:05d} n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _xref_entries(payload: bytes) -> list[bytes]:
    start = payload.rfind(b"\nxref\n") + 1
    assert start > 0
    lines = payload[start:].splitlines()
    assert lines[0] == b"xref"
    first, size = (int(value) for value in lines[1].split())
    assert first == 0
    return lines[2:2 + size]


def test_nested_partial_flatten_prunes_only_selected_branch(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _nested_sibling_form(tmp_path / "nested-siblings.pdf")
    output = tmp_path / "nested-partial-flatten.pdf"
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-nested.json", source, output, {"person.first": "Alice"}),
    )

    assert result["status"] == "success", result
    reader = PdfReader(output)
    assert len(reader.pages[0]["/Annots"]) == 1
    page = reader.pages[0]
    content = page["/Contents"][-1].get_object().get_data()
    assert b"/DSForm1 Do" in content
    xobjects = page["/Resources"]["/XObject"]
    appearance = xobjects["/DSForm1"].get_object()
    assert appearance["/Subtype"] == "/Form"
    assert list(appearance["/BBox"]) == [0, 0, 160, 30]
    assert list(appearance["/Matrix"]) == [1, 0, 0, 1, 0, 0]
    appearance_data = appearance.get_data()
    assert b"1 1 0 rg" in appearance_data
    assert b"0 0 1 RG" in appearance_data
    assert b"2 w" in appearance_data
    assert b"(Alice) Tj" in appearance_data
    read_result = _public(
        project_root,
        _request(tmp_path, "read-nested.json", "pdf.read", output),
    )
    operation = read_result["diagnostics"]["operation_result"]
    assert [field["qualified_name"] for field in operation["acroform_fields"]] == [
        "person.second"
    ]
    assert operation["text_by_page"][0]["text"] == "Alice"


def test_checkbox_flatten_paints_selected_appearance_and_removes_form(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _checkbox_form(tmp_path / "checkbox.pdf")
    output = tmp_path / "checkbox-flattened.pdf"
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-checkbox.json", source, output, {"agree": True}),
    )

    assert result["status"] == "success", result
    output_bytes = output.read_bytes()
    assert b"0 1 0 rg 0 0 20 20 re f" in output_bytes
    assert b"1 0 0 1 20 300 cm" in output_bytes
    assert b"/AcroForm" not in output_bytes
    assert b"/Subtype /Widget" not in output_bytes


def test_radio_flatten_paints_each_effective_state_and_removes_widgets(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _radio_form(tmp_path / "radio.pdf")
    output = tmp_path / "radio-flattened.pdf"
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-radio.json", source, output, {"size": "Large"}),
    )

    assert result["status"] == "success", result
    output_bytes = output.read_bytes()
    assert b"0.8 g 0 0 20 20 re f" in output_bytes
    assert b"0 0 1 rg 0 0 20 20 re f" in output_bytes
    assert b"/AcroForm" not in output_bytes
    assert b"/Subtype /Widget" not in output_bytes


def test_flatten_appends_unfiltered_stream_and_writes_legal_xref(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source, original, compressed = _flate_text_form(tmp_path / "flate-form.pdf")
    output = tmp_path / "flate-flattened.pdf"
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-flate.json", source, output, {"name": "Alice"}),
    )

    assert result["status"] == "success", result
    output_bytes = output.read_bytes()
    assert compressed in output_bytes
    reader = PdfReader(output, strict=True)
    first_page_contents = reader.pages[0]["/Contents"]
    assert len(first_page_contents) == 2
    original_stream = first_page_contents[0].get_object()
    flattened_stream = first_page_contents[1].get_object()
    assert original_stream["/Filter"] == "/FlateDecode"
    assert original_stream.get_data() == original
    assert flattened_stream.get("/Filter") is None
    assert b"/DSForm1 Do" in flattened_stream.get_data()
    appearance = reader.pages[0]["/Resources"]["/XObject"]["/DSForm1"].get_object()
    assert b"(Alice) Tj" in appearance.get_data()

    shared_reference = reader.pages[1].raw_get("/Contents")
    assert shared_reference.idnum == 4
    assert shared_reference.generation == 3
    assert reader.xref[3][4] > 0
    assert reader.xref[2][5] > 0

    entries = _xref_entries(output_bytes)
    assert entries[0] == b"0000000006 65535 f"
    assert entries[4].endswith(b"00003 n")
    assert entries[5].endswith(b"00002 n")
    assert entries[6] == b"0000000007 00005 f"
    assert entries[7] == b"0000000000 00002 f"
    assert entries[9].endswith(b"00000 n")


def test_flatten_rejects_external_objr_reference_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _tagged_checkbox_form(tmp_path / "tagged-checkbox.pdf")
    output = tmp_path / "tagged-checkbox-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-tagged.json", source, output, {"agree": True}),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == "pdf.form-flatten"
    assert result["errors"][0]["details"]["source_object"] == 11
    assert result["errors"][0]["details"]["target_object"] == 6
    assert output.read_bytes() == destination_before


def test_text_flatten_rejects_f1_only_page_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _f1_text_form(tmp_path / "f1-only.pdf")
    output = tmp_path / "f1-only-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-f1.json", source, output, {"name": "Alice"}),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == "pdf.form-flatten"
    assert output.read_bytes() == destination_before


def test_combo_choice_flatten_uses_form_xobject_and_remains_readable(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _combo_choice_form(tmp_path / "combo-choice.pdf")
    output = tmp_path / "combo-choice-output.pdf"
    result = _public(
        project_root,
        _form_request(tmp_path, "flatten-choice.json", source, output, {"color": "Green"}),
    )

    assert result["status"] == "success", result
    reader = PdfReader(output, strict=True)
    content = reader.pages[0]["/Contents"][-1].get_object().get_data()
    assert b"/DSForm1 Do" in content
    appearance = reader.pages[0]["/Resources"]["/XObject"]["/DSForm1"].get_object()
    assert b"(Green) Tj" in appearance.get_data()
    read_result = _public(
        project_root,
        _request(tmp_path, "read-choice.json", "pdf.read", output),
    )
    assert read_result["diagnostics"]["operation_result"]["text_by_page"][0]["text"] == (
        "Green"
    )


@pytest.mark.parametrize(
    ("case", "tail"),
    [
        ("appearance", b"/AP << /N << >> >>"),
        ("default-appearance", b"/DA (/Helv 12 Tf 0 g 1 w)"),
        ("appearance-characteristics", b"/MK << /R 90 >>"),
        ("border-style", b"/BS << /W 1 /S /D >>"),
    ],
)
def test_text_flatten_rejects_unsupported_appearance_styles_atomically(
    project_root: Path,
    tmp_path: Path,
    case: str,
    tail: bytes,
) -> None:
    source = _unsupported_style_text_form(tmp_path / f"{case}.pdf", tail)
    output = tmp_path / f"{case}-output.pdf"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)
    result = _public(
        project_root,
        _form_request(tmp_path, f"flatten-{case}.json", source, output, {"name": "Alice"}),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["details"]["capability"] == "pdf.form-appearance"
    assert output.read_bytes() == destination_before
