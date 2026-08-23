"""PDF Info dictionary metadata updates with page/object preservation.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
from pathlib import Path
import re
from typing import Any

from .object_model import IndirectReference, PdfObjectModel, parse_pdf

_INFO_KEYS = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
}


def update_metadata(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Update the PDF Info dictionary without rewriting page content."""
    metadata = primitive["metadata"]
    replacements: dict[int, bytes] = {}
    added: dict[int, bytes] = {}
    changed: set[int] = set()
    info_reference = model.trailer.info
    if info_reference is None:
        info_object = max(model.objects) + 1
        info_reference = IndirectReference(info_object, 0)
        added[info_object] = _new_info_object(info_object, metadata)
    else:
        info_object = info_reference.obj_num
        replacements[info_object] = _update_info_payload(
            model.objects[info_object].payload_bytes,
            metadata,
        )
        changed.add(info_object)

    output_bytes = _write_pdf(
        model,
        replacements,
        added,
        info_reference,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_model = parse_pdf(output)
    output_hashes = output_model.object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=changed,
        added=set(added),
        removed=set(),
    )
    return {
        "primitive": "metadata_update",
        "updated_fields": sorted(metadata),
        "info_object": info_reference.obj_num,
        "preservation": manifest,
    }, manifest


def _update_info_payload(payload: bytes, metadata: dict[str, str]) -> bytes:
    result = payload
    for field, value in metadata.items():
        key = _INFO_KEYS[field].encode("ascii")
        encoded = f"{_INFO_KEYS[field]} ({_escape_pdf_string(value)})".encode("latin-1")
        pattern = re.compile(re.escape(key) + rb"\s*\((?:\\.|[^)])*\)")
        if pattern.search(result):
            result = pattern.sub(encoded, result, count=1)
        else:
            end = result.rfind(b">>")
            result = result[:end] + b" " + encoded + b" " + result[end:]
    return result


def _new_info_object(obj_num: int, metadata: dict[str, str]) -> bytes:
    entries = " ".join(
        f"{_INFO_KEYS[field]} ({_escape_pdf_string(value)})"
        for field, value in sorted(metadata.items())
    )
    return f"{obj_num} 0 obj\n<< {entries} >>\nendobj".encode("latin-1")


def _write_pdf(
    model: PdfObjectModel,
    replacements: dict[int, bytes],
    added: dict[int, bytes],
    info_reference: IndirectReference,
) -> bytes:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for obj_num in sorted(model.objects):
        offsets[obj_num] = len(header) + len(body)
        body.extend(replacements.get(obj_num, model.objects[obj_num].payload_bytes) + b"\n")
    for obj_num in sorted(added):
        offsets[obj_num] = len(header) + len(body)
        body.extend(added[obj_num] + b"\n")
    max_object = max(offsets)
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {max_object + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for obj_num in range(1, max_object + 1):
        xref.extend(f"{offsets.get(obj_num, 0):010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {max_object + 1} "
        f"/Root {model.catalog_ref.obj_num} {model.catalog_ref.gen_num} R "
        f"/Info {info_reference.obj_num} {info_reference.gen_num} R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _escape_pdf_string(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
