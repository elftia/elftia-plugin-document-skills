"""PDF edit primitives: merge, split, rotate, watermark, form-fill.

Each primitive preserves every untargeted page, object, stream, font, image,
annotation, form field, outline item, XMP metadata, and embedded file byte-
for-byte at the object payload level.  Copy-through byte-level mutation with
explicit changed/added object set.

Merge and split use object-number renumbering: each input's objects get a
non-overlapping offset into the output's object stream, all internal indirect
references are rewritten via the mapping, and the output gets a fresh Catalog +
Pages tree.  Split additionally computes the transitive resource closure of the
retained pages so that fonts/images/ExtGState only used by removed pages are
dropped with explicit cleanup evidence and no orphan objects remain.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mutation_plan import build_manifest as _build_manifest
from .mutation_writer import write_pdf_mutation
from .object_model import IndirectReference, PdfDict, parse_pdf, PdfObjectModel
from .object_renumbering import renumber_payload as _renumber_payload
from .object_serialization import serialize_pdf_value
from .page_tree import walk_pages


def edit_pdf(
    input_path: Path,
    output_path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute edit primitives on a PDF.

    Returns (operation_result, preservation_manifest).
    """
    primitives = arguments["primitives"]
    from .edit_pipeline import run_edit_pipeline

    return run_edit_pipeline(
        input_path,
        output_path,
        primitives,
        run_primitive=_edit_primitive,
    )


def _edit_primitive(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output_path: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one primitive to one parsed staged input."""
    prim_type = primitive["type"]

    if prim_type == "merge":
        from .page_merge_split import edit_merge

        return edit_merge(
            model,
            primitive,
            output_path,
            transitive_closure=_transitive_closure,
            build_pdf=_build_renumbered_pdf,
            renumber_payload=_renumber_payload,
        )
    elif prim_type == "split":
        from .page_merge_split import edit_split

        return edit_split(
            model,
            primitive,
            output_path,
            transitive_closure=_transitive_closure,
            build_pdf=_build_renumbered_pdf,
            renumber_payload=_renumber_payload,
        )
    elif prim_type == "rotate":
        return _edit_rotate(model, primitive, output_path, input_hashes)
    elif prim_type == "watermark":
        return _edit_watermark(model, primitive, output_path, input_hashes)
    elif prim_type == "form_fill":
        return _edit_form_fill(model, primitive, output_path, input_hashes)
    elif prim_type == "metadata_update":
        from .metadata_edit import update_metadata

        return update_metadata(
            model,
            primitive,
            output_path,
            input_hashes,
            build_manifest=_build_manifest,
        )
    elif prim_type == "outline":
        from .outlines_edit import edit_outline

        return edit_outline(
            model,
            primitive,
            output_path,
            input_hashes,
            build_manifest=_build_manifest,
        )
    elif prim_type == "annotation":
        from .annotations_edit import edit_annotation

        return edit_annotation(
            model,
            primitive,
            output_path,
            input_hashes,
            build_manifest=_build_manifest,
        )
    elif prim_type == "page_insert":
        from .page_insert import edit_page_insert

        return edit_page_insert(
            model,
            primitive,
            output_path,
            input_hashes,
        )
    elif prim_type == "page_sequence":
        from .page_sequence_edit import edit_page_sequence

        return edit_page_sequence(
            model,
            primitive,
            output_path,
        )
    elif prim_type == "page_labels":
        from .page_labels import edit_page_labels

        return edit_page_labels(
            model,
            primitive,
            output_path,
            input_hashes,
            build_manifest=_build_manifest,
        )
    elif prim_type == "redact_text":
        from .redaction import redact_literal_text

        return redact_literal_text(
            model,
            primitive,
            output_path,
            input_hashes,
            build_manifest=_build_manifest,
        )
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        f"Unknown edit primitive: {prim_type}",
        status="invalid_request",
    )


def _transitive_closure(
    model: PdfObjectModel, root_obj_nums: list[int]
) -> set[int]:
    """Compute the transitive closure of objects reachable from root_obj_nums.

    Walks the parsed values of each object and follows every IndirectReference
    recursively, collecting all reachable object numbers — EXCEPT ``/Parent``
    back-references (which point up to the intermediate /Pages node we replace
    with our own).  This identifies exactly the objects a page subset needs
    (content streams, font resources, image XObjects, ExtGState, color spaces,
    annotation appearance streams, form field objects) and nothing else.
    """
    seen: set[int] = set()
    stack: list[int] = list(root_obj_nums)
    while stack:
        num = stack.pop()
        if num in seen:
            continue
        if num not in model.objects:
            continue
        seen.add(num)
        obj = model.objects[num]
        for ref in _collect_references(obj.value, skip_parent=True):
            if ref.obj_num not in seen and ref.obj_num in model.objects:
                stack.append(ref.obj_num)
    return seen


def _collect_references(
    value: Any, skip_parent: bool = False
) -> list[IndirectReference]:
    """Collect all IndirectReference objects from a parsed PDF value tree.

    When *skip_parent* is True, ``/Parent`` back-references are not followed
    (used during merge/split closure computation since /Pages is replaced).
    """
    refs: list[IndirectReference] = []
    _collect_refs_into(value, refs, set(), skip_parent)
    return refs


def _collect_refs_into(
    value: Any,
    refs: list[IndirectReference],
    seen: set[int],
    skip_parent: bool,
) -> None:
    if isinstance(value, IndirectReference):
        if value.obj_num not in seen:
            seen.add(value.obj_num)
            refs.append(value)
    elif isinstance(value, PdfDict):
        for k, v in value.entries.items():
            if skip_parent and k == "/Parent":
                continue
            _collect_refs_into(v, refs, seen, skip_parent)
    elif isinstance(value, list):
        for v in value:
            _collect_refs_into(v, refs, seen, skip_parent)
    elif isinstance(value, tuple):
        for v in value:
            if isinstance(v, (PdfDict, list, IndirectReference)):
                _collect_refs_into(v, refs, seen, skip_parent)


def _build_renumbered_pdf(
    catalog_num: int,
    pages_num: int,
    page_refs: list[int],
    per_input: list[tuple[PdfObjectModel, dict[int, int], list[int]]],
    max_obj: int,
    info_ref: int | None,
    catalog_entries: bytes = b"",
    extra_objects: dict[int, bytes] | None = None,
    payload_replacements: list[dict[int, bytes]] | None = None,
) -> bytes:
    """Assemble a complete PDF with Catalog + Pages + renumbered objects.

    This is the shared output builder for merge and split.  The Catalog is at
    obj ``catalog_num`` and Pages at obj ``pages_num``; every input object is
    renumbered via its per-input mapping, with page-leaf /Parent references
    rewritten to point to ``pages_num``.
    """
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}

    # Catalog
    offsets[catalog_num] = len(header) + len(body)
    body.extend(f"{catalog_num} 0 obj\n".encode("ascii"))
    body.extend(f"<< /Type /Catalog /Pages {pages_num} 0 R".encode("ascii"))
    body.extend(catalog_entries)
    body.extend(b" >>")
    body.extend(b"\nendobj\n")

    # Pages
    kids = " ".join(f"{n} 0 R" for n in page_refs)
    offsets[pages_num] = len(header) + len(body)
    body.extend(f"{pages_num} 0 obj\n".encode("ascii"))
    body.extend(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode("ascii")
    )
    body.extend(b"\nendobj\n")

    # Renumbered objects from each input.  The renumbered payload already
    # contains the full "N G obj … endobj" — no extra wrapping needed.
    replacements_by_input = payload_replacements or [{} for _item in per_input]
    if len(replacements_by_input) != len(per_input):
        raise ValueError("payload_replacements must align with per_input")
    for input_index, (m, mapping, page_obj_nums) in enumerate(per_input):
        page_set = set(page_obj_nums)
        for old_num in sorted(mapping):
            new_num = mapping[old_num]
            obj = m.objects[old_num]
            is_page = old_num in page_set
            renumbered = _renumber_payload(
                replacements_by_input[input_index].get(old_num, obj.payload_bytes),
                new_obj_num=new_num,
                mapping=mapping,
                pages_obj_num=pages_num,
                is_page=is_page,
            )
            offsets[new_num] = len(header) + len(body)
            body.extend(renumbered)
            body.extend(b"\n")

    for object_number, payload in sorted((extra_objects or {}).items()):
        offsets[object_number] = len(header) + len(body)
        body.extend(payload)
        body.extend(b"\n")

    # Xref + trailer + EOF
    xref_offset = len(header) + len(body)
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {max_obj + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for i in range(1, max_obj + 1):
        offset = offsets.get(i, 0)
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    info_entry = f" /Info {info_ref} 0 R" if info_ref is not None else ""
    xref.extend(
        f"trailer\n<< /Size {max_obj + 1} /Root {catalog_num} 0 R{info_entry} >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _edit_rotate(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rotate: change only targeted pages' /Rotate entry."""
    pages = walk_pages(model)
    target_pages = set(primitive["pages"])
    degrees = primitive["degrees"]
    changed: set[int] = set()

    # Build output with modified page objects
    output_bytes = _copy_with_rotation(model, pages, target_pages, degrees, changed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)

    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = _build_manifest(input_hashes, output_hashes, changed=changed, added=set(), removed=set())
    operation_result = {
        "primitive": "rotate",
        "pages": sorted(target_pages),
        "degrees": degrees,
        "preservation": manifest,
    }
    return operation_result, manifest


def _copy_with_rotation(
    model: PdfObjectModel,
    pages: list,
    target_pages: set[int],
    degrees: int,
    changed: set[int],
) -> bytes:
    """Serialize only the selected page dictionaries with a top-level Rotate."""
    selected = {
        page.obj_num for page in pages if page.page_number in target_pages
    }
    mutations: dict[int, bytes] = {}
    for object_number in sorted(selected):
        obj = model.objects[object_number]
        if not isinstance(obj.value, PdfDict):
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Rotate target page is not a dictionary object.",
                details={"object": object_number},
            )
        page_value = PdfDict(dict(obj.value.entries))
        page_value.entries["/Rotate"] = degrees
        mutations[object_number] = (
            f"{object_number} {obj.gen_num} obj\n".encode("ascii")
            + serialize_pdf_value(page_value)
            + b"\nendobj"
        )
        changed.add(object_number)
    return write_pdf_mutation(model, mutations, {}, set())


def _edit_watermark(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Watermark: add text operators plus an effective opacity resource."""
    from .watermark import apply_text_watermark

    return apply_text_watermark(
        model,
        primitive,
        output,
        input_hashes,
        build_manifest=_build_manifest,
    )

def _edit_form_fill(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Form fill: update values plus deterministic widget appearances."""
    from .forms import fill_acroform

    return fill_acroform(
        model,
        primitive,
        output,
        input_hashes,
        build_manifest=_build_manifest,
    )
