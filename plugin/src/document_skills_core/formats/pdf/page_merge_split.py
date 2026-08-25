"""Merge/split page graphs with labels, outlines, annotations, and forms."""

from collections.abc import Callable
import hashlib
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .catalog_preservation import (
    CatalogPreservation,
    select_catalog_preservation,
    validate_catalog_safety,
)
from .form_reconciliation import (
    SelectedFormGraph,
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


def edit_merge(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    *,
    transitive_closure: Callable[[PdfObjectModel, list[int]], set[int]],
    build_pdf: Callable[..., bytes],
    renumber_payload: Callable[..., bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Concatenate multiple page trees and reconcile supported catalog graphs."""
    inputs = primitive["inputs"]
    if len(inputs) < 2:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Merge requires at least 2 inputs.",
            status="invalid_request",
        )
    donors = [
        load_hash_bound_pdf(
            Path(item["input"]),
            item["source_sha256"],
            capability="pdf.merge-source-precondition",
            field=f"merge.inputs.{input_index}.input",
        )
        for input_index, item in enumerate(inputs[1:], start=1)
    ]
    models = [model, *(donor_model for donor_model, _digest in donors)]
    next_object = 3
    per_input: list[tuple[PdfObjectModel, dict[int, int], list[int]]] = []
    selected_forms: list[SelectedFormGraph | None] = []
    label_parts: list[list[str] | None] = []
    output_outlines: list[dict[str, Any]] = []
    has_labels = False
    has_outlines = False
    page_offset = 0
    page_refs: list[int] = []
    info_ref = None
    primary_catalog: CatalogPreservation | None = None
    for model_index, current in enumerate(models):
        pages = walk_pages(current)
        page_objects = [page.obj_num for page in pages]
        page_numbers = [page.page_number for page in pages]
        labels = selected_page_labels(current, len(pages), page_numbers)
        label_parts.append(labels)
        has_labels = has_labels or labels is not None
        outlines = selected_flat_outlines(current, page_numbers)
        has_outlines = has_outlines or outlines is not None
        output_outlines.extend(
            {**outline, "page": outline["page"] + page_offset}
            for outline in (outlines or [])
        )
        page_offset += len(pages)
        closure = transitive_closure(current, page_objects)
        if model_index == 0:
            primary_catalog = select_catalog_preservation(
                current,
                transitive_closure,
            )
            closure.update(primary_catalog.required_objects)
        else:
            validate_catalog_safety(current)
        form = select_form_graph(current, page_numbers)
        if form is not None:
            closure.update(form.required_objects)
        if model_index == 0 and current.trailer.info is not None:
            closure.add(current.trailer.info.obj_num)
        mapping = {
            old_number: new_number
            for new_number, old_number in enumerate(
                sorted(closure),
                start=next_object,
            )
        }
        next_object += len(mapping)
        per_input.append((current, mapping, page_objects))
        selected_forms.append(form)
        page_refs.extend(mapping[page.obj_num] for page in pages)
        if model_index == 0 and current.trailer.info is not None:
            info_ref = mapping[current.trailer.info.obj_num]

    output_labels = _merged_labels(models, label_parts) if has_labels else None
    outlines = output_outlines if has_outlines else None
    outline_root, outline_objects = build_flat_outline_objects(
        outlines,
        page_refs,
        next_object,
    )
    next_object = max([next_object - 1, *outline_objects]) + 1
    form_selections = [
        (selection, per_input[index][1])
        for index, selection in enumerate(selected_forms)
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
    if acroform_object is not None:
        next_object += 1
    payload_replacements = [
        selection.replacements if selection is not None else {}
        for selection in selected_forms
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    if primary_catalog is None:
        raise AssertionError("Merge primary Catalog was not selected.")
    output.write_bytes(
        build_pdf(
            catalog_num=1,
            pages_num=2,
            page_refs=page_refs,
            per_input=per_input,
            max_obj=next_object - 1,
            info_ref=info_ref,
            catalog_entries=(
                primary_catalog.serialize(per_input[0][1])
                + page_labels_catalog_entry(output_labels)
                + outline_catalog_entry(outline_root)
                + acroform_catalog_entry(acroform_object)
            ),
            extra_objects={**outline_objects, **form_objects},
            payload_replacements=payload_replacements,
        )
    )
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_renumbered_manifest(
        per_input,
        output_hashes,
        renumber_payload=renumber_payload,
        payload_replacements=payload_replacements,
    )
    return {
        "primitive": "merge",
        "input_count": len(inputs),
        "source_sha256": [inputs[0]["source_sha256"], *(
            digest for _donor_model, digest in donors
        )],
        "page_count": len(page_refs),
        "form_fields": [
            name
            for selection, _mapping in form_selections
            for name in selection.field_names
        ],
        "page_labels": output_labels or [],
        "outlines": outlines or [],
        "preservation": manifest,
    }, manifest


def edit_split(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    *,
    transitive_closure: Callable[[PdfObjectModel, list[int]], set[int]],
    build_pdf: Callable[..., bytes],
    renumber_payload: Callable[..., bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Emit the requested page ranges and reconcile supported catalog graphs."""
    pages = walk_pages(model)
    wanted = {
        page
        for start, end in primitive["page_ranges"]
        for page in range(start, min(end + 1, len(pages) + 1))
    }
    retained = [page for page in pages if page.page_number in wanted]
    removed_pages = [page for page in pages if page.page_number not in wanted]
    page_objects = [page.obj_num for page in retained]
    page_numbers = [page.page_number for page in retained]
    labels = selected_page_labels(model, len(pages), page_numbers)
    outlines = selected_flat_outlines(model, page_numbers)
    closure = transitive_closure(model, page_objects)
    catalog = select_catalog_preservation(model, transitive_closure)
    closure.update(catalog.required_objects)
    form = select_form_graph(model, page_numbers)
    if form is not None:
        closure.update(form.required_objects)
    if model.trailer.info is not None:
        closure.add(model.trailer.info.obj_num)
    removed_objects = set(model.objects) - closure
    mapping = {
        old_number: new_number
        for new_number, old_number in enumerate(sorted(closure), start=3)
    }
    next_object = max(mapping.values()) + 1
    page_refs = [mapping[object_number] for object_number in page_objects]
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
    if acroform_object is not None:
        next_object += 1
    info_ref = (
        mapping[model.trailer.info.obj_num]
        if model.trailer.info is not None
        else None
    )
    payload_replacements = [form.replacements if form is not None else {}]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        build_pdf(
            catalog_num=1,
            pages_num=2,
            page_refs=page_refs,
            per_input=[(model, mapping, page_objects)],
            max_obj=next_object - 1,
            info_ref=info_ref,
            catalog_entries=(
                catalog.serialize(mapping)
                + page_labels_catalog_entry(labels)
                + outline_catalog_entry(outline_root)
                + acroform_catalog_entry(acroform_object)
            ),
            extra_objects={**outline_objects, **form_objects},
            payload_replacements=payload_replacements,
        )
    )
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_renumbered_manifest(
        [(model, mapping, page_objects)],
        output_hashes,
        renumber_payload=renumber_payload,
        payload_replacements=payload_replacements,
        removed_objects=removed_objects,
    )
    return {
        "primitive": "split",
        "retained_pages": len(retained),
        "removed_pages": len(removed_pages),
        "removed_objects": sorted(removed_objects),
        "form_fields": list(form.field_names) if form is not None else [],
        "page_labels": labels or [],
        "outlines": outlines or [],
        "preservation": manifest,
    }, manifest


def _merged_labels(
    models: list[PdfObjectModel],
    label_parts: list[list[str] | None],
) -> list[str]:
    return [
        label
        for index, labels in enumerate(label_parts)
        for label in (
            labels
            if labels is not None
            else [str(page.page_number) for page in walk_pages(models[index])]
        )
    ]


def build_renumbered_manifest(
    per_input: list[tuple[PdfObjectModel, dict[int, int], list[int]]],
    output_hashes: dict[int, str],
    *,
    renumber_payload: Callable[..., bytes],
    payload_replacements: list[dict[int, bytes]] | None = None,
    removed_objects: set[int] | None = None,
) -> dict[str, Any]:
    """Compare mapped source objects in the output identity space.

    ``input_hashes`` contains the source payload after deterministic
    renumbering. ``expected_output_hashes`` additionally accounts for explicit
    graph-reconciliation replacements. The latter is checked for every mapped
    object even when an object is intentionally listed as changed.
    """
    preserved: list[int] = []
    changed: list[int] = []
    unexpected_mismatches: list[int] = []
    input_hashes: dict[str, str] = {}
    expected_output_hashes: dict[str, str] = {}
    normalized_output_hashes: dict[str, str] = {}
    replacements_by_input = payload_replacements or [
        {} for _item in per_input
    ]
    if len(replacements_by_input) != len(per_input):
        raise ValueError("payload_replacements must align with per_input")
    for input_index, (model, mapping, page_objects) in enumerate(per_input):
        page_set = set(page_objects)
        replacements = replacements_by_input[input_index]
        for old_number, new_number in sorted(mapping.items()):
            source_payload = model.objects[old_number].payload_bytes
            expected_source = hashlib.sha256(
                renumber_payload(
                    source_payload,
                    new_obj_num=new_number,
                    mapping=mapping,
                    pages_obj_num=2,
                    is_page=old_number in page_set,
                )
            ).hexdigest()
            expected_output = hashlib.sha256(
                renumber_payload(
                    replacements.get(old_number, source_payload),
                    new_obj_num=new_number,
                    mapping=mapping,
                    pages_obj_num=2,
                    is_page=old_number in page_set,
                )
            ).hexdigest()
            actual = output_hashes.get(new_number, "")
            input_hashes[str(new_number)] = expected_source
            expected_output_hashes[str(new_number)] = expected_output
            normalized_output_hashes[str(new_number)] = actual
            if expected_source != expected_output:
                changed.append(new_number)
            elif actual == expected_source:
                preserved.append(new_number)
            if actual != expected_output:
                unexpected_mismatches.append(new_number)
    mapped = {
        new_number
        for _model, mapping, _pages in per_input
        for new_number in mapping.values()
    }
    return {
        "changed_objects": sorted(changed),
        "added_objects": sorted(set(output_hashes) - mapped),
        "removed_objects": sorted(removed_objects or set()),
        "preserved_objects": sorted(preserved),
        "input_hashes": input_hashes,
        "expected_output_hashes": expected_output_hashes,
        "output_hashes": normalized_output_hashes,
        "unexpected_mismatches": sorted(unexpected_mismatches),
    }
