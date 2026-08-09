"""Text block, AcroForm field, annotation, outline, and embedded-file mapping.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from typing import Any

from .actions import ActionClassification, classify_actions
from .content_streams import TextBlock, extract_content_stream, walk_text_operators
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .resources import FontInfo, inventory_fonts, inventory_images, ImageInfo


@dataclass(frozen=True)
class AcroFieldInfo:
    """AcroForm field inventory entry."""
    qualified_name: str
    field_type: str
    flags: int
    value_type: str
    annotation_rect: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class AnnotationInfo:
    """Annotation inventory entry."""
    page: int
    subtype: str
    rectangle: tuple[float, float, float, float] | None
    action_kind: str | None


@dataclass(frozen=True)
class OutlineInfo:
    """Outline/bookmark entry."""
    title: str
    destination_page: int | None
    action_kind: str | None


@dataclass(frozen=True)
class EmbeddedFileInfo:
    """Embedded file inventory entry."""
    relationship: str
    filename: str
    mime_type: str
    size: int


def map_text_blocks(
    model: PdfObjectModel, pages: list[PageInfo], max_blocks_per_page: int = 5_000
) -> list[TextBlock]:
    """Extract text blocks from all pages."""
    all_blocks: list[TextBlock] = []
    for page in pages:
        content = extract_content_stream(model, page.contents, page.page_number)
        blocks = walk_text_operators(content, page.page_number)
        all_blocks.extend(blocks[:max_blocks_per_page])
    return all_blocks


def map_acroform_fields(model: PdfObjectModel) -> list[AcroFieldInfo]:
    """Inventory AcroForm fields."""
    try:
        catalog_obj = model.get_object(model.catalog_ref)
        catalog = model.resolve(catalog_obj.value)
    except Exception:
        return []
    if not isinstance(catalog, PdfDict):
        return []
    acroform = catalog.get("/AcroForm")
    if isinstance(acroform, IndirectReference):
        try:
            af_obj = model.get_object(acroform)
            acroform = model.resolve(af_obj.value)
        except Exception:
            return []
    if not isinstance(acroform, PdfDict):
        return []
    fields = acroform.get("/Fields")
    if not isinstance(fields, list):
        return []
    result: list[AcroFieldInfo] = []
    for field_ref in fields:
        if isinstance(field_ref, IndirectReference):
            try:
                f_obj = model.get_object(field_ref)
                f_val = model.resolve(f_obj.value)
                if isinstance(f_val, PdfDict):
                    result.append(_build_field_info(f_val))
            except Exception:
                pass
    return result


def _build_field_info(d: PdfDict) -> AcroFieldInfo:
    """Build an AcroFieldInfo from a field dictionary."""
    ft = d.get("/FT", "/Unknown")
    name = d.get("/T", "")
    flags = d.get("/Ff", 0)
    value = d.get("/V")
    value_type = type(value).__name__ if value is not None else "null"
    rect = d.get("/Rect")
    annotation_rect = None
    if isinstance(rect, list) and len(rect) >= 4:
        try:
            annotation_rect = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
        except (TypeError, ValueError):
            pass
    field_type = "text"
    ft_str = str(ft) if isinstance(ft, str) else ""
    if ft_str == "/Tx":
        field_type = "text"
    elif ft_str == "/Btn":
        field_type = "checkbox"
    elif ft_str == "/Ch":
        field_type = "choice"
    elif ft_str == "/Sig":
        field_type = "signature"
    return AcroFieldInfo(
        qualified_name=str(name) if isinstance(name, str) else "",
        field_type=field_type,
        flags=int(flags) if isinstance(flags, int) else 0,
        value_type=value_type,
        annotation_rect=annotation_rect,
    )


def map_annotations(model: PdfObjectModel, pages: list[PageInfo]) -> list[AnnotationInfo]:
    """Inventory annotations across all pages."""
    result: list[AnnotationInfo] = []
    for page in pages:
        annots = _get_page_annotations(model, page)
        for annot_val in annots:
            if isinstance(annot_val, PdfDict):
                subtype = annot_val.get("/Subtype", "/Unknown")
                rect = annot_val.get("/Rect")
                rectangle = None
                if isinstance(rect, list) and len(rect) >= 4:
                    try:
                        rectangle = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
                    except (TypeError, ValueError):
                        pass
                action_kind = None
                action = annot_val.get("/A")
                if isinstance(action, PdfDict):
                    s = action.get("/S", "")
                    action_kind = str(s) if isinstance(s, str) else None
                result.append(AnnotationInfo(
                    page=page.page_number,
                    subtype=str(subtype) if isinstance(subtype, str) else "/Unknown",
                    rectangle=rectangle,
                    action_kind=action_kind,
                ))
    return result


def _get_page_annotations(model: PdfObjectModel, page: PageInfo) -> list:
    """Get annotation list from a page's dictionary."""
    page_obj = model.objects.get(page.obj_num)
    if page_obj is None:
        return []
    page_val = model.resolve(page_obj.value)
    if not isinstance(page_val, PdfDict):
        return []
    annots = page_val.get("/Annots")
    if isinstance(annots, list):
        return annots
    return []


def map_outlines(model: PdfObjectModel) -> list[OutlineInfo]:
    """Inventory outline/bookmark items."""
    try:
        catalog_obj = model.get_object(model.catalog_ref)
        catalog = model.resolve(catalog_obj.value)
    except Exception:
        return []
    if not isinstance(catalog, PdfDict):
        return []
    outlines = catalog.get("/Outlines")
    if isinstance(outlines, IndirectReference):
        try:
            o_obj = model.get_object(outlines)
            outlines = model.resolve(o_obj.value)
        except Exception:
            return []
    if not isinstance(outlines, PdfDict):
        return []
    result: list[OutlineInfo] = []
    first = outlines.get("/First")
    visited: set[int] = set()
    current = first
    while isinstance(current, IndirectReference):
        if current.obj_num in visited:
            break
        visited.add(current.obj_num)
        try:
            item_obj = model.get_object(current)
            item_val = model.resolve(item_obj.value)
        except Exception:
            break
        if not isinstance(item_val, PdfDict):
            break
        title = item_val.get("/Title", "")
        result.append(OutlineInfo(
            title=str(title) if isinstance(title, str) else "",
            destination_page=None,
            action_kind=None,
        ))
        current = item_val.get("/Next")
    return result


def map_embedded_files(model: PdfObjectModel) -> list[EmbeddedFileInfo]:
    """Inventory embedded files (EF)."""
    result: list[EmbeddedFileInfo] = []
    for obj in model.objects.values():
        if isinstance(obj.value, PdfDict):
            ef = obj.value.get("/EF")
            if isinstance(ef, PdfDict):
                for rel, ef_val in ef.entries.items():
                    if isinstance(ef_val, PdfDict):
                        filename = ef_val.get("/UF") or ef_val.get("/F", "")
                        mime = ef_val.get("/Subtype", "")
                        size = ef_val.get("/Length", 0)
                        result.append(EmbeddedFileInfo(
                            relationship=rel,
                            filename=str(filename) if isinstance(filename, str) else "",
                            mime_type=str(mime) if isinstance(mime, str) else "",
                            size=int(size) if isinstance(size, int) else 0,
                        ))
    return result
