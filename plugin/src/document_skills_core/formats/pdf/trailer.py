"""Shared classical-trailer serialization for copy-through PDF mutations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from .object_model import IndirectReference, PdfObjectModel


def trailer_bytes(
    model: PdfObjectModel,
    *,
    size: int,
    root: IndirectReference | None = None,
) -> bytes:
    """Serialize Root plus preserved Info/ID entries for a classical trailer."""
    root_reference = root or model.catalog_ref
    entries = [
        f"/Size {size}",
        f"/Root {root_reference.obj_num} {root_reference.gen_num} R",
    ]
    if model.trailer.info is not None:
        info = model.trailer.info
        entries.append(f"/Info {info.obj_num} {info.gen_num} R")
    if model.trailer.id_array:
        ids = " ".join(f"<{value}>" for value in model.trailer.id_array)
        entries.append(f"/ID [{ids}]")
    return f"trailer\n<< {' '.join(entries)} >>\n".encode("ascii")
