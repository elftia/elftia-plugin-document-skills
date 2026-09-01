"""Public extraction coverage for images invoked from Form XObjects."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
import zipfile

from PIL import Image


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


def _request(tmp_path: Path, output: Path, source: Path, name: str) -> Path:
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


def test_public_images_extract_walks_form_xobject_resources_and_matrices(
    project_root: Path,
    tmp_path: Path,
) -> None:
    page_content = b"q 4 0 0 5 10 20 cm /Fm1 Do Q"
    form_content = b"q 2 0 0 3 1 2 cm /Im1 Do Q"
    source = _write_pdf(
        tmp_path / "form-image.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                b"/Resources << /XObject << /Fm1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            _stream(b"<<", page_content),
            _stream(
                (
                    b"<< /Type /XObject /Subtype /Form /BBox [0 0 20 20] "
                    b"/Matrix [1 0 0 1 5 7] "
                    b"/Resources << /XObject << /Im1 6 0 R >> >>"
                ),
                form_content,
            ),
            _stream(
                (
                    b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                    b"/ColorSpace /DeviceRGB /BitsPerComponent 8"
                ),
                bytes([255, 0, 0]),
            ),
        ],
    )
    output = tmp_path / "form-image.zip"

    result = _public(
        project_root,
        _request(tmp_path, output, source, "form-image.json"),
    )

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["image_count"] == 1
    record = operation_result["images"][0]
    assert record["object"] == 6
    assert record["resource"] == "/Fm1/Im1"
    assert record["bbox"] == [34.0, 65.0, 42.0, 80.0]
    with zipfile.ZipFile(output) as archive:
        payload = archive.read(record["archive_path"])
    with Image.open(BytesIO(payload)) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)


def test_public_images_extract_rejects_recursive_form_graph_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    page_content = b"/Fm1 Do"
    form_content = b"/Self Do"
    source = _write_pdf(
        tmp_path / "recursive-form.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
                b"/Resources << /XObject << /Fm1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            _stream(b"<<", page_content),
            _stream(
                (
                    b"<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] "
                    b"/Resources << /XObject << /Self 5 0 R >> >>"
                ),
                form_content,
            ),
        ],
    )
    output = tmp_path / "recursive-form.zip"
    before = b"existing destination"
    output.write_bytes(before)

    result = _public(
        project_root,
        _request(tmp_path, output, source, "recursive-form.json"),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert output.read_bytes() == before
