"""Bounded pixel-decode proof for directly embedded JPEG assets."""

from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.jpeg_assets import (
    inspect_jpeg,
    JpegParseError,
    JpegUnsupportedError,
)
from tests.test_pdf_jpeg_creation import (
    _image_document,
    _load_jpeg_asset,
    _oriented_jpeg,
    _public,
    _request,
)

_CMYK_DECODE = (1, 0, 1, 0, 1, 0, 1, 0)


@pytest.mark.parametrize(
    ("mode", "adobe_transform", "color_space", "decode", "progressive"),
    [
        ("L", None, "/DeviceGray", None, False),
        ("RGB", None, "/DeviceRGB", None, False),
        ("RGB", None, "/DeviceRGB", None, True),
        ("CMYK", 0, "/DeviceCMYK", _CMYK_DECODE, False),
        ("CMYK", 2, "/DeviceCMYK", _CMYK_DECODE, False),
    ],
)
def test_direct_jpeg_decode_proof_preserves_original_dct_bytes(
    tmp_path: Path,
    mode: str,
    adobe_transform: int | None,
    color_space: str,
    decode: tuple[int, ...] | None,
    progressive: bool,
) -> None:
    raw = _direct_jpeg(mode, progressive=progressive)
    if adobe_transform is not None:
        raw = _set_adobe_transform(raw, adobe_transform)
    image = tmp_path / f"direct-{mode}-{adobe_transform}.jpg"
    image.write_bytes(raw)

    asset = _load_jpeg_asset(image)

    assert inspect_jpeg(raw).adobe_transform == adobe_transform
    assert (asset.width, asset.height) == (4, 3)
    assert asset.color_space == color_space
    assert asset.filter_name == "/DCTDecode"
    assert asset.decode == decode
    assert asset.decode_parms is None
    assert asset.transcoded is False
    assert asset.image_data == raw
    assert (b"\xff\xc2" in raw) is progressive


@pytest.mark.parametrize(
    ("second_marker", "forge_first"),
    [(0xC0, True), (0xC2, False)],
    ids=["conflicting-sof0", "mixed-sof0-sof2"],
)
def test_inspect_rejects_duplicate_or_mixed_sof_frames(
    second_marker: int,
    forge_first: bool,
) -> None:
    raw = _duplicate_sof(
        _direct_jpeg("RGB"),
        second_marker=second_marker,
        forge_first=forge_first,
    )

    with pytest.raises(JpegParseError, match="duplicate or conflicting SOF"):
        inspect_jpeg(raw)


@pytest.mark.parametrize("unsupported_first", [True, False])
def test_inspect_rejects_unsupported_and_sof0_in_any_order(
    unsupported_first: bool,
) -> None:
    raw = _mixed_unsupported_sof(
        _direct_jpeg("RGB"),
        unsupported_first=unsupported_first,
    )

    with pytest.raises(JpegParseError, match="duplicate or conflicting SOF"):
        inspect_jpeg(raw)


def test_single_unsupported_sof_is_explicit_enhancement(tmp_path: Path) -> None:
    image = tmp_path / "unsupported-sof1.jpg"
    raw = _replace_sof_marker(_direct_jpeg("RGB"), 0xC1)
    image.write_bytes(raw)

    with pytest.raises(JpegUnsupportedError, match="requires enhancement"):
        inspect_jpeg(raw)

    with pytest.raises(DocumentSkillsError) as caught:
        _load_jpeg_asset(image)

    assert caught.value.code == ErrorCode.ENHANCEMENT_REQUIRED
    assert caught.value.status == "enhancement_required"
    assert caught.value.details["capability"] == "pdf.jpeg-variant"


def test_inspect_rejects_conflicting_exif_orientations() -> None:
    raw = _oriented_jpeg("RGB", 6)
    conflicting = _marker_segment(_oriented_jpeg("RGB", 3), 0xE1)
    app1 = raw.index(b"\xff\xe1")

    with pytest.raises(JpegParseError, match="EXIF orientations conflict"):
        inspect_jpeg(raw[:app1] + conflicting + raw[app1:])


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        ("corrupt-entropy", "JPEG pixel decoding failed"),
        ("duplicate-sof", "duplicate or conflicting SOF"),
    ],
)
def test_public_create_rejects_invalid_direct_jpeg_before_candidate(
    project_root: Path,
    tmp_path: Path,
    variant: str,
    message: str,
) -> None:
    raw = _direct_jpeg("RGB")
    raw = (
        _corrupt_entropy(raw)
        if variant == "corrupt-entropy"
        else _duplicate_sof(raw, second_marker=0xC0, forge_first=True)
    )
    image = tmp_path / f"{variant}.jpg"
    image.write_bytes(raw)
    output = tmp_path / f"{variant}.pdf"
    output.write_bytes(b"existing-destination")
    request = _request(
        tmp_path,
        f"{variant}.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": _image_document(image)},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request", result
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert message in result["errors"][0]["message"]
    assert result["errors"][0]["details"]["reason"] == "JpegParseError"
    assert result["artifacts"] == []
    assert output.read_bytes() == b"existing-destination"
    assert set(tmp_path.iterdir()) == {image, output, request}


def _direct_jpeg(mode: str, *, progressive: bool = False) -> bytes:
    image = Image.new(mode, (4, 3))
    channels = len(image.getbands())
    image.putdata([
        tuple((index * 37 + channel * 53) % 256 for channel in range(channels))
        if channels > 1
        else (index * 37) % 256
        for index in range(12)
    ])
    payload = BytesIO()
    image.save(
        payload,
        format="JPEG",
        quality=95,
        subsampling=0,
        progressive=progressive,
    )
    return payload.getvalue()


def _set_adobe_transform(raw: bytes, transform: int) -> bytes:
    updated = bytearray(raw)
    marker = updated.index(b"\xff\xee")
    assert updated[marker + 4 : marker + 9] == b"Adobe"
    updated[marker + 15] = transform
    return bytes(updated)


def _duplicate_sof(
    raw: bytes,
    *,
    second_marker: int,
    forge_first: bool,
) -> bytes:
    start = raw.index(b"\xff\xc0")
    length = int.from_bytes(raw[start + 2 : start + 4], "big")
    end = start + 2 + length
    original = raw[start:end]
    first = bytearray(original)
    if forge_first:
        first[5:9] = (50_000).to_bytes(2, "big") * 2
    second = bytes([0xFF, second_marker]) + original[2:]
    return raw[:start] + bytes(first) + second + raw[end:]


def _corrupt_entropy(raw: bytes) -> bytes:
    scan = raw.index(b"\xff\xda")
    scan_header_length = int.from_bytes(raw[scan + 2 : scan + 4], "big")
    entropy = scan + 2 + scan_header_length
    return raw[:entropy] + b"\xff\xc0\x00\x02\xff\xd9"


def _mixed_unsupported_sof(raw: bytes, *, unsupported_first: bool) -> bytes:
    original = _marker_segment(raw, 0xC0)
    unsupported = b"\xff\xc1" + original[2:]
    frames = unsupported + original if unsupported_first else original + unsupported
    start = raw.index(b"\xff\xc0")
    return raw[:start] + frames + raw[start + len(original) :]


def _replace_sof_marker(raw: bytes, marker: int) -> bytes:
    start = raw.index(b"\xff\xc0")
    return raw[: start + 1] + bytes([marker]) + raw[start + 2 :]


def _marker_segment(raw: bytes, marker: int) -> bytes:
    start = raw.index(bytes([0xFF, marker]))
    length = int.from_bytes(raw[start + 2 : start + 4], "big")
    return raw[start : start + 2 + length]
