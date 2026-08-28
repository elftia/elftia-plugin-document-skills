"""AcroForm appearance, field-graph, and copy-through update helpers."""

import re

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel
from .object_serialization import serialize_pdf_value
from .trailer import trailer_bytes


def appearance_stream(
    obj_num: int,
    value: str,
    rect: tuple[float, float, float, float],
    font_ref: IndirectReference,
) -> bytes:
    width = max(1.0, rect[2] - rect[0])
    height = max(1.0, rect[3] - rect[1])
    escaped = _escape_pdf_string(value)
    stream = (
        f"q\n0.8 G 1 w 0 0 {pdf_number(width)} {pdf_number(height)} re S\n"
        f"BT /Helv 12 Tf 0 g 2 {pdf_number(max(2.0, (height - 12.0) / 2.0))} "
        f"Tm ({escaped}) Tj ET\nQ"
    ).encode("latin-1", errors="strict")
    dictionary = (
        f"<< /Type /XObject /Subtype /Form /FormType 1 "
        f"/BBox [0 0 {pdf_number(width)} {pdf_number(height)}] "
        f"/Resources << /Font << /Helv {font_ref.obj_num} {font_ref.gen_num} R >> >> "
        f"/Length {len(stream)} >>"
    ).encode("ascii")
    return (
        f"{obj_num} 0 obj\n".encode("ascii")
        + dictionary
        + b"\nstream\n"
        + stream
        + b"\nendstream\nendobj"
    )


def replace_field_value_and_appearance(
    model: PdfObjectModel,
    field: PdfObject,
    value: str,
    appearance_object: int,
) -> bytes:
    return replace_widget_appearance(
        model,
        field,
        appearance_object,
        field_value=value,
    )


def replace_text_field_value(field: PdfObject, value: str) -> bytes:
    """Set the parsed top-level field value and serialize balanced strings."""
    if not isinstance(field.value, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Text form field is not a dictionary object.",
            details={"object": field.obj_num},
        )
    updated = PdfDict(dict(field.value.entries))
    updated.entries["/V"] = value
    return (
        f"{field.obj_num} {field.gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(updated)
        + b"\nendobj"
    )


def replace_widget_appearance(
    model: PdfObjectModel,
    widget: PdfObject,
    appearance_object: int,
    *,
    field_value: str | None = None,
) -> bytes:
    """Bind a widget to a new normal appearance without mutating shared AP objects."""
    if not isinstance(widget.value, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "AcroForm widget is not a dictionary object.",
            details={"object": widget.obj_num},
        )
    appearance_value = widget.value.get("/AP")
    if isinstance(appearance_value, IndirectReference):
        appearance_value = model.get_object(appearance_value).value
    if appearance_value is None:
        appearance = PdfDict()
    elif isinstance(appearance_value, PdfDict):
        appearance = PdfDict(dict(appearance_value.entries))
    else:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "AcroForm widget AP entry is not a dictionary.",
            details={"object": widget.obj_num},
        )
    appearance.entries["/N"] = IndirectReference(appearance_object, 0)
    updated = PdfDict(dict(widget.value.entries))
    updated.entries["/AP"] = appearance
    if field_value is not None:
        updated.entries["/V"] = field_value
    return (
        f"{widget.obj_num} {widget.gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(updated)
        + b"\nendobj"
    )


def button_on_states(model: PdfObjectModel, field: PdfDict) -> list[str]:
    appearance = field.get("/AP")
    if isinstance(appearance, IndirectReference):
        appearance = model.get_object(appearance).value
    if not isinstance(appearance, PdfDict):
        return []
    normal = appearance.get("/N")
    if isinstance(normal, IndirectReference):
        normal = model.get_object(normal).value
    if not isinstance(normal, PdfDict):
        return []
    return sorted(state for state in normal.entries if state != "/Off")


def radio_widgets(
    model: PdfObjectModel,
    field: PdfDict,
    name: str,
) -> list[tuple[PdfObject, list[str]]]:
    kids = field.get("/Kids")
    if not isinstance(kids, list) or not kids:
        _enhancement("Radio fields require an indirect widget Kids array.", field=name)
    widgets: list[tuple[PdfObject, list[str]]] = []
    for kid in kids:
        if not isinstance(kid, IndirectReference):
            _enhancement("Direct radio widget dictionaries are not implemented.", field=name)
        widget = model.get_object(kid)
        if not isinstance(widget.value, PdfDict):
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Radio widget is not a dictionary object.",
                details={"field": name, "object": widget.obj_num},
            )
        states = button_on_states(model, widget.value)
        if len(states) != 1:
            _enhancement(
                "Each radio widget requires one deterministic on-state appearance.",
                field=name,
                object=widget.obj_num,
                states=states,
            )
        widgets.append((widget, states))
    return widgets


def choice_options(field: PdfDict) -> list[str]:
    options = field.get("/Opt")
    if not isinstance(options, list):
        return []
    result: list[str] = []
    for option in options:
        if isinstance(option, str):
            result.append(option)
        elif isinstance(option, list) and option and isinstance(option[0], str):
            result.append(option[0])
    return result


def replace_button_value_and_state(payload: bytes, state: str) -> bytes:
    for key in (b"V", b"AS"):
        payload = replace_name_entry(payload, key, state)
    return payload


def replace_name_entry(payload: bytes, key: bytes, state: str) -> bytes:
    encoded_state = state.encode("ascii", errors="strict")
    pattern = rb"/" + key + rb"\s*/[^\s/<>{}\[\]()]+"
    replacement = b"/" + key + b" " + encoded_state
    if re.search(pattern, payload):
        return re.sub(pattern, replacement, payload, count=1)
    return _insert_before_dictionary_end(payload, b" " + replacement)


def set_need_appearances_false(payload: bytes) -> bytes:
    if b"/NeedAppearances" in payload:
        return re.sub(
            rb"/NeedAppearances\s+(?:true|false)",
            b"/NeedAppearances false",
            payload,
            count=1,
        )
    return _insert_before_dictionary_end(payload, b" /NeedAppearances false")


def page_content_stream(obj_num: int, operators: bytes) -> bytes:
    """Serialize one unfiltered content stream owned by a flattened page."""
    return (
        f"{obj_num} 0 obj\n<< /Length {len(operators)} >>\nstream\n".encode("ascii")
        + operators
        + b"\nendstream\nendobj"
    )


def append_page_content_reference(
    model: PdfObjectModel,
    page: PdfObject,
    payload: bytes,
    content_object: int,
) -> bytes:
    """Append a content-stream reference without changing existing stream bytes."""
    page_value = page.value
    if not isinstance(page_value, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Flatten target page is not a dictionary.",
        )
    contents = page_value.get("/Contents")
    references: list[IndirectReference]
    if contents is None:
        references = []
    elif isinstance(contents, IndirectReference):
        references = [contents]
    elif isinstance(contents, list) and all(
        isinstance(item, IndirectReference) for item in contents
    ):
        references = contents
    else:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Page Contents entry is malformed or unsupported.",
        )
    if any(not model.get_object(reference).is_stream for reference in references):
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Indirect page Contents arrays cannot yet be extended safely.",
            status="enhancement_required",
            details={"capability": "pdf.form-flatten"},
        )
    reference = f"{content_object} 0 R".encode("ascii")
    array_pattern = rb"/Contents\s*\[(.*?)\]"
    array_match = re.search(array_pattern, payload, flags=re.DOTALL)
    if array_match is not None:
        body = array_match.group(1).strip()
        residual = re.sub(rb"\d+\s+\d+\s+R", b"", body)
        if residual.strip():
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Page Contents array contains a non-reference entry.",
            )
        updated = b"/Contents [" + body
        if body:
            updated += b" "
        updated += reference + b"]"
        return payload[:array_match.start()] + updated + payload[array_match.end():]

    single_pattern = rb"/Contents\s+(\d+)\s+(\d+)\s+R"
    single_match = re.search(single_pattern, payload)
    if single_match is not None:
        existing = single_match.group(1) + b" " + single_match.group(2) + b" R"
        updated = b"/Contents [" + existing + b" " + reference + b"]"
        return payload[:single_match.start()] + updated + payload[single_match.end():]
    if b"/Contents" in payload:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Page Contents entry is malformed or unsupported.",
        )
    return _insert_before_dictionary_end(payload, b" /Contents " + reference)


def remove_acroform_reference(payload: bytes) -> bytes:
    return re.sub(rb"\s*/AcroForm\s+\d+\s+\d+\s+R", b"", payload, count=1)


def remove_annotation_references(payload: bytes, annotations: set[int]) -> bytes:
    return _remove_references_from_array(payload, b"Annots", annotations)


def remove_field_references(payload: bytes, fields: set[int]) -> bytes:
    return _remove_references_from_array(payload, b"Fields", fields)


def acroform_object(model: PdfObjectModel) -> int | None:
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        return None
    acroform = catalog.get("/AcroForm")
    return acroform.obj_num if isinstance(acroform, IndirectReference) else None


def acroform_field_objects(model: PdfObjectModel, object_number: int) -> set[int]:
    acroform = model.objects[object_number].value
    if not isinstance(acroform, PdfDict):
        return set()
    fields = acroform.get("/Fields")
    if not isinstance(fields, list):
        return set()
    return {field.obj_num for field in fields if isinstance(field, IndirectReference)}


def write_form_pdf(
    model: PdfObjectModel,
    replacements: dict[int, bytes],
    added_objects: dict[int, bytes],
    *,
    removed: set[int],
) -> bytes:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for obj_num in sorted(model.objects):
        if obj_num in removed:
            continue
        payload = replacements.get(obj_num, model.objects[obj_num].payload_bytes)
        offsets[obj_num] = len(header) + len(body)
        body.extend(payload + b"\n")
    for obj_num in sorted(added_objects):
        offsets[obj_num] = len(header) + len(body)
        body.extend(added_objects[obj_num] + b"\n")
    xref_offset = len(header) + len(body)
    max_object = max((*model.objects, *added_objects))
    free_objects = [
        obj_num
        for obj_num in range(1, max_object + 1)
        if obj_num not in offsets
    ]
    next_free = {
        obj_num: free_objects[index + 1] if index + 1 < len(free_objects) else 0
        for index, obj_num in enumerate(free_objects)
    }
    xref = bytearray(f"xref\n0 {max_object + 1}\n".encode("ascii"))
    free_head = free_objects[0] if free_objects else 0
    xref.extend(f"{free_head:010d} 65535 f\r\n".encode("ascii"))
    for obj_num in range(1, max_object + 1):
        if obj_num in offsets:
            generation = (
                model.objects[obj_num].gen_num
                if obj_num in model.objects
                else 0
            )
            xref.extend(
                f"{offsets[obj_num]:010d} {generation:05d} n\r\n".encode("ascii")
            )
            continue
        original = model.objects.get(obj_num)
        generation = min(original.gen_num + 1, 65535) if original is not None else 0
        xref.extend(
            f"{next_free[obj_num]:010d} {generation:05d} f\r\n".encode("ascii")
        )
    xref.extend(trailer_bytes(model, size=max_object + 1))
    xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return header + bytes(body) + bytes(xref)


def _remove_references_from_array(
    payload: bytes,
    key: bytes,
    objects: set[int],
) -> bytes:
    pattern = rb"/" + key + rb"\s*\[(.*?)\]"
    match = re.search(pattern, payload, flags=re.DOTALL)
    if match is None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            f"PDF {key.decode('ascii')} reference array is malformed.",
        )
    body = match.group(1)
    for obj_num in sorted(objects):
        body, count = re.subn(
            rb"(?:^|\s)" + str(obj_num).encode("ascii") + rb"\s+\d+\s+R",
            b"",
            body,
            count=1,
        )
        if count != 1:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Requested form reference is absent from its owner array.",
                details={"object": obj_num, "owner": key.decode("ascii")},
            )
    replacement = b"/" + key + b" [" + body.strip() + b"]"
    return payload[:match.start()] + replacement + payload[match.end():]


def _insert_before_dictionary_end(payload: bytes, entry: bytes) -> bytes:
    end = payload.rfind(b">>")
    if end < 0:
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "Malformed PDF dictionary payload.")
    return payload[:end] + entry + b" " + payload[end:]


def _escape_pdf_string(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _enhancement(message: str, **details: object) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
