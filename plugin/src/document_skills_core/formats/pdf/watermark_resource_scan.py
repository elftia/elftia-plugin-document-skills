"""Strict resource resolution for reopened PDF watermarks."""

from dataclasses import dataclass
import hashlib

from .object_model import (
    IndirectReference,
    PdfDict,
    PdfObject,
    PdfObjectModel,
)
from .object_serialization import serialize_pdf_value
from .page_tree import PageInfo


@dataclass(frozen=True)
class FontResource:
    """One strictly resolved indirect font resource."""

    object_number: int
    object_generation: int
    object_sha256: str
    dictionary_sha256: str
    keys: tuple[str, ...]
    type_name: object
    subtype: object
    base_font: str | None
    encoding: object


def page_resource_names(
    model: PdfObjectModel,
    page: PageInfo,
    category: str,
) -> set[str]:
    """Return occupied names from one strictly resolved resource category."""
    entries = _resource_category(model, page, category)
    return set(entries.entries) if entries is not None else set()


def page_font_map(
    model: PdfObjectModel,
    page: PageInfo,
) -> dict[str, FontResource | None]:
    """Return occupied font names and exact valid indirect Base-14 records."""
    fonts = _resource_category(model, page, "/Font")
    if fonts is None:
        return {}
    return {
        name: _font_record(model, value)
        for name, value in fonts.entries.items()
    }


def resource_dictionary_entry(
    model: PdfObjectModel,
    page: PageInfo,
    category: str,
    name: str | None,
) -> PdfDict | None:
    """Resolve a named dictionary while enforcing reference generation."""
    entries = _resource_category(model, page, category)
    value = entries.get(name) if entries is not None and name is not None else None
    return resolved_dictionary(model, value)


def resource_indirect_object(
    model: PdfObjectModel,
    page: PageInfo,
    category: str,
    name: str | None,
) -> PdfObject | None:
    """Resolve a named indirect resource with an exact generation match."""
    entries = _resource_category(model, page, category)
    value = entries.get(name) if entries is not None and name is not None else None
    return strict_indirect_object(model, value)


def font_resource_record(
    model: PdfObjectModel,
    page: PageInfo,
    name: str | None,
) -> FontResource | None:
    """Return one exact font record or None for a missing/invalid resource."""
    fonts = _resource_category(model, page, "/Font")
    value = fonts.get(name) if fonts is not None and name is not None else None
    return _font_record(model, value)


def strict_indirect_object(
    model: PdfObjectModel,
    value: object,
) -> PdfObject | None:
    """Resolve only when the reference and object generations agree."""
    if not isinstance(value, IndirectReference):
        return None
    obj = model.objects.get(value.obj_num)
    if obj is None or value.gen_num != obj.gen_num:
        return None
    return obj


def soft_mask_record(model: PdfObjectModel, image: object) -> dict[str, object]:
    """Return exact soft-mask dictionary evidence with strict generation."""
    value = image.get("/SMask") if isinstance(image, PdfDict) else None
    if value is None:
        return {"present": False, "indirect": False}
    obj = strict_indirect_object(model, value)
    if obj is None:
        return {"present": True, "indirect": False}
    base = {
        "present": True,
        "indirect": True,
        "object": obj.obj_num,
        "object_generation": obj.gen_num,
    }
    if not isinstance(obj.value, tuple):
        return {**base, "object_sha256": obj.sha256}
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        return base
    return {
        **base,
        "object_sha256": obj.sha256,
        "keys": tuple(sorted(dictionary.entries)),
        "type": dictionary.get("/Type"),
        "subtype": dictionary.get("/Subtype"),
        "width": dictionary.get("/Width"),
        "height": dictionary.get("/Height"),
        "color_space": dictionary.get("/ColorSpace"),
        "bits_per_component": dictionary.get("/BitsPerComponent"),
        "filter": dictionary.get("/Filter"),
        "decode": dictionary.get("/Decode"),
        "decode_parms": dictionary.get("/DecodeParms"),
        "length": dictionary.get("/Length"),
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
    }


def resolved_dictionary(
    model: PdfObjectModel,
    value: object,
) -> PdfDict | None:
    """Resolve a direct/indirect dictionary with strict generation checks."""
    if isinstance(value, IndirectReference):
        obj = strict_indirect_object(model, value)
        value = obj.value if obj is not None else None
    return value if isinstance(value, PdfDict) else None


def _resource_category(
    model: PdfObjectModel,
    page: PageInfo,
    category: str,
) -> PdfDict | None:
    resources = resolved_dictionary(model, page.resources)
    return resolved_dictionary(
        model,
        resources.get(category) if resources is not None else None,
    )


def _font_record(model: PdfObjectModel, value: object) -> FontResource | None:
    obj = strict_indirect_object(model, value)
    if obj is None or not isinstance(obj.value, PdfDict):
        return None
    font = obj.value
    base_font = font.get("/BaseFont")
    return FontResource(
        object_number=obj.obj_num,
        object_generation=obj.gen_num,
        object_sha256=obj.sha256,
        dictionary_sha256=hashlib.sha256(serialize_pdf_value(font)).hexdigest(),
        keys=tuple(sorted(font.entries)),
        type_name=font.get("/Type"),
        subtype=font.get("/Subtype"),
        base_font=(
            base_font.removeprefix("/") if isinstance(base_font, str) else None
        ),
        encoding=font.get("/Encoding"),
    )
