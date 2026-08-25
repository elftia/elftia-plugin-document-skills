"""Appearance painting and field-tree pruning for explicit form flattening."""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .form_appearance import FormAppearanceManager
from .form_updates import (
    append_page_content_reference,
    page_content_stream,
    remove_annotation_references,
)
from .form_widget_layout import next_object_number
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel
from .object_serialization import serialize_pdf_value


@dataclass(frozen=True)
class FormPrunePlan:
    replacements: dict[int, bytes]
    removed_objects: frozenset[int]
    changed_objects: frozenset[int]
    allowed_inbound_references: frozenset[tuple[int, str, int]]


def button_appearance_operators(
    model: PdfObjectModel,
    widget: PdfObject,
    state: str,
    rect: tuple[float, float, float, float],
) -> bytes:
    """Place one resource-free button appearance into page user space."""
    value = widget.value
    assert isinstance(value, PdfDict)
    appearance = value.get("/AP")
    normal = appearance.get("/N") if isinstance(appearance, PdfDict) else None
    reference = normal.get(state) if isinstance(normal, PdfDict) else None
    if not isinstance(reference, IndirectReference):
        _enhancement(
            "Button flatten requires an indirect normal appearance for every state.",
            object=widget.obj_num,
            state=state,
        )
    appearance_object = model.get_object(reference)
    if not appearance_object.is_stream or not isinstance(appearance_object.value, tuple):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Button appearance is not a Form XObject stream.",
            details={"object": reference.obj_num},
        )
    dictionary, stream = appearance_object.value
    if not isinstance(dictionary, PdfDict) or dictionary.get("/Subtype") != "/Form":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Button appearance is not a Form XObject stream.",
            details={"object": reference.obj_num},
        )
    resources = dictionary.get("/Resources")
    if resources is not None and (
        not isinstance(resources, PdfDict) or bool(resources.entries)
    ):
        _enhancement(
            "Button appearances with resources cannot yet be flattened.",
            object=reference.obj_num,
        )
    matrix = dictionary.get("/Matrix")
    if matrix is not None and matrix != [1, 0, 0, 1, 0, 0]:
        _enhancement(
            "Button appearances with a non-identity Matrix cannot yet be flattened.",
            object=reference.obj_num,
        )
    bbox = _rectangle(dictionary.get("/BBox"), "appearance BBox")
    bbox_width = bbox[2] - bbox[0]
    bbox_height = bbox[3] - bbox[1]
    if bbox_width <= 0 or bbox_height <= 0:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Button appearance BBox must have positive area.",
            details={"object": reference.obj_num},
        )
    scale_x = (rect[2] - rect[0]) / bbox_width
    scale_y = (rect[3] - rect[1]) / bbox_height
    translate_x = rect[0] - bbox[0] * scale_x
    translate_y = rect[1] - bbox[1] * scale_y
    matrix_operator = " ".join(
        pdf_number(component)
        for component in (scale_x, 0, 0, scale_y, translate_x, translate_y)
    )
    return b"\nq\n" + matrix_operator.encode("ascii") + b" cm\n" + stream + b"\nQ\n"


def prune_flattened_fields(
    model: PdfObjectModel,
    field_objects: set[int],
    widget_objects: set[int],
) -> FormPrunePlan:
    """Remove flattened terminals, prune empty ancestors, and update AcroForm."""
    catalog_object = model.get_object(model.catalog_ref)
    catalog = catalog_object.value
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    acroform_ref = catalog.get("/AcroForm")
    if not isinstance(acroform_ref, IndirectReference):
        _enhancement("Flatten requires an indirect AcroForm dictionary.")
    acroform_object = model.get_object(acroform_ref)
    acroform = acroform_object.value
    if not isinstance(acroform, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm is not a dictionary.")
    unsupported = [key for key in ("/XFA", "/CO") if acroform.get(key) is not None]
    if unsupported:
        _enhancement(
            "XFA and calculation-order graphs cannot be partially flattened.",
            features=unsupported,
        )
    roots = acroform.get("/Fields")
    if not isinstance(roots, list):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm Fields is not an array.")

    removed = set(field_objects) | set(widget_objects)
    replacements: dict[int, bytes] = {}
    changed: set[int] = set()
    retained_roots: list[IndirectReference] = []
    visited: set[int] = set()
    allowed_inbound: set[tuple[int, str, int]] = set()
    for root in roots:
        if not isinstance(root, IndirectReference):
            _enhancement("Direct AcroForm fields cannot be flattened.")
        if _retain_field(
            model,
            root,
            field_objects,
            widget_objects,
            removed,
            replacements,
            changed,
            visited,
            allowed_inbound,
        ):
            retained_roots.append(root)
        else:
            allowed_inbound.add((acroform_object.obj_num, "/Fields", root.obj_num))

    if retained_roots:
        updated = PdfDict(dict(acroform.entries))
        updated.entries["/Fields"] = retained_roots
        updated.entries["/NeedAppearances"] = False
        replacements[acroform_object.obj_num] = _object_payload(acroform_object, updated)
        changed.add(acroform_object.obj_num)
    else:
        updated_catalog = PdfDict(dict(catalog.entries))
        updated_catalog.entries.pop("/AcroForm", None)
        replacements[catalog_object.obj_num] = _object_payload(catalog_object, updated_catalog)
        changed.add(catalog_object.obj_num)
        removed.add(acroform_object.obj_num)
        allowed_inbound.add(
            (catalog_object.obj_num, "/AcroForm", acroform_object.obj_num)
        )
    return FormPrunePlan(
        replacements=replacements,
        removed_objects=frozenset(removed),
        changed_objects=frozenset(changed),
        allowed_inbound_references=frozenset(allowed_inbound),
    )


def audit_flattened_inbound_references(
    model: PdfObjectModel,
    removed_objects: set[int],
    allowed_references: set[tuple[int, str, int]],
) -> None:
    """Reject inbound references not removed by the bounded flatten rewrite."""
    for source_number, source in sorted(model.objects.items()):
        if source_number in removed_objects:
            continue
        for path, reference in _indirect_references(source.value):
            if reference.obj_num not in removed_objects:
                continue
            owner_key = path[0] if path and isinstance(path[0], str) else ""
            edge = (source_number, owner_key, reference.obj_num)
            if edge in allowed_references and _is_rewritten_reference_path(path):
                continue
            _enhancement(
                "Flatten would leave an external reference to a removed form object.",
                source_object=source_number,
                target_object=reference.obj_num,
                reference_path=_reference_path(path),
            )


def finalize_form_flatten(
    model: PdfObjectModel,
    replacements: dict[int, bytes],
    added_objects: dict[int, bytes],
    flattened_fields: set[int],
    flattened_widgets: set[int],
    page_annotation_removals: dict[int, set[int]],
    page_content_additions: dict[int, bytes],
    appearance_manager: FormAppearanceManager,
) -> tuple[set[int], set[int]]:
    """Prune form owners, attach page streams/resources, and audit references."""
    plan = prune_flattened_fields(model, flattened_fields, flattened_widgets)
    replacements.update(plan.replacements)
    removed = set(plan.removed_objects)
    changed = set(plan.changed_objects)
    for page_object, annotations in page_annotation_removals.items():
        replacements[page_object] = remove_annotation_references(
            replacements.get(page_object, model.objects[page_object].payload_bytes),
            annotations,
        )
    for page_object, operators in sorted(page_content_additions.items()):
        content_object = next_object_number(model, added_objects)
        added_objects[content_object] = page_content_stream(content_object, operators)
        replacements[page_object] = append_page_content_reference(
            model,
            model.objects[page_object],
            replacements.get(page_object, model.objects[page_object].payload_bytes),
            content_object,
        )
        if appearance_manager.rewrites_page(page_object):
            replacements[page_object] = appearance_manager.rewrite_page_resources(
                page_object,
                replacements[page_object],
            )
    allowed_inbound = set(plan.allowed_inbound_references)
    for page_object, annotations in page_annotation_removals.items():
        allowed_inbound.update(
            (page_object, "/Annots", annotation)
            for annotation in annotations
        )
    audit_flattened_inbound_references(model, removed, allowed_inbound)
    return removed, changed


def _retain_field(
    model: PdfObjectModel,
    reference: IndirectReference,
    flattened_fields: set[int],
    flattened_widgets: set[int],
    removed: set[int],
    replacements: dict[int, bytes],
    changed: set[int],
    visited: set[int],
    allowed_inbound: set[tuple[int, str, int]],
) -> bool:
    if reference.obj_num in visited:
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field graph contains a cycle.")
    visited.add(reference.obj_num)
    field = model.get_object(reference)
    if not isinstance(field.value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field is not a dictionary.")
    if field.obj_num in flattened_fields:
        kids = field.value.get("/Kids", [])
        if isinstance(kids, list):
            widget_kids = {
                kid.obj_num
                for kid in kids
                if isinstance(kid, IndirectReference)
                and isinstance(model.get_object(kid).value, PdfDict)
                and model.get_object(kid).value.get("/Subtype") == "/Widget"
            }
            if not widget_kids.issubset(flattened_widgets):
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "Flattened field widget set is incomplete.",
                    details={"object": field.obj_num},
                )
        return False

    kids = field.value.get("/Kids")
    if not isinstance(kids, list):
        return True
    updated_kids: list[IndirectReference] = []
    had_child_fields = False
    for kid in kids:
        if not isinstance(kid, IndirectReference):
            _enhancement("Direct AcroForm Kids cannot be flattened.")
        child = model.get_object(kid).value
        is_widget = isinstance(child, PdfDict) and child.get("/Subtype") == "/Widget"
        if is_widget:
            if kid.obj_num not in flattened_widgets:
                updated_kids.append(kid)
            else:
                allowed_inbound.add((field.obj_num, "/Kids", kid.obj_num))
            continue
        had_child_fields = True
        if _retain_field(
            model,
            kid,
            flattened_fields,
            flattened_widgets,
            removed,
            replacements,
            changed,
            visited,
            allowed_inbound,
        ):
            updated_kids.append(kid)
        else:
            allowed_inbound.add((field.obj_num, "/Kids", kid.obj_num))
    if had_child_fields and not updated_kids:
        removed.add(field.obj_num)
        return False
    if len(updated_kids) != len(kids):
        updated = PdfDict(dict(field.value.entries))
        updated.entries["/Kids"] = updated_kids
        replacements[field.obj_num] = _object_payload(field, updated)
        changed.add(field.obj_num)
    return True


def _rectangle(value: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) < 4:
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, f"Button {label} is malformed.")
    try:
        return tuple(float(component) for component in value[:4])
    except (TypeError, ValueError) as error:
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, f"Button {label} is malformed.") from error


def _indirect_references(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> list[tuple[tuple[str | int, ...], IndirectReference]]:
    references: list[tuple[tuple[str | int, ...], IndirectReference]] = []
    if isinstance(value, IndirectReference):
        references.append((path, value))
    elif isinstance(value, PdfDict):
        for key, child in value.entries.items():
            references.extend(_indirect_references(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            references.extend(_indirect_references(child, (*path, index)))
    elif isinstance(value, tuple) and value and isinstance(value[0], PdfDict):
        references.extend(_indirect_references(value[0], (*path, "<stream>")))
    return references


def _reference_path(path: tuple[str | int, ...]) -> str:
    parts: list[str] = []
    for component in path:
        if isinstance(component, int):
            parts.append(f"[{component}]")
        else:
            parts.append(component)
    return "/".join(parts) or "<root>"


def _is_rewritten_reference_path(path: tuple[str | int, ...]) -> bool:
    if path == ("/AcroForm",):
        return True
    return (
        len(path) == 2
        and path[0] in {"/Annots", "/Fields", "/Kids"}
        and isinstance(path[1], int)
    )


def _object_payload(obj: PdfObject, value: PdfDict) -> bytes:
    return (
        f"{obj.obj_num} {obj.gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(value)
        + b"\nendobj"
    )


def _enhancement(message: str, **details: object) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.form-flatten", **details},
    )
