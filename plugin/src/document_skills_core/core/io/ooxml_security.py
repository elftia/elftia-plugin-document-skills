"""Inventory active, executable, and externally linked OOXML content."""

import json
from pathlib import PurePosixPath
import re
from typing import Any
import zipfile

from defusedxml.ElementTree import fromstring

_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DDE_PATTERN = re.compile(r"(?i)\bDDE(?:AUTO)?\b")
_WORD_NAMESPACES = {
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
_EXECUTABLE_SUFFIXES = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".hta",
    ".js",
    ".lnk",
    ".ps1",
    ".scr",
    ".vbs",
    ".xla",
    ".xlam",
    ".xll",
}
_XLM_CONTENT_MARKERS = (
    "vnd.ms-excel.macrosheet",
    "vnd.ms-excel.intlmacrosheet",
    "vnd.ms-excel.addin",
    "vnd.ms-excel.sheet.binary.macroenabled",
    "vnd.ms-excel.template.binary.macroenabled",
    "vnd.ms-excel.binary",
)
_XLM_RELATIONSHIP_TYPES = {
    "addin",
    "binaryindex",
    "intlmacrosheet",
    "macrosheet",
    "xladdin",
    "xlbinaryindex",
    "xlintladdin",
    "xlintlmacrosheet",
    "xlmacrosheet",
}
_XLM_ROOT_NAMES = {
    "addin",
    "binaryindex",
    "intlmacrosheet",
    "macrosheet",
    "xladdin",
    "xlbinaryindex",
    "xlintladdin",
    "xlintlmacrosheet",
    "xlmacrosheet",
}
_XLM_PATH_MARKERS = (
    "/xl/addins/",
    "/xl/binaryindex/",
    "/xl/intlmacrosheets/",
    "/xl/macrosheets/",
)
_CATEGORIES = (
    "vba",
    "xlm",
    "activex",
    "ole",
    "templates",
    "dde",
    "external_targets",
    "executable_parts",
)


def security_inventory(
    archive: zipfile.ZipFile,
    *,
    max_xml_bytes: int,
) -> dict[str, Any]:
    categories: dict[str, list[dict[str, str]]] = {
        category: [] for category in _CATEGORIES
    }
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        lowered = name.lower()
        suffix = PurePosixPath(lowered).suffix
        _classify_part(categories, name, lowered, suffix)
        if name == "[Content_Types].xml":
            _classify_content_types(categories, archive.read(info))
        if lowered.endswith(".rels") and info.file_size <= max_xml_bytes:
            _classify_relationships(categories, name, archive.read(info))
        if lowered.endswith(".xml") and info.file_size <= max_xml_bytes:
            _classify_xml(categories, name, archive.read(info))
    normalized = {
        category: _deduplicate(records)
        for category, records in categories.items()
    }
    counts = {category: len(records) for category, records in normalized.items()}
    return {
        "dangerous": any(counts.values()),
        "counts": counts,
        "categories": normalized,
    }


def _classify_part(
    categories: dict[str, list[dict[str, str]]],
    name: str,
    lowered: str,
    suffix: str,
) -> None:
    record = {"part": name, "kind": "package-part"}
    if lowered.endswith("vbaproject.bin") or "/vba" in lowered:
        categories["vba"].append(record)
    if _is_xlm_part(lowered, suffix):
        categories["xlm"].append(record)
    if "/activex/" in lowered:
        categories["activex"].append(record)
    if "/embeddings/" in lowered or "oleobject" in lowered:
        categories["ole"].append(record)
    if "attachedtemplate" in lowered or suffix in {".dotm", ".dotx", ".xltm", ".potm"}:
        categories["templates"].append(record)
    if suffix in _EXECUTABLE_SUFFIXES:
        categories["executable_parts"].append(record)


def _classify_content_types(
    categories: dict[str, list[dict[str, str]]],
    payload: bytes,
) -> None:
    root = fromstring(payload)
    for child in root:
        content_type = child.attrib.get("ContentType", "")
        part = child.attrib.get("PartName", child.attrib.get("Extension", ""))
        record = {
            "part": part or "[Content_Types].xml",
            "kind": "content-type",
            "type": content_type,
        }
        lowered_type = content_type.lower()
        lowered_part = part.lower()
        if "macroenabled" in lowered_type or "vbaproject" in lowered_type:
            categories["vba"].append(record)
        if _is_xlm_content_type(lowered_type) or _is_xlm_part(
            lowered_part, PurePosixPath(lowered_part).suffix
        ):
            categories["xlm"].append(record)
        if "activex" in lowered_type:
            categories["activex"].append(record)
        if "oleobject" in lowered_type:
            categories["ole"].append(record)
        if "template" in lowered_type:
            categories["templates"].append(record)


def _classify_relationships(
    categories: dict[str, list[dict[str, str]]],
    source: str,
    payload: bytes,
) -> None:
    root = fromstring(payload)
    for relationship in root.findall(f"{_REL_NS}Relationship"):
        target = relationship.attrib.get("Target", "")
        rel_type = relationship.attrib.get("Type", "")
        target_mode = relationship.attrib.get("TargetMode", "")
        lowered_target = target.lower()
        lowered_type = rel_type.lower()
        record = {
            "source": source,
            "id": relationship.attrib.get("Id", ""),
            "target": target,
            "type": rel_type,
            "target_mode": target_mode,
        }
        if "vbaproject" in lowered_type or "vbaproject" in lowered_target:
            categories["vba"].append(record)
        if _is_xlm_relationship(lowered_type) or _is_xlm_part(
            lowered_target, PurePosixPath(lowered_target).suffix
        ):
            categories["xlm"].append(record)
        if "activex" in lowered_type or "activex" in lowered_target:
            categories["activex"].append(record)
        if "oleobject" in lowered_type or "embeddings/" in lowered_target:
            categories["ole"].append(record)
        if "attachedtemplate" in lowered_type or lowered_target.endswith((".dotm", ".dotx")):
            categories["templates"].append(record)
        if "dde" in lowered_type:
            categories["dde"].append(record)
        if target_mode.lower() == "external":
            categories["external_targets"].append(record)
        if PurePosixPath(lowered_target).suffix in _EXECUTABLE_SUFFIXES:
            categories["executable_parts"].append(record)


def _classify_xml(
    categories: dict[str, list[dict[str, str]]],
    name: str,
    payload: bytes,
) -> None:
    root = fromstring(payload)
    local_name = _normalized_terminal(root.tag.rsplit("}", 1)[-1])
    if local_name in _XLM_ROOT_NAMES:
        categories["xlm"].append({"part": name, "kind": "xml-root"})
    if any(_DDE_PATTERN.search(item) for item in _word_field_instructions(root)):
        categories["dde"].append({"part": name, "kind": "field-code"})


def _word_field_instructions(root: Any) -> list[str]:
    instructions: list[str] = []
    complex_fields: list[list[str] | None] = []
    for element in root.iter():
        namespace, terminal = _split_tag(element.tag)
        if namespace not in _WORD_NAMESPACES:
            continue
        if terminal == "fldSimple":
            instructions.append(
                next(
                    (
                        value
                        for key, value in element.attrib.items()
                        if _split_tag(key) == (namespace, "instr")
                    ),
                    "",
                )
            )
        elif terminal == "fldChar":
            field_type = next(
                (
                    value
                    for key, value in element.attrib.items()
                    if _split_tag(key) == (namespace, "fldCharType")
                ),
                "",
            )
            if field_type == "begin":
                complex_fields.append([])
            elif field_type == "separate" and complex_fields:
                fragments = complex_fields[-1]
                if fragments is not None:
                    instructions.append("".join(fragments))
                    complex_fields[-1] = None
            elif field_type == "end" and complex_fields:
                fragments = complex_fields.pop()
                if fragments is not None:
                    instructions.append("".join(fragments))
        elif terminal == "instrText":
            fragment = "".join(element.itertext())
            if complex_fields and complex_fields[-1] is not None:
                complex_fields[-1].append(fragment)
            else:
                instructions.append(fragment)
    instructions.extend(
        "".join(fragments)
        for fragments in complex_fields
        if fragments is not None
    )
    return [instruction for instruction in instructions if instruction]


def _split_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, terminal = tag[1:].split("}", 1)
        return namespace, terminal
    return "", tag


def _is_xlm_part(lowered: str, suffix: str) -> bool:
    normalized = f"/{lowered.lstrip('/')}"
    return (
        any(marker in normalized for marker in _XLM_PATH_MARKERS)
        or suffix in {".xla", ".xlam", ".xll"}
    )


def _is_xlm_content_type(lowered: str) -> bool:
    return any(marker in lowered for marker in _XLM_CONTENT_MARKERS)


def _is_xlm_relationship(lowered: str) -> bool:
    return _normalized_terminal(lowered.rsplit("/", 1)[-1]) in _XLM_RELATIONSHIP_TYPES


def _normalized_terminal(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _deduplicate(records: list[dict[str, str]]) -> list[dict[str, str]]:
    indexed = {
        json.dumps(record, ensure_ascii=False, sort_keys=True): record for record in records
    }
    return [indexed[key] for key in sorted(indexed)]
