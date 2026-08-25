"""Renumbering and normalized preservation regression tests."""

import hashlib
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf import edit as edit_module
from document_skills_core.formats.pdf.edit import _build_renumbered_pdf, edit_pdf
from document_skills_core.formats.pdf.object_model import (
    IndirectReference,
    PdfDict,
    parse_pdf,
)
from document_skills_core.formats.pdf.object_renumbering import renumber_payload
from document_skills_core.formats.pdf.validation import validate_mutation


def test_renumber_changes_only_real_references_and_rebuilds_page_parent() -> None:
    payload = (
        b"7 4 obj\n<< /Type /Page /Parent 99 8 R /Ref 2 9 R "
        b"/Literal (99 4 R and \\(3 7 R\\)) /Hex <393920342052> "
        b"% 99 4 R in comment\n/Other 3 7 R /Length 8 >>\n"
        b"stream\n99 4 R\nendstream\nendobj"
    )

    result = renumber_payload(
        payload,
        new_obj_num=70,
        mapping={2: 20, 3: 30, 7: 70},
        pages_obj_num=88,
        is_page=True,
    )

    assert result.startswith(b"70 0 obj")
    assert b"/Parent 88 0 R" in result
    assert b"/Ref 20 0 R" in result
    assert b"/Other 30 0 R" in result
    assert b"(99 4 R and \\(3 7 R\\))" in result
    assert b"<393920342052>" in result
    assert b"% 99 4 R in comment" in result
    assert b"stream\n99 4 R\nendstream" in result


def test_renumber_rejects_unmapped_indirect_reference() -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        renumber_payload(
            b"7 0 obj\n<< /Ref 99 4 R >>\nendobj",
            new_obj_num=70,
            mapping={7: 70},
        )

    assert captured.value.code is ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details == {"object": 99}


def test_renumbered_pdf_uses_generation_zero_for_objects_references_and_xref(
    tmp_path: Path,
) -> None:
    source = _write_pdf(
        tmp_path / "nonzero-generations.pdf",
        [
            (4, b"<< /Type /Catalog /Pages 2 7 R >>"),
            (7, b"<< /Type /Pages /Kids [3 9 R] /Count 1 >>"),
            (
                9,
                b"<< /Type /Page /Parent 2 7 R /MediaBox [0 0 200 300] "
                b"/Contents 4 2 R >>",
            ),
            (2, b"<< /Length 0 >>\nstream\n\nendstream"),
        ],
        root=(1, 4),
    )
    source_model = parse_pdf(source)
    output = tmp_path / "generation-zero.pdf"
    output.write_bytes(
        _build_renumbered_pdf(
            catalog_num=1,
            pages_num=2,
            page_refs=[3],
            per_input=[(source_model, {3: 3, 4: 4}, [3])],
            max_obj=4,
            info_ref=None,
        )
    )

    output_model = parse_pdf(output)
    assert all(obj.gen_num == 0 for obj in output_model.objects.values())
    assert all(
        entry.gen_num == 0
        for entry in output_model.xref_entries.values()
        if entry.in_use
    )
    assert output_model.trailer.root == IndirectReference(1, 0)
    page = output_model.objects[3].value
    assert isinstance(page, PdfDict)
    assert page.get("/Parent") == IndirectReference(2, 0)
    assert page.get("/Contents") == IndirectReference(4, 0)


def test_page_sequence_and_split_preservation_use_output_identity_space(
    tmp_path: Path,
) -> None:
    source = _two_page_pdf(tmp_path / "preservation-source.pdf")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    cases = [
        ("page-sequence", {"type": "page_sequence", "pages": [2, 1]}),
        ("split", {"type": "split", "page_ranges": [[2, 2]]}),
    ]
    for name, primitive in cases:
        output = tmp_path / f"{name}.pdf"
        _operation, manifest = edit_pdf(
            source,
            output,
            {"primitives": [primitive]},
        )

        assert manifest["changed_objects"] == []
        assert manifest["unexpected_mismatches"] == []
        assert manifest["input_hashes"] == manifest["expected_output_hashes"]
        assert set(manifest["input_hashes"]) == set(manifest["output_hashes"])
        report = validate_mutation(
            output,
            source=source,
            source_sha256=source_sha256,
            manifest=manifest,
        )
        assert report["status"] == "pass"


def test_page_graph_mismatch_is_not_self_authorized_as_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _two_page_pdf(tmp_path / "mismatch-source.pdf")
    donor = _two_page_pdf(tmp_path / "mismatch-donor.pdf")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    original_builder = edit_module._build_renumbered_pdf

    def corrupt_builder(*args: object, **kwargs: object) -> bytes:
        candidate = original_builder(*args, **kwargs)
        corrupted = candidate.replace(
            b"/MediaBox [0 0 200 300]",
            b"/MediaBox [0 0 201 300]",
            1,
        )
        assert corrupted != candidate
        return corrupted

    monkeypatch.setattr(edit_module, "_build_renumbered_pdf", corrupt_builder)
    donor_sha256 = hashlib.sha256(donor.read_bytes()).hexdigest()
    cases = [
        ("page-sequence", {"type": "page_sequence", "pages": [2, 1]}),
        ("split", {"type": "split", "page_ranges": [[2, 2]]}),
        (
            "merge",
            {
                "type": "merge",
                "inputs": [
                    {"input": str(source), "source_sha256": source_sha256},
                    {"input": str(donor), "source_sha256": donor_sha256},
                ],
            },
        ),
    ]
    for name, primitive in cases:
        output = tmp_path / f"mismatched-{name}.pdf"
        _operation, manifest = edit_pdf(
            source,
            output,
            {"primitives": [primitive]},
        )

        assert manifest["changed_objects"] == []
        assert manifest["unexpected_mismatches"]
        with pytest.raises(DocumentSkillsError) as captured:
            validate_mutation(
                output,
                source=source,
                source_sha256=source_sha256,
                manifest=manifest,
            )
        assert captured.value.code is ErrorCode.VALIDATION_FAILED


def _two_page_pdf(path: Path) -> Path:
    return _write_pdf(
        path,
        [
            (0, b"<< /Type /Catalog /Pages 2 0 R >>"),
            (0, b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>"),
            (
                0,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] "
                b"/Contents 5 0 R >>",
            ),
            (
                0,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] "
                b"/Contents 6 0 R >>",
            ),
            (0, b"<< /Length 0 >>\nstream\n\nendstream"),
            (0, b"<< /Length 0 >>\nstream\n\nendstream"),
        ],
        root=(1, 0),
    )


def _write_pdf(
    path: Path,
    objects: list[tuple[int, bytes]],
    *,
    root: tuple[int, int],
) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, (generation, payload) in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} {generation} obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset, (generation, _payload) in zip(offsets, objects, strict=True):
        xref.extend(f"{offset:010d} {generation:05d} n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} "
        f"/Root {root[0]} {root[1]} R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path
