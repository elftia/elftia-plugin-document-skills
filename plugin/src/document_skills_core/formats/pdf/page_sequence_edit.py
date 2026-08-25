"""Ordered page selection for safe extract, reorder, and delete semantics.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .catalog_preservation import select_catalog_preservation
from .form_reconciliation import (
    acroform_catalog_entry,
    build_merged_acroform_object,
    select_form_graph,
)
from .object_model import PdfObjectModel, parse_pdf
from .outline_reconciliation import (
    build_flat_outline_objects,
    outline_catalog_entry,
    selected_flat_outlines,
)
from .page_labels import page_labels_catalog_entry, selected_page_labels
from .page_merge_split import build_renumbered_manifest
from .page_tree import walk_pages


def edit_page_sequence(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Emit exactly the requested unique source pages in requested order."""
    from .edit import _build_renumbered_pdf, _renumber_payload, _transitive_closure

    pages = walk_pages(model)
    requested = primitive["pages"]
    outside = [page for page in requested if page > len(pages)]
    if outside:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "page_sequence contains a page outside the document.",
            status="invalid_request",
            details={"pages": outside, "page_count": len(pages)},
        )
    page_labels = selected_page_labels(model, len(pages), requested)
    outlines = selected_flat_outlines(model, requested)
    form = select_form_graph(model, requested)
    selected_objects = [pages[page - 1].obj_num for page in requested]
    closure = _transitive_closure(model, selected_objects)
    catalog = select_catalog_preservation(model, _transitive_closure)
    closure.update(catalog.required_objects)
    if form is not None:
        closure.update(form.required_objects)
    if model.trailer.info is not None:
        closure.add(model.trailer.info.obj_num)
    removed_objects = set(model.objects) - closure
    mapping = {
        old_num: new_num
        for new_num, old_num in enumerate(sorted(closure), start=3)
    }
    page_refs = [mapping[obj_num] for obj_num in selected_objects]
    next_object = max(mapping.values()) + 1
    outline_root, outline_objects = build_flat_outline_objects(
        outlines,
        page_refs,
        next_object,
    )
    next_object = max([next_object - 1, *outline_objects]) + 1
    acroform_object = next_object if form is not None else None
    form_objects = (
        {
            acroform_object: build_merged_acroform_object(
                acroform_object,
                [(form, mapping)],
            )
        }
        if form is not None and acroform_object is not None
        else {}
    )
    extra_objects = {**outline_objects, **form_objects}
    info_ref = (
        mapping[model.trailer.info.obj_num]
        if model.trailer.info is not None
        else None
    )
    payload_replacements = [form.replacements if form is not None else {}]
    output_bytes = _build_renumbered_pdf(
        catalog_num=1,
        pages_num=2,
        page_refs=page_refs,
        per_input=[(model, mapping, selected_objects)],
        max_obj=max([*mapping.values(), *extra_objects]),
        info_ref=info_ref,
        catalog_entries=(
            catalog.serialize(mapping)
            + page_labels_catalog_entry(page_labels)
            + outline_catalog_entry(outline_root)
            + acroform_catalog_entry(acroform_object)
        ),
        extra_objects=extra_objects,
        payload_replacements=payload_replacements,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_renumbered_manifest(
        [(model, mapping, selected_objects)],
        output_hashes,
        renumber_payload=_renumber_payload,
        payload_replacements=payload_replacements,
        removed_objects=removed_objects,
    )
    return {
        "primitive": "page_sequence",
        "selected_pages": requested,
        "retained_pages": len(requested),
        "removed_pages": len(pages) - len(requested),
        "removed_objects": sorted(removed_objects),
        "page_labels": page_labels or [],
        "outlines": outlines or [],
        "form_fields": list(form.field_names) if form is not None else [],
        "preservation": manifest,
    }, manifest
