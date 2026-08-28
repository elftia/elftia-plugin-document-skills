"""PDF object index: numbered object parse, xref table/stream decode, trailer.

Records header version, body objects (number, generation, byte offset, type,
payload byte range), classical xref table and xref stream entries, trailer
dictionary resolution, Catalog, Info, Encrypt presence, and per-object SHA-256.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .byte_preflight import PdfByteLimits
from .object_stream import extract_stream_from_value as _extract_stream_from_value
from .object_values import (
    IndirectReference,
    parse_array as _parse_array,
    parse_dict as _parse_dict,
    parse_simple_value as _parse_simple_value,
    PdfDict,
)
from .object_xref import (
    parse_xref as _find_and_parse_xref,
    TrailerInfo,
    XrefEntry,
)


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
