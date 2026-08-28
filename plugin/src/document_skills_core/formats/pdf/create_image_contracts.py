"""Closed writer-derived Image XObject contracts for PDF create."""

import hashlib
from typing import Any

from .byte_preflight import decode_stream
from .image_assets import ImageAsset
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel

_BASE_IMAGE_KEYS = frozenset({
    "/Type",
    "/Subtype",
    "/Width",
    "/Height",
    "/ColorSpace",
    "/BitsPerComponent",
    "/Filter",
    "/Length",
})


def image_dictionary_record(
    dictionary: PdfDict,
    stream: bytes,
    reference: IndirectReference,
    obj: PdfObject,
) -> dict[str, Any]:
    """Project every writer-controlled main Image dictionary field."""
    return {
        "object": obj.obj_num,
        "reference_generation": reference.gen_num,
        "object_generation": obj.gen_num,
        "object_sha256": obj.sha256,
        "keys": frozenset(dictionary.entries),
        "type": dictionary.get("/Type"),
        "subtype": dictionary.get("/Subtype"),
        "width": dictionary.get("/Width"),
        "height": dictionary.get("/Height"),
        "color_space": dictionary.get("/ColorSpace"),
        "bits_per_component": dictionary.get("/BitsPerComponent"),
        "filter": dictionary.get("/Filter"),
        "length": dictionary.get("/Length"),
        "decode": dictionary.get("/Decode"),
        "decode_parms": dictionary.get("/DecodeParms"),
        "alt": dictionary.get("/Alt"),
        "stream": stream,
    }


def image_dictionary_mismatch(
    candidate: dict[str, Any],
    asset: ImageAsset,
    alt: Any,
) -> bool:
    """Compare a main Image against the exact dictionary the writer emits."""
    expected_keys = set(_BASE_IMAGE_KEYS)
    if asset.decode is not None:
        expected_keys.add("/Decode")
    if asset.decode_parms is not None:
        expected_keys.add("/DecodeParms")
    if asset.alpha_data is not None:
        expected_keys.add("/SMask")
    if alt:
        expected_keys.add("/Alt")
    expected_decode_parms = (
        PdfDict(dict(asset.decode_parms))
        if asset.decode_parms is not None
        else None
    )
    return (
        candidate.get("keys") != expected_keys
        or candidate.get("type") != "/XObject"
        or candidate.get("subtype") != "/Image"
        or candidate.get("width") != asset.width
        or candidate.get("height") != asset.height
        or candidate.get("color_space") != asset.color_space
        or candidate.get("bits_per_component") != asset.bits_per_component
        or candidate.get("filter") != asset.filter_name
        or candidate.get("length") != len(asset.image_data)
        or candidate.get("decode")
        != (list(asset.decode) if asset.decode is not None else None)
        or candidate.get("decode_parms") != expected_decode_parms
        or candidate.get("alt") != (alt if alt else None)
        or (candidate.get("reference_generation"), candidate.get("object_generation"))
        != (0, 0)
        or candidate.get("stream")
        != decode_stream(asset.image_data, [asset.filter_name])
    )


def soft_mask_record(
    model: PdfObjectModel,
    value: Any,
) -> dict[str, Any] | None:
    """Project every writer-controlled soft-mask dictionary field."""
    if value is None:
        return None
    if not isinstance(value, IndirectReference):
        return {"indirect": False}
    obj = model.get_object(value)
    if not isinstance(obj.value, tuple):
        return {"indirect": True, "object": obj.obj_num, "stream": None}
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        return {"indirect": True, "object": obj.obj_num, "stream": None}
    return {
        "indirect": True,
        **image_dictionary_record(dictionary, stream, value, obj),
    }


def soft_mask_mismatch(
    candidate: dict[str, Any] | None,
    asset: ImageAsset,
) -> tuple[str | None, dict[str, Any] | None]:
    """Bind an optional grayscale soft mask to the source alpha channel."""
    if asset.alpha_data is None:
        return (("unexpected-soft-mask" if candidate is not None else None), None)
    if candidate is None:
        return "missing-soft-mask", None
    if not candidate.get("indirect"):
        return "soft-mask-not-indirect", None
    if (
        candidate.get("keys") != _BASE_IMAGE_KEYS
        or candidate.get("type") != "/XObject"
        or candidate.get("subtype") != "/Image"
        or candidate.get("width") != asset.width
        or candidate.get("height") != asset.height
        or candidate.get("color_space") != "/DeviceGray"
        or candidate.get("bits_per_component") != 8
        or candidate.get("filter") != "/FlateDecode"
        or candidate.get("length") != len(asset.alpha_data)
        or candidate.get("decode") is not None
        or candidate.get("decode_parms") is not None
        or candidate.get("alt") is not None
        or (candidate.get("reference_generation"), candidate.get("object_generation"))
        != (0, 0)
        or candidate.get("stream")
        != decode_stream(asset.alpha_data, ["/FlateDecode"])
    ):
        return "soft-mask-mismatch", None
    return None, {
        "soft_mask_object": candidate["object"],
        "soft_mask_object_sha256": candidate["object_sha256"],
        "alpha_sha256": hashlib.sha256(candidate["stream"]).hexdigest(),
    }
