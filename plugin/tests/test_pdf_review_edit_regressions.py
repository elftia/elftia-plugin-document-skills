"""Public-boundary regressions for the round-one PDF edit findings."""

import json
from pathlib import Path
import subprocess

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pdf.mutation_plan import (
    authorize_step_manifest,
    declare_mutation_plan,
)
from document_skills_core.formats.pdf.object_model import PdfDict, parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages


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
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def _request(
    path: Path,
    operation: str,
    source: Path,
    output: Path,
    arguments: dict[str, object],
) -> Path:
    path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": operation,
            "input": str(source),
            "output": str(output),
            "arguments": arguments,
        }),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} 0 obj\n".encode("ascii"))
        body.extend(payload + b"\nendobj\n")
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


def _text_form(path: Path, value: bytes = b"()") -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 7 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R "
            b"/Annots [6 0 R] >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /V "
            + value
            + b" /Rect [72 700 300 730] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>"
        ),
        b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> >>",
    ])


def test_public_rotate_changes_only_top_level_page_dictionary(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_pdf(tmp_path / "rotate.pdf", [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >> >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
    ])
    output = tmp_path / "rotate-output.pdf"
    request = _request(
        tmp_path / "rotate.json",
        "pdf.edit",
        source,
        output,
        {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    model = parse_pdf(output)
    page = model.objects[walk_pages(model)[0].obj_num].value
    assert isinstance(page, PdfDict)
    assert page.get("/Rotate") == 90
    resources = page.get("/Resources")
    assert isinstance(resources, PdfDict)
    assert resources.get("/Rotate") is None
    fonts = resources.get("/Font")
    assert isinstance(fonts, PdfDict)
    font = fonts.get("/F1")
    assert isinstance(font, PdfDict)
    assert font.get("/Rotate") is None
    assert model.objects[3].payload_bytes.count(b"/Rotate") == 1


@pytest.mark.parametrize(
    "existing",
    [b"(A\\)B)", b"(A(B)C)", b"(A\\\\B)", b"(Existing)"],
    ids=["escaped-parenthesis", "nested-parentheses", "backslash", "non-empty"],
)
def test_public_form_fill_replaces_complete_existing_literal(
    project_root: Path,
    tmp_path: Path,
    existing: bytes,
) -> None:
    source = _text_form(tmp_path / "form.pdf", existing)
    output = tmp_path / "form-output.pdf"
    request = _request(
        tmp_path / "form.json",
        "pdf.edit",
        source,
        output,
        {"primitives": [{
            "type": "form_fill",
            "fields": {"name": "Alice"},
            "flatten": False,
        }]},
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    field = parse_pdf(output).objects[6].value
    assert isinstance(field, PdfDict)
    assert field.get("/V") == "Alice"
    payload = parse_pdf(output).objects[6].payload_bytes
    assert payload.count(b"/V (Alice)") == 1
    assert b"/V (Alice) /Rect" in payload


def test_public_image_extract_ignores_bi_in_non_operator_tokens(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = (
        b"BT (Power BI dashboard) Tj <42492064617461> Tj ET\n"
        b"% BI /W 1 /H 1 ID ignored EI\n"
    )
    source = _write_pdf(tmp_path / "text-bi.pdf", [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream",
    ])
    output = tmp_path / "images.zip"
    request = _request(
        tmp_path / "images.json",
        "pdf.images.extract",
        source,
        output,
        {},
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["image_count"] == 0


def test_form_fill_plan_rejects_unrelated_catalog_fault(tmp_path: Path) -> None:
    model = parse_pdf(_text_form(tmp_path / "plan.pdf"))
    primitive = {"type": "form_fill", "fields": {"name": "Alice"}, "flatten": False}
    plan = declare_mutation_plan(model, primitive)
    assert plan.changed == frozenset({6, 7})
    assert plan.added == frozenset({8})
    assert plan.removed == frozenset()
    input_hashes = model.object_hashes()
    output_hashes = dict(input_hashes)
    output_hashes[1] = "fault-injected-catalog-hash"
    manifest = {
        "changed_objects": [1],
        "added_objects": [],
        "removed_objects": [],
        "expected_output_hashes": {
            str(number): digest for number, digest in output_hashes.items()
        },
        "output_hashes": {
            str(number): digest for number, digest in output_hashes.items()
        },
    }

    with pytest.raises(DocumentSkillsError) as caught:
        authorize_step_manifest(plan, manifest, input_hashes, output_hashes)

    assert caught.value.details["unexpected_changed_objects"] == [1]
