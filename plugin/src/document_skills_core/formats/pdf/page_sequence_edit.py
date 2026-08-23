"""Ordered page selection for safe extract, reorder, and delete semantics.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import PdfDict, PdfObjectModel, parse_pdf
from .page_tree import walk_pages


def edit_page_sequence(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Emit exactly the requested unique source pages in requested order."""
    from .edit import _build_renumbered_pdf, _transitive_closure

    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    coupled = sorted(
        key for key in ("/AcroForm", "/Outlines", "/PageLabels")
        if catalog.get(key) is not None
    )
    if coupled:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Page sequencing requires catalog-level page graph rewrites for this document.",
            status="enhancement_required",
            details={"capability": "pdf.page-sequence-catalog-graphs", "features": coupled},
        )
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
    selected_objects = [pages[page - 1].obj_num for page in requested]
    closure = _transitive_closure(model, selected_objects)
    if model.trailer.info is not None:
        closure.add(model.trailer.info.obj_num)
    removed_objects = set(model.objects) - closure
    mapping = {
        old_num: new_num
        for new_num, old_num in enumerate(sorted(closure), start=3)
    }
    page_refs = [mapping[obj_num] for obj_num in selected_objects]
    info_ref = (
        mapping[model.trailer.info.obj_num]
        if model.trailer.info is not None
        else None
    )
    output_bytes = _build_renumbered_pdf(
        catalog_num=1,
        pages_num=2,
        page_refs=page_refs,
        per_input=[(model, mapping, selected_objects)],
        max_obj=max(mapping.values()),
        info_ref=info_ref,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=set(),
        added=set(),
        removed=removed_objects,
    )
    return {
        "primitive": "page_sequence",
        "selected_pages": requested,
        "retained_pages": len(requested),
        "removed_pages": len(pages) - len(requested),
        "removed_objects": sorted(removed_objects),
        "preservation": manifest,
    }, manifest
