"""Calc chain reader for SpreadsheetML — calculation order and precedent graph."""

from typing import Any

from .constants import CALC_CHAIN_PART, qn


def read_calc_chain(parts: dict[str, bytes]) -> list[dict[str, str]]:
    """Read the calc chain, returning a list of {ref, sheet, level} in calculation order.

    Returns empty list when ``xl/calcChain.xml`` is absent.
    """
    payload = parts.get(CALC_CHAIN_PART)
    if payload is None:
        return []
    from defusedxml.ElementTree import fromstring
    root = fromstring(payload)
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    entries: list[dict[str, str]] = []
    for c in root.findall(f"{{{main_ns}}}c"):
        entries.append({
            "ref": c.attrib.get("r", ""),
            "sheet": c.attrib.get("s", ""),
            "level": c.attrib.get("l", ""),
        })
    return entries


def has_calc_chain(parts: dict[str, bytes]) -> bool:
    """Return True if the calc chain part is present."""
    return CALC_CHAIN_PART in parts


def build_calc_chain_from_formulas(
    formula_cells: dict[str, dict[str, Any]],
) -> bytes:
    """Build a calc chain XML part from a map of formula cells.

    This is used during workbook creation to emit a calc chain for formulas.
    """
    from xml.etree.ElementTree import Element, SubElement, tostring
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = Element(f"{{{main_ns}}}calcChain")
    for ref, info in sorted(formula_cells.items()):
        c = SubElement(root, f"{{{main_ns}}}c")
        c.attrib["r"] = ref
        if info.get("sheet"):
            c.attrib["s"] = str(info["sheet"])
    return tostring(root, encoding="UTF-8", xml_declaration=True)
