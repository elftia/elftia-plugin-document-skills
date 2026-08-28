"""AcroForm value and appearance updates for the Core-safe field subset.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .form_appearance import FormAppearanceManager
from .form_flatten import (
    button_appearance_operators as _button_appearance_operators,
    finalize_form_flatten as _finalize_form_flatten,
)
from .form_graph import preflight_form_fill
from .form_updates import (
    appearance_stream as _appearance_stream,
    button_on_states as _button_on_states,
    choice_options as _choice_options,
    replace_name_entry as _replace_name_entry,
    replace_text_field_value as _replace_text_field_value,
    replace_widget_appearance as _replace_widget_appearance,
    set_need_appearances_false as _set_need_appearances_false,
    write_form_pdf as _write_pdf,
)
from .form_widget_layout import (
    page_font_reference as _page_font_reference,
    widget_layout as _widget_layout,
    widget_page_layout as _widget_page_layout,
    widget_value as _widget_value,
)
from .object_model import PdfDict, PdfObjectModel, parse_pdf
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
    requested = primitive["fields"]
    acroform_object, fields = preflight_form_fill(model, requested)
    pages = walk_pages(model)
    page_numbers = {page.obj_num: page.page_number for page in pages}
    pages_by_object = {page.obj_num: page for page in pages}
    page_fonts = {
        page.obj_num: _page_font_reference(
            page.resources,
            allow_f1=not flatten,
        )
        for page in pages
    }
    replacements: dict[int, bytes] = {}
    added_objects: dict[int, bytes] = {}
    appearance_manager = FormAppearanceManager(model, added_objects)
    changed: set[int] = set()
    removed: set[int] = set()
    page_content_additions: dict[int, bytes] = {}
    page_annotation_removals: dict[int, set[int]] = {}
    flattened_fields: set[int] = set()
    flattened_widgets: set[int] = set()
    filled: list[str] = []
    filled_types: dict[str, str] = {}
    appearance_updates = 0
    next_object = max(model.objects) + 1

    for field in fields:
        obj = field.field
        obj_num = obj.obj_num
        value = obj.value
        assert isinstance(value, PdfDict)
        name = field.qualified_name
        if name not in requested:
            continue
        field_type = field.field_type
        widgets = list(field.widgets)
        requested_value = requested[name]
        if field_type == "/Btn":
            is_radio = bool(field.flags & 32768)
            if is_radio:
                if not isinstance(requested_value, str):
                    raise DocumentSkillsError(
                        ErrorCode.REQUEST_INVALID,
                        "Radio field values must be strings.",
                        status="invalid_request",
                        details={"field": name},
                    )
                widget_states = [
                    (widget, _button_on_states(model, _widget_value(widget, name)))
                    for widget in widgets
                ]
                if any(len(states) != 1 for _, states in widget_states):
                    raise DocumentSkillsError(
                        ErrorCode.ENHANCEMENT_REQUIRED,
                        "Each radio widget requires one deterministic on-state appearance.",
                        status="enhancement_required",
                        details={"field": name},
                    )
                allowed_states = sorted({
                    state
                    for _, states in widget_states
                    for state in states
                })
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
                if flatten:
                    for widget, states in widget_states:
                        state = requested_state if requested_state in states else "/Off"
                        rect, page_obj_num = _widget_page_layout(
                            widget,
                            name,
                            page_numbers,
                        )
                        page_content_additions[page_obj_num] = (
                            page_content_additions.get(page_obj_num, b"")
                            + _button_appearance_operators(
                                model,
                                widget,
                                state,
                                rect,
                            )
                        )
                        page_annotation_removals.setdefault(page_obj_num, set()).add(
                            widget.obj_num
                        )
                        flattened_widgets.add(widget.obj_num)
                        changed.add(page_obj_num)
                    flattened_fields.add(obj_num)
                    filled.append(name)
                    filled_types[name] = "radio"
                    appearance_updates += len(widgets)
                    continue
                replacements[obj_num] = _replace_name_entry(
                    obj.payload_bytes,
                    b"V",
                    requested_state,
                )
                changed.add(obj_num)
                for widget, states in widget_states:
                    state = requested_state if requested_state in states else "/Off"
                    widget_payload = replacements.get(
                        widget.obj_num,
                        widget.payload_bytes,
                    )
                    replacements[widget.obj_num] = _replace_name_entry(
                        widget_payload,
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
            widget_states = [
                (widget, _button_on_states(model, _widget_value(widget, name)))
                for widget in widgets
            ]
            on_states = sorted({
                state
                for _, states in widget_states
                for state in states
            })
            if len(on_states) != 1:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Checkbox requires one deterministic on-state appearance.",
                    status="enhancement_required",
                    details={"field": name, "states": on_states},
                )
            state = on_states[0] if requested_value else "/Off"
            if flatten:
                for widget, states in widget_states:
                    widget_state = state if state in states else "/Off"
                    rect, page_obj_num = _widget_page_layout(
                        widget,
                        name,
                        page_numbers,
                    )
                    page_content_additions[page_obj_num] = (
                        page_content_additions.get(page_obj_num, b"")
                        + _button_appearance_operators(
                            model,
                            widget,
                            widget_state,
                            rect,
                        )
                    )
                    page_annotation_removals.setdefault(page_obj_num, set()).add(
                        widget.obj_num
                    )
                    flattened_widgets.add(widget.obj_num)
                    changed.add(page_obj_num)
                flattened_fields.add(obj_num)
                filled.append(name)
                filled_types[name] = "checkbox"
                appearance_updates += len(widgets)
                continue
            replacements[obj_num] = _replace_name_entry(
                obj.payload_bytes,
                b"V",
                state,
            )
            changed.add(obj_num)
            for widget, states in widget_states:
                widget_state = state if state in states else "/Off"
                widget_payload = replacements.get(
                    widget.obj_num,
                    widget.payload_bytes,
                )
                replacements[widget.obj_num] = _replace_name_entry(
                    widget_payload,
                    b"AS",
                    widget_state,
                )
                changed.add(widget.obj_num)
            filled.append(name)
            filled_types[name] = "checkbox"
            appearance_updates += len(widgets)
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
        if flatten:
            for widget in widgets:
                rect, page_obj_num, font_ref = _widget_layout(
                    model,
                    widget,
                    name,
                    page_numbers,
                    page_fonts,
                    flatten=True,
                )
                page_content_additions[page_obj_num] = (
                    page_content_additions.get(page_obj_num, b"")
                    + appearance_manager.add_text_widget(
                        page_object=page_obj_num,
                        page_resources=pages_by_object[page_obj_num].resources,
                        field=obj,
                        widget=widget,
                        field_type=field_type,
                        field_flags=field.flags,
                        value=requested_value,
                        rect=rect,
                        font_reference=font_ref,
                    )
                )
                page_annotation_removals.setdefault(page_obj_num, set()).add(
                    widget.obj_num
                )
                flattened_widgets.add(widget.obj_num)
                changed.add(page_obj_num)
            flattened_fields.add(obj_num)
            filled.append(name)
            filled_types[name] = filled_type
            appearance_updates += len(widgets)
            continue
        replacements[obj_num] = _replace_text_field_value(
            obj,
            requested_value,
        )
        changed.add(obj_num)
        for widget in widgets:
            rect, _page_obj_num, font_ref = _widget_layout(
                model,
                widget,
                name,
                page_numbers,
                page_fonts,
                flatten=False,
            )
            appearance_object = next_object
            next_object += 1
            added_objects[appearance_object] = _appearance_stream(
                appearance_object,
                requested_value,
                rect,
                font_ref,
            )
            replacements[widget.obj_num] = _replace_widget_appearance(
                model,
                widget,
                appearance_object,
                field_value=(
                    requested_value
                    if widget.obj_num == obj_num
                    else None
                ),
            )
            changed.add(widget.obj_num)
        filled.append(name)
        filled_types[name] = filled_type
        appearance_updates += len(widgets)

    missing = sorted(set(requested) - set(filled))
    if missing:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Requested AcroForm fields were not found.",
            status="invalid_request",
            details={"missing_fields": missing},
        )
    if flatten:
        flatten_removed, flatten_changed = _finalize_form_flatten(
            model,
            replacements,
            added_objects,
            flattened_fields,
            flattened_widgets,
            page_annotation_removals,
            page_content_additions,
            appearance_manager,
        )
        removed.update(flatten_removed)
        changed.update(flatten_changed)
    if not flatten and acroform_object is not None:
        replacements[acroform_object] = _set_need_appearances_false(
            model.objects[acroform_object].payload_bytes
        )
        changed.add(acroform_object)

    output_bytes = _write_pdf(
        model,
        replacements,
        added_objects,
        removed=removed,
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
