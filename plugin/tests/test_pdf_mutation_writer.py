"""Generation and free-list coverage for the shared PDF mutation writer."""

from pathlib import Path

from pypdf import PdfReader

from document_skills_core.formats.pdf.mutation_writer import write_pdf_mutation
from document_skills_core.formats.pdf.object_model import parse_pdf


def test_mutation_writer_preserves_generations_and_links_removed_free_entries(
    tmp_path: Path,
) -> None:
    source = _nonzero_generation_pdf(tmp_path / "nonzero-generations.pdf")
    model = parse_pdf(source)
    output = tmp_path / "mutated.pdf"

    output.write_bytes(write_pdf_mutation(
        model,
        {},
        {6: b"6 0 obj\n<< /Note (new) >>\nendobj"},
        {5},
    ))

    raw = output.read_bytes()
    xref = raw[raw.index(b"xref\n") : raw.index(b"trailer\n")]
    assert b"0000000005 65535 f\r\n" in xref
    assert b"0000000000 00008 f\r\n" in xref
    for generation in (2, 3, 4, 5):
        assert f" {generation:05d} n\r\n".encode("ascii") in xref
    assert b" 00000 n\r\n" in xref
    assert len(PdfReader(output, strict=True).pages) == 1
    assert parse_pdf(output).catalog_ref.gen_num == 2


def _nonzero_generation_pdf(path: Path) -> Path:
    objects = [
        (1, 2, b"<< /Type /Catalog /Pages 2 3 R >>"),
        (2, 3, b"<< /Type /Pages /Kids [3 4 R] /Count 1 >>"),
        (
            3,
            4,
            b"<< /Type /Page /Parent 2 3 R /MediaBox [0 0 100 100] "
            b"/Resources << >> /Contents 4 5 R >>",
        ),
        (4, 5, b"<< /Length 0 >>\nstream\n\nendstream"),
        (5, 7, b"<< /Unused true >>"),
    ]
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for object_number, generation, payload in objects:
        offsets[object_number] = len(header) + len(body)
        body.extend(
            f"{object_number} {generation} obj\n".encode("ascii")
            + payload
            + b"\nendobj\n"
        )
    xref_offset = len(header) + len(body)
    xref = bytearray(b"xref\n0 6\n0000000000 65535 f\r\n")
    for object_number, generation, _payload in objects:
        xref.extend(
            f"{offsets[object_number]:010d} {generation:05d} n\r\n".encode(
                "ascii"
            )
        )
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 2 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    path.write_bytes(header + bytes(body) + bytes(xref) + trailer)
    return path
