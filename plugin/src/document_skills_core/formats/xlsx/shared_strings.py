"""Shared string table reader/indexer for SpreadsheetML."""

from typing import Any

from .constants import SHARED_STRINGS_PART, qn


def read_shared_strings(parts: dict[str, bytes]) -> list[str]:
    """Read the shared strings table, returning a list of string values indexed by position."""
    payload = parts.get(SHARED_STRINGS_PART)
    if payload is None:
        return []
    from defusedxml.ElementTree import fromstring
    root = fromstring(payload)
    strings: list[str] = []
    for si in root.findall(qn("main", "si")):
        strings.append(_extract_si_text(si))
    return strings


def _extract_si_text(si: Any) -> str:
    """Extract text from a shared string item (<si>)."""
    # Rich text: collect all <t> children of <r> runs
    parts: list[str] = []
    for child in si:
        tag = child.tag
        if tag.endswith("}t"):
            parts.append(child.text or "")
        elif tag.endswith("}r"):
            for t in child:
                if t.tag.endswith("}t"):
                    parts.append(t.text or "")
    return "".join(parts)


def shared_string_index(value: str, existing: list[str]) -> int | None:
    """Find the index of a value in the shared strings table, or None if not found."""
    for idx, item in enumerate(existing):
        if item == value:
            return idx
    return None


def build_shared_strings_xml(strings: list[str]) -> bytes:
    """Build a shared strings XML part from a list of strings."""
    from xml.etree.ElementTree import tostring
    from .constants import NS
    main_ns = NS["main"]
    root_tag = f"{{{main_ns}}}sst"
    from xml.etree.ElementTree import Element, SubElement
    root = Element(root_tag)
    root.set("count", str(len(strings)))
    root.set("uniqueCount", str(len(strings)))
    for text in strings:
        si = SubElement(root, f"{{{main_ns}}}si")
        t = SubElement(si, f"{{{main_ns}}}t")
        t.text = text
    return tostring(root, encoding="UTF-8", xml_declaration=True)
