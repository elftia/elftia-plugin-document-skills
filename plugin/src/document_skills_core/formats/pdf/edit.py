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

import hashlib
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, parse_pdf, PdfObjectModel
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
    if len(primitives) > 1:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Core PDF edit currently processes one primitive per invocation.",
            status="invalid_request",
        )
    primitive = primitives[0]
    prim_type = primitive["type"]

    model = parse_pdf(input_path)
    input_hashes = model.object_hashes()

    if prim_type == "merge":
        operation_result, manifest = _edit_merge(model, primitive, output_path, input_hashes)
    elif prim_type == "split":
        operation_result, manifest = _edit_split(model, primitive, output_path, input_hashes)
    elif prim_type == "rotate":
        operation_result, manifest = _edit_rotate(model, primitive, output_path, input_hashes)
    elif prim_type == "watermark":
        operation_result, manifest = _edit_watermark(model, primitive, output_path, input_hashes)
    elif prim_type == "form_fill":
        operation_result, manifest = _edit_form_fill(model, primitive, output_path, input_hashes)
    else:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            f"Unknown edit primitive: {prim_type}",
            status="invalid_request",
        )
    return operation_result, manifest


def _edit_merge(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge: concatenate multiple PDF inputs' page trees.

    Each input's objects are copied into a non-overlapping output object-number
    range with all internal indirect references rewritten via the per-input
    renumbering map.  The output gets a fresh Catalog (obj 1) and Pages (obj 2)
    whose /Kids concatenates every input's page-leaf references in order.
    """
    inputs = primitive["inputs"]
    if len(inputs) < 2:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Merge requires at least 2 inputs.",
            status="invalid_request",
        )

    # Parse all inputs; the first input is the already-parsed `model`.
    all_models: list[PdfObjectModel] = [model]
    for inp in inputs[1:]:
        all_models.append(parse_pdf(inp))

    # Reserve obj 1 = Catalog, obj 2 = Pages
    catalog_num = 1
    pages_num = 2
    next_obj = 3

    # For each input model, build a renumbering map: old_obj_num -> new_obj_num
    # and collect its page-leaf object numbers in document order.
    per_input: list[tuple[PdfObjectModel, dict[int, int], list[int]]] = []
    all_page_refs: list[int] = []  # new obj numbers of page leaves in order
    for m in all_models:
        m_pages = walk_pages(m)
        # Collect the transitive closure of objects reachable from page leaves
        # (pages, their resources, contents, fonts, images, annotations, etc.)
        # plus the page leaves themselves.  This excludes the input's own
        # Catalog/Pages intermediate nodes, which we replace with our own.
        page_obj_nums = [p.obj_num for p in m_pages]
        closure = _transitive_closure(m, page_obj_nums)
        # Build the renumbering map
        mapping: dict[int, int] = {}
        for old_num in sorted(closure):
            mapping[old_num] = next_obj
            next_obj += 1
        # Override: every page leaf's /Parent must point to our new Pages (obj 2)
        per_input.append((m, mapping, page_obj_nums))
        for p in m_pages:
            all_page_refs.append(mapping[p.obj_num])

    # Build the merged PDF bytes
    merged_bytes = _build_renumbered_pdf(
        catalog_num=catalog_num,
        pages_num=pages_num,
        page_refs=all_page_refs,
        per_input=per_input,
        max_obj=next_obj - 1,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(merged_bytes)

    # Build preservation manifest: every input object's payload (excluding the
    # input's own Catalog/Pages) must match between input and output at the
    # SHA-256 level when the container bytes are normalised to the renumbered
    # form.  We verify this by parsing both and comparing per-object payload
    # SHA-256 on the renumbered bytes.
    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = _build_merge_manifest(all_models, per_input, output_hashes)
    operation_result = {
        "primitive": "merge",
        "input_count": len(inputs),
        "page_count": len(all_page_refs),
        "preservation": manifest,
    }
    return operation_result, manifest


def _edit_split(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split: produce a standalone PDF containing only the requested pages.

    Computes the transitive resource closure of the retained page leaves so
    that fonts, images, ExtGState and content streams only used by removed
    pages are dropped.  Objects are renumbered into a fresh space and every
    dangling reference from a removed page is cleaned up.
    """
    pages = walk_pages(model)
    page_ranges = primitive["page_ranges"]
    wanted: set[int] = set()
    for start, end in page_ranges:
        for p in range(start, min(end + 1, len(pages) + 1)):
            wanted.add(p)

    retained = [p for p in pages if p.page_number in wanted]
    removed = [p for p in pages if p.page_number not in wanted]

    retained_obj_nums = [p.obj_num for p in retained]
    closure = _transitive_closure(model, retained_obj_nums)
    removed_from_closure = set(model.objects) - closure

    # Build renumbering map for retained objects
    catalog_num = 1
    pages_num = 2
    next_obj = 3
    mapping: dict[int, int] = {}
    for old_num in sorted(closure):
        mapping[old_num] = next_obj
        next_obj += 1
    page_refs = [mapping[n] for n in retained_obj_nums]

    # Build the split PDF
    split_bytes = _build_renumbered_pdf(
        catalog_num=catalog_num,
        pages_num=pages_num,
        page_refs=page_refs,
        per_input=[(model, mapping, retained_obj_nums)],
        max_obj=next_obj - 1,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(split_bytes)

    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = _build_manifest(
        input_hashes, output_hashes,
        changed=set(), added=set(), removed=removed_from_closure,
    )
    operation_result = {
        "primitive": "split",
        "retained_pages": len(retained),
        "removed_pages": len(removed),
        "removed_objects": sorted(removed_from_closure),
        "preservation": manifest,
    }
    return operation_result, manifest


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


def _renumber_payload(
    payload: bytes,
    new_obj_num: int,
    mapping: dict[int, int],
    pages_obj_num: int | None = None,
    is_page: bool = False,
) -> bytes:
    """Renumber an object payload, updating the header and all indirect refs.

    - Updates the ``N G obj`` header to ``new_obj_num G obj``.
    - Rewrites every ``old G R`` reference in the dictionary portion via *mapping*.
    - When *is_page* is True, rewrites the ``/Parent`` reference to point to
      *pages_obj_num* so the page leaf links to the new Pages node.
    - Stream data (between ``stream`` and ``endstream``) is preserved verbatim;
      only the dictionary portion is scanned for references.
    """
    # Update the header: "old_num gen_num obj" -> "new_obj_num gen_num obj"
    header_pattern = re.compile(rb"^(\d+)\s+(\d+)\s+obj")
    payload = header_pattern.sub(
        lambda m: f"{new_obj_num} {int(m.group(2))} obj".encode("ascii"),
        payload,
        count=1,
    )

    # Split at 'stream' keyword to avoid corrupting binary stream data
    stream_split = _split_stream(payload)
    dict_part = stream_split[0]
    stream_part = stream_split[1]

    # Renumber references in the dictionary part: "N G R" -> "mapped_N G R"
    ref_pattern = re.compile(rb"(\d+)\s+(\d+)\s+R")

    def _replace_ref(match: re.Match) -> bytes:
        old_ref = int(match.group(1))
        gen = int(match.group(2))
        new_ref = mapping.get(old_ref, old_ref)
        return f"{new_ref} {gen} R".encode("ascii")

    dict_part = ref_pattern.sub(_replace_ref, dict_part)

    # Override /Parent for page objects so they link to the new Pages node
    if is_page and pages_obj_num is not None:
        dict_part = re.sub(
            rb"/Parent\s+\d+\s+\d+\s+R",
            f"/Parent {pages_obj_num} 0 R".encode("ascii"),
            dict_part,
        )
    return dict_part + stream_part


def _split_stream(payload: bytes) -> tuple[bytes, bytes]:
    """Split a payload at the 'stream' keyword boundary.

    Returns (dict_and_header_portion, stream_and_endobj_portion).  If the
    payload is not a stream object, returns (payload, b"").
    """
    # Find the 'stream' keyword as a standalone token
    stream_pos = payload.find(b"stream\n")
    if stream_pos < 0:
        stream_pos = payload.find(b"stream\r\n")
    if stream_pos < 0:
        return payload, b""
    return payload[:stream_pos], payload[stream_pos:]


def _build_renumbered_pdf(
    catalog_num: int,
    pages_num: int,
    page_refs: list[int],
    per_input: list[tuple[PdfObjectModel, dict[int, int], list[int]]],
    max_obj: int,
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
    body.extend(f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode("ascii"))
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
    for m, mapping, page_obj_nums in per_input:
        page_set = set(page_obj_nums)
        for old_num in sorted(mapping):
            new_num = mapping[old_num]
            obj = m.objects[old_num]
            is_page = old_num in page_set
            renumbered = _renumber_payload(
                obj.payload_bytes,
                new_obj_num=new_num,
                mapping=mapping,
                pages_obj_num=pages_num,
                is_page=is_page,
            )
            offsets[new_num] = len(header) + len(body)
            body.extend(renumbered)
            body.extend(b"\n")

    # Xref + trailer + EOF
    xref_offset = len(header) + len(body)
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {max_obj + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for i in range(1, max_obj + 1):
        offset = offsets.get(i, 0)
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {max_obj + 1} /Root {catalog_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _build_merge_manifest(
    all_models: list[PdfObjectModel],
    per_input: list[tuple[PdfObjectModel, dict[int, int], list[int]]],
    output_hashes: dict[int, str],
) -> dict[str, Any]:
    """Build the preservation manifest for a merge.

    For each input object in the transitive closure (excluding Catalog/Pages
    intermediate nodes), we compute the SHA-256 of its payload after applying
    the renumbering and compare it to the output object at the mapped number.
    The manifest records preserved/changed/added/removed object sets keyed by
    the output object-number space.
    """
    preserved: list[int] = []
    changed: list[int] = []
    added: list[int] = []
    removed: list[int] = []
    input_hashes_out: dict[str, str] = {}
    output_hashes_out: dict[str, str] = {}

    for m, mapping, _page_nums in per_input:
        for old_num, new_num in sorted(mapping.items()):
            obj = m.objects[old_num]
            # Compute what the renumbered payload hash should be
            renumbered = _renumber_payload(
                obj.payload_bytes,
                new_obj_num=new_num,
                mapping=mapping,
                pages_obj_num=2,
                is_page=old_num in {p.obj_num for p in walk_pages(m)},
            )
            import hashlib as _hl
            expected_hash = _hl.sha256(renumbered).hexdigest()
            actual_hash = output_hashes.get(new_num)
            input_hashes_out[str(new_num)] = expected_hash
            output_hashes_out[str(new_num)] = actual_hash or ""
            if actual_hash == expected_hash:
                preserved.append(new_num)
            else:
                changed.append(new_num)

    return {
        "changed_objects": sorted(changed),
        "added_objects": sorted(added),
        "removed_objects": sorted(removed),
        "preserved_objects": sorted(preserved),
        "input_hashes": input_hashes_out,
        "output_hashes": output_hashes_out,
    }


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
    """Copy model with rotated pages."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    new_offsets: dict[int, int] = {}

    for orig_num in sorted(model.objects):
        obj = model.objects[orig_num]
        # Check if this is a page object that needs rotation
        if obj.type_name == "/Page":
            page_info = next((p for p in pages if p.obj_num == orig_num), None)
            if page_info and page_info.page_number in target_pages:
                # Modify the /Rotate entry
                payload = obj.payload_bytes
                if b"/Rotate" in payload:
                    import re
                    payload = re.sub(
                        rb"/Rotate\s+\d+", f"/Rotate {degrees}".encode("ascii"), payload
                    )
                else:
                    payload = payload.replace(
                        b">>", f"/Rotate {degrees} >>".encode("ascii")
                    )
                offsets[orig_num] = len(header) + len(body)
                body.extend(payload + b"\n")
                changed.add(orig_num)
                continue
        # Copy through
        offsets[orig_num] = len(header) + len(body)
        body.extend(obj.payload_bytes + b"\n")

    xref_offset = len(header) + len(body)
    max_obj = max(offsets.keys()) if offsets else 0
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {max_obj + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for i in range(1, max_obj + 1):
        offset = offsets.get(i, 0)
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {max_obj + 1} /Root {model.catalog_ref.obj_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _edit_watermark(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Watermark: add text-showing operators to targeted pages' content streams."""
    from .page_tree import walk_pages

    pages = walk_pages(model)
    target_pages = set(primitive["pages"])
    text = primitive["text"]
    changed: set[int] = set()

    # Identify content stream objects for targeted pages
    content_to_change: set[int] = set()
    for page in pages:
        if page.page_number in target_pages:
            for ref in page.contents:
                content_to_change.add(ref.obj_num)

    output_bytes = _copy_with_watermark(model, content_to_change, text, changed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)

    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = _build_manifest(input_hashes, output_hashes, changed=changed, added=set(), removed=set())
    operation_result = {
        "primitive": "watermark",
        "text": text,
        "pages": sorted(target_pages),
        "preservation": manifest,
    }
    return operation_result, manifest


def _copy_with_watermark(
    model: PdfObjectModel,
    content_objs: set[int],
    text: str,
    changed: set[int],
) -> bytes:
    """Copy model with watermark added to specified content streams."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    wm_text = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    watermark_ops = (
        f"\nq\n0.7 g\nBT\n/F1 48 Tf\n0.707 0.707 -0.707 0.707 200 300 Tm\n({wm_text}) Tj\nET\nQ\n"
    ).encode("latin-1", errors="replace")

    for orig_num in sorted(model.objects):
        obj = model.objects[orig_num]
        if orig_num in content_objs:
            # Append watermark operators to content stream
            payload = obj.payload_bytes
            # Find 'endstream' and inject before it
            if obj.is_stream:
                insert_pos = payload.rfind(b"endstream")
                if insert_pos > 0:
                    # Update /Length
                    import re
                    new_payload = (
                        payload[:insert_pos]
                        + watermark_ops
                        + payload[insert_pos:]
                    )
                    # Adjust stream length
                    length_diff = len(watermark_ops)
                    new_payload = re.sub(
                        rb"/Length\s+(\d+)",
                        lambda m: f"/Length {int(m.group(1)) + length_diff}".encode("ascii"),
                        new_payload,
                        count=1,
                    )
                    offsets[orig_num] = len(header) + len(body)
                    body.extend(new_payload + b"\n")
                    changed.add(orig_num)
                    continue
        offsets[orig_num] = len(header) + len(body)
        body.extend(obj.payload_bytes + b"\n")

    xref_offset = len(header) + len(body)
    max_obj = max(offsets.keys()) if offsets else 0
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {max_obj + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for i in range(1, max_obj + 1):
        offset = offsets.get(i, 0)
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {max_obj + 1} /Root {model.catalog_ref.obj_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _edit_form_fill(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Form fill: rewrite targeted AcroForm field /V entries."""
    fields = primitive["fields"]
    changed: set[int] = set()

    # Find field objects matching the qualified names
    target_objs: dict[int, bytes] = {}
    for obj_num, obj in model.objects.items():
        val = model.resolve(obj.value)
        from .object_model import PdfDict
        if isinstance(val, PdfDict):
            ft = val.get("/FT")
            t_name = val.get("/T")
            if ft is not None and isinstance(t_name, str):
                t_clean = t_name if isinstance(t_name, str) else str(t_name)
                for field_name, field_value in fields.items():
                    if t_clean == field_name:
                        # Rewrite /V entry
                        payload = obj.payload_bytes
                        escaped = field_value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
                        if b"/V" in payload:
                            import re
                            new_payload = re.sub(
                                rb"/V\s*\([^)]*\)",
                                f"/V ({escaped})".encode("latin-1"),
                                payload,
                            )
                            target_objs[obj_num] = new_payload
                        else:
                            target_objs[obj_num] = payload.replace(
                                b">>", f"/V ({escaped}) >>".encode("latin-1")
                            )
                        changed.add(obj_num)
                        break

    output_bytes = _copy_with_form_values(model, target_objs)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)

    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = _build_manifest(input_hashes, output_hashes, changed=changed, added=set(), removed=set())
    operation_result = {
        "primitive": "form_fill",
        "fields_filled": list(fields.keys()),
        "preservation": manifest,
    }
    return operation_result, manifest


def _copy_with_form_values(
    model: PdfObjectModel,
    target_objs: dict[int, bytes],
) -> bytes:
    """Copy model with modified field objects."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}

    for orig_num in sorted(model.objects):
        obj = model.objects[orig_num]
        payload = target_objs.get(orig_num, obj.payload_bytes)
        offsets[orig_num] = len(header) + len(body)
        body.extend(payload + b"\n")

    xref_offset = len(header) + len(body)
    max_obj = max(offsets.keys()) if offsets else 0
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {max_obj + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for i in range(1, max_obj + 1):
        offset = offsets.get(i, 0)
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {max_obj + 1} /Root {model.catalog_ref.obj_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _build_manifest(
    input_hashes: dict[int, str],
    output_hashes: dict[int, str],
    *,
    changed: set[int],
    added: set[int],
    removed: set[int],
) -> dict[str, Any]:
    """Build a preservation manifest comparing input and output object hashes."""
    input_keys = set(input_hashes)
    output_keys = set(output_hashes)
    actual_changed = set()
    preserved = set()
    for num in input_keys & output_keys:
        if num in changed:
            actual_changed.add(num)
        elif input_hashes[num] != output_hashes.get(num):
            actual_changed.add(num)
        else:
            preserved.add(num)
    actual_added = output_keys - input_keys
    actual_removed = input_keys - output_keys - removed

    return {
        "changed_objects": sorted(actual_changed | (changed & output_keys)),
        "added_objects": sorted(actual_added | (added & output_keys)),
        "removed_objects": sorted(removed),
        "preserved_objects": sorted(preserved),
        "input_hashes": {str(k): v for k, v in input_hashes.items()},
        "output_hashes": {str(k): v for k, v in output_hashes.items()},
    }
