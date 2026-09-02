"""Public transaction and reopen limits for PDF image extraction."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
import zipfile

from PIL import Image
import pytest

from document_skills_core.formats.pdf import images_extract
from document_skills_core.formats.pdf.image_extraction_archive import (
    validate_image_archive,
)
from document_skills_core.formats.pdf.service import PdfService


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
    source: Path,
    output: Path,
    name: str,
    *,
    arguments: dict[str, object] | None = None,
) -> Path:
    request = tmp_path / name
    request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": arguments or {},
        }),
        encoding="utf-8",
        newline="\n",
    )
    return request


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


def _stream(dictionary: bytes, content: bytes) -> bytes:
    return (
        dictionary
        + b" /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )


def _image_pdf(
    path: Path,
    images: list[tuple[int, int, bytes, bytes]],
) -> Path:
    resources = b" ".join(
        f"/Im{index} {index + 4} 0 R".encode("ascii")
        for index in range(1, len(images) + 1)
    )
    content = b" ".join(
        f"/Im{index} Do".encode("ascii")
        for index in range(1, len(images) + 1)
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << /XObject << "
            + resources
            + b" >> >> /Contents 4 0 R >>"
        ),
        _stream(b"<<", content),
    ]
    for width, height, dictionary_suffix, payload in images:
        objects.append(_stream(
            (
                b"<< /Type /XObject /Subtype /Image /Width "
                + str(width).encode("ascii")
                + b" /Height "
                + str(height).encode("ascii")
                + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                + dictionary_suffix
            ),
            payload,
        ))
    return _write_pdf(path, objects)


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


def _assert_failed_atomically(
    result: dict[str, object],
    source: Path,
    source_before: bytes,
    output: Path,
    output_before: bytes,
) -> None:
    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert result["artifacts"] == []
    assert source.read_bytes() == source_before
    assert output.read_bytes() == output_before


def test_public_images_extract_rejects_fake_jpeg_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _image_pdf(
        tmp_path / "fake-jpeg.pdf",
        [(1, 1, b"/Filter /DCTDecode", b"\xff\xd8garbage\xff\xd9")],
    )
    output = tmp_path / "fake-jpeg.zip"
    source_before = source.read_bytes()
    output_before = b"existing destination"
    output.write_bytes(output_before)

    result = _public(
        project_root,
        _request(tmp_path, source, output, "fake-jpeg.json"),
    )

    _assert_failed_atomically(
        result,
        source,
        source_before,
        output,
        output_before,
    )


def test_public_images_extract_accepts_verified_jpeg(
    project_root: Path,
    tmp_path: Path,
) -> None:
    buffer = BytesIO()
    Image.new("RGB", (2, 1), (12, 34, 56)).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()
    source = _image_pdf(
        tmp_path / "real-jpeg.pdf",
        [(2, 1, b"/Filter /DCTDecode", jpeg)],
    )
    source_before = source.read_bytes()
    output = tmp_path / "real-jpeg.zip"

    result = _public(
        project_root,
        _request(tmp_path, source, output, "real-jpeg.json"),
    )

    assert result["status"] == "success", result
    assert source.read_bytes() == source_before
    record = result["diagnostics"]["operation_result"]["images"][0]
    assert record["format"] == "jpeg"
    with zipfile.ZipFile(output) as archive:
        extracted = archive.read(record["archive_path"])
    assert extracted == jpeg
    with Image.open(BytesIO(extracted)) as image:
        assert image.format == "JPEG"
        assert image.size == (2, 1)


def test_public_images_extract_enforces_max_images_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _image_pdf(
        tmp_path / "too-many-images.pdf",
        [
            (1, 1, b"", bytes([255, 0, 0])),
            (1, 1, b"", bytes([0, 255, 0])),
        ],
    )
    output = tmp_path / "too-many-images.zip"
    source_before = source.read_bytes()
    output_before = b"existing destination"
    output.write_bytes(output_before)

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            "too-many-images.json",
            arguments={"max_images": 1},
        ),
    )

    _assert_failed_atomically(
        result,
        source,
        source_before,
        output,
        output_before,
    )


def test_public_images_extract_enforces_max_total_bytes_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _image_pdf(
        tmp_path / "too-many-bytes.pdf",
        [(1, 1, b"", bytes([255, 0, 0]))],
    )
    output = tmp_path / "too-many-bytes.zip"
    source_before = source.read_bytes()
    output_before = b"existing destination"
    output.write_bytes(output_before)

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            "too-many-bytes.json",
            arguments={"max_total_bytes": 1},
        ),
    )

    _assert_failed_atomically(
        result,
        source,
        source_before,
        output,
        output_before,
    )


def test_service_images_extract_enforces_aggregate_pixels_atomically(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image_pdf(
        tmp_path / "too-many-pixels.pdf",
        [(2, 1, b"", bytes([255, 0, 0, 0, 255, 0]))],
    )
    output = tmp_path / "too-many-pixels.zip"
    source_before = source.read_bytes()
    output_before = b"existing destination"
    output.write_bytes(output_before)
    monkeypatch.setattr(images_extract, "_MAX_TOTAL_IMAGE_PIXELS", 1)

    result = PdfService(project_root).execute(
        "pdf.images.extract",
        {
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": {},
        },
    )

    _assert_failed_atomically(
        result,
        source,
        source_before,
        output,
        output_before,
    )


def test_public_inline_parser_checks_count_before_decoding_next_image(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _inline_image_pdf(
        tmp_path / "inline-count-budget.pdf",
        (
            b"BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI\n"
            b"BI /W 1 /H 1 /CS /RGB /BPC 8 /F /Fl ID not-zlib EI"
        ),
    )
    output = tmp_path / "inline-count-budget.zip"
    source_before = source.read_bytes()
    output_before = b"existing destination"
    output.write_bytes(output_before)

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            "inline-count-budget.json",
            arguments={"max_images": 1},
        ),
    )

    _assert_failed_atomically(
        result,
        source,
        source_before,
        output,
        output_before,
    )
    assert "count exceeds" in result["errors"][0]["message"]


def test_public_xobject_walker_checks_count_before_decoding_next_image(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _image_pdf(
        tmp_path / "xobject-count-budget.pdf",
        [
            (1, 1, b"", bytes([255, 0, 0])),
            (1, 1, b"/Filter /DCTDecode", b"\xff\xd8garbage\xff\xd9"),
        ],
    )
    output = tmp_path / "xobject-count-budget.zip"
    source_before = source.read_bytes()
    output_before = b"existing destination"
    output.write_bytes(output_before)

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            "xobject-count-budget.json",
            arguments={"max_images": 1},
        ),
    )

    _assert_failed_atomically(
        result,
        source,
        source_before,
        output,
        output_before,
    )
    assert "count exceeds" in result["errors"][0]["message"]


def test_archive_reopen_rejects_manifest_dimension_mismatch(tmp_path: Path) -> None:
    buffer = BytesIO()
    Image.new("RGB", (2, 1), (12, 34, 56)).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()
    archive_path = tmp_path / "dimension-mismatch.zip"
    entry = "page-0001-image-0001-object-00000005.jpg"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry, jpeg)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"preserved source")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    operation_result = {
        "image_count": 1,
        "total_image_bytes": len(jpeg),
        "total_image_pixels": 3,
        "images": [{
            "archive_path": entry,
            "format": "jpeg",
            "width": 3,
            "height": 1,
            "bytes": len(jpeg),
            "sha256": hashlib.sha256(jpeg).hexdigest(),
        }],
    }

    validation = validate_image_archive(
        archive_path,
        operation_result,
        source=source,
        source_sha256=source_sha256,
    )

    assert validation["status"] == "fail"
    reopen = next(
        gate for gate in validation["gates"]
        if gate["id"] == "archive.zip-reopen"
    )
    assert reopen["outcome"] == "fail"
