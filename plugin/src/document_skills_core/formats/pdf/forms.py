"""AcroForm value and appearance updates for the Core-safe field subset.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .form_updates import (
    acroform_field_objects as _acroform_field_objects,
    acroform_object as _acroform_object,
    appearance_stream as _appearance_stream,
    button_on_states as _button_on_states,
    choice_options as _choice_options,
    flattened_text_operators as _flattened_text_operators,
    radio_widgets as _radio_widgets,
    remove_acroform_reference as _remove_acroform_reference,
    remove_annotation_references as _remove_annotation_references,
    remove_field_references as _remove_field_references,
    replace_button_value_and_state as _replace_button_value_and_state,
    replace_field_value_and_appearance as _replace_field_value_and_appearance,
    replace_name_entry as _replace_name_entry,
    set_need_appearances_false as _set_need_appearances_false,
    write_form_pdf as _write_pdf,
)
from .object_model import IndirectReference, PdfDict, PdfObjectModel, parse_pdf
from .page_tree import walk_pages


def fill_acroform(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fill text fields and write deterministic widget appearance streams."""
    flatten = primitive["flatten"]
    pages = walk_pages(model)
    page_numbers = {page.obj_num: page.page_number for page in pages}
    pages_by_object = {page.obj_num: page for page in pages}
    page_fonts = {
        page.obj_num: _page_font_reference(page.resources)
        for page in pages
    }
    requested = primitive["fields"]
    replacements: dict[int, bytes] = {}
    added_objects: dict[int, bytes] = {}
    changed: set[int] = set()
    removed: set[int] = set()
    content_additions: dict[int, bytes] = {}
    page_annotation_removals: dict[int, set[int]] = {}
    filled: list[str] = []
    filled_types: dict[str, str] = {}
    appearance_updates = 0
    next_object = max(model.objects) + 1

    for obj_num, obj in sorted(model.objects.items()):
        value = obj.value
        if not isinstance(value, PdfDict):
            continue
        name = value.get("/T")
        if not isinstance(name, str) or name not in requested:
            continue
        field_type = value.get("/FT")
        requested_value = requested[name]
        if field_type == "/Btn":
            if flatten:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Flattening button fields is not implemented.",
                    status="enhancement_required",
                    details={"field": name, "field_type": field_type},
                )
            field_flags = value.get("/Ff", 0)
            is_radio = isinstance(field_flags, int) and bool(field_flags & 32768)
            if is_radio:
                if not isinstance(requested_value, str):
                    raise DocumentSkillsError(
                        ErrorCode.REQUEST_INVALID,
                        "Radio field values must be strings.",
                        status="invalid_request",
                        details={"field": name},
                    )
                widgets = _radio_widgets(model, value, name)
                allowed_states = sorted({state for _, states in widgets for state in states})
                requested_state = "/" + requested_value.removeprefix("/")
                if requested_state not in allowed_states:
                    raise DocumentSkillsError(
                        ErrorCode.REQUEST_INVALID,
                        "Radio field value is not one of the allowed appearance states.",
                        status="invalid_request",
                        details={
                            "field": name,
                            "allowed_values": [state.removeprefix("/") for state in allowed_states],
                        },
                    )
                replacements[obj_num] = _replace_name_entry(
                    obj.payload_bytes,
                    b"V",
                    requested_state,
                )
                changed.add(obj_num)
                for widget, states in widgets:
                    state = requested_state if requested_state in states else "/Off"
                    replacements[widget.obj_num] = _replace_name_entry(
                        widget.payload_bytes,
                        b"AS",
                        state,
                    )
                    changed.add(widget.obj_num)
                filled.append(name)
                filled_types[name] = "radio"
                appearance_updates += len(widgets)
                continue
            if type(requested_value) is not bool:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "Checkbox field values must be boolean.",
                    status="invalid_request",
                    details={"field": name},
                )
            on_states = _button_on_states(value)
            if len(on_states) != 1:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Checkbox requires one deterministic on-state appearance.",
                    status="enhancement_required",
                    details={"field": name, "states": on_states},
                )
            state = on_states[0] if requested_value else "/Off"
            replacements[obj_num] = _replace_button_value_and_state(
                obj.payload_bytes,
                state,
            )
            changed.add(obj_num)
            filled.append(name)
            filled_types[name] = "checkbox"
            appearance_updates += 1
            continue
        if field_type not in {"/Tx", "/Ch"}:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "This AcroForm field type is not implemented.",
                status="enhancement_required",
                details={"field": name, "field_type": field_type},
            )
        if not isinstance(requested_value, str):
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Text and choice field values must be strings.",
                status="invalid_request",
                details={"field": name},
            )
        filled_type = "choice" if field_type == "/Ch" else "text"
        if field_type == "/Ch":
            options = _choice_options(value)
            if requested_value not in options:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "Choice field value is not one of the allowed options.",
                    status="invalid_request",
                    details={"field": name, "allowed_values": options},
                )
        rect = _field_rect(value, name)
        page_ref = value.get("/P")
        page_obj_num = page_ref.obj_num if isinstance(page_ref, IndirectReference) else None
        if page_obj_num not in page_numbers:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Form widget page association is required for appearance generation.",
                status="enhancement_required",
                details={"field": name},
            )
        font_ref = page_fonts.get(page_obj_num)
        if font_ref is None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Form widget has no usable Helvetica resource.",
                status="enhancement_required",
                details={"field": name},
            )
        if flatten:
            page = pages_by_object[page_obj_num]
            if not page.contents:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Flatten requires an editable page content stream.",
                    status="enhancement_required",
                    details={"field": name},
                )
            content_obj_num = page.contents[0].obj_num
            content_additions[content_obj_num] = (
                content_additions.get(content_obj_num, b"")
                + _flattened_text_operators(requested_value, rect)
            )
            page_annotation_removals.setdefault(page_obj_num, set()).add(obj_num)
            changed.update({content_obj_num, page_obj_num})
            removed.add(obj_num)
            filled.append(name)
            filled_types[name] = filled_type
            appearance_updates += 1
            continue
        appearance_object = next_object
        next_object += 1
        added_objects[appearance_object] = _appearance_stream(
            appearance_object,
            requested_value,
            rect,
            font_ref,
        )
        replacements[obj_num] = _replace_field_value_and_appearance(
            obj.payload_bytes,
            requested_value,
            appearance_object,
        )
        changed.add(obj_num)
        filled.append(name)
        filled_types[name] = filled_type
        appearance_updates += 1

    missing = sorted(set(requested) - set(filled))
    if missing:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Requested AcroForm fields were not found.",
            status="invalid_request",
            details={"missing_fields": missing},
        )
    acroform_object = _acroform_object(model)
    if flatten:
        if acroform_object is None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Flatten requires an indirect AcroForm dictionary.",
                status="enhancement_required",
            )
        top_level_fields = _acroform_field_objects(model, acroform_object)
        if not removed.issubset(top_level_fields):
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Flattening nested AcroForm field graphs is not implemented.",
                status="enhancement_required",
                details={"capability": "pdf.nested-form-flatten"},
            )
        remaining_fields = top_level_fields - removed
        if remaining_fields:
            replacements[acroform_object] = _remove_field_references(
                model.objects[acroform_object].payload_bytes,
                removed,
            )
            changed.add(acroform_object)
        else:
            catalog_object = model.catalog_ref.obj_num
            replacements[catalog_object] = _remove_acroform_reference(
                model.objects[catalog_object].payload_bytes
            )
            changed.add(catalog_object)
            removed.add(acroform_object)
        for page_obj_num, annotations in page_annotation_removals.items():
            replacements[page_obj_num] = _remove_annotation_references(
                model.objects[page_obj_num].payload_bytes,
                annotations,
            )
    elif acroform_object is not None:
        replacements[acroform_object] = _set_need_appearances_false(
            model.objects[acroform_object].payload_bytes
        )
        changed.add(acroform_object)

    output_bytes = _write_pdf(
        model,
        replacements,
        added_objects,
        removed=removed,
        content_additions=content_additions,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=changed,
        added=set(added_objects),
        removed=removed,
    )
    return {
        "primitive": "form_fill",
        "fields_filled": filled,
        "field_types": filled_types,
        "appearances_written": appearance_updates,
        "flattened": flatten,
        "need_appearances": None if flatten else False,
        "preservation": manifest,
    }, manifest


def _page_font_reference(resources: PdfDict | None) -> IndirectReference | None:
    if resources is None:
        return None
    fonts = resources.get("/Font")
    if not isinstance(fonts, PdfDict):
        return None
    helvetica = fonts.get("/Helv") or fonts.get("/F1")
    return helvetica if isinstance(helvetica, IndirectReference) else None


def _field_rect(field: PdfDict, name: str) -> tuple[float, float, float, float]:
    rect = field.get("/Rect")
    if not isinstance(rect, list) or len(rect) < 4:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Form widget requires a four-number Rect.",
            status="invalid_request",
            details={"field": name},
        )
    try:
        return tuple(float(value) for value in rect[:4])
    except (TypeError, ValueError) as error:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Form widget Rect contains a non-number.",
            status="invalid_request",
            details={"field": name},
        ) from error
