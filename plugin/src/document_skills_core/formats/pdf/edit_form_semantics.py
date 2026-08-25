"""Form value and appearance assertions for the PDF edit semantic gate."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError

from .content_streams import extract_content_stream, walk_text_operators
from .form_graph import FormFieldNode, collect_form_fields
from .mapping import map_acroform_fields
from .object_model import IndirectReference, PdfDict, PdfObjectModel


def assert_form_semantics(
    model: PdfObjectModel,
    form_values: dict[str, Any],
    flattened_fields: set[str],
    failures: list[str],
) -> int:
    """Bind requested form values and flattening to reopened field state."""
    fields = {field.qualified_name: field for field in map_acroform_fields(model)}
    try:
        field_nodes = {
            field.qualified_name: field
            for field in collect_form_fields(model)
        }
    except DocumentSkillsError:
        field_nodes = {}
    for name in flattened_fields:
        if name in fields:
            failures.append(f"form-flatten:{name}")
    for name, value in form_values.items():
        field = fields.get(name)
        node = field_nodes.get(name)
        if (
            field is None
            or node is None
            or not _form_value_matches(field.value, value)
            or not _form_appearance_matches(model, node, value)
        ):
            failures.append(f"form-value:{name}")
    return len(flattened_fields) + len(form_values)


def _form_appearance_matches(
    model: PdfObjectModel,
    field: FormFieldNode,
    expected: Any,
) -> bool:
    if field.field_type in {"/Tx", "/Ch"}:
        return isinstance(expected, str) and all(
            _text_widget_appearance_matches(model, widget.value, expected)
            for widget in field.widgets
        )
    if field.field_type == "/Btn":
        return _button_widget_appearances_match(model, field, expected)
    return False


def _text_widget_appearance_matches(
    model: PdfObjectModel,
    widget_value: Any,
    expected: str,
) -> bool:
    if not isinstance(widget_value, PdfDict):
        return False
    appearance = _resolved_dictionary(model, widget_value.get("/AP"))
    if appearance is None:
        return False
    normal = appearance.get("/N")
    if not isinstance(normal, IndirectReference):
        return False
    try:
        appearance_object = model.get_object(normal)
    except DocumentSkillsError:
        return False
    if not appearance_object.is_stream or not isinstance(appearance_object.value, tuple):
        return False
    dictionary, _stream = appearance_object.value
    if (
        not isinstance(dictionary, PdfDict)
        or dictionary.get("/Type") != "/XObject"
        or dictionary.get("/Subtype") != "/Form"
    ):
        return False
    content = extract_content_stream(model, [normal], 0)
    return any(
        block.text == expected
        for block in walk_text_operators(content, 0)
    )


def _button_widget_appearances_match(
    model: PdfObjectModel,
    field: FormFieldNode,
    expected: Any,
) -> bool:
    selected_states: list[str] = []
    for widget in field.widgets:
        value = widget.value
        if not isinstance(value, PdfDict):
            return False
        appearance = _resolved_dictionary(model, value.get("/AP"))
        if appearance is None:
            return False
        normal = _resolved_dictionary(model, appearance.get("/N"))
        state = value.get("/AS")
        if normal is None or not isinstance(state, str) or state not in normal.entries:
            return False
        selected_states.append(state)
    if type(expected) is bool:
        return (
            any(state != "/Off" for state in selected_states)
            if expected
            else all(state == "/Off" for state in selected_states)
        )
    requested_state = "/" + str(expected).removeprefix("/")
    return requested_state in selected_states


def _resolved_dictionary(
    model: PdfObjectModel,
    value: Any,
) -> PdfDict | None:
    visited: set[int] = set()
    while isinstance(value, IndirectReference):
        if value.obj_num in visited:
            return None
        visited.add(value.obj_num)
        try:
            value = model.get_object(value).value
        except DocumentSkillsError:
            return None
    return value if isinstance(value, PdfDict) else None


def _form_value_matches(actual: Any, expected: Any) -> bool:
    if type(expected) is bool:
        return actual != "/Off" if expected else actual == "/Off"
    return actual == expected or actual == f"/{expected}"
