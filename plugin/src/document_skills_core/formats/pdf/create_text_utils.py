"""Small text-selection and PDF metadata string helpers."""

from typing import Any


def pdf_text_string(text: str) -> str:
    try:
        text.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        encoded = (b"\xfe\xff" + text.encode("utf-16-be")).hex().upper()
        return f"<{encoded}>"
    return f"({_escape_pdf_string(text)})"


def needs_unicode_shaping(block: dict[str, Any]) -> bool:
    style = block.get("style") or {}
    text = block.get("text") or ""
    return (
        style.get("font_family", "Helvetica") != "Helvetica"
        or bool(style.get("fallback_fonts"))
        or style.get("direction") == "rtl"
        or any(ord(character) > 255 for character in text)
    )


def _escape_pdf_string(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
