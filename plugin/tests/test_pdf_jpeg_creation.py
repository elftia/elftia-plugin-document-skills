"""Public JPEG creation semantics and candidate tamper regressions."""

import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
import zlib

from PIL import Image, ImageOps
from pypdf import PdfReader
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.image_assets import load_image_asset
from document_skills_core.formats.pdf.jpeg_assets import inspect_jpeg
from document_skills_core.formats.pdf.validation import validate_created
from tests.test_pdf_operations import _minimal_text_document


def test_oriented_grayscale_jpeg_transcodes_to_bounded_flate_gray(
    tmp_path: Path,
) -> None:
    image = tmp_path / "oriented-gray.jpg"
    payload = BytesIO()
    source = Image.new("L", (4, 2))
    source.putdata(range(8))
    exif = Image.Exif()
    exif[274] = 6
    source.save(payload, format="JPEG", quality=100, subsampling=0, exif=exif)
    image.write_bytes(payload.getvalue())

    asset = load_image_asset({
        "filename": str(image),
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "content_type": "image/jpeg",
    })

    with Image.open(image) as reopened:
        expected = ImageOps.exif_transpose(reopened).convert("L").tobytes()
    assert (asset.width, asset.height) == (2, 4)
    assert asset.color_space == "/DeviceGray"
    assert asset.filter_name == "/FlateDecode"
    assert asset.decode is None
    assert asset.decode_parms is None
    assert asset.transcoded is True
    assert zlib.decompress(asset.image_data) == expected


@pytest.mark.parametrize("orientation", range(2, 9))
def test_all_rgb_exif_orientations_match_pillow_transpose(
    tmp_path: Path,
    orientation: int,
) -> None:
    image = tmp_path / f"oriented-rgb-{orientation}.jpg"
    image.write_bytes(_oriented_jpeg("RGB", orientation))

    asset = _load_jpeg_asset(image)
    with Image.open(image) as source:
        expected = ImageOps.exif_transpose(source).convert("RGB")
        expected_size = expected.size
        expected_pixels = expected.tobytes()

    assert (asset.width, asset.height) == expected_size
    assert asset.color_space == "/DeviceRGB"
    assert asset.filter_name == "/FlateDecode"
    assert asset.transcoded is True
    assert zlib.decompress(asset.image_data) == expected_pixels


def test_oriented_cmyk_jpeg_transcodes_to_rgb_flate(tmp_path: Path) -> None:
    image = tmp_path / "oriented-cmyk-6.jpg"
    image.write_bytes(_oriented_jpeg("CMYK", 6))

    asset = _load_jpeg_asset(image)
    with Image.open(image) as source:
        expected = ImageOps.exif_transpose(source).convert("RGB")
        expected_size = expected.size
        expected_pixels = expected.tobytes()

    assert expected_size == (3, 4)
    assert (asset.width, asset.height) == expected_size
    assert asset.color_space == "/DeviceRGB"
    assert asset.filter_name == "/FlateDecode"
    assert asset.decode is None
    assert asset.decode_parms is None
    assert asset.transcoded is True
    assert zlib.decompress(asset.image_data) == expected_pixels


def test_oriented_jpeg_with_corrupt_entropy_fails_closed(tmp_path: Path) -> None:
    image = tmp_path / "oriented-corrupt.jpg"
    image.write_bytes(_corrupt_jpeg_entropy(_oriented_jpeg("RGB", 6)))
    metadata = inspect_jpeg(image.read_bytes())
    assert (metadata.width, metadata.height, metadata.orientation) == (4, 3, 6)

    with pytest.raises(DocumentSkillsError, match="JPEG pixel decoding failed") as caught:
        _load_jpeg_asset(image)

    assert caught.value.code == ErrorCode.REQUEST_INVALID
    assert caught.value.status == "invalid_request"
    assert caught.value.details["reason"] == "JpegParseError"


def test_public_create_normalizes_exif_orientation_then_reads_and_validates(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = project_root / "tests/fixtures/pdf-completion/exif-orientation-6.jpg"
    output = tmp_path / "oriented.pdf"
    document = _image_document(image)

    created = _public_create(project_root, tmp_path, output, document)

    creation = created["diagnostics"]["operation_result"]["creation"]
    image_result = creation["images"][0]
    source_bytes = image.read_bytes()
    assert image_result["asset_bytes"] == len(source_bytes)
    assert image_result["asset_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert image_result["source_width"] == 32
    assert image_result["source_height"] == 48
    assert image_result["transcoded"] is True
    gate = next(
        item
        for item in created["validation"]["gates"]
        if item["id"] == "operation.create-semantics"
    )
    assert gate["outcome"] == "pass"
    xobject = PdfReader(output).pages[0]["/Resources"]["/XObject"]["/Im1"].get_object()
    assert xobject["/Width"] == 32
    assert xobject["/Height"] == 48
    assert str(xobject["/ColorSpace"]) == "/DeviceRGB"
    assert str(xobject["/Filter"]) == "/FlateDecode"
    assert "/Decode" not in xobject
    assert "/DecodeParms" not in xobject
    with Image.open(image) as source:
        expected = ImageOps.exif_transpose(source).convert("RGB").tobytes()
    assert xobject.get_data() == expected

    read = _public_read(project_root, tmp_path, output, "read-oriented.json")
    assert read["status"] == "success", read
    assert read["diagnostics"]["operation_result"]["images_by_page"] == [
        [
            {
                "bits_per_component": 8,
                "color_space": "/DeviceRGB",
                "filter_chain": ["/FlateDecode"],
                "height": 48,
                "name": "/Im1",
                "width": 32,
            }
        ]
    ]
    assert _public_validate(project_root, output)["status"] == "pass"


def test_public_create_preserves_adobe_cmyk_with_closed_decode_semantics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "adobe-cmyk.jpg"
    image.write_bytes(_adobe_cmyk_jpeg())
    assert b"Adobe" in image.read_bytes()
    output = tmp_path / "adobe-cmyk.pdf"

    created = _public_create(
        project_root,
        tmp_path,
        output,
        _image_document(image),
    )

    assert created["status"] == "success", created
    image_result = created["diagnostics"]["operation_result"]["creation"]["images"][0]
    source_bytes = image.read_bytes()
    assert image_result["asset_bytes"] == len(source_bytes)
    assert image_result["asset_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert image_result["transcoded"] is False
    xobject = PdfReader(output).pages[0]["/Resources"]["/XObject"]["/Im1"].get_object()
    assert xobject["/Width"] == 3
    assert xobject["/Height"] == 2
    assert str(xobject["/ColorSpace"]) == "/DeviceCMYK"
    assert str(xobject["/Filter"]) == "/DCTDecode"
    assert [int(value) for value in xobject["/Decode"]] == [1, 0, 1, 0, 1, 0, 1, 0]
    assert "/DecodeParms" not in xobject

    read = _public_read(project_root, tmp_path, output, "read-cmyk.json")
    assert read["status"] == "success", read
    assert read["diagnostics"]["operation_result"]["images_by_page"] == [
        [
            {
                "bits_per_component": 8,
                "color_space": "/DeviceCMYK",
                "filter_chain": ["/DCTDecode"],
                "height": 2,
                "name": "/Im1",
                "width": 3,
            }
        ]
    ]
    assert _public_validate(project_root, output)["status"] == "pass"


@pytest.mark.parametrize("tamper", ["decode", "decode_parms", "filter"])
def test_create_gate_rejects_adobe_cmyk_dictionary_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    image = tmp_path / "tamper-cmyk.jpg"
    image.write_bytes(_adobe_cmyk_jpeg())
    document = _image_document(image)
    candidate = tmp_path / f"tamper-{tamper}.pdf"
    creation = create_pdf(candidate, document)
    raw = candidate.read_bytes()
    if tamper == "decode":
        source = b"/Decode [1 0 1 0 1 0 1 0]"
        replacement = b"/Decode [1 0 1 0 1 0 1 1]"
    elif tamper == "decode_parms":
        _inject_decode_parms(candidate, creation["images"][0]["image_object"])
        source = replacement = None
    else:
        source = b"/Filter /DCTDecode /Length"
        replacement = b"/Filter[/DCTDecode]/Length"
    if source is not None and replacement is not None:
        assert len(source) == len(replacement)
        assert source in raw
        candidate.write_bytes(raw.replace(source, replacement, 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)

    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    gate = next(
        item
        for item in caught.value.validation["gates"]
        if item["id"] == "operation.create-semantics"
    )
    assert gate["evidence"]["image_mismatches"] == [
        {
            "reason": "image-object-mismatch",
            "object": creation["images"][0]["image_object"],
        }
    ]


def _inject_decode_parms(candidate: Path, object_number: int) -> None:
    """Inject DecodeParms while keeping the classical xref table valid."""
    raw = candidate.read_bytes()
    object_marker = f"{object_number} 0 obj\n".encode("ascii")
    object_start = raw.index(object_marker)
    stream_start = raw.index(b"\nstream\n", object_start)
    dictionary_end = raw.rfind(b">>", object_start, stream_start)
    old_xref = int(re.search(rb"startxref\s+([0-9]+)", raw).group(1))
    assert dictionary_end > object_start
    assert raw[old_xref : old_xref + 5] == b"xref\n"

    addition = b" /DecodeParms << /ColorTransform 1 >>"
    delta = len(addition)
    tail = raw[old_xref:]

    def shifted_entry(match: re.Match[bytes]) -> bytes:
        offset = int(match.group(1))
        if offset >= dictionary_end:
            offset += delta
        return f"{offset:010d}".encode("ascii") + match.group(2)

    tail = re.sub(
        rb"(?m)^([0-9]{10})( [0-9]{5} [nf]\r?)$",
        shifted_entry,
        tail,
    )
    old_startxref = f"startxref\n{old_xref}\n".encode("ascii")
    new_startxref = f"startxref\n{old_xref + delta}\n".encode("ascii")
    assert old_startxref in tail
    tail = tail.replace(old_startxref, new_startxref, 1)
    candidate.write_bytes(
        raw[:dictionary_end] + addition + raw[dictionary_end:old_xref] + tail
    )


def _image_document(image: Path) -> dict[str, object]:
    document = _minimal_text_document("JPEG semantics")
    document["pages"][0]["blocks"].append(
        {
            "type": "image",
            "text": None,
            "style": None,
            "table": None,
            "image": {
                "filename": str(image),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "content_type": "image/jpeg",
                "fit": "contain",
                "width": 80.0,
                "height": 80.0,
                "alt": "JPEG semantics",
            },
            "shape": None,
        }
    )
    return document


def _load_jpeg_asset(image: Path):
    return load_image_asset({
        "filename": str(image),
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "content_type": "image/jpeg",
    })


def _oriented_jpeg(mode: str, orientation: int) -> bytes:
    source = Image.new(mode, (4, 3))
    channels = 4 if mode == "CMYK" else 3
    source.putdata([
        tuple((index * 37 + channel * 53) % 256 for channel in range(channels))
        for index in range(12)
    ])
    exif = Image.Exif()
    exif[274] = orientation
    payload = BytesIO()
    source.save(payload, format="JPEG", quality=100, subsampling=0, exif=exif)
    return payload.getvalue()


def _corrupt_jpeg_entropy(raw: bytes) -> bytes:
    scan = raw.index(b"\xff\xda")
    scan_header_length = int.from_bytes(raw[scan + 2 : scan + 4], "big")
    entropy = scan + 2 + scan_header_length
    return raw[:entropy] + b"\xff\xc0\x00\x02\xff\xd9"


def _adobe_cmyk_jpeg() -> bytes:
    payload = BytesIO()
    image = Image.new("CMYK", (3, 2), (10, 40, 90, 15))
    image.save(
        payload,
        format="JPEG",
        quality=90,
        subsampling=0,
        optimize=False,
        progressive=False,
    )
    return payload.getvalue()


def _public_create(
    project_root: Path,
    tmp_path: Path,
    output: Path,
    document: dict[str, object],
) -> dict[str, object]:
    request = _request(
        tmp_path,
        f"create-{output.stem}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    return result


def _public_read(
    project_root: Path,
    tmp_path: Path,
    source: Path,
    name: str,
) -> dict[str, object]:
    request = _request(
        tmp_path,
        name,
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(source),
            "arguments": {},
        },
    )
    return _public(project_root, "run", "--request", str(request))


def _public_validate(project_root: Path, source: Path) -> dict[str, object]:
    return _public(
        project_root,
        "validate",
        "--input",
        str(source),
        "--json",
    )


def _request(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pdf/scripts/run.py"),
            *arguments,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    if check:
        diagnostic = process.stdout.decode("utf-8", errors="replace")
        assert process.returncode == 0, diagnostic or "public stdout was empty"
        assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    payload, end = json.JSONDecoder().raw_decode(text)
    assert text[end:].strip() == ""
    assert isinstance(payload, dict)
    return payload
