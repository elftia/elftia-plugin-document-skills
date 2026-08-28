"""Measured evidence and semantic gates for pypdf compression."""

from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.providers.pypdf.compression_evidence import measure_compression
from document_skills_core.providers.pypdf.operations import compress_pdf
from document_skills_core.providers.pypdf.validation import validate_compressed
from tests.test_pdf_compression import _image_pdf, _photographic_png
from tests.test_pdf_public import (
    _compressible_pdf,
    _public,
    _request,
    _write_pdf_fixture,
)


def _compress_request(
    tmp_path: Path,
    source: Path,
    output: Path,
    *,
    mode: str = "lossless",
) -> Path:
    return _request(
        tmp_path,
        f"compress-{mode}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.compress",
            "input": str(source),
            "output": str(output),
            "arguments": {"mode": mode},
        },
    )


def _semantic_pdf(path: Path) -> Path:
    lines = [
        f"(Semantic compression line {index % 10}) Tj 0 -14 Td".encode("ascii")
        for index in range(500)
    ]
    content = (
        b"BT /F1 12 Tf 72 720 Td\n"
        + b"\n".join(lines)
        + b"\nET\nq 20 0 0 10 40 40 cm /Im1 Do Q"
    )
    stream = (
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream"
    )
    image = (
        b"<< /Type /XObject /Subtype /Image /Width 2 /Height 1 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 6 >>\nstream\n"
        + bytes([10, 20, 30, 40, 50, 60])
        + b"\nendstream"
    )
    _write_pdf_fixture(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/CropBox [10 20 600 780] /Rotate 90 "
            b"/Resources << /Font << /F1 5 0 R >> "
            b"/XObject << /Im1 6 0 R >> >> /Contents 4 0 R >>"
        ),
        stream,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        image,
        b"<< /Title (Semantic source) /Author (Elftia) >>",
    ])
    payload = path.read_bytes().replace(
        b"/Size 8 /Root 1 0 R >>",
        b"/Size 8 /Root 1 0 R /Info 7 0 R >>",
    )
    path.write_bytes(payload)
    return path


def _tamper_candidate(source: Path, target: Path, semantic: str) -> None:
    reader = PdfReader(source, strict=True)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    page = writer.pages[0]
    if semantic == "media_box":
        page.mediabox.upper_right = (610, 790)
    elif semantic == "crop_box":
        page.cropbox.lower_left = (12, 22)
    elif semantic == "rotation":
        page.rotation = 0
    elif semantic == "metadata":
        writer.add_metadata({"/Title": "Tampered metadata", "/Author": "Elftia"})
    elif semantic == "resources":
        del page["/Resources"]["/Font"]
    else:
        page.images[0].replace(Image.new("RGB", (2, 1), (200, 10, 10)))
    writer.write(target)


def _refresh_report(
    operation_result: dict[str, object],
    source: Path,
    candidate: Path,
) -> None:
    compression = operation_result["compression"]
    evidence = measure_compression(source, candidate)
    before = source.stat().st_size
    after = candidate.stat().st_size
    compression["before_bytes"] = before
    compression["after_bytes"] = after
    compression["bytes_saved"] = before - after
    compression["ratio"] = round(after / before, 6)
    compression["evidence"] = evidence
    compression["content_streams_recompressed"] = evidence["components"]["stream"][
        "content_changed_count"
    ]
    compression["duplicate_cleanup"] = (
        evidence["components"]["duplicate"]["after"]["count"]
        < evidence["components"]["duplicate"]["before"]["count"]
    )


def test_public_lossless_compression_reports_measured_components(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _compressible_pdf(tmp_path / "measured-source.pdf")
    output = tmp_path / "measured-output.pdf"

    result = _public(
        project_root,
        "run",
        "--request",
        str(_compress_request(tmp_path, source, output)),
        check=False,
    )

    assert result["status"] == "success", result
    compression = result["diagnostics"]["operation_result"]["compression"]
    assert compression["semantic_policy"]["allowed_changes"] == []
    assert set(compression["semantic_policy"]["preserved"]) == {
        "media_box",
        "crop_box",
        "rotation",
        "metadata",
        "resources",
        "image_identity",
    }
    evidence = compression["evidence"]
    assert evidence["source"] == "pypdf-reopen-object-measurement"
    assert evidence["before_file_bytes"] == source.stat().st_size
    assert evidence["after_file_bytes"] == output.stat().st_size
    components = evidence["components"]
    assert set(components) == {
        "object",
        "stream",
        "duplicate",
        "metadata",
        "image",
        "object_stream",
        "xref_stream",
    }
    for name in ("object", "stream", "duplicate", "metadata", "image"):
        component = components[name]
        assert component["status"] == "measured"
        assert set(component["before"]) == {"count", "bytes"}
        assert set(component["after"]) == {"count", "bytes"}
        assert all(
            type(component[side][field]) is int and component[side][field] >= 0
            for side in ("before", "after")
            for field in ("count", "bytes")
        )
        assert component["changed_object_ids"] == sorted(
            set(component["changed_object_ids"])
        )
    for name in ("object_stream", "xref_stream"):
        component = components[name]
        assert component["support"] == "unsupported"
        assert component["status"] == "not_attempted"
        assert set(component["before"]) == {"count", "bytes"}
        assert set(component["after"]) == {"count", "bytes"}
        assert component["changed_object_ids"] == []
    assert compression["content_streams_recompressed"] == components["stream"][
        "content_changed_count"
    ]
    assert compression["duplicate_cleanup"] == (
        components["duplicate"]["after"]["count"]
        < components["duplicate"]["before"]["count"]
    )


def test_compression_validation_rejects_false_measured_report(tmp_path: Path) -> None:
    source = _compressible_pdf(tmp_path / "false-report-source.pdf")
    candidate = tmp_path / "false-report-candidate.pdf"
    arguments = {"mode": "lossless"}
    operation_result = compress_pdf(source, candidate, arguments)
    stream_after = operation_result["compression"]["evidence"]["components"][
        "stream"
    ]["after"]
    stream_after["bytes"] += 1

    with pytest.raises(DocumentSkillsError) as captured:
        validate_compressed(source, candidate, arguments, operation_result)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert "evidence" in str(captured.value).casefold()


def test_compression_validation_rejects_false_legacy_claim(tmp_path: Path) -> None:
    source = _compressible_pdf(tmp_path / "false-claim-source.pdf")
    candidate = tmp_path / "false-claim-candidate.pdf"
    arguments = {"mode": "lossless"}
    operation_result = compress_pdf(source, candidate, arguments)
    operation_result["compression"]["content_streams_recompressed"] += 1

    with pytest.raises(DocumentSkillsError) as captured:
        validate_compressed(source, candidate, arguments, operation_result)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert "report" in str(captured.value).casefold()


def test_compression_validation_rejects_candidate_tampering(tmp_path: Path) -> None:
    source = _compressible_pdf(tmp_path / "tampered-source.pdf")
    candidate = tmp_path / "tampered-candidate.pdf"
    arguments = {"mode": "lossless"}
    operation_result = compress_pdf(source, candidate, arguments)
    candidate.write_bytes(
        candidate.read_bytes().replace(b"%%EOF", b"% tampered\n%%EOF")
    )

    with pytest.raises(DocumentSkillsError) as captured:
        validate_compressed(source, candidate, arguments, operation_result)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED


def test_lossless_validation_accepts_complete_semantic_projection(tmp_path: Path) -> None:
    source = _semantic_pdf(tmp_path / "semantic-positive-source.pdf")
    candidate = tmp_path / "semantic-positive-candidate.pdf"
    arguments = {"mode": "lossless"}
    operation_result = compress_pdf(source, candidate, arguments)

    validation = validate_compressed(source, candidate, arguments, operation_result)

    assert validation["status"] == "pass"


@pytest.mark.parametrize(
    "semantic",
    ["media_box", "crop_box", "rotation", "metadata", "resources", "image"],
)
def test_lossless_validation_rejects_self_consistent_semantic_drift(
    tmp_path: Path,
    semantic: str,
) -> None:
    source = _semantic_pdf(tmp_path / f"{semantic}-source.pdf")
    candidate = tmp_path / f"{semantic}-candidate.pdf"
    tampered = tmp_path / f"{semantic}-tampered.pdf"
    arguments = {"mode": "lossless"}
    operation_result = compress_pdf(source, candidate, arguments)
    _tamper_candidate(candidate, tampered, semantic)
    assert tampered.stat().st_size < source.stat().st_size
    _refresh_report(operation_result, source, tampered)

    with pytest.raises(DocumentSkillsError) as captured:
        validate_compressed(source, tampered, arguments, operation_result)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert "semantic" in str(captured.value).casefold()


def test_balanced_validation_rejects_false_visual_diff_report(tmp_path: Path) -> None:
    image = _photographic_png(tmp_path / "false-visual.png")
    source = _image_pdf(tmp_path / "false-visual-source.pdf", image)
    candidate = tmp_path / "false-visual-candidate.pdf"
    arguments = {"mode": "balanced"}
    operation_result = compress_pdf(source, candidate, arguments)
    allowed = operation_result["compression"]["semantic_policy"]["allowed_changes"]
    assert allowed == [{
        "component": "image-xobjects-only",
        "encoding": "jpeg-reencode",
        "maximum_dimension": 1_920,
        "minimum_psnr_db": 24.0,
    }]
    operation_result["visual_diff"]["images"][0]["psnr_db"] = 99.0

    with pytest.raises(DocumentSkillsError) as captured:
        validate_compressed(source, candidate, arguments, operation_result)

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert "visual" in str(captured.value).casefold()
