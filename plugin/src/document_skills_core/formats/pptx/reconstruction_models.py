"""Strict raster and OCR/vision observation contracts for reconstruction."""

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .scene import _image_metadata

MAX_RASTER_BYTES = 8 * 1024 * 1024
MAX_RASTER_DIMENSION = 8_192
MAX_RASTER_PIXELS = 40_000_000
MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
MAX_ELEMENTS = 512
MAX_TEXT_BYTES = 256 * 1024

_ELEMENT_KEYS = {
    "confidence",
    "geometry",
    "id",
    "kind",
    "reading_order",
    "source_region",
    "style",
    "text",
}
_RECT_KEYS = {"height", "width", "x", "y"}
_STYLE_KEYS = {
    "border_color",
    "border_width",
    "color",
    "fill",
    "font_family",
    "font_size",
    "font_weight",
    "radius",
    "text_align",
}
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class RasterEvidence:
    bytes_value: bytes
    height: int
    media_type: str
    sha256: str
    width: int

    @property
    def byte_count(self) -> int:
        return len(self.bytes_value)


@dataclass(frozen=True)
class ReconstructionObservations:
    canvas: dict[str, int]
    elements: tuple[dict[str, Any], ...]
    serialized_bytes: int


def screen_reconstruction_raster(path: Path) -> RasterEvidence:
    payload = _read_bound_raster(path)
    try:
        media_type, width, height = _image_metadata(payload)
    except DocumentSkillsError:
        _invalid("Reconstruction input is not a structurally valid PNG or JPEG.", field="input")
    expected_suffixes = {
        "image/jpeg": {".jpeg", ".jpg"},
        "image/png": {".png"},
    }[media_type]
    if path.suffix.casefold() not in expected_suffixes:
        _invalid("Reconstruction raster suffix and magic bytes disagree.", field="input")
    if (
        width > MAX_RASTER_DIMENSION
        or height > MAX_RASTER_DIMENSION
        or width * height > MAX_RASTER_PIXELS
    ):
        _invalid(
            "Reconstruction raster exceeds dimension or pixel limits.",
            field="input",
            width=width,
            height=height,
            pixel_ceiling=MAX_RASTER_PIXELS,
        )
    return RasterEvidence(
        bytes_value=payload,
        height=height,
        media_type=media_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        width=width,
    )


def parse_reconstruction_observations(
    value: Any,
    raster: RasterEvidence,
) -> ReconstructionObservations:
    try:
        return _parse_reconstruction_observations(value, raster)
    except DocumentSkillsError as error:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "OCR/vision provider returned invalid observations.",
            details={"validation_reason": str(error)},
        ) from error


def _parse_reconstruction_observations(
    value: Any,
    raster: RasterEvidence,
) -> ReconstructionObservations:
    if type(value) is not dict or set(value) != {"canvas", "elements"}:
        _invalid("OCR/vision observation envelope fields are invalid.")
    canvas = value["canvas"]
    if (
        type(canvas) is not dict
        or set(canvas) != {"height", "width"}
        or type(canvas["width"]) is not int
        or type(canvas["height"]) is not int
        or canvas != {"width": raster.width, "height": raster.height}
    ):
        _invalid("OCR/vision canvas does not match the screened raster.")
    values = value["elements"]
    if type(values) is not list or not 1 <= len(values) <= MAX_ELEMENTS:
        _invalid("OCR/vision elements must be a non-empty bounded array.")
    elements: list[dict[str, Any]] = []
    identities: set[str] = set()
    reading_orders: set[int] = set()
    text_bytes = 0
    for index, element in enumerate(values):
        parsed = _parse_element(element, canvas, index)
        if parsed["id"] in identities:
            _invalid("OCR/vision element ids must be unique.", field=f"elements.{index}.id")
        if parsed["reading_order"] in reading_orders:
            _invalid(
                "OCR/vision reading-order positions must be unique.",
                field=f"elements.{index}.reading_order",
            )
        identities.add(parsed["id"])
        reading_orders.add(parsed["reading_order"])
        text_bytes += len(parsed["text"].encode("utf-8"))
        if text_bytes > MAX_TEXT_BYTES:
            _invalid("OCR/vision text exceeds the aggregate byte limit.")
        elements.append(parsed)
    elements.sort(key=lambda item: (item["reading_order"], item["id"]))
    try:
        serialized = json.dumps(
            {"canvas": dict(canvas), "elements": elements},
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError):
        _invalid("OCR/vision observations are not canonical JSON values.")
    if len(serialized) > MAX_OBSERVATION_BYTES:
        _invalid(
            "OCR/vision observation envelope exceeds the byte limit.",
            observed=len(serialized),
            ceiling=MAX_OBSERVATION_BYTES,
        )
    return ReconstructionObservations(
        canvas=dict(canvas),
        elements=tuple(elements),
        serialized_bytes=len(serialized),
    )


def _parse_element(
    value: Any,
    canvas: dict[str, int],
    index: int,
) -> dict[str, Any]:
    field = f"elements.{index}"
    if type(value) is not dict or set(value) != _ELEMENT_KEYS:
        _invalid("OCR/vision element fields are invalid.", field=field)
    identity = value["id"]
    if type(identity) is not str or _SOURCE_ID.fullmatch(identity) is None:
        _invalid("OCR/vision element identity is invalid.", field=f"{field}.id")
    kind = value["kind"]
    if type(kind) is not str or kind not in {"image", "shape", "text"}:
        _invalid("OCR/vision element kind is invalid.", field=f"{field}.kind")
    reading_order = value["reading_order"]
    if type(reading_order) is not int or not 0 <= reading_order < MAX_ELEMENTS:
        _invalid("OCR/vision reading order is invalid.", field=f"{field}.reading_order")
    confidence = value["confidence"]
    if (
        type(confidence) not in {int, float}
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        _invalid("OCR/vision confidence is invalid.", field=f"{field}.confidence")
    geometry = _parse_rect(value["geometry"], canvas, f"{field}.geometry")
    source_region = _parse_rect(
        value["source_region"],
        canvas,
        f"{field}.source_region",
    )
    text = value["text"]
    if type(text) is not str or len(text.encode("utf-8")) > 64_000:
        _invalid("OCR/vision element text is invalid.", field=f"{field}.text")
    if (kind == "text" and not text) or (kind != "text" and text):
        _invalid("OCR/vision element text does not match its kind.", field=f"{field}.text")
    style = _parse_style(value["style"], f"{field}.style")
    return {
        "confidence": float(confidence),
        "geometry": geometry,
        "id": identity,
        "kind": kind,
        "reading_order": reading_order,
        "source_region": source_region,
        "style": style,
        "text": text,
    }


def _parse_rect(value: Any, canvas: dict[str, int], field: str) -> dict[str, float]:
    if type(value) is not dict or set(value) != _RECT_KEYS:
        _invalid("OCR/vision rectangle fields are invalid.", field=field)
    result: dict[str, float] = {}
    for name in ("x", "y", "width", "height"):
        number = value[name]
        if type(number) not in {int, float} or not math.isfinite(number):
            _invalid("OCR/vision rectangle value is invalid.", field=f"{field}.{name}")
        result[name] = float(number)
    if (
        result["x"] < 0
        or result["y"] < 0
        or result["width"] <= 0
        or result["height"] <= 0
        or result["x"] + result["width"] > canvas["width"]
        or result["y"] + result["height"] > canvas["height"]
    ):
        _invalid("OCR/vision rectangle is outside the canvas.", field=field)
    return result


def _parse_style(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _STYLE_KEYS:
        _invalid("OCR/vision style fields are invalid.", field=field)
    for color_field in ("border_color", "color", "fill"):
        color = value[color_field]
        if type(color) is not str or _COLOR.fullmatch(color) is None:
            _invalid("OCR/vision color must be six-digit hex.", field=f"{field}.{color_field}")
    font = value["font_family"]
    if type(font) is not str or not font or len(font) > 128:
        _invalid("OCR/vision font family is invalid.", field=f"{field}.font_family")
    text_align = value["text_align"]
    if type(text_align) is not str or text_align not in {
        "center",
        "justify",
        "left",
        "right",
    }:
        _invalid("OCR/vision text alignment is invalid.", field=f"{field}.text_align")
    result = dict(value)
    for number_field, minimum, maximum in (
        ("border_width", 0, 100),
        ("font_size", 1, 800),
        ("font_weight", 100, 900),
        ("radius", 0, 1_920),
    ):
        number = value[number_field]
        if (
            type(number) not in {int, float}
            or not math.isfinite(number)
            or not minimum <= number <= maximum
        ):
            _invalid("OCR/vision style number is invalid.", field=f"{field}.{number_field}")
        result[number_field] = float(number)
    return result


def _read_bound_raster(path: Path) -> bytes:
    try:
        before = path.lstat()
    except OSError:
        _invalid("Reconstruction input is not a readable local raster.", field="input")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        _invalid("Reconstruction input must be a regular local raster.", field="input")
    try:
        with path.open("rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_identity(before, opened):
                _invalid("Reconstruction raster changed before it was read.", field="input")
            if not 0 < opened.st_size <= MAX_RASTER_BYTES:
                _invalid(
                    "Reconstruction raster exceeds the byte limit.",
                    field="input",
                    observed=opened.st_size,
                    ceiling=MAX_RASTER_BYTES,
                )
            payload = source.read(MAX_RASTER_BYTES + 1)
            after_read = os.fstat(source.fileno())
        after_path = path.lstat()
    except OSError:
        _invalid("Reconstruction raster changed while it was read.", field="input")
    if len(payload) > MAX_RASTER_BYTES:
        _invalid(
            "Reconstruction raster exceeds the byte limit.",
            field="input",
            observed=MAX_RASTER_BYTES + 1,
            ceiling=MAX_RASTER_BYTES,
        )
    if (
        len(payload) != opened.st_size
        or after_read.st_size != opened.st_size
        or not _same_identity(opened, after_read)
        or not _same_identity(opened, after_path)
        or after_path.st_size != opened.st_size
    ):
        _invalid("Reconstruction raster changed while it was read.", field="input")
    return payload


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
