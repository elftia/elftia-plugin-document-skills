"""AcroForm reconciliation for page selection and insertion."""

from dataclasses import dataclass
import hashlib
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .form_graph import FormFieldNode, collect_form_fields
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .object_serialization import serialize_pdf_value
from .page_tree import walk_pages

_FORM_DEFAULT_KEYS = {"/Fields", "/DR", "/DA", "/Q", "/NeedAppearances"}


@dataclass(frozen=True)
class SelectedFormGraph:
    """The retained field forest and dependencies for selected source pages."""

    model: PdfObjectModel
    field_names: tuple[str, ...]
    top_level_fields: tuple[int, ...]
    required_objects: frozenset[int]
    replacements: dict[int, bytes]
    defaults: PdfDict


def select_form_graph(
    model: PdfObjectModel,
    selected_pages: list[int],
) -> SelectedFormGraph | None:
    """Select fields whose indirect widgets occur on retained pages."""
    acroform = _acroform_dictionary(model)
    if acroform is None:
        return None
    unsupported = sorted(set(acroform.entries) - _FORM_DEFAULT_KEYS)
    if unsupported:
        _enhancement(
            "AcroForm contains catalog-level features that cannot be reconciled safely.",
            features=unsupported,
        )
    fields = collect_form_fields(model)
    signatures = [field for field in fields if field.field_type == "/Sig"]
    if signatures:
        _enhancement(
            "Signature fields cannot be retained through page graph rewrites.",
            fields=[field.qualified_name for field in signatures],
        )
    widget_pages = _widget_pages(model)
    selected_page_set = set(selected_pages)
    retained: dict[int, tuple[FormFieldNode, set[int]]] = {}
    for field in fields:
        selected_widgets: set[int] = set()
        for widget in field.widgets:
            page = widget_pages.get(widget.obj_num)
            if page is None:
                _enhancement(
                    "Every retained AcroForm widget must be an indirect page annotation.",
                    field=field.qualified_name,
                    object=widget.obj_num,
                )
            if page in selected_page_set:
                selected_widgets.add(widget.obj_num)
        if selected_widgets:
            retained[field.field.obj_num] = (field, selected_widgets)
    if not retained:
        return None

    roots = acroform.get("/Fields")
    assert isinstance(roots, list)
    replacements: dict[int, bytes] = {}
    replacement_values: dict[int, PdfDict] = {}
    retained_objects: set[int] = set()
    retained_roots: list[int] = []
    for root in roots:
        if not isinstance(root, IndirectReference):
            _enhancement("Direct AcroForm field dictionaries cannot be reconciled.")
        if _retain_field(
            model,
            root,
            retained,
            replacements,
            replacement_values,
            retained_objects,
        ):
            retained_roots.append(root.obj_num)

    defaults = PdfDict(dict(acroform.entries))
    defaults.entries.pop("/Fields", None)
    defaults.entries["/NeedAppearances"] = False
    required = _dependency_closure(
        model,
        retained_objects,
        replacement_values,
        defaults,
    )
    names = tuple(
        field.qualified_name
        for field in fields
        if field.field.obj_num in retained
    )
    return SelectedFormGraph(
        model=model,
        field_names=names,
        top_level_fields=tuple(retained_roots),
        required_objects=frozenset(required),
        replacements=replacements,
        defaults=defaults,
    )


def build_merged_acroform_object(
    object_number: int,
    selections: list[tuple[SelectedFormGraph, dict[int, int]]],
) -> bytes:
    """Build one output AcroForm from one or more selected field forests."""
    names = [name for selection, _mapping in selections for name in selection.field_names]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        _enhancement(
            "Inserted AcroForm fields have conflicting qualified names.",
            fields=duplicates,
        )
    fields = [
        IndirectReference(mapping[field], 0)
        for selection, mapping in selections
        for field in selection.top_level_fields
    ]
    merged = PdfDict({"/Fields": fields, "/NeedAppearances": False})
    default_values: dict[str, Any] = {}
    resource_signatures: dict[tuple[str, str], str | None] = {}
    for selection, mapping in selections:
        for key, value in selection.defaults.entries.items():
            if key == "/NeedAppearances":
                continue
            if key == "/DR":
                _merge_default_resources(
                    merged,
                    selection,
                    mapping,
                    resource_signatures,
                )
                continue
            mapped = _map_references(value, mapping)
            previous = default_values.get(key)
            if previous is not None and serialize_pdf_value(previous) != serialize_pdf_value(mapped):
                _enhancement(
                    "AcroForm default values conflict across inserted documents.",
                    feature=key,
                )
            default_values[key] = mapped
            merged.entries[key] = mapped
    return (
        f"{object_number} 0 obj\n".encode("ascii")
        + serialize_pdf_value(merged)
        + b"\nendobj"
    )


def acroform_catalog_entry(object_number: int | None) -> bytes:
    if object_number is None:
        return b""
    return f" /AcroForm {object_number} 0 R".encode("ascii")


def _acroform_dictionary(model: PdfObjectModel) -> PdfDict | None:
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    reference = catalog.get("/AcroForm")
    if reference is None:
        return None
    if not isinstance(reference, IndirectReference):
        _enhancement("Direct AcroForm dictionaries cannot be reconciled.")
    value = model.get_object(reference).value
    if not isinstance(value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm is not a dictionary.")
    fields = value.get("/Fields")
    if not isinstance(fields, list):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm Fields is not an array.")
    return value


def _widget_pages(model: PdfObjectModel) -> dict[int, int]:
    result: dict[int, int] = {}
    for page in walk_pages(model):
        value = model.objects[page.obj_num].value
        assert isinstance(value, PdfDict)
        annotations = value.get("/Annots", [])
        if isinstance(annotations, IndirectReference):
            annotations = model.get_object(annotations).value
        if not isinstance(annotations, list):
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Page Annots is not a direct or indirect array.",
                details={"page": page.page_number},
            )
        for reference in annotations:
            if not isinstance(reference, IndirectReference):
                continue
            annotation = model.get_object(reference).value
            if isinstance(annotation, PdfDict) and annotation.get("/Subtype") == "/Widget":
                previous = result.setdefault(reference.obj_num, page.page_number)
                if previous != page.page_number:
                    raise DocumentSkillsError(
                        ErrorCode.ARCHIVE_UNSAFE,
                        "An AcroForm widget is attached to multiple pages.",
                        details={"object": reference.obj_num},
                    )
    return result


def _retain_field(
    model: PdfObjectModel,
    reference: IndirectReference,
    retained: dict[int, tuple[FormFieldNode, set[int]]],
    replacements: dict[int, bytes],
    replacement_values: dict[int, PdfDict],
    retained_objects: set[int],
) -> bool:
    field = model.get_object(reference)
    if not isinstance(field.value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "AcroForm field is not a dictionary.")
    updated = PdfDict(dict(field.value.entries))
    terminal = retained.get(field.obj_num)
    if terminal is not None:
        _node, selected_widgets = terminal
        kids = updated.get("/Kids")
        if isinstance(kids, list):
            selected_kids = [
                kid for kid in kids
                if isinstance(kid, IndirectReference) and kid.obj_num in selected_widgets
            ]
            updated.entries["/Kids"] = selected_kids
            retained_objects.update(kid.obj_num for kid in selected_kids)
        retained_objects.add(field.obj_num)
    else:
        kids = updated.get("/Kids")
        if not isinstance(kids, list):
            return False
        retained_kids: list[IndirectReference] = []
        for kid in kids:
            if not isinstance(kid, IndirectReference):
                _enhancement("Direct AcroForm Kids entries cannot be reconciled.")
            child = model.get_object(kid).value
            if isinstance(child, PdfDict) and child.get("/Subtype") == "/Widget":
                _enhancement("Mixed field and widget Kids cannot be reconciled safely.")
            if _retain_field(
                model,
                kid,
                retained,
                replacements,
                replacement_values,
                retained_objects,
            ):
                retained_kids.append(kid)
        if not retained_kids:
            return False
        updated.entries["/Kids"] = retained_kids
        retained_objects.add(field.obj_num)
    replacement_values[field.obj_num] = updated
    replacements[field.obj_num] = (
        f"{field.obj_num} {field.gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(updated)
        + b"\nendobj"
    )
    return True


def _dependency_closure(
    model: PdfObjectModel,
    roots: set[int],
    replacements: dict[int, PdfDict],
    defaults: PdfDict,
) -> set[int]:
    required = set(roots)
    stack = [reference.obj_num for reference in _references(defaults)]
    stack.extend(roots)
    while stack:
        object_number = stack.pop()
        if object_number not in model.objects:
            continue
        required.add(object_number)
        value = replacements.get(object_number, model.objects[object_number].value)
        for reference in _references(value):
            if reference.obj_num not in required:
                stack.append(reference.obj_num)
    return required


def _references(value: Any, *, owner_key: str | None = None) -> list[IndirectReference]:
    if isinstance(value, IndirectReference):
        return [] if owner_key in {"/Parent", "/P"} else [value]
    if isinstance(value, PdfDict):
        return [
            reference
            for key, entry in value.entries.items()
            for reference in _references(entry, owner_key=key)
        ]
    if isinstance(value, list):
        return [reference for entry in value for reference in _references(entry, owner_key=owner_key)]
    if isinstance(value, tuple):
        return [reference for entry in value for reference in _references(entry, owner_key=owner_key)]
    return []


def _merge_default_resources(
    merged: PdfDict,
    selection: SelectedFormGraph,
    mapping: dict[int, int],
    signatures: dict[tuple[str, str], str | None],
) -> None:
    resources = selection.defaults.get("/DR")
    if isinstance(resources, IndirectReference):
        resources = selection.model.get_object(resources).value
    if not isinstance(resources, PdfDict):
        _enhancement("AcroForm default resources must be a dictionary.")
    target = merged.entries.setdefault("/DR", PdfDict({}))
    assert isinstance(target, PdfDict)
    for category, entries in resources.entries.items():
        if isinstance(entries, IndirectReference):
            entries = selection.model.get_object(entries).value
        if not isinstance(entries, PdfDict):
            _enhancement("AcroForm resource categories must be dictionaries.", feature=category)
        target_entries = target.entries.setdefault(category, PdfDict({}))
        if not isinstance(target_entries, PdfDict):
            _enhancement("AcroForm resource categories conflict.", feature=category)
        for name, value in entries.entries.items():
            key = (category, name)
            signature = _resource_signature(selection.model, value)
            if name in target_entries.entries:
                if signatures.get(key) != signature or signature is None:
                    _enhancement(
                        "AcroForm default resources conflict across inserted documents.",
                        feature=f"{category}.{name}",
                    )
                continue
            target_entries.entries[name] = _map_references(value, mapping)
            signatures[key] = signature


def _resource_signature(model: PdfObjectModel, value: Any) -> str | None:
    if isinstance(value, IndirectReference):
        obj = model.get_object(value)
        if obj.is_stream:
            return None
        value = obj.value
    try:
        return hashlib.sha256(serialize_pdf_value(value)).hexdigest()
    except (TypeError, UnicodeEncodeError):
        return None


def _map_references(value: Any, mapping: dict[int, int]) -> Any:
    if isinstance(value, IndirectReference):
        mapped = mapping.get(value.obj_num)
        if mapped is None:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "A reconciled AcroForm dependency is absent from the output graph.",
                details={"object": value.obj_num},
            )
        return IndirectReference(mapped, 0)
    if isinstance(value, PdfDict):
        return PdfDict({key: _map_references(entry, mapping) for key, entry in value.entries.items()})
    if isinstance(value, list):
        return [_map_references(entry, mapping) for entry in value]
    return value


def _enhancement(message: str, **details: object) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.acroform-page-reconciliation", **details},
    )
