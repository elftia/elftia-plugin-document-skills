"""Trailer-aware encryption detection without decoding PDF streams."""

import re

from .dictionary_tokens import (
    top_level_dictionary_decoded_value,
    top_level_dictionary_has_key,
)


def trailer_has_encrypt(raw: bytes, *, max_depth: int) -> bool:
    """Follow the final xref/trailer Prev chain and inspect only dictionaries."""
    startxref = raw.rfind(b"startxref")
    if startxref < 0:
        return False
    match = re.match(rb"startxref\s+(\d+)", raw[startxref:])
    if match is None:
        return False
    offset = int(match.group(1))
    visited: set[int] = set()
    for _depth in range(max(1, max_depth)):
        if offset in visited or offset < 0 or offset >= len(raw):
            return False
        visited.add(offset)
        payload = _xref_dictionary_payload(raw, offset)
        if payload is None:
            return False
        if top_level_dictionary_has_key(payload, "/Encrypt"):
            return True
        previous = top_level_dictionary_decoded_value(payload, "/Prev")
        if previous is None:
            return False
        stripped = previous.strip()
        if not stripped.isdigit():
            return False
        offset = int(stripped)
    return False


def _xref_dictionary_payload(raw: bytes, offset: int) -> bytes | None:
    boundary = raw.find(b"startxref", offset)
    if boundary < 0:
        boundary = len(raw)
    if raw[offset:offset + 4] != b"xref":
        return raw[offset:boundary]
    trailer = raw.find(b"trailer", offset + 4, boundary)
    if trailer < 0:
        return None
    dictionary = raw.find(b"<<", trailer + len(b"trailer"), boundary)
    if dictionary < 0:
        return None
    return raw[dictionary:boundary]
