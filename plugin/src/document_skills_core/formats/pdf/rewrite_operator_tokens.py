"""Raw token spans for exact PDF text-operator rewrites."""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_tokenizer import _OPERATORS


@dataclass(frozen=True)
class RawToken:
    kind: str
    start: int
    end: int


def raw_operations(content: bytes) -> list[tuple[str, tuple[RawToken, ...]]]:
    operations: list[tuple[str, tuple[RawToken, ...]]] = []
    operands: list[RawToken] = []
    position = 0
    while position < len(content):
        position = _skip_space_and_comments(content, position)
        if position >= len(content):
            break
        token, atom, position = _raw_token(content, position)
        if atom in _OPERATORS:
            operations.append((atom, tuple(operands)))
            operands = []
        elif token is not None:
            operands.append(token)
    return operations


def operator_text(operator: str, operands: list[Any]) -> str:
    if not operands:
        return ""
    if operator == "TJ" and isinstance(operands[-1], list):
        return "".join(
            str(item) for item in operands[-1] if isinstance(item, (str, bytes))
        )
    return str(operands[-1])


def operator_bytes(operator: str, operands: list[Any]) -> bytes:
    if not operands:
        return b""
    values = operands[-1] if operator == "TJ" else [operands[-1]]
    if not isinstance(values, list):
        return b""
    result = bytearray()
    for value in values:
        if isinstance(value, bytes):
            result.extend(value)
        elif isinstance(value, str):
            result.extend(value.encode("latin-1", errors="strict"))
    return bytes(result)


def _raw_token(
    content: bytes,
    position: int,
) -> tuple[RawToken | None, str | None, int]:
    start = position
    if content[position] == ord("("):
        end = _literal_end(content, position)
        return RawToken("literal", start, end), None, end
    if content[position : position + 2] == b"<<":
        end = _compound_end(content, position, b"<<", b">>")
        return RawToken("dictionary", start, end), None, end
    if content[position] == ord("<"):
        end = content.find(b">", position + 1)
        if end < 0:
            _validation("Hex string operand is unterminated.")
        return RawToken("hex", start, end + 1), None, end + 1
    if content[position] == ord("["):
        end = _compound_end(content, position, b"[", b"]")
        return RawToken("array", start, end), None, end
    if content[position] == ord("/"):
        position += 1
        while (
            position < len(content)
            and content[position] not in b"\x00\t\n\f\r ()<>[]{}/%"
        ):
            position += 1
        return RawToken("name", start, position), None, position
    while (
        position < len(content) and content[position] not in b"\x00\t\n\f\r ()<>[]{}/%"
    ):
        position += 1
    if position == start:
        return None, None, position + 1
    atom = content[start:position].decode("ascii", errors="replace")
    return RawToken("atom", start, position), atom, position


def _compound_end(
    content: bytes,
    position: int,
    opener: bytes,
    closer: bytes,
) -> int:
    stack = [closer]
    position += len(opener)
    while position < len(content) and stack:
        expected = stack[-1]
        if content[position] == ord("("):
            position = _literal_end(content, position)
        elif content[position] == ord("%"):
            position = _skip_comment(content, position)
        elif content[position : position + 2] == b"<<":
            stack.append(b">>")
            position += 2
        elif content[position] == ord("["):
            stack.append(b"]")
            position += 1
        elif content[position : position + len(expected)] == expected:
            stack.pop()
            position += len(expected)
        elif content[position] == ord("<"):
            end = content.find(b">", position + 1)
            if end < 0:
                _validation("Compound PDF operand is unterminated.")
            position = end + 1
        else:
            position += 1
    if stack:
        _validation("Compound PDF operand is unterminated.")
    return position


def _literal_end(content: bytes, position: int) -> int:
    depth = 1
    position += 1
    while position < len(content) and depth:
        if content[position] == ord("\\"):
            position += 2
        elif content[position] == ord("("):
            depth += 1
            position += 1
        elif content[position] == ord(")"):
            depth -= 1
            position += 1
        else:
            position += 1
    if depth:
        _validation("Literal PDF string operand is unterminated.")
    return position


def _skip_space_and_comments(content: bytes, position: int) -> int:
    while position < len(content):
        if content[position] in b"\x00\t\n\f\r ":
            position += 1
        elif content[position] == ord("%"):
            position = _skip_comment(content, position)
        else:
            break
    return position


def _skip_comment(content: bytes, position: int) -> int:
    while position < len(content) and content[position] not in b"\r\n":
        position += 1
    return position


def _validation(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message)
