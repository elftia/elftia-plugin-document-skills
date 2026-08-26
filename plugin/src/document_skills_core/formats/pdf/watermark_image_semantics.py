"""Exact asset and geometry checks for reopened image watermarks."""

import hashlib
from typing import Any

from .byte_preflight import decode_stream
from .object_model import PdfDict
from .watermark_expectations import ExpectedWatermark
from .watermark_scan import WatermarkUse


_BBOX_TOLERANCE = 0.02
_MAIN_IMAGE_KEYS = {
    "/BitsPerComponent",
    "/ColorSpace",
    "/DSAssetSHA256",
    "/Filter",
    "/Height",
    "/Length",
    "/Subtype",
    "/Type",
    "/Width",
}
_SOFT_MASK_KEYS = {
    "/BitsPerComponent",
    "/ColorSpace",
    "/Filter",
    "/Height",
    "/Length",
    "/Subtype",
    "/Type",
    "/Width",
}


def image_use_matches(
    use: WatermarkUse,
    expected: ExpectedWatermark,
) -> bool:
    """Compare candidate XObject bytes, dictionary, and draw box to request."""
    asset = expected.image_asset
    if asset is None or expected.bbox is None:
        return False
    expected_stream = decode_stream(asset.image_data, [asset.filter_name])
    return (
        use.kind == "image"
        and use.image_resource == expected.image_resource
        and use.image_object_generation == 0
        and use.image_keys == _expected_image_keys(expected)
        and use.image_type == "/XObject"
        and use.image_subtype == "/Image"
        and use.asset_sha256 == asset.sha256
        and use.stream_sha256 == hashlib.sha256(expected_stream).hexdigest()
        and use.width == asset.width
        and use.height == asset.height
        and use.color_space == asset.color_space
        and use.bits_per_component == asset.bits_per_component
        and use.filter_name == asset.filter_name
        and use.decode == (list(asset.decode) if asset.decode is not None else None)
        and _decode_parms_matches(use.decode_parms, asset.decode_parms)
        and use.image_length == len(asset.image_data)
        and use.image_alt == expected.image_alt
        and _soft_mask_matches(use, expected)
        and _bbox_matches(use.bbox, expected.bbox)
    )


def image_evidence_matches(
    evidence: Any,
    expected: ExpectedWatermark,
) -> bool:
    """Cross-check writer-reported asset evidence against the request."""
    asset = expected.image_asset
    if not isinstance(evidence, dict) or asset is None:
        return False
    expected_stream = decode_stream(asset.image_data, [asset.filter_name])
    return (
        evidence.get("asset_sha256") == asset.sha256
        and evidence.get("resource") == expected.image_resource
        and evidence.get("image_object_generation") == 0
        and evidence.get("keys") == list(_expected_image_keys(expected))
        and evidence.get("type") == "/XObject"
        and evidence.get("subtype") == "/Image"
        and evidence.get("stream_sha256") == hashlib.sha256(expected_stream).hexdigest()
        and evidence.get("width") == asset.width
        and evidence.get("height") == asset.height
        and evidence.get("color_space") == asset.color_space
        and evidence.get("bits_per_component") == asset.bits_per_component
        and evidence.get("filter") == asset.filter_name
        and evidence.get("decode") == (
            list(asset.decode) if asset.decode is not None else None
        )
        and evidence.get("decode_parms") == (
            dict(asset.decode_parms) if asset.decode_parms is not None else None
        )
        and evidence.get("length") == len(asset.image_data)
        and evidence.get("alt") == expected.image_alt
        and _soft_mask_evidence_matches(evidence.get("soft_mask"), expected)
    )


def _decode_parms_matches(
    actual: Any,
    expected: tuple[tuple[str, int], ...] | None,
) -> bool:
    if expected is None:
        return actual is None
    return isinstance(actual, PdfDict) and actual.entries == dict(expected)


def _expected_image_keys(expected: ExpectedWatermark) -> tuple[str, ...]:
    asset = expected.image_asset
    assert asset is not None
    keys = set(_MAIN_IMAGE_KEYS)
    if asset.decode is not None:
        keys.add("/Decode")
    if asset.decode_parms is not None:
        keys.add("/DecodeParms")
    if asset.alpha_data is not None:
        keys.add("/SMask")
    if expected.image_alt is not None:
        keys.add("/Alt")
    return tuple(sorted(keys))


def _soft_mask_matches(use: WatermarkUse, expected: ExpectedWatermark) -> bool:
    asset = expected.image_asset
    assert asset is not None
    if asset.alpha_data is None:
        return not use.soft_mask_present
    expected_alpha = hashlib.sha256(
        decode_stream(asset.alpha_data, ["/FlateDecode"])
    ).hexdigest()
    return (
        use.soft_mask_present
        and use.soft_mask_indirect
        and use.soft_mask_object is not None
        and use.soft_mask_object_generation == 0
        and use.soft_mask_object_sha256 is not None
        and use.soft_mask_keys == tuple(sorted(_SOFT_MASK_KEYS))
        and use.soft_mask_type == "/XObject"
        and use.soft_mask_subtype == "/Image"
        and use.soft_mask_width == asset.width
        and use.soft_mask_height == asset.height
        and use.soft_mask_color_space == "/DeviceGray"
        and use.soft_mask_bits_per_component == 8
        and use.soft_mask_filter == "/FlateDecode"
        and use.soft_mask_decode is None
        and use.soft_mask_decode_parms is None
        and use.soft_mask_length == len(asset.alpha_data)
        and use.soft_mask_stream_sha256 == expected_alpha
    )


def _soft_mask_evidence_matches(
    evidence: Any,
    expected: ExpectedWatermark,
) -> bool:
    asset = expected.image_asset
    assert asset is not None
    if asset.alpha_data is None:
        return evidence is None
    expected_alpha = hashlib.sha256(
        decode_stream(asset.alpha_data, ["/FlateDecode"])
    ).hexdigest()
    return (
        isinstance(evidence, dict)
        and evidence.get("indirect") is True
        and type(evidence.get("object")) is int
        and evidence.get("object_generation") == 0
        and isinstance(evidence.get("object_sha256"), str)
        and evidence.get("keys") == sorted(_SOFT_MASK_KEYS)
        and evidence.get("type") == "/XObject"
        and evidence.get("subtype") == "/Image"
        and evidence.get("width") == asset.width
        and evidence.get("height") == asset.height
        and evidence.get("color_space") == "/DeviceGray"
        and evidence.get("bits_per_component") == 8
        and evidence.get("filter") == "/FlateDecode"
        and evidence.get("decode") is None
        and evidence.get("decode_parms") is None
        and evidence.get("length") == len(asset.alpha_data)
        and evidence.get("stream_sha256") == expected_alpha
    )


def bbox_matches(left: object, right: object) -> bool:
    """Compare JSON/report boxes with the same tolerance as semantic draws."""
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        return False
    if len(left) != 4 or len(right) != 4:
        return False
    try:
        return all(
            abs(float(actual) - float(wanted)) <= _BBOX_TOLERANCE
            for actual, wanted in zip(left, right)
        )
    except (TypeError, ValueError):
        return False


def _bbox_matches(
    left: tuple[float, float, float, float] | None,
    right: tuple[float, float, float, float],
) -> bool:
    return bbox_matches(left, right)
