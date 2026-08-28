"""Token-aware PDF object renumbering for page-graph rewrites.

Module provenance: original Elftia-authored clean-room implementation.
"""

import re

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_PDF_WHITESPACE = b"\x00\x09\x0a\x0c\x0d\x20"
_PDF_DELIMITERS = _PDF_WHITESPACE + b"()<>[]{}/%"


def renumber_payload(
    payload: bytes,
    new_obj_num: int,
    mapping: dict[int, int],
    pages_obj_num: int | None = None,
    is_page: bool = False,
) -> bytes:
    """Renumber real indirect-reference tokens while preserving opaque bytes."""
    header = re.match(
        rb"(\d+)([\x00\x09\x0a\x0c\x0d\x20]+)(\d+)"
        rb"([\x00\x09\x0a\x0c\x0d\x20]+)obj"
        rb"(?=[\x00\x09\x0a\x0c\x0d\x20<>()\[\]{}/%]|$)",
        payload,
    )
    if header is None:
        _unsafe("A renumbered PDF object has a malformed object header.")
    prefix = (
        str(new_obj_num).encode("ascii")
        + header.group(2)
        + b"0"
        + header.group(4)
        + b"obj"
    )
    return prefix + _renumber_body(
        payload[header.end():],
        mapping,
        pages_obj_num=pages_obj_num,
        is_page=is_page,
    )


def _renumber_body(
    body: bytes,
    mapping: dict[int, int],
    *,
    pages_obj_num: int | None,
    is_page: bool,
) -> bytes:
    output = bytearray()
    position = 0
    dictionary_depth = 0
    array_depth = 0
    top_level_expects_key = False
    top_level_key: bytes | None = None
    top_level_container: tuple[str, int] | None = None
    while position < len(body):
        byte = body[position]
        if byte in _PDF_WHITESPACE:
            end = _skip_whitespace(body, position)
            output.extend(body[position:end])
            position = end
            continue
        if byte == ord("%"):
            end = _skip_comment(body, position)
            output.extend(body[position:end])
            position = end
            continue
        if byte == ord("("):
            end = _literal_string_end(body, position)
            output.extend(body[position:end])
            position = end
            top_level_expects_key, top_level_key = _complete_scalar(
                dictionary_depth,
                array_depth,
                top_level_expects_key,
                top_level_key,
            )
            continue
        if byte == ord("<") and body[position:position + 2] != b"<<":
            end = body.find(b">", position + 1)
            if end < 0:
                _unsafe("A renumbered PDF object contains an unterminated hex string.")
            end += 1
            output.extend(body[position:end])
            position = end
            top_level_expects_key, top_level_key = _complete_scalar(
                dictionary_depth,
                array_depth,
                top_level_expects_key,
                top_level_key,
            )
            continue
        if body[position:position + 2] == b"<<":
            if dictionary_depth == 1 and array_depth == 0 and not top_level_expects_key:
                top_level_container = ("dict", dictionary_depth)
            dictionary_depth += 1
            output.extend(b"<<")
            position += 2
            if dictionary_depth == 1:
                top_level_expects_key = True
            continue
        if body[position:position + 2] == b">>":
            dictionary_depth -= 1
            if dictionary_depth < 0:
                _unsafe("A renumbered PDF object contains an unbalanced dictionary.")
            output.extend(b">>")
            position += 2
            if top_level_container == ("dict", dictionary_depth):
                top_level_container = None
                top_level_expects_key = True
                top_level_key = None
            continue
        if byte == ord("["):
            if dictionary_depth == 1 and array_depth == 0 and not top_level_expects_key:
                top_level_container = ("array", array_depth)
            array_depth += 1
            output.append(byte)
            position += 1
            continue
        if byte == ord("]"):
            array_depth -= 1
            if array_depth < 0:
                _unsafe("A renumbered PDF object contains an unbalanced array.")
            output.append(byte)
            position += 1
            if top_level_container == ("array", array_depth):
                top_level_container = None
                top_level_expects_key = True
                top_level_key = None
            continue

        token_end = _token_end(body, position)
        if token_end == position:
            _unsafe("A renumbered PDF object contains an invalid delimiter token.")
        token = body[position:token_end]
        if token == b"stream":
            output.extend(body[position:])
            break
        reference = _reference_spans(body, position, token_end)
        parent_reference = (
            reference is not None
            and is_page
            and dictionary_depth == 1
            and array_depth == 0
            and not top_level_expects_key
            and top_level_key == b"/Parent"
        )
        if reference is not None:
            generation_start, generation_end, reference_start, reference_end = reference
            old_object = int(token)
            if parent_reference:
                if pages_obj_num is None:
                    _unsafe("A page Parent reference cannot be rebuilt without a Pages object.")
                new_reference = pages_obj_num
            else:
                new_reference = mapping.get(old_object)
                if new_reference is None:
                    raise DocumentSkillsError(
                        ErrorCode.ARCHIVE_UNSAFE,
                        "A renumbered PDF object references an object outside its output graph.",
                        details={"object": old_object},
                    )
            output.extend(str(new_reference).encode("ascii"))
            output.extend(body[token_end:generation_start])
            output.extend(b"0")
            output.extend(body[generation_end:reference_start])
            output.extend(body[reference_start:reference_end])
            position = reference_end
            top_level_expects_key, top_level_key = _complete_scalar(
                dictionary_depth,
                array_depth,
                top_level_expects_key,
                top_level_key,
            )
            continue

        output.extend(token)
        position = token_end
        if dictionary_depth == 1 and array_depth == 0 and top_level_container is None:
            if top_level_expects_key and token.startswith(b"/"):
                top_level_key = token
                top_level_expects_key = False
            elif not top_level_expects_key:
                top_level_key = None
                top_level_expects_key = True
    if dictionary_depth != 0 or array_depth != 0:
        _unsafe("A renumbered PDF object contains an unterminated container.")
    return bytes(output)


def _complete_scalar(
    dictionary_depth: int,
    array_depth: int,
    expects_key: bool,
    key: bytes | None,
) -> tuple[bool, bytes | None]:
    if dictionary_depth == 1 and array_depth == 0 and not expects_key:
        return True, None
    return expects_key, key


def _skip_whitespace(payload: bytes, position: int) -> int:
    while position < len(payload) and payload[position] in _PDF_WHITESPACE:
        position += 1
    return position


def _skip_comment(payload: bytes, position: int) -> int:
    while position < len(payload) and payload[position] not in b"\r\n":
        position += 1
    return position


def _skip_separators(payload: bytes, position: int) -> int:
    while position < len(payload):
        start = position
        position = _skip_whitespace(payload, position)
        if position < len(payload) and payload[position] == ord("%"):
            position = _skip_comment(payload, position)
            continue
        if position == start:
            break
    return position


def _literal_string_end(payload: bytes, position: int) -> int:
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
    _unsafe("A renumbered PDF object contains an unterminated literal string.")


def _token_end(payload: bytes, position: int) -> int:
    if position >= len(payload):
        return position
    if payload[position] == ord("/"):
        position += 1
    while position < len(payload) and payload[position] not in _PDF_DELIMITERS:
        position += 1
    return position


def _reference_spans(
    payload: bytes,
    object_start: int,
    object_end: int,
) -> tuple[int, int, int, int] | None:
    if not payload[object_start:object_end].isdigit():
        return None
    generation_start = _skip_separators(payload, object_end)
    if generation_start >= len(payload):
        return None
    generation_end = _token_end(payload, generation_start)
    if not payload[generation_start:generation_end].isdigit():
        return None
    reference_start = _skip_separators(payload, generation_end)
    if reference_start >= len(payload):
        return None
    reference_end = _token_end(payload, reference_start)
    if payload[reference_start:reference_end] != b"R":
        return None
    return generation_start, generation_end, reference_start, reference_end


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
