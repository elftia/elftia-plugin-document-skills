"""Reopen-based measurements for pypdf compression candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import math
from pathlib import Path
import re
from typing import Any, Callable
import warnings

from PIL import Image, ImageChops
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject, PdfObject, StreamObject

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.image_assets import MAX_IMAGE_PIXELS

_MAX_COMPRESSION_IMAGES = 1_000


@dataclass(frozen=True)
class _ObjectMeasurement:
    object_id: int
    generation: int
    serialized_bytes: int
    fingerprint: str
    duplicate_key: bytes
    is_stream: bool
    stream_bytes: int
    is_content_stream: bool
    is_metadata: bool
    is_image: bool
    is_object_stream: bool


def measure_compression(source: Path, candidate: Path) -> dict[str, Any]:
    before = _measure_objects(source)
    after = _measure_objects(candidate)
    components = {
        "object": _component(before, after, lambda item: True),
        "stream": _component(
            before,
            after,
            lambda item: item.is_stream,
            stream=True,
            content=True,
        ),
        "duplicate": _duplicate_component(before, after),
        "metadata": _component(before, after, lambda item: item.is_metadata),
        "image": _component(before, after, lambda item: item.is_image, stream=True),
        "object_stream": _unsupported_stream_component(
            before,
            after,
            lambda item: item.is_object_stream,
        ),
        "xref_stream": _xref_stream_component(source, candidate),
    }
    return {
        "source": "pypdf-reopen-object-measurement",
        "before_file_bytes": source.stat().st_size,
        "after_file_bytes": candidate.stat().st_size,
        "components": components,
    }


def reopen_visual_evidence(
    source: PdfReader,
    candidate: PdfReader,
    mode: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Recompute the exact bounded image evidence accepted for a lossy mode."""
    source_images = _decoded_images(source)
    candidate_images = _decoded_images(candidate)
    max_dimension = policy["max_dimension"]
    if len(source_images) != len(candidate_images):
        raise ValueError("Compressed PDF changed the projected image count.")
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for before, after in zip(source_images, candidate_images):
        if (
            before["page"] != after["page"]
            or before["index"] != after["index"]
            or before["resource_name"] != after["resource_name"]
        ):
            raise ValueError("Compressed PDF changed image ordering.")
        original = before["image"]
        actual = after["image"]
        reference = before["object"]
        if reference is None:
            _assert_same_image(original, actual)
            skipped.append({
                "page": before["page"],
                "name": before["name"],
                "reason": "inline-image",
            })
            continue
        if "A" in original.getbands() or "transparency" in original.info:
            _assert_same_image(original, actual)
            skipped.append({
                "page": before["page"],
                "name": before["name"],
                "object": reference,
                "reason": "alpha-preservation-required",
            })
            continue
        baseline = original.convert("RGB")
        comparable = actual.convert("RGB")
        expected = baseline.copy()
        expected.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        if comparable.size != expected.size:
            raise ValueError("Compressed image dimensions exceed the mode policy.")
        metrics = image_diff_metrics(baseline, comparable)
        if metrics["psnr_db"] < policy["minimum_psnr_db"]:
            raise ValueError("Compressed image visual evidence is below the mode policy.")
        records.append({
            "page": before["page"],
            "name": before["name"],
            "object": reference,
            "before_dimensions": list(baseline.size),
            "after_dimensions": list(comparable.size),
            "downsampled": comparable.size != baseline.size,
            **metrics,
        })
    return {
        "source": "decoded-image-xobject-diff",
        "scope": "image-xobjects",
        "page_rendered": False,
        "mode": mode,
        "quality": policy["quality"],
        "max_dimension": policy["max_dimension"],
        "minimum_psnr_db": policy["minimum_psnr_db"],
        "allowed_changes": {
            "component": "image-xobjects-only",
            "encoding": "jpeg-reencode",
            "maximum_dimension": policy["max_dimension"],
            "minimum_psnr_db": policy["minimum_psnr_db"],
        },
        "images_recompressed": len(records),
        "images_downsampled": sum(record["downsampled"] for record in records),
        "images": records,
        "skipped_images": skipped,
    }


def image_diff_metrics(
    original: Image.Image, candidate: Image.Image
) -> dict[str, float]:
    comparable = candidate.resize(original.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(original, comparable)
    histogram = difference.histogram()
    channel_pixels = original.width * original.height * len(original.getbands())
    absolute = 0
    squared = 0
    maximum = 0
    for index, count in enumerate(histogram):
        error = index % 256
        absolute += error * count
        squared += error * error * count
        if count:
            maximum = max(maximum, error)
    mean_absolute = absolute / max(channel_pixels, 1)
    mean_squared = squared / max(channel_pixels, 1)
    psnr = 99.0 if mean_squared == 0 else 20.0 * math.log10(
        255.0 / math.sqrt(mean_squared)
    )
    return {
        "mean_absolute_error": round(mean_absolute, 6),
        "max_channel_error": float(maximum),
        "psnr_db": round(psnr, 6),
    }


def _decoded_images(reader: PdfReader) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    total_pixels = 0
    for page_number, page in enumerate(reader.pages, start=1):
        for index, image_file in enumerate(page.images):
            if len(decoded) >= _MAX_COMPRESSION_IMAGES:
                raise ValueError("PDF image count exceeds the visual evidence policy.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = image_file.image.copy()
                image.load()
            pixels = image.width * image.height
            total_pixels += pixels
            if pixels <= 0 or pixels > MAX_IMAGE_PIXELS or total_pixels > MAX_IMAGE_PIXELS:
                raise ValueError("PDF images exceed the visual evidence pixel policy.")
            reference = image_file.indirect_reference
            decoded.append({
                "page": page_number,
                "index": index,
                "name": image_file.name,
                "resource_name": image_file.name.rsplit(".", 1)[0],
                "object": reference.idnum if reference is not None else None,
                "image": image,
            })
    return decoded


def _assert_same_image(before: Image.Image, after: Image.Image) -> None:
    left, right = before.convert("RGBA"), after.convert("RGBA")
    if left.size != right.size or left.tobytes() != right.tobytes():
        raise ValueError("A skipped image changed during compression.")


def _measure_objects(path: Path) -> dict[tuple[int, int], _ObjectMeasurement]:
    try:
        reader = PdfReader(path, strict=True)
        content_ids = _content_reference_ids(reader)
        identities = {
            (object_id, generation)
            for generation, entries in reader.xref.items()
            for object_id in entries
            if object_id > 0
        }
        identities.update((object_id, 0) for object_id in reader.xref_objStm)
        info_id = _dictionary_reference_id(reader.trailer, "/Info")
        root_metadata_id = _dictionary_reference_id(reader.root_object, "/Metadata")
        measured: dict[tuple[int, int], _ObjectMeasurement] = {}
        for object_id, generation in sorted(identities):
            obj = reader.get_object(IndirectObject(object_id, generation, reader))
            if obj is None:
                continue
            payload = _serialize(obj)
            is_stream = isinstance(obj, StreamObject)
            type_name = str(obj.get("/Type", "")) if isinstance(obj, DictionaryObject) else ""
            subtype = str(obj.get("/Subtype", "")) if isinstance(obj, DictionaryObject) else ""
            measured[(object_id, generation)] = _ObjectMeasurement(
                object_id=object_id,
                generation=generation,
                serialized_bytes=len(payload),
                fingerprint=hashlib.sha256(payload).hexdigest(),
                duplicate_key=obj.hash_value(),
                is_stream=is_stream,
                stream_bytes=len(_stream_payload(obj)) if is_stream else 0,
                is_content_stream=object_id in content_ids,
                is_metadata=(
                    object_id in {info_id, root_metadata_id}
                    or type_name == "/Metadata"
                ),
                is_image=is_stream and subtype == "/Image",
                is_object_stream=is_stream and type_name == "/ObjStm",
            )
        return measured
    except DocumentSkillsError:
        raise
    except Exception as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Compression evidence could not reopen every measured PDF object.",
            details={"reason": type(error).__name__},
        ) from None


def _component(
    before: dict[tuple[int, int], _ObjectMeasurement],
    after: dict[tuple[int, int], _ObjectMeasurement],
    selected: Callable[[_ObjectMeasurement], bool],
    *,
    stream: bool = False,
    content: bool = False,
) -> dict[str, Any]:
    before_selected = {key: item for key, item in before.items() if selected(item)}
    after_selected = {key: item for key, item in after.items() if selected(item)}
    changed = _changed_ids(before_selected, after_selected)
    result = {
        "status": "measured",
        "before": _totals(before_selected.values(), stream=stream),
        "after": _totals(after_selected.values(), stream=stream),
        "changed_count": len(changed),
        "changed_object_ids": changed,
        "outcome": _outcome(before_selected, after_selected),
    }
    if content:
        content_before = {
            key: item for key, item in before_selected.items() if item.is_content_stream
        }
        content_after = {
            key: item for key, item in after_selected.items() if item.is_content_stream
        }
        content_changed = _changed_ids(content_before, content_after)
        result["content_changed_count"] = len(content_changed)
    return result


def _duplicate_component(
    before: dict[tuple[int, int], _ObjectMeasurement],
    after: dict[tuple[int, int], _ObjectMeasurement],
) -> dict[str, Any]:
    before_duplicates = _duplicates(before)
    after_duplicates = _duplicates(after)
    changed = sorted({item.object_id for item in before_duplicates + after_duplicates})
    return {
        "status": "measured",
        "before": _totals(before_duplicates),
        "after": _totals(after_duplicates),
        "changed_count": len(changed),
        "changed_object_ids": changed,
        "outcome": (
            "reduced"
            if len(after_duplicates) < len(before_duplicates)
            else "unchanged"
            if len(after_duplicates) == len(before_duplicates)
            else "increased"
        ),
    }


def _unsupported_stream_component(
    before: dict[tuple[int, int], _ObjectMeasurement],
    after: dict[tuple[int, int], _ObjectMeasurement],
    selected: Callable[[_ObjectMeasurement], bool],
) -> dict[str, Any]:
    component = _component(before, after, selected, stream=True)
    return {
        **component,
        "support": "unsupported",
        "status": "not_attempted",
        "reason": "pypdf does not expose an accepted object-stream conversion control.",
    }


def _xref_stream_component(source: Path, candidate: Path) -> dict[str, Any]:
    before = _xref_stream_measurement(source)
    after = _xref_stream_measurement(candidate)
    return {
        "support": "unsupported",
        "status": "not_attempted",
        "reason": "pypdf does not expose an accepted xref-stream conversion control.",
        "before": {"count": before[0], "bytes": before[1]},
        "after": {"count": after[0], "bytes": after[1]},
        "changed_count": int(before[:2] != after[:2]),
        "changed_object_ids": (
            sorted({item for item in (before[2], after[2]) if item is not None})
            if before != after
            else []
        ),
        "outcome": "changed" if before != after else "unchanged",
    }


def _duplicates(
    records: dict[tuple[int, int], _ObjectMeasurement],
) -> list[_ObjectMeasurement]:
    groups: dict[bytes, list[_ObjectMeasurement]] = {}
    for item in records.values():
        groups.setdefault(item.duplicate_key, []).append(item)
    duplicates: list[_ObjectMeasurement] = []
    for group in groups.values():
        duplicates.extend(sorted(group, key=lambda item: item.object_id)[1:])
    return duplicates


def _changed_ids(
    before: dict[tuple[int, int], _ObjectMeasurement],
    after: dict[tuple[int, int], _ObjectMeasurement],
) -> list[int]:
    return sorted({
        key[0]
        for key in set(before) | set(after)
        if key not in before
        or key not in after
        or before[key].fingerprint != after[key].fingerprint
    })


def _totals(
    records: Any,
    *,
    stream: bool = False,
) -> dict[str, int]:
    values = list(records)
    return {
        "count": len(values),
        "bytes": sum(
            item.stream_bytes if stream else item.serialized_bytes
            for item in values
        ),
    }


def _outcome(
    before: dict[tuple[int, int], _ObjectMeasurement],
    after: dict[tuple[int, int], _ObjectMeasurement],
) -> str:
    if not _changed_ids(before, after):
        return "unchanged"
    if len(after) < len(before):
        return "reduced"
    return "changed"


def _serialize(obj: PdfObject) -> bytes:
    output = BytesIO()
    obj.write_to_stream(output)
    return output.getvalue()


def _stream_payload(obj: PdfObject) -> bytes:
    if not isinstance(obj, StreamObject):
        return b""
    data = obj._data
    if data is None:
        return b""
    return data if isinstance(data, bytes) else bytes(data)


def _reference_id(value: Any) -> int:
    return value.idnum if isinstance(value, IndirectObject) else -1


def _dictionary_reference_id(value: DictionaryObject, key: str) -> int:
    try:
        return _reference_id(value.raw_get(key))
    except KeyError:
        return -1


def _content_reference_ids(reader: PdfReader) -> set[int]:
    content_ids: set[int] = set()
    for page in reader.pages:
        if "/Contents" not in page:
            continue
        value = page.raw_get("/Contents")
        values = value if isinstance(value, list) else [value]
        content_ids.update(item.idnum for item in values if isinstance(item, IndirectObject))
    return content_ids


def _xref_stream_measurement(path: Path) -> tuple[int, int, int | None]:
    raw = path.read_bytes()
    matches = list(re.finditer(rb"startxref\s+(\d+)", raw))
    if not matches:
        return (0, 0, None)
    offset = int(matches[-1].group(1))
    if raw[offset:offset + 4] == b"xref":
        return (0, 0, None)
    end = raw.find(b"endobj", offset)
    header = re.match(rb"(\d+)\s+\d+\s+obj", raw[offset:])
    object_id = int(header.group(1)) if header is not None else None
    byte_count = max(0, end + len(b"endobj") - offset) if end >= 0 else 0
    return (1, byte_count, object_id)
