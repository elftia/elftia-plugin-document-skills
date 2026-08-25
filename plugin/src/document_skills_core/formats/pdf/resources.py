"""Font/image/XObject/ExtGState/ColorSpace resource inventory.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from .object_model import IndirectReference, PdfDict, PdfObjectModel


@dataclass(frozen=True)
class FontInfo:
    """Font resource inventory entry."""
    name: str
    type: str  # /Type0, /Type1, /TrueType, /CFF, etc.
    base_font: str
    encoding: str | None
    embedded: bool
    subset: bool
    cmap: str | None


@dataclass(frozen=True)
class ImageInfo:
    """Image XObject resource inventory entry."""
    name: str
    width: int
    height: int
    bits_per_component: int
    color_space: str
    filter_chain: list[str]


def inventory_fonts(model: PdfObjectModel, resources: PdfDict | None) -> list[FontInfo]:
    """Inventory font resources from a page's /Resources dictionary."""
    if resources is None:
        return []
    font_dict = resources.get("/Font")
    if isinstance(font_dict, IndirectReference):
        obj = model.get_object(font_dict)
        font_dict = model.resolve(obj.value)
    if not isinstance(font_dict, PdfDict):
        return []
    fonts: list[FontInfo] = []
    for name, font_val in font_dict.entries.items():
        if isinstance(font_val, IndirectReference):
            obj = model.get_object(font_val)
            # Preserve nested stream references such as /ToUnicode and
            # /FontFile2 so inventory can distinguish their presence.
            font_val = obj.value
        if isinstance(font_val, PdfDict):
            fonts.append(_build_font_info(name, font_val, model))
    return fonts


def _build_font_info(name: str, d: PdfDict, model: PdfObjectModel) -> FontInfo:
    """Build a FontInfo from a font dictionary."""
    sub_type = d.get("/Subtype", "/Unknown")
    base_font = d.get("/BaseFont", "/Unknown")
    if isinstance(base_font, IndirectReference):
        try:
            obj = model.get_object(base_font)
            base_font = model.resolve(obj.value)
        except Exception:
            base_font = "/Unknown"
    encoding = d.get("/Encoding")
    if isinstance(encoding, IndirectReference):
        try:
            obj = model.get_object(encoding)
            encoding = model.resolve(obj.value)
        except Exception:
            encoding = None
    # Type0 descriptors live on the descendant CID font.
    descriptor_source = d
    if sub_type == "/Type0":
        descendants = d.get("/DescendantFonts")
        if isinstance(descendants, list) and descendants:
            descendant = descendants[0]
            if isinstance(descendant, IndirectReference):
                try:
                    descendant = model.get_object(descendant).value
                except Exception:
                    descendant = None
            if isinstance(descendant, PdfDict):
                descriptor_source = descendant
    descriptor = descriptor_source.get("/FontDescriptor")
    embedded = False
    if isinstance(descriptor, IndirectReference):
        try:
            desc_obj = model.get_object(descriptor)
            desc_val = model.resolve(desc_obj.value)
        except Exception:
            desc_val = None
    elif isinstance(descriptor, PdfDict):
        desc_val = descriptor
    else:
        desc_val = None
    if isinstance(desc_val, PdfDict):
        embedded = (
            desc_val.get("/FontFile") is not None
            or desc_val.get("/FontFile2") is not None
            or desc_val.get("/FontFile3") is not None
        )
    # Subset detection (name prefix ABCDEF+)
    subset = False
    if isinstance(base_font, str):
        base_name = base_font.lstrip("/")
        if len(base_name) >= 7 and base_name[6] == "+":
            subset = True
    # CMap for Type 0 fonts
    cmap = None
    if sub_type == "/Type0":
        cmap_ref = d.get("/ToUnicode")
        if isinstance(cmap_ref, IndirectReference):
            cmap = f"obj-{cmap_ref.obj_num}"
        elif isinstance(cmap_ref, str):
            cmap = cmap_ref
    return FontInfo(
        name=name,
        type=str(sub_type),
        base_font=str(base_font) if isinstance(base_font, str) else "/Unknown",
        encoding=str(encoding) if isinstance(encoding, str) else None,
        embedded=embedded,
        subset=subset,
        cmap=cmap,
    )


def inventory_images(model: PdfObjectModel, resources: PdfDict | None) -> list[ImageInfo]:
    """Inventory image XObject resources."""
    if resources is None:
        return []
    xobject = resources.get("/XObject")
    if isinstance(xobject, IndirectReference):
        obj = model.get_object(xobject)
        xobject = model.resolve(obj.value)
    if not isinstance(xobject, PdfDict):
        return []
    images: list[ImageInfo] = []
    for name, xobj_val in xobject.entries.items():
        if isinstance(xobj_val, IndirectReference):
            obj = model.get_object(xobj_val)
            if (
                obj.is_stream
                and isinstance(obj.value, tuple)
                and isinstance(obj.value[0], PdfDict)
            ):
                xobj_val = obj.value[0]
            else:
                xobj_val = model.resolve(obj.value)
        if isinstance(xobj_val, PdfDict):
            sub_type = xobj_val.get("/Subtype")
            if sub_type == "/Image":
                images.append(_build_image_info(name, xobj_val))
    return images


def _build_image_info(name: str, d: PdfDict) -> ImageInfo:
    """Build an ImageInfo from an Image XObject dictionary."""
    width = d.get("/Width", 0)
    height = d.get("/Height", 0)
    bpc = d.get("/BitsPerComponent", 8)
    cs = d.get("/ColorSpace", "/DeviceRGB")
    filter_spec = d.get("/Filter", [])
    filters: list[str] = []
    if isinstance(filter_spec, str):
        filters = [filter_spec]
    elif isinstance(filter_spec, list):
        filters = [str(f) for f in filter_spec if isinstance(f, str)]
    return ImageInfo(
        name=name,
        width=int(width) if isinstance(width, int) else 0,
        height=int(height) if isinstance(height, int) else 0,
        bits_per_component=int(bpc) if isinstance(bpc, int) else 8,
        color_space=str(cs) if isinstance(cs, str) else "/DeviceRGB",
        filter_chain=filters,
    )
