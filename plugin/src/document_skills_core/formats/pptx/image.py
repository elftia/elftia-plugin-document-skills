"""Bounded local raster loading and native PresentationML image geometry."""

from hashlib import sha256
import os
from pathlib import Path
import stat
import struct
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_DIMENSION = 32_768
MAX_IMAGE_PIXELS = 64_000_000

_DEFAULT_FRAME = {"x": 457_200, "y": 1_746_250, "cx": 4_572_000, "cy": 4_572_000}
_JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def load_pptx_image(value: dict[str, Any], index: int) -> dict[str, Any]:
    """Load one request image, validate its bytes, and derive native geometry."""

    path = _image_path(value)
    try:
        with path.open("rb") as handle:
            source_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                _invalid(
                    "The presentation image must be an existing local file.",
                    path=str(path),
                )
            if source_stat.st_size <= 0 or source_stat.st_size > MAX_IMAGE_BYTES:
                _invalid(
                    "The presentation image exceeds the per-asset byte limit.",
                    path=str(path),
                    bytes=source_stat.st_size,
                    ceiling=MAX_IMAGE_BYTES,
                )
            payload = handle.read(MAX_IMAGE_BYTES + 1)
    except DocumentSkillsError:
        raise
    except OSError as error:
        _invalid(
            "The presentation image must be an existing readable local file.",
            path=str(path),
            reason=type(error).__name__,
        )
    if len(payload) <= 0 or len(payload) > MAX_IMAGE_BYTES:
        _invalid(
            "The presentation image exceeds the per-asset byte limit.",
            path=str(path),
            bytes=len(payload),
            ceiling=MAX_IMAGE_BYTES,
        )
    payload_sha256 = sha256(payload).hexdigest()
    expected_sha256 = value.get("expected_sha256")
    if expected_sha256 is not None and payload_sha256 != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "The presentation image no longer matches its expected SHA-256.",
            status="invalid_request",
            details={
                "actual_sha256": payload_sha256,
                "expected_sha256": expected_sha256,
                "path": str(path),
            },
        )
    extension, content_type, width, height, orientation = _identify_image(payload)
    declared = value.get("content_type")
    if declared is not None and declared != content_type:
        _invalid(
            "The declared image content type does not match its magic bytes.",
            declared=declared,
            detected=content_type,
        )
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        _invalid(
            "The presentation image dimensions exceed the decode budget.",
            width=width,
            height=height,
            pixel_ceiling=MAX_IMAGE_PIXELS,
        )
    display_width, display_height = (
        (height, width) if orientation in {5, 6, 7, 8} else (width, height)
    )
    frame = _normalize_frame(value.get("frame"))
    fit = value.get("fit", "contain")
    geometry, fit_crop = _fit_geometry(frame, display_width, display_height, fit)
    crop = _merge_crop(fit_crop, value.get("crop"))
    rotation, flip_h, flip_v = _orientation_transform(
        orientation, float(value.get("rotation", 0.0))
    )
    return {
        "alt_text": value.get("alt_text", "Presentation image"),
        "bytes": payload,
        "content_type": content_type,
        "crop": crop,
        "extension": extension,
        "fit": fit,
        "flip_h": flip_h,
        "flip_v": flip_v,
        "frame": geometry,
        "height_px": height,
        "index": index,
        "opacity": float(value.get("opacity", 1.0)),
        "orientation": orientation,
        "part": f"ppt/media/image{index}.{extension}",
        "relationship_id": "rIdImage",
        "rotation": rotation,
        "sha256": payload_sha256,
        "source_path": str(path),
        "target": f"../media/image{index}.{extension}",
        "width_px": width,
        "z_order": int(value.get("z_order", 100)),
    }


def public_image_record(image: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded caller-visible evidence for one embedded image."""

    return {
        "alt_text": image["alt_text"],
        "bytes": len(image["bytes"]),
        "content_type": image["content_type"],
        "embedded_media_part": image["part"],
        "exif_orientation": image["orientation"],
        "fallback": "native",
        "fit": image["fit"],
        "height_px": image["height_px"],
        "source_asset_sha256": image["sha256"],
        "width_px": image["width_px"],
    }


def fit_existing_image(
    payload: bytes,
    frame: dict[str, int],
    fit: str,
    crop: dict[str, float] | None,
) -> tuple[dict[str, int], dict[str, float]]:
    """Apply the same bounded fit calculation to an already embedded image."""

    _extension, _content_type, width, height, orientation = _identify_image(payload)
    display_width, display_height = (
        (height, width) if orientation in {5, 6, 7, 8} else (width, height)
    )
    geometry, fit_crop = _fit_geometry(frame, display_width, display_height, fit)
    return geometry, _merge_crop(fit_crop, crop)


def _image_path(value: dict[str, Any]) -> Path:
    raw = value.get("path", value.get("filename"))
    if isinstance(raw, Path):
        return raw.expanduser().resolve(strict=False)
    if type(raw) is not str or not raw or "://" in raw or raw.startswith(("\\\\", "//")):
        _invalid("The presentation image path must reference a local file.")
    return Path(raw).expanduser().resolve(strict=False)


def _identify_image(payload: bytes) -> tuple[str, str, int, int, int]:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _png_dimensions(payload)
        return "png", "image/png", width, height, 1
    if payload.startswith(b"\xff\xd8\xff"):
        width, height, orientation = _jpeg_metadata(payload)
        return "jpg", "image/jpeg", width, height, orientation
    if payload.startswith((b"GIF87a", b"GIF89a")):
        width, height = _gif_dimensions(payload)
        if _gif_frame_count(payload) != 1:
            _invalid("Animated GIF is not supported; provide a static single-frame GIF.")
        return "gif", "image/gif", width, height, 1
    _invalid("The presentation image format is not PNG, JPEG, or static GIF.")


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 33 or payload[12:16] != b"IHDR":
        _invalid("The PNG image is truncated or lacks IHDR.")
    length = int.from_bytes(payload[8:12], "big")
    if length != 13:
        _invalid("The PNG IHDR length is invalid.")
    return struct.unpack(">II", payload[16:24])


def _gif_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 13:
        _invalid("The GIF image is truncated.")
    return struct.unpack("<HH", payload[6:10])


def _gif_frame_count(payload: bytes) -> int:
    packed = payload[10]
    cursor = 13 + (3 * (2 ** ((packed & 0x07) + 1)) if packed & 0x80 else 0)
    frames = 0
    while cursor < len(payload):
        marker = payload[cursor]
        cursor += 1
        if marker == 0x3B:
            return frames
        if marker == 0x21:
            if cursor >= len(payload):
                break
            cursor += 1
            cursor = _skip_gif_subblocks(payload, cursor)
            continue
        if marker != 0x2C or cursor + 9 > len(payload):
            break
        frames += 1
        descriptor_packed = payload[cursor + 8]
        cursor += 9
        if descriptor_packed & 0x80:
            cursor += 3 * (2 ** ((descriptor_packed & 0x07) + 1))
        if cursor >= len(payload):
            break
        cursor += 1
        cursor = _skip_gif_subblocks(payload, cursor)
    _invalid("The GIF image is truncated or malformed.")


def _skip_gif_subblocks(payload: bytes, cursor: int) -> int:
    while cursor < len(payload):
        block_size = payload[cursor]
        cursor += 1
        if block_size == 0:
            return cursor
        cursor += block_size
        if cursor > len(payload):
            break
    _invalid("The GIF image contains a truncated data block.")


def _jpeg_metadata(payload: bytes) -> tuple[int, int, int]:
    cursor = 2
    width = height = 0
    orientation = 1
    while cursor < len(payload):
        while cursor < len(payload) and payload[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(payload):
            break
        marker = payload[cursor]
        cursor += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(payload):
            break
        segment_length = int.from_bytes(payload[cursor:cursor + 2], "big")
        if segment_length < 2 or cursor + segment_length > len(payload):
            break
        segment = payload[cursor + 2:cursor + segment_length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            orientation = _exif_orientation(segment[6:])
        if marker in _JPEG_SOF:
            if segment_length < 7:
                break
            height = int.from_bytes(payload[cursor + 3:cursor + 5], "big")
            width = int.from_bytes(payload[cursor + 5:cursor + 7], "big")
        if marker == 0xDA:
            break
        cursor += segment_length
    if width <= 0 or height <= 0:
        _invalid("The JPEG image is truncated or lacks a supported frame header.")
    return width, height, orientation


def _exif_orientation(tiff: bytes) -> int:
    if len(tiff) < 8 or tiff[:2] not in {b"II", b"MM"}:
        _invalid("The JPEG EXIF header is malformed.")
    endian = "little" if tiff[:2] == b"II" else "big"
    if int.from_bytes(tiff[2:4], endian) != 42:
        _invalid("The JPEG EXIF byte order marker is invalid.")
    offset = int.from_bytes(tiff[4:8], endian)
    if offset + 2 > len(tiff):
        _invalid("The JPEG EXIF directory is truncated.")
    count = int.from_bytes(tiff[offset:offset + 2], endian)
    cursor = offset + 2
    for _ in range(count):
        if cursor + 12 > len(tiff):
            _invalid("The JPEG EXIF directory entry is truncated.")
        tag = int.from_bytes(tiff[cursor:cursor + 2], endian)
        field_type = int.from_bytes(tiff[cursor + 2:cursor + 4], endian)
        field_count = int.from_bytes(tiff[cursor + 4:cursor + 8], endian)
        if tag == 0x0112:
            if field_type != 3 or field_count != 1:
                _invalid("The JPEG EXIF orientation field is invalid.")
            value = int.from_bytes(tiff[cursor + 8:cursor + 10], endian)
            if value not in range(1, 9):
                _invalid("The JPEG EXIF orientation value is invalid.")
            return value
        cursor += 12
    return 1


def _normalize_frame(value: Any) -> dict[str, int]:
    if value is None:
        return dict(_DEFAULT_FRAME)
    return {key: int(value[key]) for key in ("x", "y", "cx", "cy")}


def _fit_geometry(
    frame: dict[str, int], width: int, height: int, fit: str
) -> tuple[dict[str, int], dict[str, float]]:
    if fit == "stretch":
        return dict(frame), _empty_crop()
    image_ratio = width / height
    frame_ratio = frame["cx"] / frame["cy"]
    if fit == "contain":
        if image_ratio > frame_ratio:
            cy = max(1, round(frame["cx"] / image_ratio))
            return {**frame, "y": frame["y"] + (frame["cy"] - cy) // 2, "cy": cy}, _empty_crop()
        cx = max(1, round(frame["cy"] * image_ratio))
        return {**frame, "x": frame["x"] + (frame["cx"] - cx) // 2, "cx": cx}, _empty_crop()
    if image_ratio > frame_ratio:
        visible = frame_ratio / image_ratio
        side = (1.0 - visible) / 2.0
        return dict(frame), {"left": side, "top": 0.0, "right": side, "bottom": 0.0}
    visible = image_ratio / frame_ratio
    side = (1.0 - visible) / 2.0
    return dict(frame), {"left": 0.0, "top": side, "right": 0.0, "bottom": side}


def _merge_crop(
    fit_crop: dict[str, float], explicit: dict[str, float] | None
) -> dict[str, float]:
    if explicit is None:
        return fit_crop
    return {
        "left": fit_crop["left"] + explicit["left"] * (1.0 - fit_crop["left"] - fit_crop["right"]),
        "right": fit_crop["right"] + explicit["right"] * (1.0 - fit_crop["left"] - fit_crop["right"]),
        "top": fit_crop["top"] + explicit["top"] * (1.0 - fit_crop["top"] - fit_crop["bottom"]),
        "bottom": fit_crop["bottom"] + explicit["bottom"] * (1.0 - fit_crop["top"] - fit_crop["bottom"]),
    }


def _empty_crop() -> dict[str, float]:
    return {"left": 0.0, "top": 0.0, "right": 0.0, "bottom": 0.0}


def _orientation_transform(orientation: int, requested_rotation: float) -> tuple[float, bool, bool]:
    transforms = {
        1: (0.0, False, False),
        2: (0.0, True, False),
        3: (180.0, False, False),
        4: (0.0, False, True),
        5: (90.0, True, False),
        6: (90.0, False, False),
        7: (90.0, False, True),
        8: (270.0, False, False),
    }
    rotation, flip_h, flip_v = transforms[orientation]
    return (rotation + requested_rotation) % 360.0, flip_h, flip_v


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
