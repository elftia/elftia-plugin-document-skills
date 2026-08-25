"""Hash-bound page insertion with bounded graph copy-through."""

import hashlib
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .catalog_preservation import select_catalog_preservation, validate_catalog_safety
from .constants import MAX_PAGES
from .form_reconciliation import (
    acroform_catalog_entry,
    build_merged_acroform_object,
    select_form_graph,
)
from .hash_bound_sources import load_hash_bound_pdf
from .object_model import PdfObjectModel, parse_pdf
from .outline_reconciliation import (
    build_flat_outline_objects,
    outline_catalog_entry,
    selected_flat_outlines,
)
from .page_labels import page_labels_catalog_entry, selected_page_labels
from .page_tree import walk_pages


def edit_page_insert(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    _input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert selected pages from a hash-bound local PDF before ``at``."""
    from .edit import (
        _build_renumbered_pdf,
        _renumber_payload,
        _transitive_closure,
    )

    source = Path(primitive["input"])
    inserted_model, source_sha256 = load_hash_bound_pdf(
        source,
        primitive["source_sha256"],
        capability="pdf.page-insert-source-precondition",
        field="page_insert.input",
    )
    destination_pages = walk_pages(model)
    inserted_pages = walk_pages(inserted_model)
    at = primitive["at"]
    if at > len(destination_pages) + 1:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "page_insert.at is outside the destination page sequence.",
            status="invalid_request",
            details={"at": at, "page_count": len(destination_pages)},
        )
    selected = primitive["pages"] or [
        page.page_number for page in inserted_pages
    ]
    outside = [page for page in selected if page > len(inserted_pages)]
    if outside:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "page_insert.pages contains a page outside the inserted document.",
            status="invalid_request",
            details={"pages": outside, "page_count": len(inserted_pages)},
        )
    if len(destination_pages) + len(selected) > MAX_PAGES:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Page insertion exceeds the page limit.",
            status="invalid_request",
            details={"max_pages": MAX_PAGES},
        )

    destination_labels = selected_page_labels(
        model,
        len(destination_pages),
        [page.page_number for page in destination_pages],
    )
    inserted_labels = selected_page_labels(
        inserted_model,
        len(inserted_pages),
        selected,
    )
    output_labels = _inserted_page_labels(
        destination_labels,
        inserted_labels,
        destination_page_count=len(destination_pages),
        selected_pages=selected,
        insertion_index=at - 1,
    )
    destination_outlines = selected_flat_outlines(
        model,
        [page.page_number for page in destination_pages],
    )
    inserted_outlines = selected_flat_outlines(inserted_model, selected)
    output_outlines = _inserted_outlines(
        destination_outlines,
        inserted_outlines,
        at=at,
        inserted_page_count=len(selected),
    )
    destination_form = select_form_graph(
        model,
        [page.page_number for page in destination_pages],
    )
    inserted_form = select_form_graph(inserted_model, selected)

    destination_objects = [page.obj_num for page in destination_pages]
    inserted_objects = [inserted_pages[page - 1].obj_num for page in selected]
    destination_closure = _transitive_closure(model, destination_objects)
    destination_catalog = select_catalog_preservation(model, _transitive_closure)
    destination_closure.update(destination_catalog.required_objects)
    validate_catalog_safety(inserted_model)
    if destination_form is not None:
        destination_closure.update(destination_form.required_objects)
    if model.trailer.info is not None:
        destination_closure.add(model.trailer.info.obj_num)
    inserted_closure = _transitive_closure(inserted_model, inserted_objects)
    if inserted_form is not None:
        inserted_closure.update(inserted_form.required_objects)

    destination_mapping, next_object = _object_mapping(destination_closure, 3)
    inserted_mapping, next_object = _object_mapping(inserted_closure, next_object)
    insertion_index = at - 1
    page_refs = [
        *(destination_mapping[obj_num] for obj_num in destination_objects[:insertion_index]),
        *(inserted_mapping[obj_num] for obj_num in inserted_objects),
        *(destination_mapping[obj_num] for obj_num in destination_objects[insertion_index:]),
    ]
    outline_root, outline_objects = build_flat_outline_objects(
        output_outlines,
        page_refs,
        next_object,
    )
    next_object = max([next_object - 1, *outline_objects]) + 1
    form_selections = [
        (selection, mapping)
        for selection, mapping in (
            (destination_form, destination_mapping),
            (inserted_form, inserted_mapping),
        )
        if selection is not None
    ]
    acroform_object = next_object if form_selections else None
    form_objects = (
        {
            acroform_object: build_merged_acroform_object(
                acroform_object,
                form_selections,
            )
        }
        if acroform_object is not None
        else {}
    )
    extra_objects = {**outline_objects, **form_objects}
    info_ref = (
        destination_mapping[model.trailer.info.obj_num]
        if model.trailer.info is not None
        else None
    )
    output_bytes = _build_renumbered_pdf(
        catalog_num=1,
        pages_num=2,
        page_refs=page_refs,
        per_input=[
            (model, destination_mapping, destination_objects),
            (inserted_model, inserted_mapping, inserted_objects),
        ],
        max_obj=max([next_object - 1, *extra_objects]),
        info_ref=info_ref,
        catalog_entries=(
            destination_catalog.serialize(destination_mapping)
            + page_labels_catalog_entry(output_labels)
            + outline_catalog_entry(outline_root)
            + acroform_catalog_entry(acroform_object)
        ),
        extra_objects=extra_objects,
        payload_replacements=[
            destination_form.replacements if destination_form is not None else {},
            inserted_form.replacements if inserted_form is not None else {},
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_hashes = parse_pdf(output).object_hashes()
    manifest = _insertion_manifest(
        model,
        destination_mapping,
        destination_objects,
        destination_closure,
        inserted_mapping,
        set(extra_objects),
        output_hashes,
        renumber_payload=_renumber_payload,
    )
    return {
        "primitive": "page_insert",
        "at": at,
        "inserted_pages": selected,
        "inserted_page_count": len(selected),
        "page_count": len(page_refs),
        "source_sha256": source_sha256,
        "page_labels": output_labels or [],
        "outlines": output_outlines or [],
        "form_fields": [
            name
            for selection, _mapping in form_selections
            for name in selection.field_names
        ],
        "added_objects": manifest["added_objects"],
        "removed_objects": manifest["removed_objects"],
        "preservation": manifest,
    }, manifest


def _inserted_page_labels(
    destination_labels: list[str] | None,
    inserted_labels: list[str] | None,
    *,
    destination_page_count: int,
    selected_pages: list[int],
    insertion_index: int,
) -> list[str] | None:
    if destination_labels is None and inserted_labels is None:
        return None
    destination = destination_labels or [
        str(page) for page in range(1, destination_page_count + 1)
    ]
    inserted = inserted_labels or [str(page) for page in selected_pages]
    return [
        *destination[:insertion_index],
        *inserted,
        *destination[insertion_index:],
    ]


def _inserted_outlines(
    destination_outlines: list[dict[str, Any]] | None,
    inserted_outlines: list[dict[str, Any]] | None,
    *,
    at: int,
    inserted_page_count: int,
) -> list[dict[str, Any]] | None:
    if destination_outlines is None and inserted_outlines is None:
        return None
    destination = destination_outlines or []
    insertion_index = next(
        (
            index
            for index, outline in enumerate(destination)
            if outline["page"] >= at
        ),
        len(destination),
    )
    shifted_destination = [
        {
            **outline,
            "page": (
                outline["page"] + inserted_page_count
                if outline["page"] >= at
                else outline["page"]
            ),
        }
        for outline in destination
    ]
    shifted_inserted = [
        {**outline, "page": outline["page"] + at - 1}
        for outline in (inserted_outlines or [])
    ]
    return [
        *shifted_destination[:insertion_index],
        *shifted_inserted,
        *shifted_destination[insertion_index:],
    ]


def _object_mapping(objects: set[int], start: int) -> tuple[dict[int, int], int]:
    mapping: dict[int, int] = {}
    next_object = start
    for old_number in sorted(objects):
        mapping[old_number] = next_object
        next_object += 1
    return mapping, next_object


def _insertion_manifest(
    model: PdfObjectModel,
    mapping: dict[int, int],
    page_objects: list[int],
    closure: set[int],
    inserted_mapping: dict[int, int],
    additional_objects: set[int],
    output_hashes: dict[int, str],
    *,
    renumber_payload: Any,
) -> dict[str, Any]:
    input_hashes: dict[str, str] = {}
    normalized_output_hashes: dict[str, str] = {}
    preserved: list[int] = []
    changed: list[int] = []
    page_set = set(page_objects)
    for old_number, new_number in sorted(mapping.items()):
        expected = hashlib.sha256(
            renumber_payload(
                model.objects[old_number].payload_bytes,
                new_obj_num=new_number,
                mapping=mapping,
                pages_obj_num=2,
                is_page=old_number in page_set,
            )
        ).hexdigest()
        actual = output_hashes.get(new_number, "")
        input_hashes[str(new_number)] = expected
        normalized_output_hashes[str(new_number)] = actual
        (preserved if actual == expected else changed).append(new_number)
    return {
        "changed_objects": changed,
        "added_objects": sorted({
            1,
            2,
            *inserted_mapping.values(),
            *additional_objects,
        }),
        "removed_objects": sorted(set(model.objects) - closure),
        "preserved_objects": preserved,
        "input_hashes": input_hashes,
        "output_hashes": normalized_output_hashes,
    }
