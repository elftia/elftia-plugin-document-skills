"""Widget page, rectangle, and font resolution for AcroForm updates."""

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel


def page_font_reference(
    resources: PdfDict | None,
    *,
    allow_f1: bool,
) -> IndirectReference | None:
    if resources is None:
        return None
    fonts = resources.get("/Font")
    if not isinstance(fonts, PdfDict):
        return None
    reference = fonts.get("/Helv")
    if not isinstance(reference, IndirectReference) and allow_f1:
        reference = fonts.get("/F1")
    return reference if isinstance(reference, IndirectReference) else None


def widget_value(widget: PdfObject, field_name: str) -> PdfDict:
    value = widget.value
    if not isinstance(value, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Form widget is not a dictionary.",
            details={"field": field_name},
        )
    return value


def widget_layout(
    model: PdfObjectModel,
    widget: PdfObject,
    field_name: str,
    page_numbers: dict[int, int],
    page_fonts: dict[int, IndirectReference | None],
    *,
    flatten: bool,
) -> tuple[tuple[float, float, float, float], int, IndirectReference]:
    value = widget_value(widget, field_name)
    rect = _field_rect(value, field_name)
    page_ref = value.get("/P")
    page_obj_num = page_ref.obj_num if isinstance(page_ref, IndirectReference) else None
    if page_obj_num not in page_numbers:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Form widget page association is required for appearance generation.",
            status="enhancement_required",
            details={"field": field_name},
        )
    font_ref = page_fonts.get(page_obj_num)
    if font_ref is not None:
        font = model.get_object(font_ref).value
        if not isinstance(font, PdfDict) or font.get("/Type") != "/Font":
            font_ref = None
    if font_ref is None:
        message = (
            "Text flatten requires an indirect /Helv page font resource."
            if flatten
            else "Form widget has no usable Helvetica resource."
        )
        details = {"field": field_name}
        if flatten:
            details["capability"] = "pdf.form-flatten"
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            message,
            status="enhancement_required",
            details=details,
        )
    return rect, page_obj_num, font_ref


def widget_page_layout(
    widget: PdfObject,
    field_name: str,
    page_numbers: dict[int, int],
) -> tuple[tuple[float, float, float, float], int]:
    value = widget_value(widget, field_name)
    rect = _field_rect(value, field_name)
    page_ref = value.get("/P")
    page_obj_num = page_ref.obj_num if isinstance(page_ref, IndirectReference) else None
    if page_obj_num not in page_numbers:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Form widget page association is required for flattening.",
            status="enhancement_required",
            details={"field": field_name},
        )
    return rect, page_obj_num


def next_object_number(
    model: PdfObjectModel,
    added_objects: dict[int, bytes],
) -> int:
    return max(set(model.objects) | set(added_objects)) + 1


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
