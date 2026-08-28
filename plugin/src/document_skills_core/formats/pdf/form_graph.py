"""Strict AcroForm field-tree traversal with inherited field attributes."""

from collections.abc import Collection
from dataclasses import dataclass

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .form_updates import acroform_object
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel


@dataclass(frozen=True)
class FormFieldNode:
    field: PdfObject
    qualified_name: str
    field_type: str
    flags: int
    widgets: tuple[PdfObject, ...]


def preflight_form_fill(
    model: PdfObjectModel,
    requested_names: Collection[str],
) -> tuple[int | None, list[FormFieldNode]]:
    """Reject unsupported form containers and requested read-only fields."""
    acroform_obj_num = acroform_object(model)
    if acroform_obj_num is not None:
        acroform = model.objects[acroform_obj_num].value
        if isinstance(acroform, PdfDict) and "/XFA" in acroform:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "XFA form filling is not implemented.",
                status="enhancement_required",
                details={"capability": "pdf.form-xfa"},
            )
    fields = collect_form_fields(model)
    readonly_fields = sorted({
        field.qualified_name
        for field in fields
        if field.qualified_name in requested_names and field.flags & 1
    })
    if readonly_fields:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Read-only AcroForm fields cannot be filled.",
            status="invalid_request",
            details={
                "capability": "pdf.form-readonly",
                "readonly_fields": readonly_fields,
            },
        )
    return acroform_obj_num, fields


def collect_form_fields(model: PdfObjectModel) -> list[FormFieldNode]:
    """Collect terminal fields from an indirect, bounded AcroForm graph."""
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    acroform_ref = catalog.get("/AcroForm")
    if acroform_ref is None:
        return []
    if not isinstance(acroform_ref, IndirectReference):
        raise _unsupported("Direct AcroForm dictionaries are not implemented.")
    acroform = model.get_object(acroform_ref).value
    if not isinstance(acroform, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm is not a dictionary.")
    fields = acroform.get("/Fields")
    if not isinstance(fields, list):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm Fields is not an array.")
    result: list[FormFieldNode] = []
    visited: set[int] = set()
    for field_ref in fields:
        _walk_field(
            model,
            field_ref,
            parent_name="",
            inherited_type=None,
            inherited_flags=0,
            visited=visited,
            result=result,
        )
    names = [field.qualified_name for field in result]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise _unsupported("Terminal AcroForm field names must be unique and non-empty.")
    return result


def _walk_field(
    model: PdfObjectModel,
    field_ref: object,
    *,
    parent_name: str,
    inherited_type: str | None,
    inherited_flags: int,
    visited: set[int],
    result: list[FormFieldNode],
) -> None:
    if not isinstance(field_ref, IndirectReference):
        raise _unsupported("Direct AcroForm field dictionaries are not implemented.")
    if field_ref.obj_num in visited:
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field graph contains a cycle.")
    visited.add(field_ref.obj_num)
    field = model.get_object(field_ref)
    value = field.value
    if not isinstance(value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field is not a dictionary.")
    part = value.get("/T")
    if part is not None and not isinstance(part, str):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field name is malformed.")
    qualified_name = _qualified_name(parent_name, part)
    field_type = value.get("/FT", inherited_type)
    if field_type is not None and not isinstance(field_type, str):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field type is malformed.")
    flags = value.get("/Ff", inherited_flags)
    flags = flags if isinstance(flags, int) else inherited_flags
    widget_objects: list[PdfObject] = []
    child_fields: list[IndirectReference] = []
    kids = value.get("/Kids")
    if kids is not None and not isinstance(kids, list):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field Kids is not an array.")
    for kid_ref in kids or []:
        if not isinstance(kid_ref, IndirectReference):
            raise _unsupported("Direct AcroForm Kids entries are not implemented.")
        kid = model.get_object(kid_ref)
        if not isinstance(kid.value, PdfDict):
            raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm Kid is not a dictionary.")
        if kid.value.get("/Subtype") == "/Widget":
            widget_objects.append(kid)
        else:
            child_fields.append(kid_ref)
    if child_fields:
        for child_ref in child_fields:
            _walk_field(
                model,
                child_ref,
                parent_name=qualified_name,
                inherited_type=field_type,
                inherited_flags=flags,
                visited=visited,
                result=result,
            )
        return
    if field_type is None:
        raise _unsupported("A terminal AcroForm field has no inherited field type.")
    if value.get("/Subtype") == "/Widget" or value.get("/Rect") is not None:
        widget_objects.insert(0, field)
    if not widget_objects:
        raise _unsupported("A terminal AcroForm field has no indirect widget.")
    result.append(FormFieldNode(
        field=field,
        qualified_name=qualified_name,
        field_type=field_type,
        flags=flags,
        widgets=tuple(widget_objects),
    ))


def _qualified_name(parent: str, part: str | None) -> str:
    if not part:
        return parent
    return f"{parent}.{part}" if parent else part


def _unsupported(message: str) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.acroform-field-graph"},
    )
