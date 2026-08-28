"""Deterministic page-count, page-box, metadata, and reference projection.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .resources import FontInfo, ImageInfo


def project_document_info(model: PdfObjectModel) -> dict[str, Any]:
    """Project document-level metadata (version, ID, encryption)."""
    return {
        "version": f"PDF-{model.version_major}.{model.version_minor}",
        "encrypted": model.trailer.encrypt is not None,
        "document_id": _format_id_array(model.trailer.id_array),
        "object_count": len(model.objects),
        "sha256": model.sha256,
    }


def _format_id_array(id_array: list[str] | None) -> str | None:
    if id_array is None or not id_array:
        return None
    if isinstance(id_array[0], str):
        return id_array[0][:32]
    return None


def project_page_info(page: PageInfo) -> dict[str, Any]:
    """Project page-level information (boxes, rotation, content refs)."""
    return {
        "page_number": page.page_number,
        "obj_num": page.obj_num,
        "media_box": list(page.media_box),
        "crop_box": list(page.crop_box) if page.crop_box else None,
        "bleed_box": list(page.bleed_box) if page.bleed_box else None,
        "trim_box": list(page.trim_box) if page.trim_box else None,
        "art_box": list(page.art_box) if page.art_box else None,
        "rotation": page.rotation,
    }


def project_info_dictionary(model: PdfObjectModel) -> dict[str, Any]:
    """Project the Info dictionary metadata."""
    if model.trailer.info is None:
        return {}
    try:
        info_obj = model.get_object(model.trailer.info)
        info_val = model.resolve(info_obj.value)
    except Exception:
        return {}
    if not isinstance(info_val, PdfDict):
        return {}
    metadata: dict[str, Any] = {}
    for key, py_key in [
        ("/Title", "title"),
        ("/Author", "author"),
        ("/Subject", "subject"),
        ("/Keywords", "keywords"),
        ("/Creator", "creator"),
        ("/Producer", "producer"),
        ("/CreationDate", "creation_date"),
        ("/ModDate", "mod_date"),
    ]:
        val = info_val.get(key)
        if val is not None:
            metadata[py_key] = str(val) if not isinstance(val, bool) else val
    return metadata


def project_xmp_presence(model: PdfObjectModel) -> bool:
    """Report only a well-shaped XMP stream linked by the active Catalog."""
    try:
        catalog = model.get_object(model.catalog_ref).value
        if not isinstance(catalog, PdfDict):
            return False
        reference = catalog.get("/Metadata")
        if not isinstance(reference, IndirectReference):
            return False
        obj = model.get_object(reference)
        if obj.gen_num != reference.gen_num or not isinstance(obj.value, tuple):
            return False
        dictionary, _stream = obj.value
        return (
            isinstance(dictionary, PdfDict)
            and dictionary.get("/Type") == "/Metadata"
            and dictionary.get("/Subtype") == "/XML"
        )
    except Exception:
        return False


def project_font_summary(fonts: list[FontInfo]) -> list[dict[str, Any]]:
    """Project font information into JSON-safe form."""
    return [
        {
            "name": f.name,
            "type": f.type,
            "base_font": f.base_font,
            "encoding": f.encoding,
            "embedded": f.embedded,
            "subset": f.subset,
            "cmap": f.cmap,
        }
        for f in fonts
    ]


def project_image_summary(images: list[ImageInfo]) -> list[dict[str, Any]]:
    """Project image information into JSON-safe form."""
    return [
        {
            "name": img.name,
            "width": img.width,
            "height": img.height,
            "bits_per_component": img.bits_per_component,
            "color_space": img.color_space,
            "filter_chain": img.filter_chain,
        }
        for img in images
    ]


def project_object_inventory(model: PdfObjectModel) -> list[dict[str, Any]]:
    """Project a sorted object inventory (obj_num, type, is_stream, sha256)."""
    inventory: list[dict[str, Any]] = []
    for obj_num in sorted(model.objects):
        obj = model.objects[obj_num]
        type_name = obj.type_name if obj.type_name else (
            "stream" if obj.is_stream else "object"
        )
        inventory.append({
            "obj_num": obj.obj_num,
            "gen_num": obj.gen_num,
            "offset": obj.offset,
            "type": type_name,
            "is_stream": obj.is_stream,
            "sha256": obj.sha256,
        })
    return inventory
