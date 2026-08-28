"""Text block, AcroForm field, annotation, outline, and embedded-file mapping.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError

from .content_streams import TextBlock, extract_content_stream, walk_text_operators
from .form_graph import collect_form_fields, FormFieldNode
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo, walk_pages


@dataclass(frozen=True)
class AcroFieldInfo:
    """AcroForm field inventory entry."""
    qualified_name: str
    field_type: str
    flags: int
    value_type: str
    value: Any
    default_value: Any
    required: bool
    readonly: bool
    options: tuple[str, ...]
    page: int | None
    widget: bool
    has_appearance: bool
    annotation_rect: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class AnnotationInfo:
    """Annotation inventory entry."""
    page: int
    index: int
    subtype: str
    rectangle: tuple[float, float, float, float] | None
    contents: str | None
    title: str | None
    color: tuple[float, float, float] | None
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
        catalog = catalog_obj.value
    except Exception:
        return []
    if not isinstance(catalog, PdfDict):
        return []
    acroform = catalog.get("/AcroForm")
    if isinstance(acroform, IndirectReference):
        try:
            af_obj = model.get_object(acroform)
            acroform = af_obj.value
        except Exception:
            return []
    if not isinstance(acroform, PdfDict):
        return []
    page_numbers = {page.obj_num: page.page_number for page in _safe_pages(model)}
    result: list[AcroFieldInfo] = []
    try:
        fields = collect_form_fields(model)
    except Exception:
        return []
    for field in fields:
        result.append(_build_field_info(field, page_numbers))
    return result


def _build_field_info(
    field: FormFieldNode,
    page_numbers: dict[int, int],
) -> AcroFieldInfo:
    """Build an AcroFieldInfo from a field dictionary."""
    d = field.field.value
    assert isinstance(d, PdfDict)
    ft = field.field_type
    name = field.qualified_name
    flags = field.flags
    value = d.get("/V")
    default_value = d.get("/DV")
    value_type = type(value).__name__ if value is not None else "null"
    widget_values = [
        widget.value
        for widget in field.widgets
        if isinstance(widget.value, PdfDict)
    ]
    rect = d.get("/Rect")
    if rect is None and widget_values:
        rect = widget_values[0].get("/Rect")
    annotation_rect = None
    if isinstance(rect, list) and len(rect) >= 4:
        try:
            annotation_rect = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
        except (TypeError, ValueError):
            pass
    numeric_flags = int(flags) if isinstance(flags, int) else 0
    widgets = widget_values
    field_type = "text"
    ft_str = str(ft) if isinstance(ft, str) else ""
    if ft_str == "/Tx":
        field_type = "text"
    elif ft_str == "/Btn":
        field_type = "radio" if numeric_flags & 32768 else "checkbox"
    elif ft_str == "/Ch":
        field_type = "choice"
    elif ft_str == "/Sig":
        field_type = "signature"
    options_value = d.get("/Opt")
    options = tuple(
        str(option)
        for option in options_value
    ) if isinstance(options_value, list) else ()
    if field_type == "radio":
        options = tuple(sorted({
            state.removeprefix("/")
            for widget in widgets
            for state in _appearance_states(widget)
            if state != "/Off"
        }))
    page_ref = d.get("/P")
    if not isinstance(page_ref, IndirectReference) and widgets:
        page_ref = widgets[0].get("/P")
    page = page_numbers.get(page_ref.obj_num) if isinstance(page_ref, IndirectReference) else None
    return AcroFieldInfo(
        qualified_name=str(name) if isinstance(name, str) else "",
        field_type=field_type,
        flags=numeric_flags,
        value_type=value_type,
        value=value,
        default_value=default_value,
        required=bool(numeric_flags & 2),
        readonly=bool(numeric_flags & 1),
        options=options,
        page=page,
        widget=bool(widgets),
        has_appearance=d.get("/AP") is not None or any(
            widget.get("/AP") is not None for widget in widgets
        ),
        annotation_rect=annotation_rect,
    )


def _appearance_states(widget: PdfDict) -> list[str]:
    appearance = widget.get("/AP")
    if not isinstance(appearance, PdfDict):
        return []
    normal = appearance.get("/N")
    if not isinstance(normal, PdfDict):
        return []
    return list(normal.entries)


def _safe_pages(model: PdfObjectModel) -> list[PageInfo]:
    from .page_tree import walk_pages

    try:
        return walk_pages(model)
    except DocumentSkillsError:
        return []


def map_annotations(model: PdfObjectModel, pages: list[PageInfo]) -> list[AnnotationInfo]:
    """Inventory annotations across all pages."""
    result: list[AnnotationInfo] = []
    for page in pages:
        annots = _get_page_annotations(model, page)
        for index, annot_val in enumerate(annots, start=1):
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
                contents = annot_val.get("/Contents")
                title = annot_val.get("/T")
                color_value = annot_val.get("/C")
                color = None
                if isinstance(color_value, list) and len(color_value) == 3:
                    try:
                        color = tuple(float(component) for component in color_value)
                    except (TypeError, ValueError):
                        pass
                result.append(AnnotationInfo(
                    page=page.page_number,
                    index=index,
                    subtype=str(subtype) if isinstance(subtype, str) else "/Unknown",
                    rectangle=rectangle,
                    contents=contents if isinstance(contents, str) else None,
                    title=title if isinstance(title, str) else None,
                    color=color,
                    action_kind=action_kind,
                ))
    return result


def _get_page_annotations(model: PdfObjectModel, page: PageInfo) -> list:
    """Get annotation list from a page's dictionary."""
    page_obj = model.objects.get(page.obj_num)
    if page_obj is None:
        return []
    page_val = page_obj.value
    if not isinstance(page_val, PdfDict):
        return []
    annots = page_val.get("/Annots")
    if not isinstance(annots, list):
        return []
    resolved = []
    for annotation in annots:
        if isinstance(annotation, IndirectReference):
            annotation = model.get_object(annotation).value
        if isinstance(annotation, PdfDict):
            resolved.append(annotation)
    return resolved


def map_outlines(model: PdfObjectModel) -> list[OutlineInfo]:
    """Inventory outline/bookmark items."""
    try:
        catalog_obj = model.get_object(model.catalog_ref)
        catalog = catalog_obj.value
    except Exception:
        return []
    if not isinstance(catalog, PdfDict):
        return []
    outlines = catalog.get("/Outlines")
    if isinstance(outlines, IndirectReference):
        try:
            o_obj = model.get_object(outlines)
            outlines = o_obj.value
        except Exception:
            return []
    if not isinstance(outlines, PdfDict):
        return []
    result: list[OutlineInfo] = []
    page_numbers = {page.obj_num: page.page_number for page in walk_pages(model)}
    first = outlines.get("/First")
    visited: set[int] = set()
    current = first
    while isinstance(current, IndirectReference):
        if current.obj_num in visited:
            break
        visited.add(current.obj_num)
        try:
            item_obj = model.get_object(current)
            item_val = item_obj.value
        except Exception:
            break
        if not isinstance(item_val, PdfDict):
            break
        title = item_val.get("/Title", "")
        destination = item_val.get("/Dest")
        destination_page = None
        if (
            isinstance(destination, list)
            and destination
            and isinstance(destination[0], IndirectReference)
        ):
            destination_page = page_numbers.get(destination[0].obj_num)
        result.append(OutlineInfo(
            title=str(title) if isinstance(title, str) else "",
            destination_page=destination_page,
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
