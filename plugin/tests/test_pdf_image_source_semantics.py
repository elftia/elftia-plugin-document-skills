"""Archive regressions for fresh PDF image-source semantic replay."""

import hashlib
from io import BytesIO
from pathlib import Path
import zipfile

from PIL import Image

from document_skills_core.formats.pdf import images_extract
from document_skills_core.formats.pdf.image_extraction_archive import (
    validate_image_archive,
)


def _stream(dictionary: bytes, content: bytes) -> bytes:
    return (
        dictionary
        + b" /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )


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


def _inline_image_pdf(path: Path, content: bytes) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << >> /Contents 4 0 R >>"
        ),
        _stream(b"<<", content),
    ])


def _repeated_form_inline_pdf(path: Path) -> Path:
    inline = b"BI /W 1 /H 1 /CS /G /BPC 8 /D [1 0] ID \x00 EI"
    draws = b"q 1 0 0 1 10 10 cm /Fm1 Do Q q 1 0 0 1 20 10 cm /Fm1 Do Q"
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << /XObject << /Fm1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        _stream(b"<<", draws),
        _stream(
            b"<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] /Resources << >>",
            inline,
        ),
    ])


def _two_page_inline_pdf(path: Path) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << >> /Contents 5 0 R >>"
        ),
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << >> /Contents 6 0 R >>"
        ),
        _stream(b"<<", b"BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI"),
        _stream(b"<<", b"BI /W 1 /H 1 /CS /G /BPC 8 ID \xff EI"),
    ])


def _extract(source: Path, output: Path) -> dict[str, object]:
    return images_extract.extract_pdf_images(
        source,
        output,
        {"pages": None, "max_images": 4, "max_total_bytes": 100_000},
    )


def _gates(validation: dict[str, object]) -> dict[str, str]:
    return {
        gate["id"]: gate["outcome"]
        for gate in validation["gates"]
    }


def test_archive_rejects_self_consistent_inline_decode_pixel_tamper(
    tmp_path: Path,
) -> None:
    source = _repeated_form_inline_pdf(tmp_path / "inline-decode-source.pdf")
    original = tmp_path / "inline-decode-original.zip"
    operation = _extract(source, original)
    black_buffer = BytesIO()
    Image.new("L", (1, 1), 0).save(black_buffer, format="PNG")
    black = black_buffer.getvalue()
    with zipfile.ZipFile(original) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    record = operation["images"][1]
    record["bytes"] = len(black)
    record["sha256"] = hashlib.sha256(black).hexdigest()
    record["pixel_sha256"] = hashlib.sha256(b"\x00").hexdigest()
    payloads[record["archive_path"]] = black
    operation["total_image_bytes"] = sum(len(payload) for payload in payloads.values())
    tampered = tmp_path / "inline-decode-tampered.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(name, payloads[name])

    validation = validate_image_archive(
        tampered,
        operation,
        source=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    gates = _gates(validation)
    assert gates["archive.zip-reopen"] == "pass"
    assert gates["source.preservation"] == "fail"


def test_archive_rejects_duplicate_inline_source_identity_tamper(
    tmp_path: Path,
) -> None:
    content = (
        b"q 1 0 0 1 10 10 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI Q "
        b"q 1 0 0 1 20 10 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \xff EI Q"
    )
    source = _inline_image_pdf(tmp_path / "two-inline-source.pdf", content)
    original = tmp_path / "two-inline-original.zip"
    operation = _extract(source, original)
    with zipfile.ZipFile(original) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}

    first = operation["images"][0]
    second_path = operation["images"][1]["archive_path"]
    duplicate = dict(first)
    duplicate["archive_path"] = second_path
    operation["images"][1] = duplicate
    payloads[second_path] = payloads[first["archive_path"]]
    operation["total_image_bytes"] = sum(len(payload) for payload in payloads.values())
    operation["total_image_pixels"] = sum(
        item["width"] * item["height"] for item in operation["images"]
    )

    tampered = tmp_path / "two-inline-tampered.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(name, payloads[name])

    validation = validate_image_archive(
        tampered,
        operation,
        source=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    gates = _gates(validation)
    assert gates["artifact.exists-size"] == "pass"
    assert gates["archive.zip-reopen"] == "pass"
    assert gates["source.preservation"] == "fail"


def test_archive_rejects_self_consistent_selected_page_drop(
    tmp_path: Path,
) -> None:
    source = _two_page_inline_pdf(tmp_path / "two-page-source.pdf")
    original = tmp_path / "two-page-original.zip"
    operation = _extract(source, original)
    retained = operation["images"][0]
    with zipfile.ZipFile(original) as archive:
        retained_payload = archive.read(retained["archive_path"])

    operation["images"] = [retained]
    operation["image_count"] = 1
    operation["total_image_bytes"] = len(retained_payload)
    operation["total_image_pixels"] = retained["width"] * retained["height"]
    operation["selected_pages"] = [1]
    tampered = tmp_path / "two-page-tampered.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(retained["archive_path"], retained_payload)

    validation = validate_image_archive(
        tampered,
        operation,
        source=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        expected_pages=None,
    )

    gates = _gates(validation)
    assert gates["artifact.exists-size"] == "pass"
    assert gates["archive.zip-reopen"] == "pass"
    assert gates["source.preservation"] == "fail"
