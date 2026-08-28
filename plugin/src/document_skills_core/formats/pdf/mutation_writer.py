"""Copy-through PDF writer for bounded object mutations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from .object_model import IndirectReference, PdfObjectModel
from .trailer import trailer_bytes


def write_pdf_mutation(
    model: PdfObjectModel,
    mutations: dict[int, bytes],
    additions: dict[int, bytes],
    removed: set[int],
    *,
    info_reference: IndirectReference | None = None,
) -> bytes:
    """Write a classical-xref PDF with explicit changed/added/free objects."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for obj_num in sorted(model.objects):
        if obj_num in removed:
            continue
        offsets[obj_num] = len(header) + len(body)
        body.extend(mutations.get(obj_num, model.objects[obj_num].payload_bytes) + b"\n")
    for obj_num in sorted(additions):
        offsets[obj_num] = len(header) + len(body)
        body.extend(additions[obj_num] + b"\n")
    xref_offset = len(header) + len(body)
    max_object = max(
        model.trailer.size - 1,
        *model.objects,
        *additions,
    )
    xref = bytearray(f"xref\n0 {max_object + 1}\n".encode("ascii"))
    free_objects = [
        obj_num
        for obj_num in range(1, max_object + 1)
        if obj_num not in offsets
    ]
    next_free = {
        obj_num: free_objects[index + 1] if index + 1 < len(free_objects) else 0
        for index, obj_num in enumerate(free_objects)
    }
    free_head = free_objects[0] if free_objects else 0
    xref.extend(f"{free_head:010d} 65535 f\r\n".encode("ascii"))
    for obj_num in range(1, max_object + 1):
        if obj_num in offsets:
            generation = (
                model.objects[obj_num].gen_num
                if obj_num in model.objects
                else 0
            )
            xref.extend(
                f"{offsets[obj_num]:010d} {generation:05d} n\r\n".encode("ascii")
            )
            continue
        if obj_num in removed and obj_num in model.objects:
            generation = min(model.objects[obj_num].gen_num + 1, 65535)
        else:
            entry = model.xref_entries.get(obj_num)
            generation = entry.gen_num if entry is not None else 0
        xref.extend(
            f"{next_free[obj_num]:010d} {generation:05d} f\r\n".encode("ascii")
        )
    xref.extend(
        trailer_bytes(
            model,
            size=max_object + 1,
            info_override=info_reference,
        )
    )
    xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return header + bytes(body) + bytes(xref)
