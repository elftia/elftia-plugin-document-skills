"""Deterministic serialization for parsed non-stream PDF values.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from .create_layout import pdf_number
from .object_model import IndirectReference, PdfDict

_NAME_DELIMITERS = frozenset(" \t\r\n/[]<>()")


def serialize_pdf_value(value: Any) -> bytes:
    """Serialize the bounded value types produced by the Core PDF parser."""
    if isinstance(value, PdfDict):
        entries = b" ".join(
            key.encode("latin-1", errors="strict")
            + b" "
            + serialize_pdf_value(entry)
            for key, entry in value.entries.items()
        )
        return b"<< " + entries + b" >>"
    if isinstance(value, IndirectReference):
        return f"{value.obj_num} {value.gen_num} R".encode("ascii")
    if isinstance(value, list):
        return b"[" + b" ".join(serialize_pdf_value(item) for item in value) + b"]"
    if isinstance(value, str):
        if value.startswith("/") and not any(
            character in _NAME_DELIMITERS for character in value[1:]
        ):
            return value.encode("latin-1", errors="strict")
        escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        return b"(" + escaped.encode("latin-1", errors="strict") + b")"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if value is None:
        return b"null"
    if isinstance(value, (int, float)):
        return pdf_number(value).encode("ascii")
    raise TypeError(f"Unsupported parsed PDF value: {type(value).__name__}")
