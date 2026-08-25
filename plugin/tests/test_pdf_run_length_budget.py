"""Fail-before-allocation regressions for PDF RunLengthDecode streams."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf import byte_preflight
from document_skills_core.formats.pdf import object_model
from document_skills_core.formats.pdf.byte_preflight import PdfByteLimits, decode_stream
from document_skills_core.formats.pdf.service import build_pdf_service


class _NoExtendBytearray(bytearray):
    def extend(self, value: object) -> None:
        raise AssertionError("RunLengthDecode allocated before enforcing its budget")


def test_repeat_run_is_rejected_before_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(byte_preflight, "bytearray", _NoExtendBytearray, raising=False)
    limits = PdfByteLimits(max_uncompressed_bytes=1, max_expansion_ratio=100.0)

    with pytest.raises(DocumentSkillsError) as captured:
        decode_stream(bytes([129, ord("A"), 128]), ["/RunLengthDecode"], limits)

    assert captured.value.code is ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details == {"uncompressed_bytes": 128, "limit": 1}


def test_literal_run_is_rejected_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(byte_preflight, "bytearray", _NoExtendBytearray, raising=False)
    limits = PdfByteLimits(max_uncompressed_bytes=1, max_expansion_ratio=100.0)

    with pytest.raises(DocumentSkillsError) as captured:
        decode_stream(bytes([1, ord("A"), ord("B"), 128]), ["RunLengthDecode"], limits)

    assert captured.value.code is ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details == {"uncompressed_bytes": 2, "limit": 1}


@pytest.mark.parametrize(
    ("encoded", "limits", "expected"),
    [
        (bytes([253, ord("A"), 128]), PdfByteLimits(max_uncompressed_bytes=4), b"AAAA"),
        (
            bytes([254, ord("B"), 128]),
            PdfByteLimits(max_uncompressed_bytes=100, max_expansion_ratio=1.0),
            b"BBB",
        ),
    ],
)
def test_run_length_exact_budget_boundary_is_accepted(
    encoded: bytes,
    limits: PdfByteLimits,
    expected: bytes,
) -> None:
    assert decode_stream(encoded, ["RunLengthDecode"], limits) == expected


@pytest.mark.parametrize(
    ("limits", "details"),
    [
        (PdfByteLimits(max_uncompressed_bytes=3, max_expansion_ratio=100.0), {"uncompressed_bytes": 4, "limit": 3}),
        (PdfByteLimits(max_uncompressed_bytes=100, max_expansion_ratio=1.0), {"ratio": 4 / 3, "limit": 1.0}),
    ],
)
def test_run_length_uses_the_tighter_absolute_or_ratio_budget(
    limits: PdfByteLimits,
    details: dict[str, float | int],
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        decode_stream(bytes([253, ord("A"), 128]), ["RunLengthDecode"], limits)

    assert captured.value.code is ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details == details


@pytest.mark.parametrize("encoded", [bytes([2, ord("A")]), bytes([129])])
def test_malformed_run_length_stream_remains_truncated(encoded: bytes) -> None:
    limits = PdfByteLimits(max_uncompressed_bytes=0, max_expansion_ratio=0.0)

    with pytest.raises(DocumentSkillsError) as captured:
        decode_stream(encoded, ["RunLengthDecode"], limits)

    assert captured.value.code is ErrorCode.ARCHIVE_UNSAFE
    assert str(captured.value) == "RunLengthDecode stream is truncated."


@pytest.mark.parametrize(
    ("encoded", "expected"),
    [
        (bytes([128, 129, ord("A")]), b""),
        (bytes([0, ord("A")]), b"A"),
    ],
)
def test_run_length_eod_behavior_remains_stable(encoded: bytes, expected: bytes) -> None:
    assert decode_stream(encoded, ["RunLengthDecode"]) == expected


def test_public_edit_parse_failure_does_not_promote_destination(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _run_length_pdf(tmp_path / "unsafe.pdf", bytes([129, ord("A"), 128]))
    source_bytes = source.read_bytes()
    destination = tmp_path / "existing.pdf"
    destination.write_bytes(b"existing-destination")
    limits = PdfByteLimits(max_uncompressed_bytes=1, max_expansion_ratio=100.0)
    monkeypatch.setattr(object_model, "PdfByteLimits", lambda: limits)
    execute = build_pdf_service(project_root)

    result = execute("pdf.edit", {
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": str(source),
        "output": str(destination),
        "arguments": {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
    })

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert result["artifacts"] == []
    assert destination.read_bytes() == b"existing-destination"
    assert source.read_bytes() == source_bytes
    assert list(tmp_path.glob(".*.primitive-*.pdf")) == []


def _run_length_pdf(path: Path, encoded: bytes) -> Path:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R >>",
        f"<< /Length {len(encoded)} /Filter /RunLengthDecode >>\nstream\n".encode("ascii")
        + encoded
        + b"\nendstream",
    ]
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f\r\n".encode("ascii"))
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path
