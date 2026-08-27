"""Standard custom properties carrying bounded Elftia document identity."""

import json
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .package import OpcPackage
from .style_profiles import public_style_profile
from .xml_utils import xml_bytes

_FORMAT_ID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"
_PROPERTY_NAMES = {
    "ElftiaDocumentSpecVersion": "document_spec_version",
    "ElftiaStyleProfile": "style_profile",
    "ElftiaDomainProfile": "domain_profile",
}


def render_document_manifest(report: dict[str, Any]) -> bytes:
    root = Element(qn("cust", "Properties"))
    values: list[tuple[str, str]] = [
        ("ElftiaDocumentSpecVersion", report["document_spec_version"]),
    ]
    for name, key in (
        ("ElftiaStyleProfile", "style_profile"),
        ("ElftiaDomainProfile", "domain_profile"),
    ):
        value = report.get(key)
        if key == "style_profile":
            value = public_style_profile(value)
        if value is not None:
            values.append(
                (
                    name,
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
            )
    for property_id, (name, value) in enumerate(values, start=2):
        item = SubElement(
            root,
            qn("cust", "property"),
            {"fmtid": _FORMAT_ID, "pid": str(property_id), "name": name},
        )
        SubElement(item, qn("vt", "lpwstr")).text = value
    return xml_bytes(root)


def project_document_manifest(package: OpcPackage) -> dict[str, Any] | None:
    if "docProps/custom.xml" not in package.parts:
        return None
    result: dict[str, Any] = {}
    for item in package.xml("docProps/custom.xml").findall(qn("cust", "property")):
        key = _PROPERTY_NAMES.get(item.attrib.get("name", ""))
        value_node = next(iter(item), None)
        value = value_node.text if value_node is not None else None
        if key is None or value is None:
            continue
        if key.endswith("_profile"):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                continue
            if type(parsed) is dict:
                result[key] = parsed
        else:
            result[key] = value
    return result or None
