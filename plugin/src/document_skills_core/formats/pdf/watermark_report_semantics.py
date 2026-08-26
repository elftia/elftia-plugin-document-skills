"""Closed writer-evidence checks for PDF watermark promotion."""

import hashlib
import math
from typing import Any

from .create_layout import pdf_number
from .watermark_expectations import ExpectedWatermark
from .watermark_fonts import watermark_font_object_sha256
from .watermark_image_semantics import (
    bbox_matches,
    image_evidence_matches,
)
from .watermark_objects import (
    stream_object_payload,
    watermark_image_object_payload,
    watermark_soft_mask_object_payload,
)
from .watermark_scan import WatermarkUse


_OPACITY_TOLERANCE = 1e-9
_COMMON_RECORD_KEYS = {
    "bbox",
    "content_object",
    "content_object_generation",
    "content_object_sha256",
    "content_decode_parms",
    "content_filter",
    "content_keys",
    "content_length",
    "content_stream_sha256",
    "font_object",
    "font_object_generation",
    "font_object_sha256",
    "font_resource",
    "graphics_state",
    "image_object",
    "image_resource",
    "page",
}


def opacity_matches(actual: Any, expected: float) -> bool:
    """Compare PDF numeric opacity at writer precision."""
    if type(actual) not in {int, float}:
        return False
    return math.isclose(
        float(actual),
        float(pdf_number(expected)),
        rel_tol=0.0,
        abs_tol=_OPACITY_TOLERANCE,
    )


def report_matches(
    report: dict[str, Any] | None,
    expected: ExpectedWatermark,
    use: WatermarkUse,
    *,
    identity_replaced: bool,
    trusted_stage_hashes: dict[str, str],
) -> bool:
    """Cross-bind one exact request page to closed writer evidence."""
    if report is None or not _report_header_matches(report, expected):
        return False
    records = report.get("watermark_uses")
    pages = list(expected.primitive_pages)
    if (
        not isinstance(records, list)
        or len(records) != len(pages)
        or any(not isinstance(record, dict) for record in records)
        or [record.get("page") for record in records] != pages
        or len({record.get("content_object") for record in records}) != len(records)
    ):
        return False
    record = records[pages.index(expected.page)]
    added = report.get("added_objects")
    preservation = report.get("preservation")
    if (
        not isinstance(added, list)
        or not isinstance(preservation, dict)
        or added != preservation.get("added_objects")
    ):
        return False
    if not _use_evidence_matches(
        record,
        expected,
        use,
        added,
        identity_replaced=identity_replaced,
        trusted_stage_hashes=trusted_stage_hashes,
    ):
        return False
    if expected.kind == "text":
        return _text_report_matches(report, expected) and _font_evidence_matches(
            record,
            expected,
            use,
            added,
            identity_replaced=identity_replaced,
            trusted_stage_hashes=trusted_stage_hashes,
        )
    image = report.get("image")
    return (
        isinstance(image, dict)
        and image.get("page_bboxes") == records
        and bbox_matches(image.get("bbox"), records[0].get("bbox"))
        and _image_evidence_matches(
            image,
            expected,
            use,
            record,
            added,
            identity_replaced=identity_replaced,
            trusted_stage_hashes=trusted_stage_hashes,
        )
    )


def _report_header_matches(
    report: dict[str, Any],
    expected: ExpectedWatermark,
) -> bool:
    return (
        report.get("graphics_state") == expected.graphics_state
        and report.get("pages") == list(expected.primitive_pages)
        and _number_matches(report.get("opacity"), expected.opacity)
        and _number_matches(report.get("rotation"), expected.rotation)
        and _position_matches(report.get("position"), expected.position)
    )


def _text_report_matches(
    report: dict[str, Any],
    expected: ExpectedWatermark,
) -> bool:
    return (
        report.get("text") == expected.text
        and report.get("font") == expected.base_font
        and _number_matches(report.get("size"), expected.size)
        and _numeric_tuple(report.get("color"), 3) == expected.color
    )


def _use_evidence_matches(
    record: dict[str, Any],
    expected: ExpectedWatermark,
    use: WatermarkUse,
    added: list[Any],
    *,
    identity_replaced: bool,
    trusted_stage_hashes: dict[str, str],
) -> bool:
    keys = set(_COMMON_RECORD_KEYS)
    if expected.kind == "image":
        keys.add("stream_sha256")
    if set(record) != keys:
        return False
    common = (
        record.get("graphics_state") == expected.graphics_state
        and record.get("font_resource") == expected.font_resource
        and record.get("image_resource") == expected.image_resource
        and record.get("content_object_generation") == 0
        and record.get("content_stream_sha256")
        == expected.content_stream_sha256
        and record.get("content_keys") == ["/Length"]
        and record.get("content_length") == expected.content_length
        and record.get("content_filter") is None
        and record.get("content_decode_parms") is None
        and use.content_object_generation == 0
        and use.content_stream_sha256 == expected.content_stream_sha256
        and (
            expected.kind == "text"
            or (
                record.get("font_object") is None
                and record.get("font_object_generation") is None
                and record.get("font_object_sha256") is None
            )
        )
        and (
            expected.kind != "image"
            or bbox_matches(record.get("bbox"), expected.bbox)
        )
    )
    if not common:
        return False
    if identity_replaced:
        object_number = record.get("content_object")
        digest = record.get("content_object_sha256")
        return (
            object_number in added
            and _payload_hash_matches(
                trusted_stage_hashes,
                object_number,
                digest,
                stream_object_payload(
                    object_number,
                    f"<< /Length {expected.content_length} >>".encode("ascii"),
                    expected.content_stream,
                ),
            )
        )
    return (
        record.get("content_object") == use.content_object
        and record.get("content_object_sha256") == use.content_object_sha256
        and use.content_object in added
        and use.content_object not in expected.source_objects
    )


def _font_evidence_matches(
    record: dict[str, Any],
    expected: ExpectedWatermark,
    use: WatermarkUse,
    added: list[Any],
    *,
    identity_replaced: bool,
    trusted_stage_hashes: dict[str, str],
) -> bool:
    object_number = record.get("font_object")
    generation = record.get("font_object_generation")
    digest = record.get("font_object_sha256")
    if (
        type(object_number) is not int
        or generation != 0
        or expected.base_font is None
        or digest
        != watermark_font_object_sha256(object_number, expected.base_font)
    ):
        return False
    if expected.font_source_dictionary_sha256 is None:
        if expected.font_must_be_added and object_number not in added:
            return False
        if identity_replaced:
            return _stage_hash_matches(
                trusted_stage_hashes,
                object_number,
                digest,
            )
        return (
            object_number == use.font_object
            and generation == use.font_object_generation
            and digest == use.font_object_sha256
            and (
                not expected.font_must_be_added
                or use.font_object not in expected.source_objects
            )
        )
    if identity_replaced:
        return _stage_hash_matches(
            trusted_stage_hashes,
            object_number,
            digest,
        )
    return (
        object_number == use.font_object
        and generation == use.font_object_generation
        and digest == use.font_object_sha256
    )


def _image_evidence_matches(
    evidence: dict[str, Any],
    expected: ExpectedWatermark,
    use: WatermarkUse,
    record: dict[str, Any],
    added: list[Any],
    *,
    identity_replaced: bool,
    trusted_stage_hashes: dict[str, str],
) -> bool:
    if (
        not image_evidence_matches(evidence, expected)
        or record.get("image_object") != evidence.get("image_object")
        or record.get("stream_sha256") != evidence.get("stream_sha256")
    ):
        return False
    if identity_replaced:
        if not _image_role_hash_matches(
            evidence,
            expected,
            trusted_stage_hashes,
            added,
        ):
            return False
    elif not (
        evidence.get("image_object") == use.image_object
        and evidence.get("image_object_sha256") == use.image_object_sha256
        and evidence.get("stream_sha256") == use.stream_sha256
        and use.image_object in added
        and use.image_object not in expected.source_objects
    ):
        return False
    return _soft_mask_binding_matches(
        evidence,
        expected,
        use,
        added,
        identity_replaced=identity_replaced,
        trusted_stage_hashes=trusted_stage_hashes,
    )


def _soft_mask_binding_matches(
    evidence: dict[str, Any],
    expected: ExpectedWatermark,
    use: WatermarkUse,
    added: list[Any],
    *,
    identity_replaced: bool,
    trusted_stage_hashes: dict[str, str],
) -> bool:
    asset = expected.image_asset
    assert asset is not None
    soft_mask = evidence.get("soft_mask")
    if asset.alpha_data is None:
        return soft_mask is None and not use.soft_mask_present
    if not isinstance(soft_mask, dict):
        return False
    object_number = soft_mask.get("object")
    if identity_replaced:
        return object_number in added and _payload_hash_matches(
            trusted_stage_hashes,
            object_number,
            soft_mask.get("object_sha256"),
            watermark_soft_mask_object_payload(object_number, asset),
        )
    return (
        object_number == use.soft_mask_object
        and soft_mask.get("object_sha256") == use.soft_mask_object_sha256
        and use.soft_mask_object in added
        and use.soft_mask_object not in expected.source_objects
    )


def _position_matches(actual: Any, expected: object) -> bool:
    if isinstance(expected, str):
        return actual == expected
    if not isinstance(actual, dict) or set(actual) != {"x", "y"}:
        return False
    return _numeric_tuple([actual["x"], actual["y"]], 2) == expected


def _numeric_tuple(value: Any, length: int) -> tuple[float, ...] | None:
    if not isinstance(value, list) or len(value) != length:
        return None
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None


def _number_matches(actual: Any, expected: float | None) -> bool:
    return (
        type(actual) in {int, float}
        and expected is not None
        and float(actual) == expected
    )


def _stage_hash_matches(
    trusted_stage_hashes: dict[str, str],
    object_number: Any,
    digest: Any,
) -> bool:
    return (
        type(object_number) is int
        and isinstance(digest, str)
        and trusted_stage_hashes.get(str(object_number)) == digest
    )


def _payload_hash_matches(
    trusted_stage_hashes: dict[str, str],
    object_number: Any,
    digest: Any,
    payload: bytes,
) -> bool:
    return (
        isinstance(digest, str)
        and digest == hashlib.sha256(payload).hexdigest()
        and _stage_hash_matches(trusted_stage_hashes, object_number, digest)
    )


def _image_role_hash_matches(
    evidence: dict[str, Any],
    expected: ExpectedWatermark,
    trusted_stage_hashes: dict[str, str],
    added: list[Any],
) -> bool:
    asset = expected.image_asset
    image_object = evidence.get("image_object")
    soft_mask = evidence.get("soft_mask")
    soft_mask_object = (
        soft_mask.get("object") if isinstance(soft_mask, dict) else None
    )
    if asset is None or type(image_object) is not int or image_object not in added:
        return False
    return _payload_hash_matches(
        trusted_stage_hashes,
        image_object,
        evidence.get("image_object_sha256"),
        watermark_image_object_payload(
            image_object,
            asset,
            expected.image_alt,
            soft_mask_object,
        ),
    )
