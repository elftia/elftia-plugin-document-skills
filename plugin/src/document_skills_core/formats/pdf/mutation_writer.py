"""Copy-through PDF writer for bounded object mutations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from .object_model import PdfObjectModel
from .trailer import trailer_bytes


def write_pdf_mutation(
    model: PdfObjectModel,
    mutations: dict[int, bytes],
    additions: dict[int, bytes],
    removed: set[int],
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
    max_object = max(set(model.objects) | set(additions))
    xref = bytearray(f"xref\n0 {max_object + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for obj_num in range(1, max_object + 1):
        if obj_num in offsets:
            xref.extend(f"{offsets[obj_num]:010d} 00000 n\r\n".encode("ascii"))
        else:
            xref.extend(b"0000000000 00000 f\r\n")
    xref.extend(trailer_bytes(model, size=max_object + 1))
    xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return header + bytes(body) + bytes(xref)
