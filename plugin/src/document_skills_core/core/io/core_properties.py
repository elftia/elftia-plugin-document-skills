"""Uniform OOXML core-properties projection for the metadata read block.

Parses ``docProps/core.xml`` from an OOXML package and projects the uniform
``metadata`` block consumed by all four format ``read`` operations (DOCX, XLSX,
PPTX).  Independently authored from the public OPC/Microsoft Office Open XML
file-format specifications; no third-party restricted material is copied.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from defusedxml.ElementTree import fromstring

_CORE_PART = "docProps/core.xml"

_DC_NS = "http://purl.org/dc/elements/1.1/"
_CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DCTERMS_NS = "http://purl.org/dc/terms/"

_FIELDS = (
    ("title", f"{{{_DC_NS}}}title"),
    ("creator", f"{{{_DC_NS}}}creator"),
    ("subject", f"{{{_DC_NS}}}subject"),
    ("keywords", f"{{{_CP_NS}}}keywords"),
    ("created", f"{{{_DCTERMS_NS}}}created"),
    ("modified", f"{{{_DCTERMS_NS}}}modified"),
)


def project_core_properties(parts: dict[str, bytes]) -> dict[str, str | None]:
    """Project the uniform ``metadata`` block from OOXML ``docProps/core.xml``.

    Returns a dict with the uniform keys ``title``, ``creator``, ``created``,
    ``modified``, ``subject``, ``keywords``.  Missing fields are ``None`` (never
    fabricated).  The projection is inert (no fetch, no refresh).
    """
    payload = parts.get(_CORE_PART)
    if payload is None:
        return {field: None for field, _ in _FIELDS}
    try:
        root = fromstring(payload)
    except Exception:
        return {field: None for field, _ in _FIELDS}
    result: dict[str, str | None] = {}
    for field, tag in _FIELDS:
        element = root.find(tag)
        if element is None or element.text is None:
            result[field] = None
            continue
        text = element.text.strip()
        result[field] = text if text else None
    return result


def empty_metadata() -> dict[str, str | None]:
    """Return the uniform metadata block with every field set to ``None``."""
    return {field: None for field, _ in _FIELDS}
