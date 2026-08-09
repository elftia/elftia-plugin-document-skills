"""PDF object index: numbered object parse, xref table/stream decode, trailer.

Records header version, body objects (number, generation, byte offset, type,
payload byte range), classical xref table and xref stream entries, trailer
dictionary resolution, Catalog, Info, Encrypt presence, and per-object SHA-256.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .byte_preflight import PdfByteLimits, decode_stream


@dataclass(frozen=True)
class IndirectReference:
    obj_num: int
    gen_num: int

    def __repr__(self) -> str:
        return f"{self.obj_num} {self.gen_num} R"


@dataclass
class PdfObject:
    """A numbered PDF object with its parsed value and byte metadata."""
    obj_num: int
    gen_num: int
    offset: int
    value: Any
    payload_bytes: bytes
    is_stream: bool
    sha256: str

    @property
    def type_name(self) -> str | None:
        if isinstance(self.value, PdfDict):
            return self.value.get("/Type")
        return None


@dataclass
class PdfDict:
    """PDF dictionary object — ordered, name-keyed."""
    entries: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.entries.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __getitem__(self, key: str) -> Any:
        return self.entries[key]


@dataclass
class XrefEntry:
    obj_num: int
    offset: int | None  # None for free entries
    gen_num: int
    in_use: bool
    is_stream: bool = False  # True for xref stream entries


@dataclass
class TrailerInfo:
    size: int
    root: IndirectReference | None
    info: IndirectReference | None
    encrypt: IndirectReference | None
    id_array: list[str] | None
    prev: int | None


@dataclass
class PdfObjectModel:
    """Indexed PDF object model with per-object SHA-256 baseline."""
    raw: bytes
    version_major: int
    version_minor: int
    objects: dict[int, PdfObject]
    xref_entries: dict[int, XrefEntry]
    trailer: TrailerInfo
    sha256: str

    @property
    def catalog_ref(self) -> IndirectReference:
        if self.trailer.root is None:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF trailer does not contain a /Root reference.",
            )
        return self.trailer.root

    def get_object(self, ref: IndirectReference) -> PdfObject:
        obj = self.objects.get(ref.obj_num)
        if obj is None:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                f"PDF indirect reference {ref.obj_num} {ref.gen_num} R is dangling.",
                details={"obj_num": ref.obj_num},
            )
        return obj

    def resolve(self, value: Any) -> Any:
        """Resolve indirect references to their values."""
        seen: set[int] = set()
        return self._resolve(value, seen, depth=0)

    def _resolve(self, value: Any, seen: set[int], depth: int) -> Any:
        if depth > 64:
            # Return the value as-is rather than raising; deep nesting is not a security issue
            return value
        if isinstance(value, IndirectReference):
            if value.obj_num in seen:
                # Cycle detected — return the reference itself (PDF /Parent cycles are normal)
                return value
            seen.add(value.obj_num)
            obj = self.get_object(value)
            return self._resolve(obj.value, seen, depth + 1)
        if isinstance(value, PdfDict):
            return PdfDict({k: self._resolve(v, seen, depth + 1) for k, v in value.entries.items()})
        if isinstance(value, list):
            return [self._resolve(v, seen, depth + 1) for v in value]
        return value

    def object_hashes(self) -> dict[int, str]:
        return {num: obj.sha256 for num, obj in self.objects.items()}


def parse_pdf(path: str | Path, limits: PdfByteLimits | None = None) -> PdfObjectModel:
    """Parse a PDF file into a bounded object model.

    This is the entry point for read/inspect operations. It performs:
    1. Byte read and SHA-256
    2. Xref table/stream parsing to locate objects
    3. Individual object parsing at their byte offsets
    4. Trailer dictionary resolution
    """
    budget = limits or PdfByteLimits()
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            f"PDF input does not exist: {resolved.name}",
        )
    raw = resolved.read_bytes()
    if len(raw) > budget.max_bytes:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF exceeds the byte-count budget.",
        )
    if not raw[:5] == b"%PDF-":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF header magic (%PDF-) is missing.",
        )
    sha256 = hashlib.sha256(raw).hexdigest()

    version_match = re.match(rb"%PDF-(\d+)\.(\d+)", raw[:20])
    if version_match is None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF version string is malformed.",
        )
    version_major = int(version_match.group(1))
    version_minor = int(version_match.group(2))

    # Find the last xref table/stream and trailer
    xref_entries, trailer = _find_and_parse_xref(raw, budget)

    # Parse all objects referenced by the xref
    objects: dict[int, PdfObject] = {}
    for obj_num, entry in xref_entries.items():
        if not entry.in_use or entry.offset is None:
            continue
        if obj_num in objects:
            continue
        obj = _parse_object_at(raw, obj_num, entry.gen_num, entry.offset, entry.is_stream, budget)
        if obj is not None:
            objects[obj_num] = obj

    return PdfObjectModel(
        raw=raw,
        version_major=version_major,
        version_minor=version_minor,
        objects=objects,
        xref_entries=xref_entries,
        trailer=trailer,
        sha256=sha256,
    )


def _find_and_parse_xref(raw: bytes, budget: PdfByteLimits) -> tuple[dict[int, XrefEntry], TrailerInfo]:
    """Find and parse the last xref table or stream + trailer dictionary."""
    # Search from the end for 'startxref' to find the xref offset
    startxref_pos = raw.rfind(b"startxref")
    if startxref_pos < 0:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF startxref keyword is missing.",
        )
    # Parse the offset after startxref
    offset_match = re.search(rb"startxref\s+(\d+)\s+%%EOF", raw[startxref_pos:])
    if offset_match is None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF startxref offset or %%EOF marker is malformed.",
        )
    xref_offset = int(offset_match.group(1))
    if xref_offset >= len(raw):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF xref offset is beyond the file end.",
        )

    # Check whether it's a classical xref table or an xref stream
    peek = raw[xref_offset : xref_offset + 20]
    if peek.startswith(b"xref"):
        return _parse_classical_xref(raw, xref_offset, budget)
    # Try parsing as an xref stream object
    return _parse_xref_stream(raw, xref_offset, budget)


def _parse_classical_xref(
    raw: bytes, offset: int, budget: PdfByteLimits
) -> tuple[dict[int, XrefEntry], TrailerInfo]:
    """Parse a classical xref table + trailer dictionary."""
    entries: dict[int, XrefEntry] = {}
    pos = offset + 4  # skip 'xref'
    # Parse subsections
    while True:
        # Skip whitespace
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        if pos >= len(raw):
            break
        # Check for 'trailer' keyword
        if raw[pos : pos + 7] == b"trailer":
            pos += 7
            break
        # Parse subsection header: first_obj count
        line_end = raw.find(b"\n", pos)
        if line_end < 0:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF xref subsection header is malformed.",
            )
        header = raw[pos:line_end].strip()
        parts = header.split()
        if len(parts) != 2:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF xref subsection header must have two fields.",
            )
        try:
            first_obj = int(parts[0])
            count = int(parts[1])
        except ValueError as error:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF xref subsection header is not numeric.",
            ) from error
        pos = line_end + 1
        # Parse entries (20 bytes each)
        for i in range(count):
            entry_start = pos + i * 20
            entry_line = raw[entry_start : entry_start + 20]
            if len(entry_line) < 18:
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "PDF xref entry is truncated.",
                )
            line_str = entry_line.strip().decode("ascii", errors="replace")
            fields = line_str.split()
            if len(fields) < 3:
                continue
            try:
                obj_offset = int(fields[0])
                gen = int(fields[1])
                status = fields[2]
            except ValueError:
                continue
            obj_num = first_obj + i
            if obj_num > budget.max_objects:
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "PDF xref object number exceeds the bound.",
                )
            if status == "n":
                entries[obj_num] = XrefEntry(obj_num, obj_offset, gen, True)
            elif status == "f":
                entries[obj_num] = XrefEntry(obj_num, None, gen, False)
        pos = entry_start + 20 if count > 0 else pos

    # Parse trailer dictionary
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    if pos >= len(raw) or raw[pos : pos + 2] != b"<<":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF trailer dictionary is missing.",
        )
    trailer_dict, _ = _parse_dict(raw, pos)
    trailer = _build_trailer(trailer_dict)
    return entries, trailer


def _parse_xref_stream(
    raw: bytes, offset: int, budget: PdfByteLimits
) -> tuple[dict[int, XrefEntry], TrailerInfo]:
    """Parse an xref stream object (Type XRef with W-array decoded entries)."""
    # Parse the object header at offset
    obj_header = re.match(rb"(\d+)\s+(\d+)\s+obj", raw[offset:offset + 40])
    if obj_header is None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF xref position does not point to a valid xref table or stream.",
        )
    obj_num = int(obj_header.group(1))
    gen_num = int(obj_header.group(2))
    pos = offset + obj_header.end()
    # Parse the dictionary
    dict_value, dict_end = _parse_dict(raw, pos)
    if not isinstance(dict_value, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF xref stream dictionary is malformed.",
        )
    if dict_value.get("/Type") != "/XRef":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF xref stream Type is not /XRef.",
        )
    size = dict_value.get("/Size", 0)
    w_array = dict_value.get("/W", [1, 2, 1])
    if not isinstance(w_array, list) or len(w_array) < 3:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF xref stream /W array is malformed.",
        )
    w1, w2, w3 = int(w_array[0]), int(w_array[1]), int(w_array[2])
    entry_size = w1 + w2 + w3
    if entry_size == 0:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF xref stream entry size is zero.",
        )
    # Find and decode the stream
    stream_data, _ = _extract_stream(raw, dict_end, dict_value, budget)
    # Parse entries
    entries: dict[int, XrefEntry] = {}
    index_array = dict_value.get("/Index")
    if isinstance(index_array, list):
        indices: list[tuple[int, int]] = []
        for i in range(0, len(index_array), 2):
            indices.append((int(index_array[i]), int(index_array[i + 1])))
    else:
        indices = [(0, size)]
    pos_s = 0
    for first_obj, count in indices:
        for i in range(count):
            if pos_s + entry_size > len(stream_data):
                break
            field1 = int.from_bytes(stream_data[pos_s : pos_s + w1], "big") if w1 > 0 else 1
            field2_raw = stream_data[pos_s + w1 : pos_s + w1 + w2]
            field2 = int.from_bytes(field2_raw, "big") if w2 > 0 else 0
            field3_raw = stream_data[pos_s + w1 + w2 : pos_s + entry_size]
            field3 = int.from_bytes(field3_raw, "big") if w3 > 0 else 0
            pos_s += entry_size
            obj_num_xref = first_obj + i
            if field1 == 0:
                entries[obj_num_xref] = XrefEntry(obj_num_xref, None, field3, False)
            elif field1 == 1:
                entries[obj_num_xref] = XrefEntry(obj_num_xref, field2, field3, True)
            elif field1 == 2:
                entries[obj_num_xref] = XrefEntry(obj_num_xref, field2, field3, True, is_stream=True)
    # Build trailer from the xref stream dictionary
    trailer = _build_trailer(dict_value)
    return entries, trailer


def _build_trailer(d: PdfDict) -> TrailerInfo:
    root = d.get("/Root")
    if isinstance(root, IndirectReference):
        root_ref = root
    elif isinstance(root, list) and len(root) == 3:
        root_ref = IndirectReference(int(root[0]), int(root[1]))
    else:
        root_ref = None
    info = d.get("/Info")
    if isinstance(info, IndirectReference):
        info_ref = info
    else:
        info_ref = None
    encrypt = d.get("/Encrypt")
    if isinstance(encrypt, IndirectReference):
        encrypt_ref = encrypt
    else:
        encrypt_ref = None
    id_array = d.get("/ID")
    if not isinstance(id_array, list):
        id_array = None
    prev = d.get("/Prev")
    if not isinstance(prev, int):
        prev = None
    size = d.get("/Size", 0)
    if not isinstance(size, int):
        size = 0
    return TrailerInfo(
        size=size,
        root=root_ref,
        info=info_ref,
        encrypt=encrypt_ref,
        id_array=id_array,
        prev=prev,
    )


def _parse_object_at(
    raw: bytes, obj_num: int, gen_num: int, offset: int, is_stream_obj: bool, budget: PdfByteLimits
) -> PdfObject | None:
    """Parse a single object at the given byte offset."""
    # Match 'N G obj'
    header = raw[offset : offset + 60]
    header_match = re.match(rb"(\d+)\s+(\d+)\s+obj", header)
    if header_match is None:
        return None
    content_start = offset + header_match.end()
    # Find 'endobj'
    endobj_pos = _find_endobj(raw, content_start)
    if endobj_pos < 0:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            f"PDF object {obj_num} {gen_num} R is missing 'endobj'.",
        )
    payload = raw[offset : endobj_pos + 6]
    sha256 = hashlib.sha256(payload).hexdigest()
    # Parse the value between header and endobj
    value_text = raw[content_start:endobj_pos]
    # Skip whitespace
    vpos = 0
    while vpos < len(value_text) and value_text[vpos] in b" \t\r\n":
        vpos += 1
    is_stream = False
    if vpos < len(value_text) - 1 and value_text[vpos : vpos + 2] == b"<<":
        dict_value, dict_end = _parse_dict(value_text, vpos)
        # Check for stream keyword
        after = dict_end
        while after < len(value_text) and value_text[after] in b" \t\r\n":
            after += 1
        if value_text[after : after + 6] == b"stream":
            is_stream = True
            stream_data, stream_end = _extract_stream_from_value(value_text, after, dict_value, budget)
            parsed_value: Any = (dict_value, stream_data)
        else:
            parsed_value = dict_value
    elif vpos < len(value_text) and value_text[vpos : vpos + 1] == b"[":
        parsed_value, _ = _parse_array(value_text, vpos)
    else:
        parsed_value = _parse_simple_value(value_text[vpos:].strip())
    return PdfObject(
        obj_num=obj_num,
        gen_num=gen_num,
        offset=offset,
        value=parsed_value,
        payload_bytes=payload,
        is_stream=is_stream,
        sha256=sha256,
    )


def _find_endobj(raw: bytes, start: int) -> int:
    """Find the next 'endobj' keyword, accounting for stream content."""
    pos = start
    while True:
        pos = raw.find(b"endobj", pos)
        if pos < 0:
            return -1
        # Check it's a standalone keyword (not inside a string)
        before = raw[pos - 1 : pos] if pos > 0 else b" "
        if before in b" \t\r\n":
            return pos
        pos += 6


def _parse_dict(raw: bytes | bytearray, start: int) -> tuple[PdfDict, int]:
    """Parse a PDF dictionary starting at '<<' position."""
    if raw[start : start + 2] != b"<<":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF dictionary does not start with <<.",
        )
    pos = start + 2
    entries: dict[str, Any] = {}
    while pos < len(raw):
        # Skip whitespace and comments
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        if pos >= len(raw):
            break
        if raw[pos : pos + 2] == b">>":
            return PdfDict(entries), pos + 2
        # Parse key (name)
        if raw[pos] != ord("/"):
            pos += 1
            continue
        key, pos = _parse_name(raw, pos)
        # Skip whitespace
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        # Parse value
        value, pos = _parse_value(raw, pos)
        entries[key] = value
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "PDF dictionary is not properly terminated with >>.",
    )


def _parse_array(raw: bytes | bytearray, start: int) -> tuple[list, int]:
    """Parse a PDF array starting at '[' position."""
    if raw[start] != ord("["):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF array does not start with [.",
        )
    pos = start + 1
    items: list = []
    while pos < len(raw):
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        if pos >= len(raw):
            break
        if raw[pos] == ord("]"):
            return items, pos + 1
        value, pos = _parse_value(raw, pos)
        items.append(value)
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "PDF array is not properly terminated with ].",
    )


def _parse_value(raw: bytes | bytearray, pos: int) -> tuple[Any, int]:
    """Parse a single PDF value at the given position."""
    if pos >= len(raw):
        return None, pos
    ch = raw[pos]
    if ch == ord("/"):
        return _parse_name(raw, pos)
    if ch == ord("("):
        return _parse_literal_string(raw, pos)
    if ch == ord("<"):
        if pos + 1 < len(raw) and raw[pos + 1] == ord("<"):
            return _parse_dict(raw, pos)
        return _parse_hex_string(raw, pos)
    if ch == ord("["):
        return _parse_array(raw, pos)
    if ch == ord("t") and raw[pos : pos + 4] == b"true":
        return True, pos + 4
    if ch == ord("f") and raw[pos : pos + 5] == b"false":
        return False, pos + 5
    if ch == ord("n") and raw[pos : pos + 4] == b"null":
        return None, pos + 4
    # Try number or reference
    return _parse_number_or_ref(raw, pos)


def _parse_name(raw: bytes | bytearray, pos: int) -> tuple[str, int]:
    """Parse a PDF name /Name."""
    if raw[pos] != ord("/"):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF name does not start with /.",
        )
    pos += 1
    start = pos
    while pos < len(raw) and raw[pos] not in b" \t\r\n/[]<>()":
        pos += 1
    name = raw[start:pos].decode("utf-8", errors="replace")
    return "/" + name, pos


def _parse_literal_string(raw: bytes | bytearray, pos: int) -> tuple[str, int]:
    """Parse a PDF literal string (text in parentheses)."""
    if raw[pos] != ord("("):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF literal string does not start with (.",
        )
    pos += 1
    depth = 1
    result = bytearray()
    while pos < len(raw) and depth > 0:
        ch = raw[pos]
        if ch == ord("\\"):
            pos += 1
            if pos >= len(raw):
                break
            esc = raw[pos]
            if esc == ord("n"):
                result.append(0x0A)
            elif esc == ord("r"):
                result.append(0x0D)
            elif esc == ord("t"):
                result.append(0x09)
            elif esc == ord("b"):
                result.append(0x08)
            elif esc == ord("f"):
                result.append(0x0C)
            elif esc == ord("("):
                result.append(0x28)
            elif esc == ord(")"):
                result.append(0x29)
            elif esc == ord("\\"):
                result.append(0x5C)
            elif ord("0") <= esc <= ord("7"):
                octal = chr(esc)
                for _ in range(2):
                    if pos + 1 < len(raw) and ord("0") <= raw[pos + 1] <= ord("7"):
                        pos += 1
                        octal += chr(raw[pos])
                    else:
                        break
                result.append(int(octal, 8) & 0xFF)
            else:
                result.append(esc)
            pos += 1
        elif ch == ord("("):
            depth += 1
            result.append(ch)
            pos += 1
        elif ch == ord(")"):
            depth -= 1
            if depth > 0:
                result.append(ch)
            pos += 1
        else:
            result.append(ch)
            pos += 1
    return result.decode("latin-1", errors="replace"), pos


def _parse_hex_string(raw: bytes | bytearray, pos: int) -> tuple[str, int]:
    """Parse a PDF hex string <...>."""
    if raw[pos] != ord("<"):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF hex string does not start with <.",
        )
    pos += 1
    hex_chars = bytearray()
    while pos < len(raw) and raw[pos] != ord(">"):
        if raw[pos] not in b" \t\r\n\f":
            hex_chars.append(raw[pos])
        pos += 1
    pos += 1  # skip >
    if len(hex_chars) % 2 == 1:
        hex_chars.append(ord("0"))
    try:
        decoded = bytes.fromhex(hex_chars.decode("ascii"))
    except ValueError as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF hex string contains invalid characters.",
        ) from error
    return decoded.decode("latin-1", errors="replace"), pos


def _parse_number_or_ref(raw: bytes | bytearray, pos: int) -> tuple[Any, int]:
    """Parse a number or an indirect reference (N G R)."""
    start = pos
    while pos < len(raw) and raw[pos] not in b" \t\r\n/[]<>()":
        pos += 1
    token = raw[start:pos]
    token_str = token.decode("ascii", errors="replace")
    # Check for indirect reference: N G R
    if pos < len(raw) and raw[pos] in b" \t\r\n":
        save_pos = pos
        # Skip whitespace after N
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        # Read G (generation number)
        gen_start = pos
        while pos < len(raw) and raw[pos] not in b" \t\r\n/[]<>()":
            pos += 1
        gen_token = raw[gen_start:pos]
        gen_str = gen_token.decode("ascii", errors="replace")
        # Skip whitespace after G
        ws_pos = pos
        while pos < len(raw) and raw[pos] in b" \t\r\n":
            pos += 1
        # Check for 'R' keyword
        if pos < len(raw) and raw[pos] == ord("R"):
            after_r = pos + 1
            # R must be followed by whitespace or delimiter (not part of a longer token)
            if after_r >= len(raw) or raw[after_r] in b" \t\r\n/[]<>()":
                try:
                    obj_num = int(token_str)
                    gen_num = int(gen_str)
                    return IndirectReference(obj_num, gen_num), after_r
                except ValueError:
                    pass
        # Not a reference — restore position to just after N
        pos = save_pos
    # Try as number
    try:
        if b"." in token:
            return float(token_str), pos
        return int(token_str), pos
    except ValueError:
        return token_str, pos


def _parse_simple_value(raw: bytes) -> Any:
    """Parse a simple value (for non-dict, non-array objects)."""
    raw_str = raw.strip()
    if not raw_str:
        return None
    try:
        if b"." in raw_str:
            return float(raw_str)
        return int(raw_str)
    except ValueError:
        return raw_str.decode("latin-1", errors="replace")


def _extract_stream(
    raw: bytes, pos: int, dict_value: PdfDict, budget: PdfByteLimits
) -> tuple[bytes, int]:
    """Extract and decode a stream payload from raw bytes."""
    # Find 'stream' keyword
    while pos < len(raw) and raw[pos] in b" \t\r\n":
        pos += 1
    if raw[pos : pos + 6] != b"stream":
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF stream object is missing 'stream' keyword.",
        )
    pos += 6
    # Skip EOL after 'stream'
    if pos < len(raw) and raw[pos] == ord("\r"):
        pos += 1
    if pos < len(raw) and raw[pos] == ord("\n"):
        pos += 1
    # Get stream length
    length = dict_value.get("/Length")
    if isinstance(length, int):
        stream_raw = raw[pos : pos + length]
        pos += length
    else:
        # Find 'endstream'
        endstream = raw.find(b"endstream", pos)
        if endstream < 0:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "PDF stream is missing 'endstream'.",
            )
        stream_raw = raw[pos:endstream]
        pos = endstream + 9
    # Apply filters
    filter_spec = dict_value.get("/Filter")
    filters: list[str] = []
    if isinstance(filter_spec, str):
        filters = [filter_spec]
    elif isinstance(filter_spec, list):
        filters = [f for f in filter_spec if isinstance(f, str)]
    if filters:
        stream_raw = decode_stream(stream_raw, filters, budget)
    return stream_raw, pos


def _extract_stream_from_value(
    value_text: bytes, stream_pos: int, dict_value: PdfDict, budget: PdfByteLimits
) -> tuple[bytes, int]:
    """Extract stream from within an object's value bytes."""
    pos = stream_pos + 6  # skip 'stream'
    if pos < len(value_text) and value_text[pos] == ord("\r"):
        pos += 1
    if pos < len(value_text) and value_text[pos] == ord("\n"):
        pos += 1
    length = dict_value.get("/Length")
    if isinstance(length, int):
        stream_raw = value_text[pos : pos + length]
    else:
        endstream = value_text.find(b"endstream", pos)
        if endstream < 0:
            return b"", pos
        stream_raw = value_text[pos:endstream]
    filter_spec = dict_value.get("/Filter")
    filters: list[str] = []
    if isinstance(filter_spec, str):
        filters = [filter_spec]
    elif isinstance(filter_spec, list):
        filters = [f for f in filter_spec if isinstance(f, str)]
    if filters:
        stream_raw = decode_stream(stream_raw, filters, budget)
    return stream_raw, pos + len(stream_raw)
