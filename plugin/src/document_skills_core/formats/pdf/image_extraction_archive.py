"""PNG reconstruction plus deterministic extraction-archive validation.

Module provenance: original Elftia-authored clean-room implementation.
"""

import binascii
import hashlib
from io import BytesIO
from pathlib import Path
import struct
from typing import Any
import warnings
import zipfile
import zlib

from PIL import Image

from document_skills_core.core.io.paths import assert_source_preserved, file_record
from document_skills_core.core.validation.runner import ValidationRunner

from .extract_contracts import MAX_EXTRACTED_TOTAL_BYTES
from .image_assets import PNG_SIGNATURE
from .image_extraction_limits import MAX_TOTAL_IMAGE_PIXELS
from .object_model import PdfObjectModel, parse_pdf

_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def encode_png(
    width: int,
    height: int,
    color: bytes,
    color_channels: int,
    alpha: bytes | None,
) -> bytes:
    """Encode unfiltered 8-bit grayscale/RGB samples and optional alpha."""
    channels = color_channels + (1 if alpha is not None else 0)
    rows = bytearray()
    for row in range(height):
        rows.append(0)
        color_start = row * width * color_channels
        if alpha is None:
            rows.extend(color[color_start : color_start + width * color_channels])
            continue
        alpha_start = row * width
        for column in range(width):
            pixel = color_start + column * color_channels
            rows.extend(color[pixel : pixel + color_channels])
            rows.append(alpha[alpha_start + column])
    color_type = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )


def write_deterministic_image_zip(path: Path, payloads: dict[str, bytes]) -> None:
    """Write stable sorted entries with fixed timestamps and compression."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(payloads):
            info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, payloads[name], compresslevel=9)


def validate_image_archive(
    archive: Path,
    operation_result: dict[str, Any],
    *,
    source: Path,
    source_sha256: str,
    expected_pages: list[int] | None = None,
) -> dict[str, Any]:
    """Validate exact ZIP identity, deterministic entries, and source preservation."""
    runner = ValidationRunner()
    runner.run_gate("artifact.exists-size", lambda: _artifact_identity(archive))
    runner.run_gate(
        "archive.zip-reopen",
        lambda: _reopen_archive(archive, operation_result, source),
    )
    runner.run_gate(
        "source.preservation",
        lambda: _preserved_source(
            source,
            source_sha256,
            operation_result,
            expected_pages,
        ),
    )
    return runner.report()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _artifact_identity(path: Path) -> dict[str, Any]:
    record = file_record(path, "output")
    if record.bytes <= 0:
        raise ValueError("Image extraction archive is empty.")
    return {"sha256": record.sha256, "bytes": record.bytes}


def _reopen_archive(
    path: Path,
    operation_result: dict[str, Any],
    source: Path,
) -> dict[str, Any]:
    images = operation_result["images"]
    expected = {item["archive_path"]: item for item in images}
    if len(expected) != len(images):
        raise ValueError("Image extraction manifest contains duplicate paths.")
    expected_bytes = operation_result["total_image_bytes"]
    expected_pixels = operation_result["total_image_pixels"]
    if expected_bytes < 0 or expected_bytes > MAX_EXTRACTED_TOTAL_BYTES:
        raise ValueError("Image extraction manifest byte total exceeds its safety limit.")
    if expected_pixels < 0 or expected_pixels > MAX_TOTAL_IMAGE_PIXELS:
        raise ValueError("Image extraction manifest pixel total exceeds its safety limit.")
    if operation_result["image_count"] != len(images):
        raise ValueError("Image extraction manifest count is inconsistent.")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("Image extraction archive entries are not canonical.")
        if set(names) != set(expected):
            raise ValueError("Image extraction archive entries do not match the manifest.")
        declared_bytes = 0
        for info in infos:
            item = expected[info.filename]
            if info.file_size != item["bytes"] or item["bytes"] <= 0:
                raise ValueError("Extracted image byte count differs from the manifest.")
            declared_bytes += info.file_size
            if declared_bytes > MAX_EXTRACTED_TOTAL_BYTES:
                raise ValueError("Extracted image bytes exceed the archive safety limit.")
        if declared_bytes != expected_bytes:
            raise ValueError("Extracted image byte total differs from the manifest.")

        total_pixels = 0
        source_model = (
            parse_pdf(source)
            if any(item.get("source") == "xobject" for item in images)
            else None
        )
        for name in names:
            payload = archive.read(name)
            item = expected[name]
            if len(payload) != item["bytes"]:
                raise ValueError("Extracted image byte count differs from the manifest.")
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError("Extracted image hash differs from the manifest.")
            if item["format"] == "png" and not payload.startswith(PNG_SIGNATURE):
                raise ValueError("Extracted PNG magic is invalid.")
            if item["format"] == "jpeg" and not payload.startswith(b"\xff\xd8"):
                raise ValueError("Extracted JPEG magic is invalid.")
            pixels, pixel_sha256 = _verify_image_payload(payload, item)
            total_pixels += pixels
            if total_pixels > MAX_TOTAL_IMAGE_PIXELS:
                raise ValueError("Decoded image pixels exceed the archive safety limit.")
            if item.get("pixel_sha256") is not None:
                if pixel_sha256 != item["pixel_sha256"]:
                    raise ValueError("Extracted image pixels differ from the manifest.")
            if item.get("source") == "xobject":
                assert source_model is not None
                _verify_source_semantics(source_model, item, pixel_sha256)
        if total_pixels != expected_pixels:
            raise ValueError("Decoded image pixel total differs from the manifest.")
    return {
        "entries": len(names),
        "total_image_bytes": declared_bytes,
        "total_image_pixels": total_pixels,
    }


def _verify_image_payload(
    payload: bytes,
    item: dict[str, Any],
) -> tuple[int, str]:
    expected_format = {"png": "PNG", "jpeg": "JPEG"}.get(item["format"])
    if expected_format is None:
        raise ValueError("Extracted image format is not supported.")
    width = item["width"]
    height = item["height"]
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Extracted image dimensions are invalid.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(payload)) as image:
            if image.format != expected_format:
                raise ValueError("Extracted image format differs from the manifest.")
            if image.size != (width, height):
                raise ValueError("Extracted image dimensions differ from the manifest.")
            image.load()
            mode = "L" if item.get("color_space") == "/DeviceGray" else "RGB"
            pixel_sha256 = hashlib.sha256(image.convert(mode).tobytes()).hexdigest()
    return width * height, pixel_sha256


def _verify_source_semantics(
    model: PdfObjectModel,
    item: dict[str, Any],
    pixel_sha256: str,
) -> None:
    object_number = item.get("object")
    if type(object_number) is not int or object_number not in model.objects:
        raise ValueError("Extracted image source object is missing.")
    source_object = model.objects[object_number]
    if item.get("source_object_sha256") != source_object.sha256:
        raise ValueError("Extracted image source object hash differs from the manifest.")
    from .image_xobject_extract import extract_image

    expected = extract_image(model, source_object)
    expected_decode = list(expected.decode) if expected.decode is not None else None
    if item.get("decode") != expected_decode:
        raise ValueError("Extracted image Decode mapping differs from its source object.")
    if item.get("pixel_sha256") != expected.pixel_sha256:
        raise ValueError("Extracted image pixel hash differs from its source semantics.")
    if pixel_sha256 != expected.pixel_sha256:
        raise ValueError("Extracted image pixels differ from its source semantics.")
    expected_payload_sha256 = hashlib.sha256(expected.payload).hexdigest()
    if item.get("sha256") != expected_payload_sha256:
        raise ValueError("Extracted image payload differs from its source semantics.")


def _preserved_source(
    path: Path,
    expected_sha256: str,
    operation_result: dict[str, Any],
    expected_pages: list[int] | None,
) -> dict[str, Any]:
    assert_source_preserved(path, expected_sha256)
    from .image_source_semantics import verify_source_manifest_semantics
    from .page_tree import walk_pages

    model = parse_pdf(path)
    source_pages = [page.page_number for page in walk_pages(model)]
    trusted_pages = source_pages if expected_pages is None else expected_pages
    if operation_result.get("selected_pages") != trusted_pages:
        raise ValueError("Extracted image selected pages differ from the request.")
    semantics = verify_source_manifest_semantics(model, operation_result)
    return {
        "sha256": expected_sha256,
        "source_semantics": semantics["images"],
        "inline_semantics": semantics["inline_images"],
    }
