"""Public and Core regressions for widget appearance graph binding."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from document_skills_core.formats.pdf.content_streams import extract_content_stream
from document_skills_core.formats.pdf.edit import _build_manifest
from document_skills_core.formats.pdf.form_graph import collect_form_fields
from document_skills_core.formats.pdf.form_updates import (
    replace_text_field_value,
    write_form_pdf,
)
from document_skills_core.formats.pdf.object_model import (
    IndirectReference,
    PdfDict,
    PdfObjectModel,
    parse_pdf,
)
from document_skills_core.formats.pdf import service as service_module
from document_skills_core.formats.pdf.service import PdfService


@pytest.mark.parametrize("appearance_kind", ["direct", "indirect"])
@pytest.mark.parametrize(
    ("field_type", "field_name", "old_value", "new_value"),
    [
        ("text", "name", "OLD", "Alice"),
        ("choice", "color", "Red", "Green"),
    ],
)
def test_public_form_fill_rebinds_normal_appearance_and_preserves_other_entries(
    project_root: Path,
    tmp_path: Path,
    appearance_kind: str,
    field_type: str,
    field_name: str,
    old_value: str,
    new_value: str,
) -> None:
    source = _text_or_choice_form(
        tmp_path / f"{field_type}-{appearance_kind}.pdf",
        field_type=field_type,
        appearance_kind=appearance_kind,
    )
    source_model = parse_pdf(source)
    output = tmp_path / f"{field_type}-{appearance_kind}-output.pdf"
    request = _request(
        tmp_path / f"{field_type}-{appearance_kind}.json",
        source,
        output,
        {field_name: new_value},
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["appearances_written"] == 1
    gate = next(
        item for item in result["validation"]["gates"]
        if item["id"] == "operation.mutation-semantics"
    )
    assert gate["outcome"] == "pass"
    model = parse_pdf(output)
    field = collect_form_fields(model)[0]
    widget = field.widgets[0]
    assert isinstance(widget.value, PdfDict)
    appearance = _appearance_dictionary(model, widget.value)
    normal = appearance.get("/N")
    rollover = appearance.get("/R")
    assert isinstance(normal, IndirectReference)
    assert rollover == IndirectReference(8, 0)
    assert normal.obj_num in operation["added_objects"]
    stream = extract_content_stream(model, [normal], 1)
    assert f"({new_value}) Tj".encode("latin-1") in stream
    assert f"({old_value}) Tj".encode("latin-1") not in stream
    assert b"(OLD) Tj" in extract_content_stream(
        source_model,
        [IndirectReference(8, 0)],
        1,
    )
    assert set(operation["changed_objects"]) == {6, 10}
    assert operation["removed_objects"] == []
    assert 8 in operation["preservation"]["preserved_objects"]
    if appearance_kind == "indirect":
        assert 9 in operation["preservation"]["preserved_objects"]
        assert source_model.objects[9].sha256 == model.objects[9].sha256


def test_public_checkbox_fill_resolves_indirect_normal_state_dictionary(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _checkbox_form(tmp_path / "checkbox-indirect-ap.pdf")
    output = tmp_path / "checkbox-indirect-ap-output.pdf"
    request = _request(
        tmp_path / "checkbox-indirect-ap.json",
        source,
        output,
        {"agree": True},
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["appearances_written"] == 1
    model = parse_pdf(output)
    field = collect_form_fields(model)[0]
    widget = field.widgets[0]
    assert isinstance(widget.value, PdfDict)
    assert widget.value.get("/V") == "/Yes"
    assert widget.value.get("/AS") == "/Yes"
    appearance = _appearance_dictionary(model, widget.value)
    normal = appearance.get("/N")
    if isinstance(normal, IndirectReference):
        normal = model.get_object(normal).value
    assert isinstance(normal, PdfDict)
    assert normal.get("/Yes") == IndirectReference(8, 0)
    gate = next(
        item for item in result["validation"]["gates"]
        if item["id"] == "operation.mutation-semantics"
    )
    assert gate["outcome"] == "pass"


def test_core_semantic_gate_rejects_new_value_bound_to_old_appearance(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _text_or_choice_form(
        tmp_path / "semantic-source.pdf",
        field_type="text",
        appearance_kind="indirect",
    )
    destination = tmp_path / "semantic-output.pdf"
    destination.write_bytes(b"preserve destination")

    def stale_appearance_edit(
        input_path: Path,
        output_path: Path,
        _arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        model = parse_pdf(input_path)
        replacement = replace_text_field_value(model.objects[6], "Alice")
        output_path.write_bytes(write_form_pdf(
            model,
            {6: replacement},
            {},
            removed=set(),
        ))
        manifest = _build_manifest(
            model.object_hashes(),
            parse_pdf(output_path).object_hashes(),
            changed={6},
            added=set(),
            removed=set(),
        )
        return {
            "primitive": "form_fill",
            "fields_filled": ["name"],
            "field_types": {"name": "text"},
            "appearances_written": 1,
            "flattened": False,
            "need_appearances": False,
            "preservation": manifest,
        }, manifest

    monkeypatch.setattr(service_module, "edit_pdf", stale_appearance_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request_payload(source, destination, {"name": "Alice"}),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics",
    ]
    assert destination.read_bytes() == b"preserve destination"


def _appearance_dictionary(model: PdfObjectModel, widget: PdfDict) -> PdfDict:
    appearance = widget.get("/AP")
    if isinstance(appearance, IndirectReference):
        appearance = model.get_object(appearance).value
    assert isinstance(appearance, PdfDict)
    return appearance


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
    fields: dict[str, str | bool],
) -> Path:
    path.write_text(
        json.dumps(_request_payload(source, output, fields), ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _request_payload(
    source: Path,
    output: Path,
    fields: dict[str, str | bool],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"primitives": [{
            "type": "form_fill",
            "fields": fields,
            "flatten": False,
        }]},
    }


def _text_or_choice_form(
    path: Path,
    *,
    field_type: str,
    appearance_kind: str,
) -> Path:
    if field_type == "text":
        field_entries = b"/FT /Tx /T (name) /V (OLD)"
    else:
        field_entries = b"/FT /Ch /T (color) /V (Red) /Opt [(Red) (Green)]"
    appearance = (
        b"/AP 9 0 R"
        if appearance_kind == "indirect"
        else b"/AP << /N 8 0 R /R 8 0 R >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 10 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [6 0 R] >>"
        ),
        _stream(b""),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        (
            b"<< /Type /Annot /Subtype /Widget "
            + field_entries
            + b" /Rect [72 700 300 730] /P 3 0 R /DA (/Helv 12 Tf 0 g) "
            + appearance
            + b" >>"
        ),
        b"<< >>",
        _appearance_stream(b"OLD"),
        b"<< /N 8 0 R /R 8 0 R >>",
        (
            b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> "
            b"/DA (/Helv 12 Tf 0 g) /NeedAppearances false >>"
        ),
    ]
    return _write_pdf(path, objects)


def _checkbox_form(path: Path) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 10 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << >> /Contents 4 0 R /Annots [6 0 R] >>"
        ),
        _stream(b""),
        b"<< >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) "
            b"/V /Off /AS /Off /Rect [72 700 92 720] /P 3 0 R /AP 9 0 R >>"
        ),
        b"<< >>",
        _appearance_stream(b"CHECK"),
        b"<< /N 11 0 R >>",
        b"<< /Fields [6 0 R] /NeedAppearances false >>",
        b"<< /Off 8 0 R /Yes 8 0 R >>",
    ])


def _appearance_stream(text: bytes) -> bytes:
    return _stream(b"BT /Helv 12 Tf 2 8 Td (" + text + b") Tj ET")


def _stream(content: bytes) -> bytes:
    return (
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 228 30] /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )


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
