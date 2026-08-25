"""Proof-oriented encoding for exact in-place PDF text rewrites."""

from __future__ import annotations

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError

from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .pdf_simple_encodings import decode_simple_bytes, encode_simple_text

_BASE14_LATIN_FONTS = frozenset({
    "/Courier",
    "/Courier-Bold",
    "/Courier-BoldOblique",
    "/Courier-Oblique",
    "/Helvetica",
    "/Helvetica-Bold",
    "/Helvetica-BoldOblique",
    "/Helvetica-Oblique",
    "/Times-Bold",
    "/Times-BoldItalic",
    "/Times-Italic",
    "/Times-Roman",
})


def encode_text_for_font(
    model: PdfObjectModel,
    page: PageInfo,
    font_name: str,
    text: str,
) -> bytes | None:
    """Encode text only when the target font mapping proves a round trip."""
    font = resolve_font_dictionary(model, page, font_name)
    encoding = _closed_simple_encoding(model, font)
    if font is None or encoding is None:
        return None
    encoded = encode_simple_text(encoding, text)
    if encoded is None:
        return None
    mapping, mapping_is_valid = _font_to_unicode_mapping(model, font)
    if not mapping_is_valid or not _mapping_agrees(mapping, encoded, text):
        return None
    return encoded


def decode_text_for_font(
    model: PdfObjectModel,
    page: PageInfo,
    font_name: str,
    encoded: bytes,
) -> str | None:
    """Decode candidate operand bytes through the actual target font mapping."""
    font = resolve_font_dictionary(model, page, font_name)
    encoding = _closed_simple_encoding(model, font)
    if font is None or encoding is None:
        return None
    decoded = decode_simple_bytes(encoding, encoded)
    if decoded is None:
        return None
    mapping, mapping_is_valid = _font_to_unicode_mapping(model, font)
    if not mapping_is_valid or not _mapping_agrees(mapping, encoded, decoded):
        return None
    return decoded


def resolve_font_dictionary(
    model: PdfObjectModel,
    page: PageInfo,
    font_name: str,
) -> PdfDict | None:
    resources = page.resources
    if not isinstance(resources, PdfDict):
        return None
    fonts = _resolve_value(model, resources.get("/Font"))
    if not isinstance(fonts, PdfDict):
        return None
    name = font_name if font_name.startswith("/") else f"/{font_name}"
    font = _resolve_value(model, fonts.get(name))
    return font if isinstance(font, PdfDict) else None


def _closed_simple_encoding(
    model: PdfObjectModel,
    font: PdfDict | None,
) -> str | None:
    if (
        font is None
        or font.get("/Subtype") != "/Type1"
        or font.get("/BaseFont") not in _BASE14_LATIN_FONTS
        or _has_embedded_font_program(model, font)
    ):
        return None
    encoding = _resolve_value(model, font.get("/Encoding"))
    if isinstance(encoding, PdfDict):
        if "/Differences" in encoding.entries:
            return None
        encoding = _resolve_value(model, encoding.get("/BaseEncoding"))
    if encoding is None and "/Encoding" not in font.entries:
        return "/StandardEncoding"
    if encoding in {
        "/MacRomanEncoding",
        "/StandardEncoding",
        "/WinAnsiEncoding",
    }:
        return encoding
    return None


def _has_embedded_font_program(model: PdfObjectModel, font: PdfDict) -> bool:
    if "/FontDescriptor" not in font.entries:
        return False
    descriptor_value = font.get("/FontDescriptor")
    descriptor = _resolve_value(model, descriptor_value)
    if not isinstance(descriptor, PdfDict):
        return True
    return any(
        key in descriptor.entries
        for key in ("/FontFile", "/FontFile2", "/FontFile3")
    )


def _font_to_unicode_mapping(
    model: PdfObjectModel,
    font: PdfDict,
) -> tuple[dict[bytes, str] | None, bool]:
    if "/ToUnicode" not in font.entries:
        return None, True
    value = font.get("/ToUnicode")
    mapping = _to_unicode_mapping(model, value)
    return mapping, mapping is not None


def _mapping_agrees(
    mapping: dict[bytes, str] | None,
    encoded: bytes,
    decoded: str,
) -> bool:
    if mapping is None:
        return True
    return len(encoded) == len(decoded) and all(
        mapping.get(bytes((code,))) == character
        for code, character in zip(encoded, decoded)
    )


def _to_unicode_mapping(
    model: PdfObjectModel,
    value: Any,
) -> dict[bytes, str] | None:
    value = _resolve_value(model, value)
    if not (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], PdfDict)
        and isinstance(value[1], bytes)
    ):
        return None
    mapping: dict[bytes, str] = {}
    raw = value[1]
    for section in re.findall(rb"beginbfchar(.*?)endbfchar", raw, flags=re.DOTALL):
        for source, target in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
            section,
        ):
            decoded = _unicode_hex(target)
            source_bytes = _hex_bytes(source)
            if decoded is None or source_bytes is None:
                return None
            if not _add_mapping(mapping, source_bytes, decoded):
                return None
    for section in re.findall(rb"beginbfrange(.*?)endbfrange", raw, flags=re.DOTALL):
        for match in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*"
            rb"(?:<([0-9A-Fa-f]+)>|\[((?:\s*<[0-9A-Fa-f]+>\s*)+)\])",
            section,
        ):
            if not _add_bf_range(mapping, *match.groups()):
                return None
    return mapping or None


def _add_bf_range(
    mapping: dict[bytes, str],
    start_raw: bytes,
    end_raw: bytes,
    target_raw: bytes | None,
    array_raw: bytes | None,
) -> bool:
    if len(start_raw) != len(end_raw) or len(start_raw) % 2:
        return False
    start = int(start_raw, 16)
    end = int(end_raw, 16)
    if end < start or end - start > 65_535:
        return False
    width = len(start_raw) // 2
    if target_raw is not None:
        if len(target_raw) % 2:
            return False
        target_width = len(target_raw) // 2
        target_start = int(target_raw, 16)
        if target_start + (end - start) >= 1 << (target_width * 8):
            return False
        targets = [
            (target_start + offset).to_bytes(target_width, "big")
            for offset in range(end - start + 1)
        ]
    else:
        assert array_raw is not None
        targets = []
        for item in re.findall(rb"<([0-9A-Fa-f]+)>", array_raw):
            target = _hex_bytes(item)
            if target is None:
                return False
            targets.append(target)
        if len(targets) != end - start + 1:
            return False
    for offset, target in enumerate(targets):
        decoded = _unicode_bytes(target)
        if decoded is None:
            return False
        if not _add_mapping(
            mapping,
            (start + offset).to_bytes(width, "big"),
            decoded,
        ):
            return False
    return True


def _add_mapping(
    mapping: dict[bytes, str],
    source: bytes,
    decoded: str,
) -> bool:
    if not source or source in mapping:
        return False
    mapping[source] = decoded
    return True


def _unicode_hex(value: bytes) -> str | None:
    decoded = _hex_bytes(value)
    return _unicode_bytes(decoded) if decoded is not None else None


def _hex_bytes(value: bytes) -> bytes | None:
    if len(value) % 2:
        return None
    try:
        return bytes.fromhex(value.decode("ascii"))
    except ValueError:
        return None


def _unicode_bytes(value: bytes) -> str | None:
    if len(value) % 2:
        return None
    try:
        return value.decode("utf-16-be", errors="strict")
    except UnicodeDecodeError:
        return None


def _resolve_value(model: PdfObjectModel, value: Any) -> Any:
    visited: set[int] = set()
    while isinstance(value, IndirectReference):
        if value.obj_num in visited:
            return None
        visited.add(value.obj_num)
        try:
            value = model.get_object(value).value
        except DocumentSkillsError:
            return None
    return value
