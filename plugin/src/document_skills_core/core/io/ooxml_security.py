"""Inventory active, executable, and externally linked OOXML content."""

import json
from pathlib import PurePosixPath
import re
from typing import Any
import zipfile

from defusedxml.ElementTree import iterparse

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_CONTENT_TYPES_ROOT = f"{{{_CONTENT_TYPES_NS}}}Types"
_CONTENT_TYPE_DECLARATIONS = {
    f"{{{_CONTENT_TYPES_NS}}}Default",
    f"{{{_CONTENT_TYPES_NS}}}Override",
}
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
    return _security_inventory(
        archive,
        max_xml_bytes=max_xml_bytes,
        max_relationships=None,
    )


def spreadsheet_security_inventory(
    archive: zipfile.ZipFile,
    *,
    max_xml_bytes: int,
    max_relationships: int,
) -> dict[str, Any]:
    """Inventory SpreadsheetML risks while streaming every XML package part."""

    return _security_inventory(
        archive,
        max_xml_bytes=max_xml_bytes,
        max_relationships=max_relationships,
    )


def _security_inventory(
    archive: zipfile.ZipFile,
    *,
    max_xml_bytes: int,
    max_relationships: int | None,
) -> dict[str, Any]:
    categories: dict[str, list[dict[str, str]]] = {
        category: [] for category in _CATEGORIES
    }
    relationship_count = 0
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        lowered = name.lower()
        suffix = PurePosixPath(lowered).suffix
        _classify_part(categories, name, lowered, suffix)
        if (
            lowered.endswith((".xml", ".rels"))
            and info.file_size <= max_xml_bytes
        ):
            with archive.open(info) as source_stream:
                relationship_count = _classify_xml_stream(
                    categories,
                    name,
                    source_stream,
                    relationship_count=relationship_count,
                    max_relationships=max_relationships,
                )
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


def _classify_xml_stream(
    categories: dict[str, list[dict[str, str]]],
    name: str,
    source_stream: Any,
    *,
    relationship_count: int,
    max_relationships: int | None,
) -> int:
    root_seen = False
    is_relationship_part = name.casefold().endswith(".rels")
    is_content_types_part = name == "[Content_Types].xml"
    complex_fields: list[list[str] | None] = []
    depth = 0
    for event, element in iterparse(
        source_stream,
        events=("start", "end"),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    ):
        if event == "start":
            depth += 1
            if is_content_types_part:
                if depth == 1:
                    if element.tag != _CONTENT_TYPES_ROOT:
                        _invalid_content_types()
                elif depth == 2:
                    if element.tag not in _CONTENT_TYPE_DECLARATIONS:
                        _invalid_content_types()
                else:
                    _invalid_content_types()
            if not root_seen:
                root_seen = True
                root_name = _normalized_terminal(_split_tag(element.tag)[1])
                if root_name in _XLM_ROOT_NAMES:
                    categories["xlm"].append({
                        "part": name,
                        "kind": "xml-root",
                    })
            continue
        namespace, terminal = _split_tag(element.tag)
        if is_content_types_part:
            if depth == 2:
                if (
                    len(element)
                    or (element.text and element.text.strip())
                    or (element.tail and element.tail.strip())
                ):
                    _invalid_content_types()
                _classify_content_type(categories, element)
            elif depth == 1 and element.text and element.text.strip():
                _invalid_content_types()
        elif is_relationship_part and element.tag == f"{_REL_NS}Relationship":
            relationship_count += 1
            if (
                max_relationships is not None
                and relationship_count > max_relationships
            ):
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "XLSX exceeds the render relationship ceiling.",
                    details={
                        "relationship_count": relationship_count,
                        "relationship_limit": max_relationships,
                    },
                )
            _classify_relationship(categories, name, element)
        if namespace in _WORD_NAMESPACES:
            _classify_word_field(categories, name, element, terminal, complex_fields)
        element.clear()
        depth -= 1
    for fragments in complex_fields:
        if fragments is not None:
            _classify_dde_instruction(categories, name, "".join(fragments))
    return relationship_count


def _invalid_content_types() -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        "OPC content-types declarations must be direct and empty.",
    )


def _classify_content_type(
    categories: dict[str, list[dict[str, str]]],
    element: Any,
) -> None:
    content_type = element.attrib.get("ContentType", "")
    part = element.attrib.get("PartName", element.attrib.get("Extension", ""))
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


def _classify_relationship(
    categories: dict[str, list[dict[str, str]]],
    source: str,
    relationship: Any,
) -> None:
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


def _classify_word_field(
    categories: dict[str, list[dict[str, str]]],
    name: str,
    element: Any,
    terminal: str,
    complex_fields: list[list[str] | None],
) -> None:
    namespace = _split_tag(element.tag)[0]
    if terminal == "fldSimple":
        instruction = _word_attribute(element, namespace, "instr")
        _classify_dde_instruction(categories, name, instruction)
    elif terminal == "fldChar":
        field_type = _word_attribute(element, namespace, "fldCharType")
        if field_type == "begin":
            complex_fields.append([])
        elif field_type == "separate" and complex_fields:
            fragments = complex_fields[-1]
            if fragments is not None:
                _classify_dde_instruction(categories, name, "".join(fragments))
                complex_fields[-1] = None
        elif field_type == "end" and complex_fields:
            fragments = complex_fields.pop()
            if fragments is not None:
                _classify_dde_instruction(categories, name, "".join(fragments))
    elif terminal == "instrText":
        fragment = "".join(element.itertext())
        if complex_fields and complex_fields[-1] is not None:
            complex_fields[-1].append(fragment)
        else:
            _classify_dde_instruction(categories, name, fragment)


def _word_attribute(element: Any, namespace: str, terminal: str) -> str:
    return next(
        (
            value
            for key, value in element.attrib.items()
            if _split_tag(key) == (namespace, terminal)
        ),
        "",
    )


def _classify_dde_instruction(
    categories: dict[str, list[dict[str, str]]],
    name: str,
    instruction: str,
) -> None:
    if instruction and _DDE_PATTERN.search(instruction):
        categories["dde"].append({"part": name, "kind": "field-code"})


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
