"""PNG reconstruction plus deterministic extraction-archive validation.

Module provenance: original Elftia-authored clean-room implementation.
"""

import binascii
import hashlib
from pathlib import Path
import struct
from typing import Any
import zipfile
import zlib

from document_skills_core.core.io.paths import assert_source_preserved, file_record
from document_skills_core.core.validation.runner import ValidationRunner

from .image_assets import PNG_SIGNATURE

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
) -> dict[str, Any]:
    """Validate exact ZIP identity, deterministic entries, and source preservation."""
    runner = ValidationRunner()
    runner.run_gate("artifact.exists-size", lambda: _artifact_identity(archive))
    runner.run_gate(
        "archive.zip-reopen",
        lambda: _reopen_archive(archive, operation_result["images"]),
    )
    runner.run_gate(
        "source.preservation",
        lambda: _preserved_source(source, source_sha256),
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


def _reopen_archive(path: Path, images: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {item["archive_path"]: item for item in images}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("Image extraction archive entries are not canonical.")
        if set(names) != set(expected):
            raise ValueError("Image extraction archive entries do not match the manifest.")
        if archive.testzip() is not None:
            raise ValueError("Image extraction archive contains a corrupt entry.")
        total = 0
        for name in names:
            payload = archive.read(name)
            item = expected[name]
            total += len(payload)
            if len(payload) != item["bytes"]:
                raise ValueError("Extracted image byte count differs from the manifest.")
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError("Extracted image hash differs from the manifest.")
            if item["format"] == "png" and not payload.startswith(PNG_SIGNATURE):
                raise ValueError("Extracted PNG magic is invalid.")
            if item["format"] == "jpeg" and not payload.startswith(b"\xff\xd8"):
                raise ValueError("Extracted JPEG magic is invalid.")
    return {"entries": len(names), "total_image_bytes": total}


def _preserved_source(path: Path, expected_sha256: str) -> dict[str, Any]:
    assert_source_preserved(path, expected_sha256)
    return {"sha256": expected_sha256}
