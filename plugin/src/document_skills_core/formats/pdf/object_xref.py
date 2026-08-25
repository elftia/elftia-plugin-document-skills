"""Classical/xref-stream parsing and trailer projection for PDF objects."""

from dataclasses import dataclass
import re

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .byte_preflight import PdfByteLimits
from .object_stream import extract_stream
from .object_values import IndirectReference, parse_dict, PdfDict


@dataclass
class XrefEntry:
    obj_num: int
    offset: int | None
    gen_num: int
    in_use: bool
    is_stream: bool = False


@dataclass
class TrailerInfo:
    size: int
    root: IndirectReference | None
    info: IndirectReference | None
    encrypt: IndirectReference | None
    id_array: list[str] | None
    prev: int | None


def parse_xref(
    raw: bytes,
    budget: PdfByteLimits,
) -> tuple[dict[int, XrefEntry], TrailerInfo]:
    """Find and parse the final xref table or stream and its trailer."""
    startxref_pos = raw.rfind(b"startxref")
    if startxref_pos < 0:
        _unsafe("PDF startxref keyword is missing.")
    match = re.search(rb"startxref\s+(\d+)\s+%%EOF", raw[startxref_pos:])
    if match is None:
        _unsafe("PDF startxref offset or %%EOF marker is malformed.")
    xref_offset = int(match.group(1))
    if xref_offset >= len(raw):
        _unsafe("PDF xref offset is beyond the file end.")
    if raw[xref_offset : xref_offset + 20].startswith(b"xref"):
        return _parse_classical_xref(raw, xref_offset, budget)
    return _parse_xref_stream(raw, xref_offset, budget)


def _parse_classical_xref(
    raw: bytes,
    offset: int,
    budget: PdfByteLimits,
) -> tuple[dict[int, XrefEntry], TrailerInfo]:
    entries: dict[int, XrefEntry] = {}
    pos = offset + 4
    while True:
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        if pos >= len(raw):
            break
        if raw[pos : pos + 7] == b"trailer":
            pos += 7
            break
        line_end = raw.find(b"\n", pos)
        if line_end < 0:
            _unsafe("PDF xref subsection header is malformed.")
        parts = raw[pos:line_end].strip().split()
        if len(parts) != 2:
            _unsafe("PDF xref subsection header must have two fields.")
        try:
            first_obj = int(parts[0])
            count = int(parts[1])
        except ValueError as error:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF xref subsection header is not numeric.",
            ) from error
        pos = line_end + 1
        for index in range(count):
            entry_start = pos + index * 20
            entry_line = raw[entry_start : entry_start + 20]
            if len(entry_line) < 18:
                _unsafe("PDF xref entry is truncated.")
            fields = entry_line.strip().decode("ascii", errors="replace").split()
            if len(fields) < 3:
                continue
            try:
                object_offset = int(fields[0])
                generation = int(fields[1])
            except ValueError:
                continue
            object_number = first_obj + index
            if object_number > budget.max_objects:
                _unsafe("PDF xref object number exceeds the bound.")
            if fields[2] == "n":
                entries[object_number] = XrefEntry(
                    object_number,
                    object_offset,
                    generation,
                    True,
                )
            elif fields[2] == "f":
                entries[object_number] = XrefEntry(
                    object_number,
                    None,
                    generation,
                    False,
                )
        pos = entry_start + 20 if count > 0 else pos
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    if pos >= len(raw) or raw[pos : pos + 2] != b"<<":
        _unsafe("PDF trailer dictionary is missing.")
    trailer_dict, _end = parse_dict(raw, pos)
    return entries, _build_trailer(trailer_dict)


def _parse_xref_stream(
    raw: bytes,
    offset: int,
    budget: PdfByteLimits,
) -> tuple[dict[int, XrefEntry], TrailerInfo]:
    object_header = re.match(rb"(\d+)\s+(\d+)\s+obj", raw[offset : offset + 40])
    if object_header is None:
        _unsafe("PDF xref position does not point to a valid xref table or stream.")
    dictionary, dictionary_end = parse_dict(raw, offset + object_header.end())
    if dictionary.get("/Type") != "/XRef":
        _unsafe("PDF xref stream Type is not /XRef.")
    size = dictionary.get("/Size", 0)
    widths = dictionary.get("/W", [1, 2, 1])
    if not isinstance(widths, list) or len(widths) < 3:
        _unsafe("PDF xref stream /W array is malformed.")
    width_type, width_offset, width_generation = (
        int(widths[0]),
        int(widths[1]),
        int(widths[2]),
    )
    entry_size = width_type + width_offset + width_generation
    if entry_size == 0:
        _unsafe("PDF xref stream entry size is zero.")
    stream_data, _end = extract_stream(raw, dictionary_end, dictionary, budget)
    index_array = dictionary.get("/Index")
    if isinstance(index_array, list):
        indices = [
            (int(index_array[index]), int(index_array[index + 1]))
            for index in range(0, len(index_array), 2)
        ]
    else:
        indices = [(0, size)]
    entries: dict[int, XrefEntry] = {}
    position = 0
    for first_object, count in indices:
        for index in range(count):
            if position + entry_size > len(stream_data):
                break
            entry_type = (
                int.from_bytes(stream_data[position : position + width_type], "big")
                if width_type > 0
                else 1
            )
            offset_start = position + width_type
            object_offset = (
                int.from_bytes(
                    stream_data[offset_start : offset_start + width_offset],
                    "big",
                )
                if width_offset > 0
                else 0
            )
            generation_start = offset_start + width_offset
            generation = (
                int.from_bytes(
                    stream_data[
                        generation_start : generation_start + width_generation
                    ],
                    "big",
                )
                if width_generation > 0
                else 0
            )
            position += entry_size
            object_number = first_object + index
            if entry_type == 0:
                entries[object_number] = XrefEntry(
                    object_number, None, generation, False,
                )
            elif entry_type == 1:
                entries[object_number] = XrefEntry(
                    object_number, object_offset, generation, True,
                )
            elif entry_type == 2:
                entries[object_number] = XrefEntry(
                    object_number,
                    object_offset,
                    generation,
                    True,
                    is_stream=True,
                )
    return entries, _build_trailer(dictionary)


def _build_trailer(dictionary: PdfDict) -> TrailerInfo:
    root = dictionary.get("/Root")
    if isinstance(root, IndirectReference):
        root_ref = root
    elif isinstance(root, list) and len(root) == 3:
        root_ref = IndirectReference(int(root[0]), int(root[1]))
    else:
        root_ref = None
    info = dictionary.get("/Info")
    info_ref = info if isinstance(info, IndirectReference) else None
    encrypt = dictionary.get("/Encrypt")
    encrypt_ref = encrypt if isinstance(encrypt, IndirectReference) else None
    id_array = dictionary.get("/ID")
    if not isinstance(id_array, list):
        id_array = None
    previous = dictionary.get("/Prev")
    if not isinstance(previous, int):
        previous = None
    size = dictionary.get("/Size", 0)
    if not isinstance(size, int):
        size = 0
    return TrailerInfo(
        size=size,
        root=root_ref,
        info=info_ref,
        encrypt=encrypt_ref,
        id_array=id_array,
        prev=previous,
    )


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
