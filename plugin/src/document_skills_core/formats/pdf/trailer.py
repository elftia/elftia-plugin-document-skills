"""Shared classical-trailer serialization for copy-through PDF mutations.

Module provenance: original Elftia-authored clean-room implementation.
"""

import re

from .dictionary_tokens import top_level_dictionary_value
from .object_model import IndirectReference, PdfObjectModel


def trailer_bytes(
    model: PdfObjectModel,
    *,
    size: int,
    root: IndirectReference | None = None,
    info_override: IndirectReference | None = None,
) -> bytes:
    """Serialize Root plus preserved Info/ID entries for a classical trailer."""
    root_reference = root or model.catalog_ref
    entries = [
        f"/Size {size}".encode("ascii"),
        f"/Root {root_reference.obj_num} {root_reference.gen_num} R".encode("ascii"),
    ]
    info = info_override or model.trailer.info
    if info is not None:
        entries.append(f"/Info {info.obj_num} {info.gen_num} R".encode("ascii"))
    raw_id = _raw_id_array(model)
    if raw_id is not None:
        entries.append(b"/ID " + raw_id)
    return b"trailer\n<< " + b" ".join(entries) + b" >>\n"


def _raw_id_array(model: PdfObjectModel) -> bytes | None:
    """Recover the final trailer/xref-stream ID value without text decoding."""
    startxref = model.raw.rfind(b"startxref")
    if startxref < 0:
        return None
    match = re.match(rb"startxref\s+(\d+)", model.raw[startxref:])
    if match is None:
        return None
    xref_offset = int(match.group(1))
    if model.raw[xref_offset:xref_offset + 4] == b"xref":
        trailer = model.raw.find(b"trailer", xref_offset, startxref)
        if trailer < 0:
            return None
        dictionary = model.raw.find(b"<<", trailer + len(b"trailer"), startxref)
        if dictionary < 0:
            return None
        payload = model.raw[dictionary:startxref]
    else:
        payload = model.raw[xref_offset:startxref]
    raw_id = top_level_dictionary_value(payload, "/ID")
    if raw_id is None:
        return None
    if not raw_id.startswith(b"[") or not raw_id.endswith(b"]"):
        return None
    return raw_id
