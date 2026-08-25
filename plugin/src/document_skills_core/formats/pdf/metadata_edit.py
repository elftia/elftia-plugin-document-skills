"""Synchronized PDF Info and Catalog-linked XMP metadata updates.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_text_utils import pdf_text_string
from .dictionary_tokens import (
    top_level_dictionary_end,
    update_top_level_dictionary,
)
from .metadata_xmp import (
    build_xmp,
    LinkedXmp,
    load_linked_xmp,
    read_xmp_metadata,
    update_xmp,
)
from .mutation_writer import write_pdf_mutation
from .object_model import IndirectReference, PdfDict, PdfObjectModel, parse_pdf

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
    """Update Info and XMP together without rewriting page content."""
    requested = primitive["metadata"]
    linked_xmp = load_linked_xmp(model)
    info_values = _read_info(model)
    xmp_values = read_xmp_metadata(linked_xmp.xml) if linked_xmp is not None else {}
    synchronized = {
        field: requested.get(field, info_values.get(field, xmp_values.get(field, "")))
        for field in _INFO_KEYS
    }
    mutations: dict[int, bytes] = {}
    additions: dict[int, bytes] = {}
    changed: set[int] = set()
    next_object = max(model.trailer.size - 1, *model.objects) + 1

    info_reference = model.trailer.info
    if info_reference is None:
        info_reference = IndirectReference(next_object, 0)
        additions[next_object] = _new_info_object(next_object, synchronized)
        next_object += 1
    else:
        info_obj = model.get_object(info_reference)
        if info_obj.gen_num != info_reference.gen_num or not isinstance(info_obj.value, PdfDict):
            _unsafe("PDF Info reference does not resolve to its declared dictionary generation.")
        mutations[info_obj.obj_num] = update_top_level_dictionary(
            info_obj.payload_bytes,
            _serialized_info_values(synchronized),
        )
        changed.add(info_obj.obj_num)

    catalog = model.get_object(model.catalog_ref)
    if not isinstance(catalog.value, PdfDict):
        _unsafe("PDF Catalog is not a dictionary.")
    if linked_xmp is None:
        xmp_reference = IndirectReference(next_object, 0)
        xml = build_xmp(synchronized)
        additions[next_object] = _new_xmp_object(next_object, xml)
        mutations[catalog.obj_num] = update_top_level_dictionary(
            catalog.payload_bytes,
            {"/Metadata": f"{next_object} 0 R".encode("ascii")},
        )
        changed.add(catalog.obj_num)
    else:
        metadata_reference = catalog.value.get("/Metadata")
        assert isinstance(metadata_reference, IndirectReference)
        if linked_xmp.obj.gen_num != metadata_reference.gen_num:
            _unsafe("PDF Metadata reference generation is inconsistent.")
        xmp_reference = IndirectReference(linked_xmp.obj.obj_num, linked_xmp.obj.gen_num)
        xml = update_xmp(linked_xmp.xml, synchronized)
        mutations[linked_xmp.obj.obj_num] = _replace_xmp_stream(linked_xmp, xml)
        changed.add(linked_xmp.obj.obj_num)

    output_bytes = write_pdf_mutation(
        model,
        mutations,
        additions,
        set(),
        info_reference=info_reference,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=changed,
        added=set(additions),
        removed=set(),
    )
    manifest["metadata_expectation"] = synchronized
    return {
        "primitive": "metadata_update",
        "updated_fields": sorted(requested),
        "metadata": synchronized,
        "info_object": info_reference.obj_num,
        "xmp_object": xmp_reference.obj_num,
        "preservation": manifest,
    }, manifest


def _read_info(model: PdfObjectModel) -> dict[str, str]:
    reference = model.trailer.info
    if reference is None:
        return {}
    obj = model.get_object(reference)
    if obj.gen_num != reference.gen_num or not isinstance(obj.value, PdfDict):
        _unsafe("PDF Info reference does not resolve to its declared dictionary generation.")
    values: dict[str, str] = {}
    for field, key in _INFO_KEYS.items():
        value = obj.value.get(key)
        if value is not None:
            if not isinstance(value, str):
                _unsupported(f"PDF Info {key} is not a text string.")
            values[field] = value
    return values


def _serialized_info_values(metadata: dict[str, str]) -> dict[str, bytes]:
    return {
        key: pdf_text_string(metadata[field]).encode("ascii")
        for field, key in _INFO_KEYS.items()
    }


def _new_info_object(obj_num: int, metadata: dict[str, str]) -> bytes:
    entries = b" ".join(
        key.encode("ascii") + b" " + value
        for key, value in sorted(_serialized_info_values(metadata).items())
    )
    return f"{obj_num} 0 obj\n".encode("ascii") + b"<< " + entries + b" >>\nendobj"


def _new_xmp_object(obj_num: int, xml: bytes) -> bytes:
    return (
        f"{obj_num} 0 obj\n<< /Type /Metadata /Subtype /XML "
        f"/Length {len(xml)} >>\nstream\n".encode("ascii")
        + xml
        + b"\nendstream\nendobj"
    )


def _replace_xmp_stream(linked_xmp: LinkedXmp, xml: bytes) -> bytes:
    payload = linked_xmp.obj.payload_bytes
    old_length = linked_xmp.dictionary.get("/Length")
    assert isinstance(old_length, int)
    old_start = _stream_data_start(payload)
    old_end = old_start + old_length
    if old_end > len(payload) or not _has_endstream(payload, old_end):
        _unsafe("XMP stream Length does not match its serialized payload.")
    updated = update_top_level_dictionary(
        payload,
        {"/Length": str(len(xml)).encode("ascii")},
    )
    new_start = _stream_data_start(updated)
    return updated[:new_start] + xml + payload[old_end:]


def _stream_data_start(payload: bytes) -> int:
    position = top_level_dictionary_end(payload)
    while position < len(payload) and payload[position] in b" \t\r\n\x0c\x00":
        position += 1
    if payload[position:position + 6] != b"stream":
        _unsafe("XMP object is missing its stream token.")
    position += 6
    if payload[position:position + 2] == b"\r\n":
        return position + 2
    if payload[position:position + 1] in {b"\r", b"\n"}:
        return position + 1
    _unsafe("XMP stream token is not followed by an end-of-line marker.")


def _has_endstream(payload: bytes, position: int) -> bool:
    if payload[position:position + 2] == b"\r\n":
        position += 2
    elif payload[position:position + 1] in {b"\r", b"\n"}:
        position += 1
    return payload[position:position + 9] == b"endstream"


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)


def _unsupported(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.xmp-metadata-reconciliation"},
    )
