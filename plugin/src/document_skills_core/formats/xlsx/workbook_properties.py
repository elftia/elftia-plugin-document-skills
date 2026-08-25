"""XLSX-specific core and extended workbook-property support."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml.ElementTree import fromstring

from .constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    NS,
    PACKAGE_RELS,
    REL_CORE_PROPERTIES,
    REL_EXTENDED_PROPERTIES,
)

_APP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
_CORE_PART = "docProps/core.xml"
_APP_PART = "docProps/app.xml"
_REL_NS = NS["rels"]
_CORE_CONTENT_TYPE = "application/vnd.openxmlformats-package.core-properties+xml"
_APP_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.extended-properties+xml"
)

_CORE_FIELDS = {
    "title": f"{{{NS['dc']}}}title",
    "creator": f"{{{NS['dc']}}}creator",
    "subject": f"{{{NS['dc']}}}subject",
    "description": f"{{{NS['dc']}}}description",
    "keywords": f"{{{NS['cp']}}}keywords",
    "category": f"{{{NS['cp']}}}category",
    "last_modified_by": f"{{{NS['cp']}}}lastModifiedBy",
    "created": f"{{{NS['dcterms']}}}created",
    "modified": f"{{{NS['dcterms']}}}modified",
}
_APP_FIELDS = {
    "company": f"{{{_APP_NS}}}Company",
    "manager": f"{{{_APP_NS}}}Manager",
}


def build_core_properties(metadata: dict[str, Any]) -> bytes:
    return _to_bytes(_core_root(metadata))


def _core_root(metadata: dict[str, Any]) -> Element:
    root = Element(f"{{{NS['cp']}}}coreProperties")
    for field, tag in _CORE_FIELDS.items():
        value = metadata.get(field)
        if value is None:
            continue
        element = SubElement(root, tag)
        if field in {"created", "modified"}:
            element.attrib[f"{{{NS['xsi']}}}type"] = "dcterms:W3CDTF"
        element.text = value
    return root


def build_app_properties(
    sheets: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> bytes:
    return _to_bytes(_app_root(sheets, metadata))


def _app_root(sheets: list[dict[str, Any]], metadata: dict[str, Any]) -> Element:
    root = Element(f"{{{_APP_NS}}}Properties")
    SubElement(root, f"{{{_APP_NS}}}Application").text = "Elftia Document Skills"
    for field, tag in _APP_FIELDS.items():
        value = metadata.get(field)
        if value is not None:
            SubElement(root, tag).text = value
    return root


def apply_workbook_properties_edit(context: Any, properties: dict[str, str]) -> None:
    core = _ensure_part(context, _CORE_PART) if set(properties) & set(_CORE_FIELDS) else None
    app = _ensure_part(context, _APP_PART) if set(properties) & set(_APP_FIELDS) else None
    for field, value in properties.items():
        if field in _CORE_FIELDS:
            assert core is not None
            element = _replace_text(core, _CORE_FIELDS[field], value)
            if field in {"created", "modified"}:
                element.attrib[f"{{{NS['xsi']}}}type"] = "dcterms:W3CDTF"
            context.mark_dirty(_CORE_PART)
        else:
            assert app is not None
            _replace_text(app, _APP_FIELDS[field], value)
            context.mark_dirty(_APP_PART)


def project_workbook_properties(parts: dict[str, bytes]) -> dict[str, str | None]:
    result = {field: None for field in (*_CORE_FIELDS, *_APP_FIELDS)}
    for part, fields in ((_CORE_PART, _CORE_FIELDS), (_APP_PART, _APP_FIELDS)):
        payload = parts.get(part)
        if payload is None:
            continue
        try:
            root = fromstring(payload)
        except Exception:
            continue
        for field, tag in fields.items():
            element = root.find(tag)
            if element is not None:
                result[field] = element.text or ""
    return result


def _replace_text(root: Element, tag: str, value: str) -> Element:
    element = root.find(tag)
    if element is None:
        element = SubElement(root, tag)
    element.text = value
    return element


def _ensure_part(context: Any, part: str) -> Element:
    if part in context.package.parts or part in context.added:
        return context.root(part)
    if part == _CORE_PART:
        root = _core_root({})
        relationship_type = REL_CORE_PROPERTIES
        content_type = _CORE_CONTENT_TYPE
    else:
        root = _app_root(context.workbook.get("sheets", []), {})
        relationship_type = REL_EXTENDED_PROPERTIES
        content_type = _APP_CONTENT_TYPE
    context.add_root(part, root)
    relationships = context.root(PACKAGE_RELS)
    SubElement(
        relationships,
        f"{{{_REL_NS}}}Relationship",
        {
            "Id": _next_relationship_id(relationships),
            "Type": relationship_type,
            "Target": part,
        },
    )
    content_types = context.root(CONTENT_TYPES)
    SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": f"/{part}", "ContentType": content_type},
    )
    context.mark_dirty(PACKAGE_RELS)
    context.mark_dirty(CONTENT_TYPES)
    return root


def _next_relationship_id(root: Element) -> str:
    used = {
        item.attrib.get("Id", "")
        for item in root.findall(f"{{{_REL_NS}}}Relationship")
    }
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def _to_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)
