"""PDF Image XObject `/Decode` semantics and archive binding."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
import zipfile
import zlib

from PIL import Image
import pytest

from document_skills_core.formats.pdf import images_extract
from document_skills_core.formats.pdf.image_extraction_archive import (
    validate_image_archive,
)


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
) -> Path:
    request = tmp_path / name
    request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": {},
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


def _decode_image_pdf(
    path: Path,
    *,
    decode: bytes = b"/Decode [1 0]",
    color_space: bytes = b"/DeviceGray",
    bits_per_component: int = 8,
    filter_entry: bytes = b"",
    samples: bytes = b"\x00",
    extra_objects: list[bytes] | None = None,
) -> Path:
    content = b"q 1 0 0 1 0 0 cm /Im1 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] "
            b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        _stream(b"<<", content),
        _stream(
            (
                b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                b"/ColorSpace "
                + color_space
                + b" /BitsPerComponent "
                + str(bits_per_component).encode("ascii")
                + b" "
                + filter_entry
                + b" "
                + decode
            ),
            samples,
        ),
    ]
    return _write_pdf(path, objects + (extra_objects or []))


def _gray_jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("L", (1, 1), 0).save(buffer, format="JPEG")
    return buffer.getvalue()


def _assert_public_error_atomically(
    project_root: Path,
    tmp_path: Path,
    source: Path,
    stem: str,
    *,
    status: str,
    code: str,
) -> dict[str, object]:
    output = tmp_path / f"{stem}.zip"
    before = b"existing destination"
    output.write_bytes(before)
    result = _public(
        project_root,
        _request(tmp_path, source, output, f"{stem}.json"),
    )
    assert result["status"] == status, result
    assert result["errors"][0]["code"] == code
    assert result["artifacts"] == []
    assert output.read_bytes() == before
    return result


def test_core_images_extract_applies_inverted_devicegray_decode(
    tmp_path: Path,
) -> None:
    source = _decode_image_pdf(tmp_path / "decode-gray-core.pdf")
    output = tmp_path / "decode-gray-core.zip"

    operation = images_extract.extract_pdf_images(
        source,
        output,
        {"pages": None, "max_images": 4, "max_total_bytes": 100_000},
    )

    record = operation["images"][0]
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("L").getpixel((0, 0)) == 255


def test_public_images_extract_applies_inverted_devicegray_decode(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _decode_image_pdf(tmp_path / "decode-gray-public.pdf")
    output = tmp_path / "decode-gray-public.zip"

    result = _public(
        project_root,
        _request(tmp_path, source, output, "decode-gray-public.json"),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    record = operation["images"][0]
    assert record["decode"] == [1.0, 0.0]
    assert len(record["source_object_sha256"]) == 64
    assert len(record["pixel_sha256"]) == 64
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("L").getpixel((0, 0)) == 255


def test_archive_reopen_rejects_self_consistent_decode_pixel_tamper(
    tmp_path: Path,
) -> None:
    source = _decode_image_pdf(tmp_path / "decode-gray-source.pdf")
    original = tmp_path / "decode-gray-original.zip"
    operation = images_extract.extract_pdf_images(
        source,
        original,
        {"pages": None, "max_images": 4, "max_total_bytes": 100_000},
    )
    black_buffer = BytesIO()
    Image.new("L", (1, 1), 0).save(black_buffer, format="PNG")
    black = black_buffer.getvalue()
    record = operation["images"][0]
    record["bytes"] = len(black)
    record["sha256"] = hashlib.sha256(black).hexdigest()
    operation["total_image_bytes"] = len(black)
    tampered = tmp_path / "decode-gray-tampered.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(record["archive_path"], black)

    validation = validate_image_archive(
        tampered,
        operation,
        source=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    reopen = next(
        gate for gate in validation["gates"]
        if gate["id"] == "archive.zip-reopen"
    )
    assert reopen["outcome"] == "fail"


@pytest.mark.parametrize(
    ("bits_per_component", "samples", "expected"),
    [
        (1, b"\x00", 255),
        (4, b"\x70", 136),
        (16, b"\x80\x00", 127),
    ],
)
def test_core_images_extract_normalizes_decode_by_bits_per_component(
    tmp_path: Path,
    bits_per_component: int,
    samples: bytes,
    expected: int,
) -> None:
    source = _decode_image_pdf(
        tmp_path / f"decode-gray-{bits_per_component}.pdf",
        decode=b"/Decode [1 0]",
        bits_per_component=bits_per_component,
        samples=samples,
    )
    output = tmp_path / f"decode-gray-{bits_per_component}.zip"

    operation = images_extract.extract_pdf_images(
        source,
        output,
        {"pages": None, "max_images": 4, "max_total_bytes": 100_000},
    )

    with zipfile.ZipFile(output) as archive:
        payload = archive.read(operation["images"][0]["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("L").getpixel((0, 0)) == expected


def test_core_images_extract_applies_device_rgb_component_decode(
    tmp_path: Path,
) -> None:
    source = _decode_image_pdf(
        tmp_path / "decode-rgb.pdf",
        decode=b"/Decode [1 0 0 1 1 0]",
        color_space=b"/DeviceRGB",
        samples=bytes([0, 127, 255]),
    )
    output = tmp_path / "decode-rgb.zip"

    operation = images_extract.extract_pdf_images(
        source,
        output,
        {"pages": None, "max_images": 4, "max_total_bytes": 100_000},
    )

    with zipfile.ZipFile(output) as archive:
        payload = archive.read(operation["images"][0]["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (255, 127, 0)


@pytest.mark.parametrize(
    ("fixture", "expected_status", "expected_code"),
    [
        ({"decode": b"/Decode [1 0 1]"}, "enhancement_required", "DS_ENHANCEMENT_REQUIRED"),
        ({"decode": b"/Decode [true 0]"}, "failed", "DS_ARCHIVE_UNSAFE"),
        (
            {
                "decode": b"/Decode [0 1 0 1 0 1 0 1]",
                "color_space": b"/DeviceCMYK",
                "samples": bytes([0, 0, 0, 0]),
            },
            "enhancement_required",
            "DS_ENHANCEMENT_REQUIRED",
        ),
        (
            {
                "filter_entry": b"/Filter /ASCIIHexDecode",
                "samples": b"00>",
            },
            "enhancement_required",
            "DS_ENHANCEMENT_REQUIRED",
        ),
    ],
)
def test_public_images_extract_rejects_unprovable_decode_atomically(
    project_root: Path,
    tmp_path: Path,
    fixture: dict[str, object],
    expected_status: str,
    expected_code: str,
) -> None:
    source = _decode_image_pdf(tmp_path / "decode-unsupported.pdf", **fixture)
    output = tmp_path / "decode-unsupported.zip"
    before = b"existing destination"
    output.write_bytes(before)

    result = _public(
        project_root,
        _request(tmp_path, source, output, "decode-unsupported.json"),
    )

    assert result["status"] == expected_status, result
    assert result["errors"][0]["code"] == expected_code
    assert result["artifacts"] == []
    assert output.read_bytes() == before


def test_public_images_extract_rejects_jpeg_precision_mismatch_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _decode_image_pdf(
        tmp_path / "decode-jpeg-16-bit.pdf",
        bits_per_component=16,
        filter_entry=b"/Filter /DCTDecode",
        samples=_gray_jpeg(),
    )
    _assert_public_error_atomically(
        project_root,
        tmp_path,
        source,
        "decode-jpeg-16-bit",
        status="failed",
        code="DS_ARCHIVE_UNSAFE",
    )


def test_public_images_extract_rejects_jpeg_component_mismatch_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _decode_image_pdf(
        tmp_path / "decode-jpeg-gray-as-rgb.pdf",
        decode=b"/Decode [1 0 0 1 1 0]",
        color_space=b"/DeviceRGB",
        filter_entry=b"/Filter /DCTDecode",
        samples=_gray_jpeg(),
    )
    _assert_public_error_atomically(
        project_root,
        tmp_path,
        source,
        "decode-jpeg-gray-as-rgb",
        status="failed",
        code="DS_ARCHIVE_UNSAFE",
    )


@pytest.mark.parametrize(
    ("filter_entry", "extra_objects"),
    [
        (b"/Filter /DCTDecode /DecodeParms << /ColorTransform 0 >>", None),
        (
            b"/Filter 6 0 R /DecodeParms 7 0 R",
            [b"/DCTDecode", b"<< /ColorTransform 0 >>"],
        ),
        (
            b"/Filter [/FlateDecode /DCTDecode] "
            b"/DecodeParms [null << /ColorTransform 0 >>]",
            None,
        ),
    ],
)
def test_public_images_extract_rejects_dct_decode_parameters_atomically(
    project_root: Path,
    tmp_path: Path,
    filter_entry: bytes,
    extra_objects: list[bytes] | None,
) -> None:
    samples = _gray_jpeg()
    if b"/FlateDecode" in filter_entry:
        samples = zlib.compress(samples)
    source = _decode_image_pdf(
        tmp_path / "decode-jpeg-parameters.pdf",
        filter_entry=filter_entry,
        samples=samples,
        extra_objects=extra_objects,
    )
    result = _assert_public_error_atomically(
        project_root,
        tmp_path,
        source,
        "decode-jpeg-parameters",
        status="enhancement_required",
        code="DS_ENHANCEMENT_REQUIRED",
    )
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.jpeg-decode-parameters"
    )
