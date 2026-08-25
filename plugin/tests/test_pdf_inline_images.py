"""Public extraction coverage for bounded PDF inline images."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import zipfile
import zlib

from PIL import Image
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
        timeout=60,
    )
    assert process.stderr == b""
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _request(
    tmp_path: Path,
    output: Path,
    source: Path,
    name: str,
    *,
    pages: list[int] | None = None,
) -> Path:
    request = tmp_path / name
    request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.images.extract",
            "input": str(source),
            "output": str(output),
            "arguments": {} if pages is None else {"pages": pages},
        }),
        encoding="utf-8",
        newline="\n",
    )
    return request


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


def _stream(dictionary: bytes, content: bytes) -> bytes:
    return (
        dictionary
        + b" /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )


def _repeated_form_inline_pdf(path: Path, second_x: int) -> Path:
    inline = b"BI /W 1 /H 1 /CS /G /BPC 8 /D [1 0] ID \x00 EI"
    draws = (
        b"q 1 0 0 1 10 10 cm /Fm1 Do Q "
        + f"q 1 0 0 1 {second_x} 10 cm /Fm1 Do Q".encode("ascii")
    )
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


def test_public_images_extract_decodes_unfiltered_inline_rgb(
    project_root: Path,
    tmp_path: Path,
) -> None:
    samples = bytes([255, 0, 0, 0, 255, 0])
    content = (
        b"q 2 0 0 1 10 10 cm\n"
        b"BI /W 2 /H 1 /CS /RGB /BPC 8 ID "
        + samples
        + b" EI\nQ"
    )
    source = _inline_image_pdf(tmp_path / "inline-rgb.pdf", content)
    output = tmp_path / "inline-rgb.zip"

    result = _public(
        project_root,
        _request(tmp_path, output, source, "inline-rgb.json"),
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["image_count"] == 1
    record = operation_result["images"][0]
    assert record["source"] == "inline"
    assert record["object"] is None
    assert record["resource"] is None
    assert record["bbox"] == [10.0, 10.0, 12.0, 11.0]
    assert record["color_space"] == "/DeviceRGB"
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.mode == "RGB"
        assert [image.getpixel((x, 0)) for x in range(2)] == [
            (255, 0, 0),
            (0, 255, 0),
        ]


def test_public_images_extract_decodes_flate_inline_rgb(
    project_root: Path,
    tmp_path: Path,
) -> None:
    samples = bytes([255, 0, 0, 0, 255, 0])
    compressed = zlib.compress(samples, level=9)
    content = (
        b"q 2 0 0 1 10 10 cm\n"
        b"BI /W 2 /H 1 /CS /RGB /BPC 8 /F /Fl ID "
        + compressed
        + b" EI\nQ"
    )
    source = _inline_image_pdf(tmp_path / "inline-flate.pdf", content)
    output = tmp_path / "inline-flate.zip"

    result = _public(
        project_root,
        _request(tmp_path, output, source, "inline-flate.json"),
    )

    assert result["status"] == "success", result
    record = result["diagnostics"]["operation_result"]["images"][0]
    assert record["filter_chain"] == ["/FlateDecode"]
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert [image.convert("RGB").getpixel((x, 0)) for x in range(2)] == [
            (255, 0, 0),
            (0, 255, 0),
        ]


def test_public_images_extract_applies_inverted_inline_gray_decode(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"BI /W 1 /H 1 /CS /G /BPC 8 /D [1 0] ID \x00 EI"
    source = _inline_image_pdf(tmp_path / "inline-decode-gray.pdf", content)
    output = tmp_path / "inline-decode-gray.zip"

    result = _public(
        project_root,
        _request(tmp_path, output, source, "inline-decode-gray.json"),
    )

    assert result["status"] == "success", result
    record = result["diagnostics"]["operation_result"]["images"][0]
    assert record["decode"] == [1.0, 0.0]
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("L").getpixel((0, 0)) == 255


def test_public_images_extract_rejects_inline_decode_length_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"BI /W 1 /H 1 /CS /G /BPC 8 /D [1 0 1] ID \x00 EI"
    source = _inline_image_pdf(tmp_path / "inline-decode-length.pdf", content)
    output = tmp_path / "inline-decode-length.zip"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)

    result = _public(
        project_root,
        _request(tmp_path, output, source, "inline-decode-length.json"),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert result["errors"][0]["details"]["capability"] == (
        "pdf.inline-image-decode"
    )
    assert result["artifacts"] == []
    assert output.read_bytes() == destination_before


def test_public_images_extract_accepts_explicit_page_subset(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _two_page_inline_pdf(tmp_path / "subset-source.pdf")
    output = tmp_path / "subset.zip"

    result = _public(
        project_root,
        _request(
            tmp_path,
            output,
            source,
            "subset.json",
            pages=[1],
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["selected_pages"] == [1]
    assert operation["image_count"] == 1
    assert operation["images"][0]["page"] == 1


def test_public_images_extract_rebinds_nested_inline_resource_path(
    project_root: Path,
    tmp_path: Path,
) -> None:
    inline = b"BI /W 1 /H 1 /CS /G /BPC 8 /D [1 0] ID \x00 EI"
    source = _write_pdf(tmp_path / "nested-inline.pdf", [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << /XObject << /Fm1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        _stream(b"<<", b"/Fm1 Do"),
        _stream(
            b"<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] /Resources << >>",
            inline,
        ),
    ])
    output = tmp_path / "nested-inline.zip"

    result = _public(
        project_root,
        _request(tmp_path, output, source, "nested-inline.json"),
    )

    assert result["status"] == "success", result
    record = result["diagnostics"]["operation_result"]["images"][0]
    assert record["resource"] == "/Fm1"
    assert record["inline_index"] == 1
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("L").getpixel((0, 0)) == 255


@pytest.mark.parametrize("second_x", [10, 20])
def test_public_images_extract_rebinds_repeated_form_occurrences(
    project_root: Path,
    tmp_path: Path,
    second_x: int,
) -> None:
    source = _repeated_form_inline_pdf(
        tmp_path / f"repeated-form-{second_x}.pdf",
        second_x,
    )
    output = tmp_path / f"repeated-form-{second_x}.zip"

    result = _public(
        project_root,
        _request(tmp_path, output, source, f"repeated-form-{second_x}.json"),
    )

    assert result["status"] == "success", result
    records = result["diagnostics"]["operation_result"]["images"]
    assert [record["page_image_index"] for record in records] == [1, 2]
    assert [record["resource"] for record in records] == ["/Fm1", "/Fm1"]
    if second_x == 10:
        assert records[0]["bbox"] == records[1]["bbox"]
    else:
        assert records[0]["bbox"] != records[1]["bbox"]


def test_public_images_extract_rejects_unsupported_filtered_inline_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = (
        b"BI /W 1 /H 1 /CS /G /BPC 8 /F /LZWDecode ID ignored EI"
    )
    source = _inline_image_pdf(tmp_path / "inline-filtered.pdf", content)
    output = tmp_path / "inline-filtered.zip"
    destination_before = b"existing destination"
    output.write_bytes(destination_before)

    result = _public(
        project_root,
        _request(tmp_path, output, source, "inline-filtered.json"),
    )

    assert result["status"] == "enhancement_required", result
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert output.read_bytes() == destination_before
