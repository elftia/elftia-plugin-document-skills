"""Token-aware access to top-level entries in serialized PDF dictionaries.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
import re

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_values import decode_pdf_name

_WHITESPACE = b"\x00\x09\x0a\x0c\x0d\x20"
_DELIMITERS = _WHITESPACE + b"()<>[]{}/%"


@dataclass(frozen=True)
class _Entry:
    key: bytes
    value_start: int
    value_end: int


def top_level_dictionary_value(payload: bytes, key: str) -> bytes | None:
    """Return one serialized top-level value without decoding its bytes."""
    _start, _end, entries = _dictionary_layout(payload)
    wanted = key.encode("ascii")
    matches = [entry for entry in entries if entry.key == wanted]
    if len(matches) > 1:
        _unsafe(f"PDF dictionary contains duplicate {key} entries.")
    if not matches:
        return None
    entry = matches[0]
    return payload[entry.value_start:entry.value_end]


def top_level_dictionary_has_key(payload: bytes, key: str) -> bool:
    """Match one top-level key after decoding PDF name escapes."""
    return top_level_dictionary_decoded_value(payload, key) is not None


def top_level_dictionary_decoded_value(payload: bytes, key: str) -> bytes | None:
    """Return one top-level value after decoding PDF name escapes."""
    _start, _end, entries = _dictionary_layout(payload)
    matches = [
        entry
        for entry in entries
        if decode_pdf_name(entry.key[1:]) == key
    ]
    if len(matches) > 1:
        _unsafe(f"PDF dictionary contains duplicate {key} entries.")
    if not matches:
        return None
    entry = matches[0]
    return payload[entry.value_start:entry.value_end]


def top_level_dictionary_end(payload: bytes) -> int:
    """Return the byte offset immediately after the top-level ``>>`` token."""
    _start, end, _entries = _dictionary_layout(payload)
    return end


def update_top_level_dictionary(
    payload: bytes,
    replacements: dict[str, bytes],
) -> bytes:
    """Replace or add exact top-level values while preserving other bytes."""
    _start, dictionary_end, entries = _dictionary_layout(payload)
    by_key: dict[bytes, list[_Entry]] = {}
    for entry in entries:
        by_key.setdefault(entry.key, []).append(entry)
    modifications: list[tuple[int, int, bytes]] = []
    additions: list[tuple[bytes, bytes]] = []
    for key, value in replacements.items():
        encoded_key = key.encode("ascii")
        matches = by_key.get(encoded_key, [])
        if len(matches) > 1:
            _unsafe(f"PDF dictionary contains duplicate {key} entries.")
        if matches:
            entry = matches[0]
            modifications.append((entry.value_start, entry.value_end, value))
        else:
            additions.append((encoded_key, value))
    if additions:
        insertion = b"".join(
            b" " + key + b" " + value
            for key, value in sorted(additions)
        ) + b" "
        modifications.append((dictionary_end - 2, dictionary_end - 2, insertion))
    result = bytearray(payload)
    for start, end, value in sorted(modifications, reverse=True):
        result[start:end] = value
    return bytes(result)


def _dictionary_layout(payload: bytes) -> tuple[int, int, list[_Entry]]:
    header = re.match(
        rb"\d+[\x00\x09\x0a\x0c\x0d\x20]+\d+"
        rb"[\x00\x09\x0a\x0c\x0d\x20]+obj"
        rb"(?=[\x00\x09\x0a\x0c\x0d\x20<>()\[\]{}/%]|$)",
        payload,
    )
    position = header.end() if header is not None else 0
    position = _skip_separators(payload, position)
    if payload[position:position + 2] != b"<<":
        _unsafe("PDF object does not contain a top-level dictionary.")
    dictionary_start = position
    position += 2
    entries: list[_Entry] = []
    while True:
        position = _skip_separators(payload, position)
        if payload[position:position + 2] == b">>":
            return dictionary_start, position + 2, entries
        if position >= len(payload) or payload[position] != ord("/"):
            _unsafe("PDF dictionary key is not a name token.")
        key_end = _token_end(payload, position)
        key = payload[position:key_end]
        value_start = _skip_separators(payload, key_end)
        if value_start >= len(payload):
            _unsafe("PDF dictionary value is missing.")
        value_end = _value_end(payload, value_start)
        entries.append(_Entry(key, value_start, value_end))
        position = value_end


def _value_end(payload: bytes, position: int) -> int:
    if payload[position] == ord("("):
        return _literal_end(payload, position)
    if payload[position:position + 2] == b"<<":
        return _nested_dictionary_end(payload, position)
    if payload[position] == ord("<"):
        end = payload.find(b">", position + 1)
        if end < 0:
            _unsafe("PDF hex string is unterminated.")
        return end + 1
    if payload[position] == ord("["):
        return _array_end(payload, position)
    token_end = _token_end(payload, position)
    if token_end == position:
        _unsafe("PDF dictionary contains an invalid value token.")
    if not payload[position:token_end].isdigit():
        return token_end
    generation_start = _skip_separators(payload, token_end)
    if generation_start >= len(payload):
        return token_end
    generation_end = _token_end(payload, generation_start)
    if not payload[generation_start:generation_end].isdigit():
        return token_end
    reference_start = _skip_separators(payload, generation_end)
    reference_end = _token_end(payload, reference_start)
    return reference_end if payload[reference_start:reference_end] == b"R" else token_end


def _nested_dictionary_end(payload: bytes, position: int) -> int:
    position += 2
    while True:
        position = _skip_separators(payload, position)
        if payload[position:position + 2] == b">>":
            return position + 2
        if position >= len(payload) or payload[position] != ord("/"):
            _unsafe("Nested PDF dictionary key is not a name token.")
        position = _skip_separators(payload, _token_end(payload, position))
        position = _value_end(payload, position)


def _array_end(payload: bytes, position: int) -> int:
    position += 1
    while True:
        position = _skip_separators(payload, position)
        if position >= len(payload):
            _unsafe("PDF array is unterminated.")
        if payload[position] == ord("]"):
            return position + 1
        position = _value_end(payload, position)


def _literal_end(payload: bytes, position: int) -> int:
    depth = 1
    position += 1
    while position < len(payload):
        byte = payload[position]
        if byte == ord("\\"):
            position += 2
            continue
        if byte == ord("("):
            depth += 1
        elif byte == ord(")"):
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    _unsafe("PDF literal string is unterminated.")


def _skip_separators(payload: bytes, position: int) -> int:
    while position < len(payload):
        start = position
        while position < len(payload) and payload[position] in _WHITESPACE:
            position += 1
        if position < len(payload) and payload[position] == ord("%"):
            while position < len(payload) and payload[position] not in b"\r\n":
                position += 1
            continue
        if position == start:
            break
    return position


def _token_end(payload: bytes, position: int) -> int:
    if position >= len(payload):
        return position
    if payload[position] == ord("/"):
        position += 1
    while position < len(payload) and payload[position] not in _DELIMITERS:
        position += 1
    return position


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
