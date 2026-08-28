"""Exact object authorization for AcroForm fill and flatten mutations."""

from typing import Any

from .form_flatten import prune_flattened_fields
from .form_graph import FormFieldNode, preflight_form_fill
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import walk_pages


def form_fill_object_plan(
    model: PdfObjectModel,
    primitive: dict[str, Any],
) -> tuple[set[int], set[int], set[int]]:
    """Return exact existing closures and deterministic new object numbers."""
    requested = set(primitive["fields"])
    acroform_object, fields = preflight_form_fill(model, requested)
    selected = [field for field in fields if field.qualified_name in requested]
    field_objects = {field.field.obj_num for field in selected}
    widget_objects = {
        widget.obj_num for field in selected for widget in field.widgets
    }
    maximum = max(model.objects)
    if not primitive["flatten"]:
        changed = field_objects | widget_objects
        if acroform_object is not None:
            changed.add(acroform_object)
        appearance_count = sum(
            len(field.widgets)
            for field in selected
            if field.field_type in {"/Tx", "/Ch"}
        )
        return changed, _additions(maximum, appearance_count), set()

    prune = prune_flattened_fields(model, field_objects, widget_objects)
    page_objects = _widget_pages(model, selected)
    text_fields = [
        field for field in selected if field.field_type in {"/Tx", "/Ch"}
    ]
    text_pages = _widget_pages(model, text_fields)
    appearance_count = sum(len(field.widgets) for field in text_fields)
    added_count = appearance_count + len(text_pages) + len(page_objects)
    changed = set(prune.changed_objects) | page_objects
    return (
        changed,
        _additions(maximum, added_count),
        set(prune.removed_objects),
    )


def _widget_pages(
    model: PdfObjectModel,
    fields: list[FormFieldNode],
) -> set[int]:
    page_objects = {page.obj_num for page in walk_pages(model)}
    result: set[int] = set()
    for field in fields:
        for widget in field.widgets:
            value = widget.value
            page = value.get("/P") if isinstance(value, PdfDict) else None
            if isinstance(page, IndirectReference) and page.obj_num in page_objects:
                result.add(page.obj_num)
    return result


def _additions(maximum: int, count: int) -> set[int]:
    return set(range(maximum + 1, maximum + count + 1))
